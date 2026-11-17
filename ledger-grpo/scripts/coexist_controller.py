"""Compare A/B/C while keeping weights, rollout, labeling, and scoring identities fixed."""
import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import secrets
from statistics import median, quantiles
import subprocess
import sys
import threading
import time

from coexist_runtime import (ActorServices, JudgeService, Telemetry, actor_fractions, memory_failure,
                             save_prometheus, transition_actors)
from coexist_labels import label_trajectory, load_evidence_snapshot, record_m3
from ledger_grpo.coexist_handoff import score_coexist_handoff
from ledger_grpo import coexist_test_grade
from redundancy_judge.adapters.model import ModelJudge
from redundancy_judge.adapters.trace import NativeByteTokenizer
from redundancy_judge.cli import jsonl, write_jsonl
from redundancy_judge.common import atomic_json, identity, read_json


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def safe_append(path, value, lock):
    with lock, path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        output.flush()
        os.fsync(output.fileno())


def p95(samples):
    return quantiles(samples, n=100, method="inclusive")[94] if len(samples) > 1 else median(samples) if samples else None


def judge_metrics(folder):
    calls = [read_json(path) for path in folder.glob("*.json")]
    durations = [row["seconds"] for row in calls]
    return {"calls": len(calls), "p50_seconds": median(durations) if durations else None,
            "p95_seconds": p95(durations), "retries": 0, "failures": sum(bool(row["failure"]) for row in calls)}


