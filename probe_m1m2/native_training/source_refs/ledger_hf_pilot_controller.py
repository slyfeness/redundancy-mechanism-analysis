"""Isolated one-update, matched-objective pilot on the frozen resident runtime."""
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import random
import secrets
import statistics
import subprocess
import sys
import threading
import time

from ledger_grpo.advantages import AdvantageConfig
from ledger_grpo.browsecomp_adapter import adapt_trajectory, extract_constraints
from ledger_grpo.observability import EventWriter, advantage_payload, rollout_payload, render_monitor
from ledger_grpo.evaluation import paired_bootstrap
from ledger_grpo.pipeline import analyze_trajectory, score_batch
from process_preflight import BoundedJudge, read, write


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def extract_training_frames(questions, active, judge, *, extractor=None):
    """A failed task frame disables its process labels, never its outcome credit."""
    extractor = extract_constraints if extractor is None else extractor
    active, frames, failures = set(active), {}, {}
    for qid, row in questions.items():
        if qid in active:
            try:
                frames[qid] = extractor(row["question"], judge)
                if not isinstance(frames[qid],list) or not frames[qid] or any(
                        not isinstance(c,dict) or not isinstance(c.get("cid"),str) or not c["cid"]
                        or not isinstance(c.get("text"),str) or not c["text"] for c in frames[qid]):
                    raise ValueError("empty task frame")
                continue
            except Exception as error:
                failures[qid] = type(error).__name__
                active.remove(qid)
        # Schema carrier only: this is explicitly NOT an extracted valid frame.
        frames[qid] = [{"cid": "frame_unavailable", "text": "Task constraints unavailable; process labels disabled."}]
    return frames, active, failures


def select_update_arms(comparison):
    candidates = ["outcome"] if comparison["objectives_exactly_identical"] else ["outcome", "ledger"]
    skipped = {"ledger": "equivalent_objective_not_reexecuted"} if len(candidates) == 1 else {}
    arms = []
    for arm in candidates:
        if comparison["arm_update_capable"].get(arm) is True:
            arms.append(arm)
        else:
            skipped[arm] = "no_effective_nonzero_advantage"
    return arms, skipped


