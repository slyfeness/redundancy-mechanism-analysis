"""Convert downloaded audit/preflight metrics to a local monitor, without API/GPU work.

Only MANIFEST.json, RESULT.json, */metrics.json and GROUP_AUDIT.json are read.
Raw trajectories, reports, credentials and runtime configurations are not read.
Files still being copied are skipped and counted; completed metric records are
idempotent. Existing artifact files alone do not prove a job is still running:
--state is an optional externally verified scheduler/process snapshot.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

from ledger_grpo.observability import EventWriter, read_events, render_monitor, sanitize_payload


def _read(path, issues):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        before = path.stat()
        if before.st_size > 20_000_000:
            issues.append("oversized")
            return None
        data = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            issues.append("copy_in_progress")
            return None
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError, UnicodeError):
        issues.append("partial_or_invalid")
        return None


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:24]


def collect(*, output_dir, run_id, training_seed=None, preflight_dir=None, audit_dir=None,
            state=None, config_hash=None, refresh_seconds=10):
    """Collect a stable prefix of downloaded files; never infer optimizer commits."""
    if preflight_dir is None and audit_dir is None:
        raise ValueError("provide a local preflight or audit directory")
    if state not in {None, "pending", "running", "failed", "unknown"}:
        raise ValueError("external state must be pending, running, failed or unknown")
    output = Path(output_dir)
    preflight = Path(preflight_dir) if preflight_dir is not None else None
    audit = Path(audit_dir) if audit_dir is not None else None
    context = {"collector": "v1", "preflight": str(preflight.resolve()) if preflight else None,
               "audit": str(audit.resolve()) if audit else None}
    # This is the collector configuration hash, not a claimed training/model hash.
    writer = EventWriter(output / "metrics.jsonl", run_id=run_id, training_seed=training_seed,
                         config_hash=config_hash or "collector-v1-" + _identity(context))
    writer.emit("run.started", {"run_kind": "historical_real_trajectory_preflight" if preflight else "frozen_rollout_audit",
                "cost_unit": "policy_tokens", "code_revision": "collector-v1"}, event_id="collector-start")
    issues, observed, error_count = [], 0, 0
    expected, manifest, result, audit_report = None, None, None, None
    usage = {"request_count": 0, "attempt_count": 0, "prompt_tokens": 0, "completion_tokens": 0}
    if audit:
        audit_report = _read(audit / "GROUP_AUDIT.json", issues)
        if audit_report:
            batch = "audit-step-" + str(audit_report.get("selected_step", "unknown"))
            for row in audit_report.get("rows", []):
                payload = {
                    "traj_id": row["traj_id"], "task_id": row["task_id"], "sample_id": row["traj_id"],
                    "split": "audit", "outcome": row.get("outcome"), "outcome_source": "persisted_reward",
                    "complete": row["complete"], "gen_tokens": row.get("generated_tokens"),
                    "tool_calls": row.get("tool_calls"), "cost": row.get("generated_tokens"),
                    "cost_unit": "policy_tokens", "grounding_score": None,
                }
                writer.emit("rollout.scored", payload, event_id="audit-" + _identity([batch, row["traj_id"]]),
                            batch_id=batch, policy_version="historical-step-" + str(audit_report.get("selected_step", "unknown")))
            if not preflight:
                observed = len(audit_report.get("rows", []))
                expected = audit_report.get("counts", {}).get("trajectories")
    if preflight:
        manifest = _read(preflight / "MANIFEST.json", issues)
        result = _read(preflight / "RESULT.json", issues)
        if manifest and isinstance(manifest.get("groups_selected"), list):
            expected = len(manifest["groups_selected"]) * 8
        for path in sorted(preflight.glob("*/metrics.json")):
            metric = _read(path, issues)
            if metric is None:
                continue
            if (not {"trajectory_id", "query_id", "qa_ok", "error_count"}.issubset(metric)
                    or type(metric["error_count"]) is not int or metric["error_count"] < 0
                    or not isinstance(metric.get("judge_usage", {}), dict)):
                issues.append("invalid_metric_fields")
                continue
            measured_usage = metric.get("judge_usage") or {}
            api_usage = {"request_count": metric.get("judge_calls"), "attempt_count": metric.get("judge_attempts"),
                         "prompt_tokens": measured_usage.get("prompt_tokens"),
                         "completion_tokens": measured_usage.get("completion_tokens")}
            qa_failed = metric.get("qa_ok") is False or metric.get("error_count", 0) > 0
            payload = {
                "traj_id": metric["trajectory_id"], "task_id": str(metric["query_id"]), "sample_id": metric["trajectory_id"],
                "split": "audit", "outcome": metric.get("outcome"), "outcome_source": "persisted_reward",
                # process_preflight's manifest explicitly selects complete native groups.
                "complete": True, "gen_tokens": metric.get("policy_tokens"), "turns": metric.get("turns"),
                "cost": metric.get("policy_tokens"), "cost_unit": "policy_tokens",
                "grounding_score": metric.get("grounding"), "process_valid": False if qa_failed else None,
                "qa_parse_ok": metric.get("qa_ok"), "qa_error_count": metric.get("error_count"),
                "api_usage": api_usage, "judge_input_tokens": measured_usage.get("prompt_tokens"),
                "judge_output_tokens": measured_usage.get("completion_tokens"),
                # judge_seconds is judge elapsed time, not rollout or whole-batch wall time.
            }
            try:
                payload = sanitize_payload("rollout.scored", payload)
            except ValueError:
                issues.append("invalid_metric_fields")
                continue
            writer.emit("rollout.scored", payload, event_id="preflight-" + _identity(metric["trajectory_id"]),
                        batch_id="preflight", policy_version="historical-frozen-policy")
            observed += 1
            error_count += metric.get("error_count", 0)
            for key in usage:
                if type(api_usage.get(key)) is int:
                    usage[key] += api_usage[key]
        if result and result.get("state") == "completed":
            if result.get("optimizer_steps_committed") != 0:
                raise ValueError("preflight result unexpectedly claims optimizer updates")
            source = result.get("method_metrics", {})
            allowed = {"phase", "process_enabled", "grounding_available", "batch_std", "batch_scale",
                       "trajectory_mean_before_scale", "conditional_efficiency_mean", "conditional_grounding_mean",
                       "valid_row_count", "process_row_count"}
            payload = {k: source[k] for k in allowed if k in source}
            payload.update(trajectory_count=result.get("trajectories"), group_count=result.get("groups"),
                           effective_policy_tokens=result.get("effective_policy_tokens"))
            for field, target in (("all_wrong_groups", "all_wrong_group_count"),
                                  ("invalid_training_groups", "invalid_training_group_count"),
                                  ("qa_disabled_groups", "qa_disabled_group_count")):
                if isinstance(source.get(field), list):
                    payload[target] = len(source[field])
            writer.emit("advantage.computed", payload, event_id="preflight-computed", batch_id="preflight",
                        policy_version="historical-frozen-policy", optimizer_steps_committed=0)
            # Final totals also include constraint extraction; do not add per-row usage twice.
            usage = {"request_count": result.get("judge_requests"), "attempt_count": None,
                     "prompt_tokens": result.get("judge_prompt_tokens"),
                     "completion_tokens": result.get("judge_completion_tokens")}
    completed = result and result.get("state") in {"completed", "no_eligible_group"} or audit_report and not preflight
    local_state = result["state"] if result and result.get("state") in {"completed", "no_eligible_group"} else (
        "completed" if audit_report and not preflight else "unknown" if manifest or observed else "pending")
    local_complete = completed and (expected is None or observed >= expected)
    status = {
        "status": local_state if completed else state or local_state,
        "status_source": "local_artifacts" if completed or state is None else "external_snapshot",
        "artifact_state": "partial_or_invalid" if issues else "complete" if local_complete else "partial" if manifest or observed or result else "missing",
        "trajectories_observed": observed, "trajectories_expected": expected,
        "qa_error_count": error_count, "input_issue_count": len(issues),
        "optimizer_steps_committed": 0, "api_usage": usage if preflight and (observed or result) else None,
    }
    if result:
        status.update(wall_seconds=result.get("seconds"), comparison_changed_tokens=result.get("changed_advantage_tokens"),
                      comparison_max_absolute_delta=result.get("max_absolute_advantage_delta"))
    previous_statuses = [e for e in read_events(output / "metrics.jsonl") if e["event_type"] == "run.status"]
    if not previous_statuses or previous_statuses[-1]["payload"] != sanitize_payload("run.status", status):
        # Identical consecutive snapshots are idempotent; a returning state is a
        # new transition, not a duplicate of an older historical snapshot.
        event_id = "status-" + str(len(previous_statuses) + 1) + "-" + _identity(status)
        writer.emit("run.status", status, event_id=event_id, optimizer_steps_committed=0)
    render_monitor(output / "metrics.jsonl", output / "monitor.html", refresh_seconds=refresh_seconds)
    return {"status": status["status"], "trajectories_observed": observed, "input_issue_count": len(issues),
            "optimizer_steps_committed": 0, "events": str(output / "metrics.jsonl"), "html": str(output / "monitor.html")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-dir", type=Path)
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--training-seed", type=int, help="omit when the historical policy training seed is unknown")
    parser.add_argument("--config-hash")
    parser.add_argument("--state", choices=("pending", "running", "failed", "unknown"))
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--refresh-seconds", type=int, default=10)
    args = vars(parser.parse_args(argv))
    watch = args.pop("watch")
    if watch and args["refresh_seconds"] < 1:
        parser.error("--watch requires positive --refresh-seconds")
    try:
        while True:
            result = collect(**args)
            if not watch:
                print(json.dumps(result, ensure_ascii=False))
                return 0
            time.sleep(args["refresh_seconds"])
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        parser.exit(2, "collector rejected inconsistent or invalid local metrics; private contents were not printed\n")


if __name__ == "__main__":
    raise SystemExit(main())