class Batch:
    """Receive native completions, bind outcomes and append core/R1 rows independently."""
    def __init__(self, root, index, rows, snapshot, common, layout):
        self.path = root / f"batch-{index}"
        self.path.mkdir()
        self.rollout = self.path / "rollout"
        self.index, self.rows, self.snapshot = index, rows, snapshot
        self.common, self.layout = common, layout
        self.tracks = [(str(row["query_id"]), f'{row["query_id"]}__rep{rep}') for row in rows for rep in range(1, 9)]
        self.questions = {str(row["query_id"]): row["question"] for row in rows}
        self.core_pool = ThreadPoolExecutor(max_workers=4)
        self.judge_pool = ThreadPoolExecutor(max_workers=16)
        self.core_completed, self.completed = {}, {}
        self.lock = threading.Lock()
        self.core_path = self.path / "handoff.jsonl"
        self.diagnostic_path = self.path / "diagnostics" / "r1-sidecar.jsonl"
        self.diagnostic_path.parent.mkdir()
        self.judge = ModelJudge({"url": common["judge"].url + "/v1", "model": common["judge"].model},
                                common["prompt_dir"], self.diagnostic_path.parent / "model_cache",
                                {**common["identity"], "policy_snapshot_id": snapshot,
                                 "policy_snapshot_sha256": snapshot, "batch_number": index})

    def submit(self, question, final, gold, receipt):
        qid, tid = self.tracks[int(receipt.stem)]
        entry = self.rollout / "trajectories" / tid / "trajectory.json"
        timing = {"traj_id": tid, "task_id": qid, "generated_monotonic": time.monotonic()}
        raw = read_json(entry)
        reason = raw["metadata"]["terminal_status"]
        # The frozen grader is unavailable. Its formal field stays unresolved for submitted answers.
        future = Future()
        now = time.monotonic()
        has_final = reason == "MODEL_FINAL_STOP"
        result = {"correct": None if has_final else False, "served_model": None, "queued_at": now,
                  "started_at": now, "ended_at": now, "latency_seconds": 0, "queue_seconds": 0,
                  "retries": 0, "attempts": [],
                  "source": "official_verifier_not_run" if has_final else "terminal_without_final"}
        atomic_json(receipt, result)
        future.set_result(result)
        core = self.core_pool.submit(self.label_core, entry, timing, future)
        self.core_completed[tid] = core
        if self.layout != "A":
            self.completed[tid] = self.judge_pool.submit(self.label_m3, core)
        return future

    def label_core(self, path, timing, outcome):
        tid, qid = timing["traj_id"], timing["task_id"]
        outcome = outcome.result()
        result = None if outcome["correct"] is None else int(outcome["correct"])
        payload = label_trajectory(path, result, self.common["evidence"], self.common["tokenizer"],
                                   environment=self.common["environment"], question=self.questions[qid])
        row = payload["score_row"]
        row.update(policy_snapshot_id=self.snapshot, labeler_versions=self.common["labeler_versions"])
        if result is None:
            row["exclusion_reason"] = "independent_outcome_unresolved"
        elif not row["recording_complete"]:
            row["exclusion_reason"] = "incomplete_native_recording"
        elif row["termination_reason"] not in ("normal", "budget_exhausted"):
            row["exclusion_reason"] = "invalid_terminal"
        safe_append(self.core_path, row, self.lock)
        timing["core_completed_monotonic"] = time.monotonic()
        return payload, timing

    def label_m3(self, core):
        payload, timing = core.result()
        tid, qid = timing["traj_id"], timing["task_id"]
        diagnostic = self.diagnostic_path.parent / (tid + ".json")
        try:
            record_m3(payload, self.judge, policy_snapshot_sha256=self.snapshot, output=diagnostic)
            out = read_json(diagnostic)
        except (KeyError, TypeError, ValueError) as exc:
            out = {"traj_id": tid, "task_id": qid, "policy_snapshot_id": self.snapshot,
                   "status": "excluded", "reason": type(exc).__name__}
            atomic_json(diagnostic, out)
        safe_append(self.diagnostic_path, out, self.lock)
        timing["m3_completed_monotonic"] = time.monotonic()
        return timing

    def drain(self):
        if set(self.core_completed) != {tid for _, tid in self.tracks}:
            raise RuntimeError("native completion ledger is not a complete 16-by-8 batch")
        if self.layout == "A":
            self.completed = {tid: self.judge_pool.submit(self.label_m3, core)
                              for tid, core in self.core_completed.items()}
        receipts = [self.completed[tid].result() for _, tid in self.tracks]
        atomic_json(self.path / "handoff-receipts.json", receipts)
        return receipts

    def scores(self, credit):
        import torch
        from ledger_grpo.browsecomp_adapter import native_trajectory

        if set(self.core_completed) != {tid for _, tid in self.tracks}:
            raise ValueError("training requires a complete snapshot-bound rollout batch")
        for core in self.core_completed.values():
            core.result()
        batch = read_json(self.rollout / "TRAIN_BATCH.json")
        raw_path = self.rollout / "trajectories"
        rows = []
        for recorded in batch["trajectories"]:
            native = native_trajectory(read_json(raw_path / recorded["id"] / "trajectory.json"), reward=recorded["reward"])
            if any(native[k] != recorded[k] for k in ("id", "terminal", "segments")):
                raise ValueError("handoff native trace differs from the source recorder")
            rows.append(native)
        native_path = self.path / "NATIVE_BATCH.json"
        score_path = self.path / "targeted-scores.pt"
        native_batch = {"trajectories": rows, "policy_snapshot_id": self.snapshot,
                        "policy_snapshot_sha256": self.snapshot, "original_batch_sha256": digest(self.rollout/"TRAIN_BATCH.json")}
        atomic_json(native_path, native_batch)
        result = score_coexist_handoff(jsonl(self.core_path), credit, native_batch=native_batch,
                                      expected_policy_snapshot_id=self.snapshot)
        scores = result["scores"]
        scores.update(config=asdict(credit), input_binding={"native_batch_sha256": digest(native_path),
                       "policy_snapshot_sha256": self.snapshot})
        torch.save(scores, score_path)
        atomic_json(self.path / "update-input-receipt.json", {
            "trajectory_count": len(rows), "snapshot": self.snapshot, "native_sha256": digest(native_path),
            "dispositions": result["dispositions"], "metrics": scores["metrics"], "skip_update": scores["skip_update"]})
        return native_path, score_path

    def test_scores(self, native_path, update_root):
        import torch

        if self.layout not in ("A", "C") or self.index != 3:
            raise ValueError("strict-match outcomes are allowed only for the third A/C batch's isolated update")
        native_batch = read_json(native_path)
        answers = {}
        for row in native_batch["trajectories"]:
            if row["terminal"] == "MODEL_FINAL_STOP":
                raw = read_json(self.rollout/"trajectories"/row["id"]/"trajectory.json")
                final = next((r for r in reversed(raw["rounds"]) if r["response_received"]), None)
                if not final or final.get("tool_calls"):
                    raise ValueError("normal termination lacks an independently recorded final response")
                answers[row["id"]] = final.get("content") or ""
        gold = {str(row["query_id"]): row["gold"] for row in self.rows}
        outcomes, score_rows, scored_native = coexist_test_grade.strict_match_updates(
            jsonl(self.core_path), native_batch, answers, gold, snapshot=self.snapshot)
        path = update_root/"test-outcomes.jsonl"
        write_jsonl(path, outcomes)
        credit = self.common["credit"]
        result = score_coexist_handoff(score_rows, credit, native_batch=scored_native,
                                      expected_policy_snapshot_id=self.snapshot)
        scores = result["scores"]
        sha = digest(Path(coexist_test_grade.__file__))
        scores.update(config=asdict(credit), test_only=True, result_source=coexist_test_grade.RESULT_SOURCE,
                      strict_rule_sha256=sha,
                      input_binding={"native_batch_sha256": digest(native_path), "policy_snapshot_sha256": self.snapshot,
                                     "test_outcomes_sha256": digest(path)})
        score_path = update_root/"targeted-scores.test-only.pt"
        torch.save(scores, score_path)
        correct = sum(row["test_outcome"] for row in outcomes)
        submitted = sum(row["had_final"] for row in outcomes)
        all_wrong = len(gold) - len({row["task_id"] for row in outcomes if row["test_outcome"]})
        atomic_json(update_root/"test-scoring-receipt.json", {
            "result_source": coexist_test_grade.RESULT_SOURCE, "rule_sha256": sha,
            "policy_snapshot_id": self.snapshot, "test_outcomes_sha256": digest(path),
            "original_B_batch_1_http_402": 56, "original_B_batch_2_partial_http_402": 24,
            "external_requests": 0, "test_correct": correct, "test_wrong": len(outcomes) - correct,
            "test_submitted_incorrect": submitted-correct, "no_final_counted_zero": len(outcomes)-submitted,
            "all_wrong_groups": all_wrong,
            "eligible_groups": scores["metrics"]["valid_row_count"] // credit.group_size,
            "groups_entering_update": 0 if scores["skip_update"] else scores["metrics"]["valid_row_count"] // credit.group_size,
            "dispositions": result["dispositions"], "stage": "isolated_test_update"})
        return score_path

    def close(self):
        self.judge_pool.shutdown(wait=True, cancel_futures=True)
        self.core_pool.shutdown(wait=True, cancel_futures=True)