def score_training(rollout, questions, output, key, writer, *, arm_writers):
    import torch
    output.mkdir()
    original = read(rollout / "TRAIN_BATCH.json")["trajectories"]
    grouped = {}
    for row in original:
        grouped.setdefault(str(row["query_id"]), []).append(row)
    if any(len(rows) != 8 for rows in grouped.values()):
        raise ValueError("incomplete same-question rollout group")
    # Entire unresolved or zero-action groups are excluded, never relabelled 0.
    dropped = {qid: "unresolved_outcome_or_no_policy_tokens" for qid, rows in grouped.items()
               if any(r["reward"] not in (0., 1.) or not r["segments"] for r in rows)}
    rows = [row for row in original if str(row["query_id"]) not in dropped]
    if not rows:
        native_path=output/"NATIVE_BATCH.json"
        write(native_path,{"trajectories":[],"original_batch_sha256":sha(rollout/"TRAIN_BATCH.json")})
        summary={"dropped_groups":dropped,"process_annotated_groups":[],"frame_qa_failed":{},
                 "arm_update_capable":{"outcome":False,"ledger":False},"changed_advantage_tokens":0,
                 "maximum_advantage_delta":0.,"objectives_exactly_identical":True,
                 "outcome_metrics":None,"ledger_metrics":None}
        write(output/"SCORE_COMPARISON.json",summary)
        return native_path,summary
    active = {qid for qid, group in grouped.items() if qid not in dropped
              and all(row["terminal"] == "MODEL_FINAL_STOP" for row in group)
              and any(row["reward"] == 1 for row in group)}
    questions = {str(row["query_id"]): row for row in questions}
    constraint_judge = BoundedJudge(key)
    constraints, active, frame_failures = extract_training_frames(
        {qid: questions[qid] for qid in grouped.keys() - dropped.keys()}, active, constraint_judge)
    write(output / "CONSTRAINTS.json", constraints)
    write(output / "PROCESS_SELECTION.json", {"annotated_groups": sorted(active), "excluded_groups": dropped,
          "frame_qa_failed": frame_failures,
          "reason": "budget-member groups have process reward disabled by explicit policy; all-wrong groups excluded",
          "coverage_limitation": "process labels on selected groups only; not population redundancy prevalence"})

    def process(row):
        qid = str(row["query_id"])
        raw = read(rollout / "trajectories" / row["id"] / "trajectory.json")
        trace, native = adapt_trajectory(raw, questions[qid]["question"], constraints[qid], outcome=int(row["reward"]))
        if (native["id"] != row["id"] or native["query_id"] != qid or native["terminal"] != row["terminal"]
                or native["segments"] != row["segments"]):
            raise ValueError("native record/graded batch identity mismatch")
        judge = BoundedJudge(key) if qid in active else None
        report = analyze_trajectory(trace, judge=judge)
        if qid not in active:
            report["qa"].update(parse_ok=False, citations_verified=False,
                                frame_qa_failed=qid in frame_failures)
            report["qa"]["errors"].append({"turn": None, "kind": "frame_qa_failed" if qid in frame_failures else "process_not_annotated",
                                            "message": "No validated task frame; process reward disabled."})
            report["metrics"]["grounding_score"] = None
            for span in report["spans"]:
                span["reward_eligible"] = False
        folder = output / row["id"]
        folder.mkdir()
        write(folder / "trace.json", trace)
        write(folder / "report.json", report)
        if judge:
            write(folder / "checks.json", judge.check_audit)
        stats = {"annotated": judge is not None, "judge_requests": judge.requests if judge else 0,
                 "judge_usage": judge.usage if judge else None, "qa_ok": report["qa"]["parse_ok"]}
        write(folder / "metrics.json", stats)
        payload = rollout_payload(trace, report, sample_id=row["id"], split="train",
                                  extra_metrics={"judge_input_tokens": judge.usage["prompt_tokens"] if judge else 0,
                                                 "judge_output_tokens": judge.usage["completion_tokens"] if judge else 0})
        writer.emit("rollout.scored", payload, event_id="train-"+row["id"], batch_id="p0-training",
                    policy_version="P0", optimizer_steps_committed=0)
        return trace, report, native

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        scored = list(pool.map(process, rows))
    traces, reports, native = map(list, zip(*scored))
    native_path = output / "NATIVE_BATCH.json"
    write(native_path, {"trajectories": native, "original_batch_sha256": sha(rollout / "TRAIN_BATCH.json")})
    advantages = {}
    for arm in ("outcome", "ledger"):
        result = score_batch(traces, reports, config=AdvantageConfig(process_enabled=arm == "ledger"),
                             budget_failure_policy="outcome_only")
        result["input_binding"] = {"native_batch_sha256": sha(native_path),
                                   "report_sha256": {trace["traj_id"]: sha(output / trace["traj_id"] / "report.json") for trace in traces}}
        torch.save(result, output / (arm + "-scores.pt"))
        arm_writers[arm].emit("advantage.computed", advantage_payload(result, task_ids=[t["task_id"] for t in traces]),
                    event_id=arm+"-advantage", batch_id="p0-training", policy_version="P0", optimizer_steps_committed=0)
        render_monitor(arm_writers[arm].path,arm_writers[arm].path.parent/"monitor.html")
        advantages[arm] = result
    changed = (advantages["outcome"]["advantages"] - advantages["ledger"]["advantages"]).abs()
    summary = {"dropped_groups": dropped, "process_annotated_groups": sorted(active),
               "frame_qa_failed": frame_failures,
               "arm_update_capable": {arm: bool(((result["advantages"] != 0) & result["effective_response_mask"].bool()).any())
                                      and not result.get("skip_update", False) for arm, result in advantages.items()},
               "changed_advantage_tokens": int((changed > 0).sum()), "maximum_advantage_delta": changed.max().item(),
               "objectives_exactly_identical": torch.equal(advantages["outcome"]["advantages"], advantages["ledger"]["advantages"])
                 and torch.equal(advantages["outcome"]["effective_response_mask"], advantages["ledger"]["effective_response_mask"]),
               "outcome_metrics": advantages["outcome"]["metrics"], "ledger_metrics": advantages["ledger"]["metrics"]}
    write(output / "SCORE_COMPARISON.json", summary)
    return native_path, summary


