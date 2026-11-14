"""Controller contracts on local receipts; no backend, model, API or GPU startup."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from ledger_grpo.observability import EventWriter, read_events, summarize_events


def controller():
    path = Path(__file__).parents[1] / "scripts/hf_pilot_controller.py"
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("pilot_controller_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def optimizer_receipts(root, *, persisted=False):
    step = root / "step-0001"
    for rank in range(4):
        write(step / f"OPTIMIZER_RETURNED-rank{rank}.json", dict(state="optimizer_returned", rank=rank,
              optimizer_step=1, batch_identity="same-native-batch", all_ranks_confirmed=False))
    write(step / "UPDATE_COMPUTED.json", dict(state="computed", computed_optimizer_steps=1,
          optimizer_steps_this_batch=1, loss=.2, entropy=.8, gradient_norm_before_clip=2.,
          learning_rate=1e-6, effective_action_tokens=20, tis_clip_fraction=.3))
    if persisted:
        write(root / "checkpoints/step-0001/COMPLETE.json", dict(optimizer_step=1, world_size=4))
        write(step / "CHECKPOINT_PERSISTED.json", dict(persisted_optimizer_steps=1))


class ControllerTests(unittest.TestCase):
    def api(self):
        module = controller()
        self.assertTrue(hasattr(module, "record_optimizer_receipt"), "receipt integration is not implemented")
        return module

    def test_checkpoint_failure_still_records_real_commit_and_no_fabricated_kl(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            optimizer_receipts(root)
            writer = EventWriter(root / "metrics.jsonl", run_id="pilot:outcome", training_seed=7, config_hash="c")
            receipt = m.record_optimizer_receipt(root, writer, terminal=True)
            self.assertEqual(receipt["optimizer_steps_committed"], 1)
            self.assertFalse(receipt["checkpoint_persisted"])
            self.assertFalse(receipt["snapshot_published"])
            event = read_events(root / "metrics.jsonl")[0]
            self.assertEqual(event["payload"]["status"], "committed")
            self.assertEqual(event["payload"]["metrics"]["grad_norm_pre_clip"], 2.)
            self.assertIsNone(event["payload"]["metrics"]["approx_kl"])
            self.assertIsNone(event["payload"]["metrics"]["clip_fraction"])

    def test_partial_rank_return_is_unknown_instead_of_false_zero_or_full_commit(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "step-0001/OPTIMIZER_RETURNED-rank0.json", dict(state="optimizer_returned",rank=0,
                  optimizer_step=1,batch_identity="b"))
            writer = EventWriter(root / "metrics.jsonl", run_id="r", training_seed=7, config_hash="c")
            receipt = m.record_optimizer_receipt(root, writer, terminal=True)
            self.assertIsNone(receipt["optimizer_steps_committed"])
            self.assertEqual(receipt["optimizer_returned_ranks"], [0])
            self.assertEqual(read_events(root / "metrics.jsonl"), [])

    def test_two_independent_arms_each_commit_step_one(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            for arm in ("outcome", "ledger"):
                root = Path(tmp) / arm
                optimizer_receipts(root, persisted=True)
                writer = EventWriter(root / "metrics.jsonl", run_id="pilot:" + arm, training_seed=7, config_hash="c")
                m.record_optimizer_receipt(root, writer, terminal=True)
                m.record_optimizer_receipt(root, writer, terminal=True)
                events += read_events(root / "metrics.jsonl")
            runs = summarize_events(events)["runs"]
            self.assertEqual(len(runs), 2)
            self.assertTrue(all(r["last_committed_step"] == 1 for r in runs.values()))
            self.assertTrue(all(r["optimizer_committed_count"] == 1 for r in runs.values()))

    def test_worker_skip_does_not_require_step_complete(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "step-0001/SKIPPED.json", dict(state="skipped",skip_reason="all_effective_advantages_zero",
                                                       computed_optimizer_steps=0))
            writer = EventWriter(root / "metrics.jsonl", run_id="r", training_seed=7, config_hash="c")
            result = m.record_optimizer_receipt(root, writer, terminal=True)
            self.assertEqual(result["state"], "skipped")
            self.assertEqual(result["optimizer_steps_committed"], 0)
            self.assertEqual(read_events(root / "metrics.jsonl")[0]["payload"]["status"], "skipped")

    def test_identical_objective_does_not_create_measured_ledger_arm(self):
        m = self.api()
        arms, skipped = m.select_update_arms({"objectives_exactly_identical": True,
                                              "arm_update_capable": {"outcome": True, "ledger": True}})
        self.assertEqual(arms, ["outcome"])
        self.assertEqual(skipped["ledger"], "equivalent_objective_not_reexecuted")
        arms, skipped = m.select_update_arms({"objectives_exactly_identical": False,
                                              "arm_update_capable": {"outcome": False, "ledger": False}})
        self.assertEqual(arms, [])
        self.assertEqual(skipped["outcome"], "no_effective_nonzero_advantage")

    def test_constraint_failure_disables_frame_without_whole_question_pseudoframe(self):
        m = self.api()
        def extractor(task, judge):
            if task == "private failing task":
                raise ValueError("PRIVATE_API_RESPONSE")
            return [{"cid":"c", "text":"constraint"}]
        frames, active, errors = m.extract_training_frames(
            {"a": {"question":"private failing task"}, "b":{"question":"works"}}, {"a","b"}, object(), extractor=extractor)
        self.assertEqual(active, {"b"})
        self.assertEqual(errors["a"], "ValueError")
        self.assertNotIn("private failing task", json.dumps(frames["a"]))
        self.assertNotIn("PRIVATE_API_RESPONSE", json.dumps(errors))

    def evaluation(self, folder, *, outcomes=(1,0), costs=(10,20), unknown=False):
        rows = [{"id":f"q{i}__rep1", "query_id":i, "reward": None if unknown and i == 0 else value,
                 "terminal":"MODEL_FINAL_STOP", "generated_tokens":cost, "tool_calls":1,
                 "question":"PRIVATE_QUERY"} for i,(value,cost) in enumerate(zip(outcomes,costs))]
        write(folder / "TRAJECTORY_METRICS.json", rows)

    def test_fixed_eval_pairs_tasks_and_does_not_expose_query_text(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.evaluation(root / "p0")
            self.evaluation(root / "outcome", outcomes=(1,1), costs=(8,16))
            initial, after = m.evaluation_summary(root / "p0"), m.evaluation_summary(root / "outcome")
            comparisons = m.paired_comparisons({"P0":initial,"outcome":after}, training_seed=7, bootstrap_seed=9, resamples=100)
            result = comparisons["outcome_minus_P0"]
            self.assertEqual(result["accuracy_delta"]["estimate"], .5)
            self.assertEqual(result["cost_delta"]["estimate"], -3.)
            self.assertEqual(result["training_seed_count"], 1)
            self.assertEqual(result["bootstrap_seed"], 9)
            self.assertEqual(result["task_count"], 2)
            self.assertNotIn("ledger_minus_P0", comparisons)
            self.assertNotIn("PRIVATE_QUERY", json.dumps(after))
            writer = EventWriter(root / "metrics.jsonl", run_id="r:outcome", training_seed=7, config_hash="c")
            m.emit_fixed_evaluation(writer, after, name="outcome", manifest_id="m", rollout_seed=12, comparison=result)
            events = read_events(root / "metrics.jsonl")
            self.assertEqual(sum(e["event_type"] == "rollout.scored" for e in events), 2)
            evaluation = next(e for e in events if e["event_type"] == "evaluation.completed")
            self.assertEqual(evaluation["payload"]["paired_accuracy_delta"], .5)
            self.assertNotIn("PRIVATE_QUERY", json.dumps(events))

    def test_unresolved_eval_never_becomes_zero_accuracy_for_bootstrap(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.evaluation(root / "p0")
            self.evaluation(root / "after", unknown=True)
            summaries = {"P0":m.evaluation_summary(root / "p0"), "outcome":m.evaluation_summary(root / "after")}
            self.assertIsNone(summaries["outcome"]["accuracy"])
            self.assertEqual(summaries["outcome"]["outcome_coverage"], .5)
            result = m.paired_comparisons(summaries, training_seed=7, resamples=100)["outcome_minus_P0"]
            self.assertIsNone(result["accuracy_delta"])
            self.assertEqual(result["state"], "unresolved_outcomes")
            self.assertEqual(result["cost_delta"]["estimate"], 0)

    def test_eval_duplicate_samples_and_mismatched_tasks_fail_closed(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.evaluation(root)
            rows=json.loads((root / "TRAJECTORY_METRICS.json").read_text())
            write(root / "TRAJECTORY_METRICS.json", rows + [rows[0]])
            with self.assertRaises(ValueError): m.evaluation_summary(root)

    def test_phase_failure_records_elapsed_and_failure_without_raw_exception(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            state, phases = {}, []
            def broken(): raise RuntimeError("PRIVATE_SECRET")
            with self.assertRaises(RuntimeError):
                m.run_phase(root, state, phases, "synthetic_phase", broken, heartbeat_seconds=.01)
            data=json.loads((root / "PHASES.json").read_text())
            self.assertEqual(data[0]["state"], "failed")
            self.assertGreaterEqual(data[0]["seconds"], 0)
            self.assertNotIn("PRIVATE_SECRET", json.dumps(data))

    def test_main_identical_fallback_runs_one_real_arm_and_paired_posteval(self):
        m=self.api()
        modules={name:ModuleType(name) for name in ("src.stability_controller","src.stability_rollout",
                                                   "src.stability_judge","src.resident_controller","isolate_runtime")}
        modules["isolate_runtime"].install_runtime_isolation=lambda:None
        class Services:
            def __init__(self,root,*args):
                self.root=root; self.servers=[]; self.port=1
                self.actors=SimpleNamespace(park=lambda:None,publish=lambda *a,**k:None)
                self.search=SimpleNamespace(post=lambda *a:None)
            def start(self,*args): pass
            def close(self): pass
        modules["src.stability_controller"].Services=Services
        modules["src.stability_controller"].read_hardware=lambda:([],{})
        modules["src.stability_controller"].GPUMonitor=lambda *a:SimpleNamespace(close=lambda:None)
        modules["src.stability_judge"].FlashJudge=lambda *a:SimpleNamespace(close=lambda:None)
        modules["src.resident_controller"].generated_probe=lambda *a:None
        def rollout(folder,*args):
            self.evaluation(folder,outcomes=(1,1) if folder.name=="eval-outcome" else (1,0))
        modules["src.stability_rollout"].run_rollout=rollout
        def score(rollout,questions,output,key,writer,*,arm_writers):
            output.mkdir()
            native=output/"NATIVE_BATCH.json"
            write(native,{"trajectories":[]})
            return native,{"objectives_exactly_identical":True,"arm_update_capable":{"outcome":True,"ledger":True}}
        class Process:
            def __init__(self,command,**kwargs):
                arm=Path(command[command.index("--output-root")+1]); optimizer_receipts(arm,persisted=True)
                write(arm/"step-0001/STEP_COMPLETE.json",{"snapshot_published":True})
                snapshots=Path(command[command.index("--snapshot-dir")+1])
                publication=command[command.index("--publication-id")+1]
                write(snapshots/f"step-{publication}.json",{"snapshot":f"step-{publication}.safetensors","fingerprint":"fake"})
            def poll(self): return 0
            def __enter__(self): return self
            def __exit__(self,*args): return False
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); plan=base/"plan.json"; key=base/"dummy.key"
            write(plan,{"training_rows":[{"query_id":1,"question":"train"}],
                        "evaluation_rows":[{"query_id":0,"question":"private-eval-0"},{"query_id":1,"question":"private-eval-1"}]})
            key.write_text("dummy-not-a-real-key")
            env={"LEDGER_HF_BACKEND_SOURCE":str(base),"LEDGER_PILOT_PLAN":str(plan),"LEDGER_PILOT_STORE":str(base),
                 "LEDGER_JUDGE_KEY_FILE":str(key),"SLURM_JOB_ID":"test","CUDA_VISIBLE_DEVICES":"0,1,2,3"}
            cwd=Path.cwd()
            original_path=list(sys.path)
            try:
                with patch.dict(os.environ,env),patch.dict(sys.modules,modules),patch.object(m,"score_training",score),patch.object(m.subprocess,"Popen",Process):
                    m.main()
            finally:
                os.chdir(cwd)
                sys.path[:]=original_path
            root=base/"runs/pilot-test"
            result=json.loads((root/"RESULT.json").read_text())
            self.assertEqual(result["state"],"completed")
            self.assertEqual(result["arms_executed"],["outcome"])
            self.assertEqual(set(result["evaluations"]),{"P0","outcome"})
            self.assertFalse((root/"EVAL-ledger.json").exists())
            self.assertEqual(result["paired_comparisons"]["outcome_minus_P0"]["accuracy_delta"]["estimate"],.5)
            outcome=summarize_events(read_events(root/"outcome/metrics.jsonl"))["runs"]["pilot-test:outcome"]
            ledger=summarize_events(read_events(root/"ledger/metrics.jsonl"))["runs"]["pilot-test:ledger"]
            self.assertEqual(outcome["optimizer_committed_count"],1)
            self.assertEqual(ledger["optimizer_committed_count"],0)
            self.assertEqual(outcome["evaluations"]["fixed-outcome"]["sample_count"],2)


if __name__ == "__main__":
    unittest.main()