def load_trial_environment(config, output):
    backend = Path(config["backend"])
    sys.path.insert(0, str(backend))
    from isolate_runtime import install_runtime_isolation
    install_runtime_isolation()
    from src.stability_controller import read_hardware
    from coexist_runtime import versions

    devices = os.environ["CUDA_VISIBLE_DEVICES"].split(",")
    uuids, hardware = read_hardware()
    read_config = read_json(config["plan"])
    rows = read_config["training_rows"]
    if len(rows) != 16 or len({row["query_id"] for row in rows}) != 16:
        raise ValueError("trial requires the 16 frozen training questions")
    settings = read_json(config["credit_settings"])
    from event_price_pilot import training_config
    credit, semantic = training_config(settings)
    if semantic or credit.group_size != 8 or credit.r1_price != 0 or credit.r2a_price != 0 or credit.r2b_price != .10:
        raise ValueError("frozen credit settings differ from R2b-only 16-by-8 scoring")
    signature = read_json(config["phase1_manifest"])["freeze"]
    config["judge_fingerprint"] = signature["model_version"]
    prompt_names = ("m3v3_intent", "m3v3_verification")
    prompt_dir = Path(config["prompts"])
    labeler_versions = {"judge_model": signature["model_version"], "code_commit": config["code_commit"],
                        "prompt_hashes": {name: digest(prompt_dir / (name + ".md")) for name in prompt_names}}
    atomic_json(output/"hardware.json", {"devices": hardware, "uuid": uuids,
                "runtime": {"actor": versions(sys.executable), "judge": versions(config["judge_python"])}})
    common = {"rows": rows, "credit": credit,
              "identity": {"study": "four-a800-coexistence", "versions": labeler_versions},
              "prompt_dir": prompt_dir, "labeler_versions": labeler_versions,
              "evidence": load_evidence_snapshot(config["evidence_snapshot"]),
              "tokenizer": NativeByteTokenizer(config["actor_tokenizer"], signature["tokenizer_version"]),
              "environment": {"id": config["retrieval_environment"], "deterministic_tools": ["search-server-search"]}}
    return devices, uuids, common