def evaluation_summary(folder, *, expected_task_ids=None):
    rows = read(folder / "TRAJECTORY_METRICS.json")
    safe, seen = [], set()
    for row in rows:
        identity = str(row["query_id"]), str(row["id"])
        if identity in seen:
            raise ValueError("duplicate evaluation task/sample identity")
        seen.add(identity)
        reward = row.get("reward")
        if reward is not None and (type(reward) not in (int, float) or reward not in (0, 1)):
            raise ValueError("evaluation reward must be binary or unresolved")
        cost, calls = row["generated_tokens"], row["tool_calls"]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (cost, calls)):
            raise ValueError("evaluation costs must be finite and nonnegative")
        safe.append({"task_id":identity[0], "sample_id":identity[1], "outcome":reward,
                     "complete":row["terminal"] == "MODEL_FINAL_STOP", "cost":cost,
                     "gen_tokens":cost, "tool_calls":calls})
    if expected_task_ids is not None and {r["task_id"] for r in safe} != {str(v) for v in expected_task_ids}:
        raise ValueError("fixed evaluation task manifest does not match observed tasks")
    return dict(summarize_evaluation_rows(safe), rows=safe,
                process_metrics="not annotated; no claim about evaluation redundancy or grounding")


def summarize_evaluation_rows(safe):
    """Recompute outcome aggregates without altering recorded cost or process fields."""
    resolved = [r for r in safe if r["outcome"] is not None]
    groups = {}
    for row in safe:
        groups.setdefault(row["task_id"], []).append(row)
    successes = sum(r["outcome"] for r in resolved)
    return {"sample_count": len(safe), "resolved_count": len(resolved), "task_count": len(groups),
            "accuracy": successes/len(safe) if safe and len(resolved)==len(safe) else None,
            "outcome_coverage":len(resolved)/len(safe) if safe else 0.,
            "completion_rate": statistics.fmean(r["complete"] for r in safe) if safe else None,
            "mean_generated_tokens": statistics.fmean(r["cost"] for r in safe) if safe else None,
            "mean_tool_calls": statistics.fmean(r["tool_calls"] for r in safe) if safe else None,
            "cost_per_success":sum(r["cost"] for r in safe)/successes if successes and len(resolved)==len(safe) else None,
            "tasks": {qid: {"accuracy": statistics.fmean(r["outcome"] for r in group) if all(r["outcome"] is not None for r in group) else None,
                            "generated_tokens": statistics.fmean(r["cost"] for r in group)} for qid, group in groups.items()}}


def paired_comparisons(evaluations, *, training_seed, bootstrap_seed=20261111, resamples=2000):
    """Exploratory task-paired intervals for ONE training seed, never seed CIs."""
    comparisons = {}
    initial = "P0" if "P0" in evaluations else "resume_base"
    pairs = [(initial, arm) for arm in evaluations if arm != initial]
    pairs += [("outcome", arm) for arm in evaluations if arm not in (initial, "outcome")]
    pairs += [(arm, "targeted") for arm in ("trajectory", "shuffled", "uniform") if arm in evaluations]
    for baseline, candidate in pairs:
        if baseline not in evaluations or candidate not in evaluations:
            continue
        left, right = evaluations[baseline]["rows"], evaluations[candidate]["rows"]
        if not left or {(r["task_id"],r["sample_id"]) for r in left} != {(r["task_id"],r["sample_id"]) for r in right}:
            raise ValueError("paired evaluation task/sample manifests differ")
        common = {"training_seed":training_seed,"training_seed_count":1,"bootstrap_seed":bootstrap_seed,
                  "baseline":baseline,"candidate":candidate,"exploratory":True,
                  "interpretation":"one training seed; task-sampling uncertainty only; no convergence or noninferiority claim"}
        if all(r["outcome"] is not None for r in left+right):
            result = paired_bootstrap(left,right,seed=bootstrap_seed,resamples=resamples)
            result.pop("seed")
            result.update(state="complete", **common)
        else:
            # Cost remains observed even when grading fails; never impute an outcome.
            tasks=sorted({r["task_id"] for r in left})
            delta=[statistics.fmean(r["cost"] for r in right if r["task_id"]==task)
                   -statistics.fmean(r["cost"] for r in left if r["task_id"]==task) for task in tasks]
            rng=random.Random(bootstrap_seed)
            samples=sorted(statistics.fmean(rng.choices(delta,k=len(delta))) for _ in range(resamples))
            def quantile(q):
                pos=(len(samples)-1)*q; lo,hi=math.floor(pos),math.ceil(pos)
                return samples[lo]+(samples[hi]-samples[lo])*(pos-lo)
            result=dict(common,state="unresolved_outcomes",task_count=len(tasks),unit="task_id",resamples=resamples,
                        accuracy_delta=None,cost_delta={"estimate":statistics.fmean(delta),"ci95":[quantile(.025),quantile(.975)]})
        comparisons[candidate+"_minus_"+baseline]=result
    return comparisons


