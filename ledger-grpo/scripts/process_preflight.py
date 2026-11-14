"""Bounded real-trajectory process-judge and token-advantage preflight (Slurm CPU).

Reads existing native rollouts without rerunning models. It never performs an
optimizer update and cannot establish post-training performance.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
from threading import Event
import time

from ledger_grpo.advantages import AdvantageConfig
from ledger_grpo.browsecomp_adapter import adapt_trajectory, extract_constraints
from ledger_grpo.client import LocalJudge, JudgeError, JudgeHTTPError
from ledger_grpo.hf_native import prepare_native_records
from ledger_grpo.pipeline import analyze_trajectory, score_batch


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class BoundedJudge(LocalJudge):
    def __init__(self, key, *, payment_blocked=None, compact_evidence=False):
        super().__init__("https://api.deepseek.com", "deepseek-flash", api_key=key,
                         allow_remote=True, thinking="disabled", timeout=60, max_tokens=4096,
                         compact_evidence=compact_evidence)
        self.attempts = 0
        self.elapsed = 0.
        self.check_audit = []
        self.format_failures = []
        self.payment_blocked = payment_blocked if payment_blocked is not None else Event()

    def check(self, kind, payload):
        verdict = super().check(kind, payload)
        self.check_audit.append({"kind": kind, "fact": payload.get("fact"),
                                 "evidence": payload.get("evidence"), "verdict": verdict})
        return verdict

    def _request(self, prompt, payload):
        # Retry transient/format errors at most once, never cache a fabricated verdict.
        # One trajectory's budget cannot silently grow without bound.
        started = time.monotonic()
        try:
            for attempt in range(2):
                if self.payment_blocked.is_set():
                    raise JudgeError('process judge paused after DeepSeek HTTP status 402')
                if self.attempts >= 160:
                    raise JudgeError("trajectory judge request budget reached")
                self.attempts += 1
                try:
                    return super()._request(prompt, payload)
                except JudgeError as error:
                    if self.last_parse_failure is not None:
                        self.format_failures.append(self.last_parse_failure)
                        self.last_parse_failure = None
                    if isinstance(error, JudgeHTTPError):
                        if error.status == 402:
                            self.payment_blocked.set()
                        if error.status in {400, 401, 402, 403, 404, 422}:
                            raise
                    if attempt:
                        raise
                    time.sleep(1)
        finally:
            self.elapsed += time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--groups", type=int, default=1, choices=(1, 2))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.chmod(args.output, 0o700)
    key = args.key_file.read_text().strip()
    if not key:
        raise ValueError("judge credential unavailable")
    batch_path = args.rollout / "TRAIN_BATCH.json"
    batch = read(batch_path)["trajectories"]
    grouped = {}
    for row in batch:
        grouped.setdefault(str(row["query_id"]), []).append(row)
    # Deliberate engineering calibration sample, never reported as an unbiased
    # estimate of redundancy prevalence or held-out accuracy.
    eligible = [qid for qid, rows in grouped.items() if len(rows) == 8
                and all(r["terminal"] == "MODEL_FINAL_STOP" and r["reward"] in (0., 1.) for r in rows)
                and any(r["reward"] == 1 for r in rows)]
    eligible.sort(key=lambda qid: (all(r["reward"] == 1 for r in grouped[qid]), qid))
    selected = eligible[:args.groups]
    manifest = {"kind": "historical_real_trajectory_preflight", "optimizer_steps_committed": 0,
                "selection": "complete eight-sample groups with a success; mixed before all-correct; ID order",
                "source_batch_sha256": hashlib.sha256(batch_path.read_bytes()).hexdigest(),
                "groups_requested": args.groups, "groups_selected": selected,
                "prompt_version": "ledger-v1.1-submission", "budget_failure_policy": "outcome_only",
                "available_complete_success_groups": len(eligible),
                "native_mask": "maximal exact spans; tool/context gaps zero",
                "constraint_projection": "task-only exact-quote extraction; semantic calibration not established",
                "document_provenance": "all returned documents share browsecomp-corpus source; docid identity preserved; publisher independence not asserted"}
    write(args.output / "MANIFEST.json", manifest)
    if not selected:
        write(args.output / "RESULT.json", {"state": "no_eligible_group", **manifest})
        return
    questions = {str(r["query_id"]): r["question"] for r in read(args.rollout / "sample_manifest.json")["selected"]}
    constraint_judge = BoundedJudge(key)
    constraints = {qid: extract_constraints(questions[qid], constraint_judge) for qid in selected}
    write(args.output / "CONSTRAINTS.json", constraints)
    rows = [row for qid in selected for row in grouped[qid]]
    started = time.monotonic()

    def process(row):
        qid = str(row["query_id"])
        raw = read(args.rollout / "trajectories" / row["id"] / "trajectory.json")
        trace, native = adapt_trajectory(raw, questions[qid], constraints[qid], outcome=int(row["reward"]))
        if (native["id"] != row["id"] or native["query_id"] != str(row["query_id"])
                or native["terminal"] != row["terminal"] or native["segments"] != row["segments"]):
            raise ValueError("raw native recording does not match its graded training batch")
        judge = BoundedJudge(key)
        report = analyze_trajectory(trace, judge=judge)
        metrics = {"trajectory_id": row["id"], "query_id": qid, "outcome": trace["outcome"],
                   "turns": len(trace["turns"]), "policy_tokens": sum(trace["response_mask"]),
                   "qa_ok": report["qa"]["parse_ok"], "error_count": len(report["qa"]["errors"]),
                   "grounding": report["metrics"]["grounding_score"],
                   "submitted_candidate_parsed": (report.get("resolved_submission") or {}).get("status") == "resolved",
                   "candidate_matching_fact_count": report["metrics"].get("candidate_matching_fact_count"),
                   "candidate_match_available": report["metrics"].get("candidate_match_available"),
                   "span_count": len(report["spans"]), "judge_calls": judge.requests,
                   "judge_attempts": judge.attempts, "judge_usage": judge.usage,
                   "judge_seconds": judge.elapsed}
        folder = args.output / row["id"]
        folder.mkdir()
        write(folder / "trace.json", trace)
        write(folder / "report.json", report)
        write(folder / "metrics.json", metrics)
        write(folder / "checks.json", judge.check_audit)
        write(folder / "format-failures.json", judge.format_failures)
        print(json.dumps({"event": "trajectory.scored", **metrics}), flush=True)
        return trace, report, native, metrics

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        outputs = list(executor.map(process, rows))
    traces, reports, native, metrics = map(list, zip(*outputs))
    baseline = score_batch(traces, reports, config=AdvantageConfig(process_enabled=False), budget_failure_policy="outcome_only")
    method = score_batch(traces, reports, config=AdvantageConfig(process_enabled=True), budget_failure_policy="outcome_only")
    mapped = prepare_native_records(native, method)
    changed = (method["advantages"] - baseline["advantages"]).abs()
    result = {"state": "completed", "optimizer_steps_committed": 0, "trajectories": len(traces),
              "groups": len(selected), "qa_ok": sum(m["qa_ok"] for m in metrics),
              "candidate_parse_ok": sum(m["submitted_candidate_parsed"] for m in metrics),
              "judge_requests": sum(m["judge_calls"] for m in metrics) + constraint_judge.requests,
              "judge_prompt_tokens": sum(m["judge_usage"]["prompt_tokens"] for m in metrics) + constraint_judge.usage["prompt_tokens"],
              "judge_completion_tokens": sum(m["judge_usage"]["completion_tokens"] for m in metrics) + constraint_judge.usage["completion_tokens"],
              "changed_advantage_tokens": int((changed > 1e-7).sum()),
              "max_absolute_advantage_delta": changed.max().item(),
              "valid_rows": int(method["valid_rows"].sum()),
              "effective_policy_tokens": int(method["effective_response_mask"].sum()),
              "native_records": len(mapped["records"]), "seconds": time.monotonic()-started,
              "baseline_metrics": baseline["metrics"], "method_metrics": method["metrics"]}
    write(args.output / "RESULT.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