def test_update(batch, inputs, root, monitor, layout):
    native, _ = inputs
    trainer = Path(__file__).with_name("coexist_train.py")
    output = root / "isolated-update"
    output.mkdir()
    scores = batch.test_scores(native, output)
    command = [sys.executable, "-u", "-m", "torch.distributed.run", "--standalone", "--nproc_per_node=4",
               str(trainer), "--native-batch", str(native), "--scores", str(scores), "--output-root", str(output),
               "--snapshot-dir", str(output / "test-snapshots"), "--publication-id", "1", "--steps", "1"]
    env = dict(os.environ)
    env.pop("OCCAM_ACTOR_ADMIN", None)
    env["COEXIST_TEST_OUTCOME_RECEIPT"] = str(output / "test-outcomes.jsonl")
    with monitor.phase("fsdp_test_update", layout=layout, batch=3), (output / "trainer.log").open("wb") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, check=False)
    receipts = output / "step-0001"
    if result.returncode:
        raise RuntimeError("isolated FSDP worker failed; see receipt and trainer.log")
    return {"step_complete": (receipts/"STEP_COMPLETE.json").is_file(), "skipped": (receipts/"SKIPPED.json").is_file()}


def compare_frozen(config, judge, common, root):
    from coexist_consistency import compare_all
    return compare_all(config, judge, common, root)