def emit_fixed_evaluation(writer, summary, *, name, manifest_id, rollout_seed, comparison=None):
    evaluation_id="fixed-"+name
    for row in summary["rows"]:
        payload={"traj_id":row["sample_id"],"task_id":row["task_id"],"sample_id":row["sample_id"],
                 "split":"eval","evaluation_id":evaluation_id,"outcome":row["outcome"],"complete":row["complete"],
                 "gen_tokens":row["gen_tokens"],"tool_calls":row["tool_calls"],"cost":row["cost"],"cost_unit":"policy_tokens",
                 "rollout_seed":rollout_seed,"grounding_score":None,"outcome_source":"independent_verifier"}
        payload.update({k: row[k] for k in ("budget_exhausted", "explicit_abandon", "exact_repeat_events",
                        "measured_return_tokens", "unmarked_event_cost", "recorded_tool_events",
                        "measured_tool_events", "reasoning_tokens", "reasoning_rounds", "reasoning_observed_rounds",
                        "reasoning_derived_tokens", "reasoning_derived_rounds") if k in row})
        writer.emit("rollout.scored",payload,event_id=evaluation_id+":"+row["sample_id"],policy_version=name)
    payload={"evaluation_id":evaluation_id,"checkpoint_id":name,"eval_manifest_id":manifest_id,
             "sample_count":summary["sample_count"],"task_count":summary["task_count"],"accuracy":summary["accuracy"],
             "completion_rate":summary["completion_rate"],"mean_cost":summary["mean_generated_tokens"],
             "mean_gen_tokens":summary["mean_generated_tokens"],"cost_per_success":summary["cost_per_success"],
             "cost_unit":"policy_tokens","mean_grounding":None,"grounding_observed":0,"grounding_coverage":0.}
    if comparison:
        payload.update(baseline_id=comparison["baseline"],pair_set_id=manifest_id,bootstrap_seed=comparison["bootstrap_seed"],
                       paired_cost_delta=comparison["cost_delta"]["estimate"],paired_cost_ci=comparison["cost_delta"]["ci95"])
        if comparison["accuracy_delta"] is not None:
            payload.update(paired_accuracy_delta=comparison["accuracy_delta"]["estimate"],
                           paired_accuracy_ci=comparison["accuracy_delta"]["ci95"])
    writer.emit("evaluation.completed",payload,event_id=evaluation_id+":complete",policy_version=name)
    render_monitor(writer.path,writer.path.parent/"monitor.html")


def record_optimizer_receipt(root, writer, *, terminal=False, world_size=4, update_index=1):
    """Translate actual rank callbacks; a checkpoint failure cannot undo a step."""
    root=Path(root); step=root/f"step-{update_index:04d}"
    previous=update_index-1
    def optional(path):
        return read(path) if path.is_file() else None
    returned=[]; identities=set()
    for rank in range(world_size):
        receipt=optional(step/f"OPTIMIZER_RETURNED-rank{rank}.json")
        if receipt is not None:
            if receipt.get("state")!="optimizer_returned" or receipt.get("rank")!=rank or receipt.get("optimizer_step")!=update_index:
                raise ValueError("inconsistent optimizer callback receipt")
            returned.append(rank); identities.add(receipt.get("batch_identity"))
    if len(identities)>1:
        raise ValueError("rank callbacks name different native batches")
    computed=optional(step/"UPDATE_COMPUTED.json")
    skipped=optional(step/"SKIPPED.json")
    full=len(returned)==world_size
    if computed and (not full or computed.get("computed_optimizer_steps")!=update_index or computed.get("optimizer_steps_this_batch")!=1):
        raise ValueError("computed receipt is not backed by one confirmed optimizer step on every rank")
    if full and previous:
        restored = [optional(step/f"RESUME-rank{rank}.json") for rank in range(world_size)]
        if (any(not r or r.get("rank")!=rank or r.get("restored_step")!=previous for rank,r in enumerate(restored))
                or len({r["checkpoint_receipt_sha256"] for r in restored}) != 1):
            raise ValueError("optimizer callbacks lack matching per-rank checkpoint restores")
    if skipped and returned:
        raise ValueError("worker cannot both skip and return from optimizer")
    checkpoint=optional(root/"checkpoints"/step.name/"COMPLETE.json")
    persisted=optional(step/"CHECKPOINT_PERSISTED.json")
    published=optional(step/"STEP_COMPLETE.json")
    checkpoint_ok=bool(full and checkpoint and persisted and checkpoint.get("optimizer_step")==update_index
                       and persisted.get("persisted_optimizer_steps")==update_index)
    snapshot_ok=bool(checkpoint_ok and published and published.get("snapshot_published") is True)
    result={"state":"pending","optimizer_returned_ranks":returned,"optimizer_steps_committed":None,
            "checkpoint_persisted":checkpoint_ok,"snapshot_published":snapshot_ok}
    payload=None
    if skipped:
        result.update(state="skipped",optimizer_steps_committed=0,skip_reason=skipped.get("skip_reason"))
        payload={"update_id":f"step-{update_index}","status":"skipped","source":"optimizer_callback",
                 "steps_before":previous,"steps_after":previous,
                 "reason":"no_valid_rows" if skipped.get("skip_reason")=="score_or_mask_skip_update" else "other"}
    elif full and (computed or terminal):
        source=computed or {}
        metrics={"policy_loss":source.get("loss"),"entropy":source.get("entropy"),
                 "grad_norm_pre_clip":source.get("gradient_norm_before_clip"),"grad_norm":source.get("gradient_norm_before_clip"),
                 "lr":source.get("learning_rate"),"effective_policy_tokens":source.get("effective_action_tokens"),
                 "approx_kl":None,"reference_kl":None,"clip_fraction":None}
        payload={"update_id":f"step-{update_index}","status":"committed","source":"optimizer_callback",
                 "steps_before":previous,"steps_after":update_index,
                 "metrics":metrics,"metric_definitions":{"grad_norm":"pre_clip","reduction":
                     source.get("loss_reduction", "token_mean")}}
        result.update(state="committed",optimizer_steps_committed=1)
    elif terminal:
        result["state"]="partial_optimizer_return" if returned else "failed_unconfirmed"
    if payload:
        batch_id = "p0-training" if update_index == 1 else f"stage-{update_index}-training"
        if writer.emit("optimizer.result",payload,event_id=f"optimizer-step-{update_index}",batch_id=batch_id,
                       trainer_iteration=update_index):
            render_monitor(writer.path,writer.path.parent/"monitor.html")
    return result


def run_phase(root, state, phases, name, callback, *, heartbeat_seconds=5):
    """Persist phase timing during blocking work and preserve failed phase records."""
    root=Path(root); started=time.monotonic(); stop=threading.Event(); lock=threading.Lock()
    state.update(phase=name,phase_state="running",phase_elapsed_seconds=0.)
    def heartbeat():
        while not stop.wait(heartbeat_seconds):
            with lock:
                state["phase_elapsed_seconds"]=time.monotonic()-started
                write(root/"STATUS.json",state)
    write(root/"STATUS.json",state)
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    print(json.dumps({"phase":name,"state":"started"}),flush=True)
    phase_state="completed"
    try:
        return callback()
    except BaseException:
        phase_state="failed"
        raise
    finally:
        stop.set();thread.join()
        record={"phase":name,"seconds":time.monotonic()-started,"state":phase_state}
        phases.append(record)
        state.update(phase_state=phase_state,phase_elapsed_seconds=record["seconds"])
        write(root/"PHASES.json",phases);write(root/"STATUS.json",state)
        print(json.dumps(record),flush=True)