def run_layout(config, layout, output, devices, common, monitor):
    from src.stability_rollout import run_rollout
    from src.resident_controller import fingerprint as read_actor_fingerprint, generated_probe

    attempts = 2 if layout == "C" else 1
    for number in range(attempts):
        root = output / f"{layout}-{number+1}"
        root.mkdir()
        secret, gate = secrets.token_urlsafe(32), root/"actor-gate"
        actor_devices = devices[:2] if layout == "B" else devices
        judge_devices = devices[2:] if layout == "B" else devices
        fractions = actor_fractions(layout, number != 0)
        judge_fraction = (.40 if not number else .34) if layout == "C" else .88
        os.environ.update(OCCAM_ACTOR_ADMIN=secret, OCCAM_ACTOR_GATE=str(gate), OCCAM_SNAPSHOT_DIR=str(root/"test-actor-gate"))
        (root/"test-actor-gate").mkdir()
        os.chdir(root)
        actor = ActorServices(root/"actor-services", actor_devices, fractions, gate, secret)
        judge = JudgeService(root/"judge-service", config["judge_python"], config["judge_model"], judge_devices, judge_fraction)
        report = {"layout": layout, "attempt": number+1, "actor_fractions": fractions, "judge_fraction": judge_fraction,
                  "launch_succeeded": False, "batches": [], "update": None}
        batch = None
        update_started = None
        try:
            with monitor.phase("judge_start", layout=layout, attempt=number+1):
                judge.start()
            if layout == "A":
                with monitor.phase("judge_preloaded_sleep", layout=layout):
                    judge.transition(True)
            with monitor.phase("actor_and_retriever_start", layout=layout, attempt=number+1):
                fingerprint = actor.start()
                outputs = actor.actors.all(generated_probe)
                atomic_json(root/"actor-native-probes.json", {"initial": outputs, "weight_fingerprint": fingerprint})
            report["launch_succeeded"] = True
            snapshot = identity([config["actor_revision"], fingerprint, config["base_model"]])
            report["policy_snapshot_id"] = snapshot
            common["judge"] = judge
            for index in range(config.get("first_batch_by_layout", {}).get(layout, 1), 4):
                step_start = time.monotonic()
                batch = Batch(root, index, common["rows"], snapshot, common, layout)
                for i, server in enumerate(actor.servers):
                    save_prometheus(server.url, batch.path / f"actor-{i}-before.prom")
                with monitor.phase("generation", layout=layout, batch=index):
                    generated = run_rollout(batch.rollout, index, batch.rows, config["seed"], actor.servers, actor.port,
                                             actor.root/"retriever"/"TOOL_TIMING.jsonl", batch)
                for i, server in enumerate(actor.servers):
                    save_prometheus(server.url, batch.path / f"actor-{i}-after.prom")
                if layout == "A":
                    with monitor.phase("actor_sleep", layout=layout, batch=index):
                        transition_actors(actor.actors, sleeping=True)
                        actor.search.post("/occam-residency", {"action": "cpu"})
                    with monitor.phase("judge_wake", layout=layout, batch=index):
                        judge.transition(False)
                with monitor.phase("verify_update_handoff", layout=layout, batch=index):
                    update_inputs = batch.scores(common["credit"])
                with monitor.phase("drain_labels", layout=layout, batch=index):
                    receipts = batch.drain()
                if layout == "A" and index < 3:
                    with monitor.phase("judge_sleep", layout=layout, batch=index):
                        judge.transition(True)
                    with monitor.phase("actor_wake", layout=layout, batch=index):
                        actor.search.post("/occam-residency", {"action": "cuda"})
                        transition_actors(actor.actors, sleeping=False)
                genesis = generated["generation_start"]
                latest = max(r["m3_completed_monotonic"] for r in receipts)
                tail_start = sorted(r["generated_monotonic"] for r in receipts)[len(receipts) - math.ceil(len(receipts)*.10) - 1]
                native = read_json(batch.rollout/"TRAJECTORY_METRICS.json")
                summary = {"batch": index, "trajectories": len(receipts), "generated_tokens": sum(row["generated_tokens"] for row in native),
                           "generation_seconds": generated["generation_seconds"], "generation_tail_seconds": generated["generation_end"]-tail_start,
                           "tail_start_epoch": time.time() - (time.monotonic()-tail_start),
                           "tail_end_epoch": time.time() - (time.monotonic()-generated["generation_end"]),
                           "judge_tail_seconds": max(0, latest-generated["generation_end"]),
                           "generation_start_monotonic": genesis, "step_seconds_to_training": time.monotonic()-step_start,
                           "max_seen_context": max(row["context_tokens_max"] for row in native),
                           "outcome_verification": generated["api"],
                           "m3": judge_metrics(batch.diagnostic_path.parent/"m3_call_receipts")}
                summary["generation_tokens_per_second"] = summary["generated_tokens"] / summary["generation_seconds"]
                report["batches"].append(summary)
                atomic_json(root/"result.json", report)
                if index < 3:
                    batch.close()
            if layout in ("A", "C"):
                update_started = time.monotonic()
                with monitor.phase("sleep_before_update", layout=layout, batch=3):
                    if layout == "C":
                        transition_actors(actor.actors, sleeping=True)
                        actor.search.post("/occam-residency", {"action": "cpu"})
                    judge.transition(True)
                report["update"] = test_update(batch, update_inputs, root, monitor, layout)
                with monitor.phase("post_update_actor_wake", layout=layout):
                    if layout == "C":
                        judge.transition(False)
                    actor.search.post("/occam-residency", {"action": "cuda"})
                    transition_actors(actor.actors, sleeping=False)
                    # Both Actor and test snapshot remain independent of any experiment arm.
                    if set(actor.actors.all(read_actor_fingerprint)) != {fingerprint}:
                        raise RuntimeError("Actor wake failed to restore the original frozen weights")
                    probes = actor.actors.all(generated_probe)
                    atomic_json(root/"actor-native-probes.json", {"initial": outputs, "after_wake": probes,
                                                                 "weight_fingerprint": fingerprint})
                report["batches"][-1]["step_seconds_including_update"] = (
                    report["batches"][-1]["step_seconds_to_training"] + time.monotonic()-update_started)
            else:
                report["update"] = {"performed": False, "reason": "B has no requested parameter update"}
            if layout == "A":
                with monitor.phase("park_actor_for_frozen_validation", layout=layout):
                    transition_actors(actor.actors, sleeping=True)
                    actor.search.post("/occam-residency", {"action": "cpu"})
                    judge.transition(False)
            with monitor.phase("frozen_label_consistency", layout=layout):
                report["consistency"] = compare_frozen(config, judge, common, root)
            report["status"] = "completed"
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__, error=str(exc), allocator_pressure=memory_failure(root))
            print(layout, number+1, report["error_type"], flush=True)
            import traceback
            (root/"failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            if batch is not None:
                batch.close()
            actor.close()
            judge.close()
            atomic_json(root/"result.json", report)
        if not (layout == "C" and not number and update_started is None and report.get("allocator_pressure")):
            return report
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    config, output = read_json(args.config), args.output.resolve()
    layouts = config.get("layouts", ["A", "B", "C"])
    if not layouts or len(set(layouts)) != len(layouts) or any(name not in ("A", "B", "C") for name in layouts):
        raise ValueError("trial layouts must be unique names among A, B and C")
    devices, uuids, common = load_trial_environment(config, output)
    monitor = Telemetry(output, uuids)
    try:
        results = [run_layout(config, name, output, devices, common, monitor) for name in layouts]
        atomic_json(output/"comparison.json", results)
    finally:
        monitor.close()


if __name__ == "__main__":
    main()