def main():
    source = Path(__file__).resolve().parents[1]
    backend = Path(os.environ["LEDGER_HF_BACKEND_SOURCE"])
    sys.path.insert(0, str(backend))
    from src.stability_controller import Services, read_hardware, GPUMonitor
    from isolate_runtime import install_runtime_isolation
    install_runtime_isolation()
    from src.stability_rollout import run_rollout
    from src.stability_judge import FlashJudge
    from src.resident_controller import generated_probe
    plan_path = Path(os.environ["LEDGER_PILOT_PLAN"])
    plan = read(plan_path)
    settings_path = os.environ.get("LEDGER_EVENT_PRICE_SETTINGS")
    settings = read(Path(settings_path)) if settings_path else None
    runs_root = Path(os.environ["LEDGER_PILOT_STORE"]).resolve()/"runs"
    parent, update_index = None, 1
    arm_names = ("outcome", "ledger")
    if settings is not None:
        from event_price_pilot import (add_evaluation_event_metrics, choose_training_rows,
                                       schedule_stage, score_event_training, verified_baseline)
        from cold_actor import start_cold_actors
        parent, arm_names = schedule_stage(settings,runs_root=runs_root)
        update_index = settings["price_schedule"]["update"]
        plan["training_rows"] = choose_training_rows(plan["training_rows"], settings)
    initial_name = "resume_base" if parent else "P0"
    root = runs_root / ("pilot-"+os.environ["SLURM_JOB_ID"])
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chdir(root)  # incidental Qwen-Agent workspace/cache stays on bulk storage
    write(root / "PLAN.json", {k: v for k, v in plan.items() if k not in {"training_rows", "evaluation_rows"}})
    write(root / "SOURCE_IDENTITIES.json", {str(p.relative_to(source)): sha(p) for p in source.rglob("*.py")})
    key = Path(os.environ["LEDGER_JUDGE_KEY_FILE"]).read_text().strip()
    config_hash = sha(plan_path)
    if settings is not None:
        config_hash = hashlib.sha256((config_hash + sha(settings_path)).encode()).hexdigest()
        write(root/"EVENT_PRICE_SETTINGS.json", settings)
        if parent:
            write(root/"RESUME_SOURCE.json", parent)
        from pilot_rollout_shape import adapt_rollout_shape
        run_rollout, shape_receipt = adapt_rollout_shape(run_rollout, root/"adapted_rollout.py")
        write(root/"ROLLOUT_SOURCE.json", shape_receipt)
    training_seed=20261109
    eval_seed=2026111100
    eval_manifest=hashlib.sha256(json.dumps(plan["evaluation_rows"],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    expected_eval_tasks=[row["query_id"] for row in plan["evaluation_rows"]]
    writer = EventWriter(root / "metrics.jsonl", run_id=root.name+":controller", training_seed=training_seed, config_hash=config_hash)
    writer.emit("run.started", {"model_id": "Qwen3.5-9B", "trainer_backend": "native_hf_fsdp", "cost_unit": "policy_tokens",
                               "judge_model": "deepseek-flash", "process_enabled": True,
                               "metric_definitions": {"reduction": "token_mean", "grad_norm": "pre_clip"}}, event_id="start")
    arm_writers={}
    for arm in (initial_name, *arm_names):
        arm_writers[arm]=EventWriter(root/arm/"metrics.jsonl",run_id=root.name+":"+arm,
                                     training_seed=training_seed,config_hash=config_hash)
        arm_writers[arm].emit("run.started",{"run_kind":"training","model_id":"Qwen3.5-9B",
                "trainer_backend":"native_hf_fsdp","cost_unit":"policy_tokens","process_enabled":arm not in (initial_name, "outcome"),
                "metric_definitions":{"reduction":"token_mean","grad_norm":"pre_clip"}},event_id="start")
    snapshots = root / "policy-snapshots"
    snapshots.mkdir()
    secret, gate = secrets.token_urlsafe(32), root / "actor-gate"
    os.environ.update(OCCAM_ACTOR_ADMIN=secret, OCCAM_ACTOR_GATE=str(gate), OCCAM_SNAPSHOT_DIR=str(snapshots))
    devices = os.environ["CUDA_VISIBLE_DEVICES"].split(",")
    uuids, hardware = read_hardware()
    write(root / "HARDWARE.json", hardware)
    monitor = GPUMonitor(uuids)
    services = Services(root / "services", devices, secret, gate)
    judge = FlashJudge(key)
    state = {"state": "running", "phase": "service_startup", "optimizer_steps_committed": 0, "checkpoints_persisted": 0,
             "counter_scope":"new commits across arms; each performs at most one update from the same stage input policy",
             "arms":{},"actual_update_capable":None}
    phases = []
    def phase(name, callback):
        return run_phase(root,state,phases,name,callback)
    def rollout(name, rows, seed):
        return run_rollout(root / name, 1, rows, seed, services.servers, services.port,
                           services.root / "retriever/TOOL_TIMING.jsonl", judge)
    def summarize_evaluation(folder):
        summary = evaluation_summary(folder,expected_task_ids=expected_eval_tasks)
        if settings is not None:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(os.environ["LEDGER_BASE_MODEL"], local_files_only=True)
            add_evaluation_event_metrics(folder, summary, tokenizer)
        return summary
    evaluations, comparisons, arm_receipts, executed, skipped_arms = {}, {}, {}, [], {}
    comparison=None
    try:
        phase("services_ready", lambda: services.start(.75, None))
        input_snapshot = None
        if parent:
            loaded = phase("restore_stage_input_actors", lambda: start_cold_actors(
                services, os.environ["LEDGER_BASE_MODEL"], Path(parent["snapshot_directory"]),
                parent["snapshot_receipt"], log_root=root/"actors-resume-base"))
            input_snapshot = loaded["sha256"]
            if input_snapshot != parent["snapshot_receipt"]["file_sha256"]:
                raise ValueError("stage input actor weights differ from the resumed checkpoint")
            write(root/"INPUT_ACTOR_PUBLICATION.json", loaded)
        cached = settings.get("baseline_evaluation") if settings is not None else None
        if cached:
            baseline_root = (root.parent/cached["run_name"]).resolve()
            if baseline_root.parent != root.parent or baseline_root == root:
                raise ValueError("saved baseline must be a separate pilot under the same run root")
            initial = phase("verify_saved_P0_evaluation", lambda: verified_baseline(
                baseline_root, plan["evaluation_rows"], eval_seed, cached["summary_sha256"]))
            write(root/"BASELINE_EVALUATION_RECEIPT.json", cached)
        else:
            phase("initial_fixed_evaluation", lambda: rollout("eval-"+initial_name, plan["evaluation_rows"], eval_seed))
            initial_folder = root/("eval-"+initial_name)
            initial = (phase("initial_evaluation_analysis", lambda: summarize_evaluation(initial_folder))
                       if settings is not None else summarize_evaluation(initial_folder))
        evaluations[initial_name]=initial
        write(root / f"EVAL-{initial_name}.json", initial)
        emit_fixed_evaluation(arm_writers[initial_name],initial,name=initial_name,manifest_id=eval_manifest,rollout_seed=eval_seed)
        rollout_seed = settings["training_rollout_seed"] if settings is not None else 2026110900
        train_name = "train-"+initial_name
        phase("fresh_training_rollout", lambda: rollout(train_name, plan["training_rows"], rollout_seed))
        phase("park_actors", services.actors.park)
        phase("retriever_offload", lambda: services.search.post("/occam-residency", {"action": "cpu"}))
        if settings is None:
            native_path, comparison = phase("ledger_scoring", lambda: score_training(root / "train-P0", plan["training_rows"], root / "scored", key, writer,
                                                                                    arm_writers=arm_writers))
            arms,skipped_arms=select_update_arms(comparison)
        else:
            native_path, comparison = phase("event_price_scoring", lambda: score_event_training(
                root/train_name, plan["training_rows"], root/"scored", key, writer,
                arm_writers={arm: arm_writers[arm] for arm in arm_names}, settings=settings,
                policy_snapshot_sha256=input_snapshot,policy_version=initial_name))
            skipped_arms = {arm: "equivalent_to_"+other for arm,other in comparison["equivalent_to"].items()}
            for arm in arm_names:
                if not comparison["arm_update_capable"][arm]:
                    skipped_arms[arm] = "no_effective_nonzero_advantage"
            arms = [arm for arm in arm_names if arm not in skipped_arms]
        state["actual_update_capable"]=comparison["arm_update_capable"]
        for arm,reason in skipped_arms.items():
            state["arms"][arm]={"state":"not_executed","reason":reason,"optimizer_steps_committed":0}
            write(root/arm/"STATUS.json",state["arms"][arm])
        for publication, arm in enumerate(arms, 1):
            def train():
                env = dict(os.environ)
                env.pop("OCCAM_ACTOR_ADMIN", None)
                with (root / (arm+"-trainer.log")).open("w") as log:
                    command=[sys.executable, "-u", "-m", "torch.distributed.run", "--standalone", "--nproc_per_node=4",
                                    str(source / "scripts/hf_pilot_train.py"), "--native-batch", str(native_path),
                                    "--scores", str(root / "scored" / (arm+"-scores.pt")), "--output-root", str(root / arm),
                                    "--snapshot-dir", str(snapshots), "--publication-id", str(publication), "--steps", "1"]
                    if parent:
                        command.extend(("--resume-checkpoint",parent["checkpoint"]))
                    with subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT) as process:
                        while True:
                            code=process.poll()
                            receipt=record_optimizer_receipt(root/arm,arm_writers[arm],terminal=code is not None,
                                                             update_index=update_index)
                            arm_receipts[arm]=receipt
                            state["arms"][arm]=receipt
                            state["optimizer_steps_committed"]=sum(r.get("optimizer_steps_committed") or 0 for r in arm_receipts.values())
                            state["checkpoints_persisted"]=sum(r["checkpoint_persisted"] for r in arm_receipts.values())
                            write(root/arm/"STATUS.json",receipt)
                            if code is not None:
                                if code:
                                    raise subprocess.CalledProcessError(code,command)
                                return receipt
                            time.sleep(2)
            executed.append(arm)
            receipt=phase(arm+"_hf_update", train)
            if receipt["state"]=="skipped":
                skipped_arms[arm]=receipt.get("skip_reason") or "worker_skipped"
                continue
            if not receipt["snapshot_published"]:
                raise RuntimeError("trainer has not published a verified snapshot")
            version = read(snapshots / f"step-{publication}.json")
            if settings is None:
                phase(arm+"_actor_publication", lambda: services.actors.publish(version["snapshot"], version["fingerprint"], validate=generated_probe))
            else:
                publication_receipt = phase(arm+"_actor_publication", lambda: start_cold_actors(
                    services, os.environ["LEDGER_BASE_MODEL"], snapshots, version, log_root=root/("actors-"+arm)))
                write(root/arm/"ACTOR_PUBLICATION.json", publication_receipt)
            phase(arm+"_restore_retriever", lambda: services.search.post("/occam-residency", {"action": "cuda"}))
            phase(arm+"_fixed_evaluation", lambda: rollout("eval-"+arm, plan["evaluation_rows"], eval_seed))
            folder = root/("eval-"+arm)
            evaluations[arm] = (phase(arm+"_evaluation_analysis", lambda: summarize_evaluation(folder))
                                if settings is not None else summarize_evaluation(folder))
            write(root / ("EVAL-"+arm+".json"), evaluations[arm])
            comparisons=paired_comparisons(evaluations,training_seed=training_seed)
            write(root/"PAIRED_COMPARISONS.json",comparisons)
            emit_fixed_evaluation(arm_writers[arm],evaluations[arm],name=arm,manifest_id=eval_manifest,
                                  rollout_seed=eval_seed,comparison=comparisons[arm+"_minus_"+initial_name])
            phase(arm+"_park_after_evaluation",services.actors.park)
            phase(arm+"_offload_after_evaluation",lambda: services.search.post("/occam-residency", {"action": "cpu"}))
        write(root / "RESULT.json", {"state": "completed", "objectives": comparison, "evaluations": evaluations,
              "arms_executed": executed,"skipped_arms":skipped_arms,"arm_receipts":arm_receipts,"paired_comparisons":comparisons,
              "equivalent_arm_not_reexecuted": "ledger" if comparison.get("objectives_exactly_identical") else None,
              "interpretation": "one-update feasibility, one training seed and fixed task-paired evaluation; identical objectives test the fallback chain, not method improvement; no convergence or noninferiority conclusion",
              "phases": phases})
        state["state"] = "completed"
    except BaseException as exc:
        state.update(state="failed", error_type=type(exc).__name__)
        write(root/"RESULT.json",{"state":"failed","error_type":type(exc).__name__,"objectives":comparison,
              "evaluations":evaluations,"arms_executed":executed,"skipped_arms":skipped_arms,
              "arm_receipts":arm_receipts,"paired_comparisons":comparisons,"phases":phases})
        raise
    finally:
        write(root / "STATUS.json", state)
        services.close()
        judge.close()
        monitor.close()


if __name__ == "__main__":
    main()
