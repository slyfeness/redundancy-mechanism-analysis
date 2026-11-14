"""Private-text-free JSONL telemetry and a dependency-free local monitor.

One rank-zero process owns a log. Events are idempotent across restarts, but this
is not a multi-process logging service. A computed advantage is never evidence of
an optimizer commit. Only the real optimizer callback may emit optimizer.result.
Metrics unavailable in the installed trainer remain null. Identifiers must be
opaque IDs, not prompts, credentials, or exception messages.

    python -m ledger_grpo.observability events.jsonl --output monitor.html --watch

The watch process regenerates the static HTML; its meta refresh reloads that
file. No server, external JavaScript, telemetry upload, or model is started.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
import threading
import time


SCHEMA_VERSION = "ledger-observe-v1"
LABELS = ("R1", "R2", "R3", "D1", "D2", "D3", "D4")
_API_USAGE = {key: "count" for key in ("request_count", "attempt_count", "prompt_tokens", "completion_tokens",
                                      "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")}
_STATS = {key: "number" for key in ("mean", "std", "min", "max", "p50", "p90", "p95", "sum")}
_STATS.update(count="count", coverage="ratio")
OPTIMIZER_METRICS = {
    "policy_loss": "number", "entropy": "number", "approx_kl": "number",
    "reference_kl": "number", "clip_fraction": "ratio", "clip_fraction_lower": "ratio",
    "grad_norm": "nonnegative", "grad_norm_pre_clip": "nonnegative",
    "grad_norm_post_clip": "nonnegative", "lr": "nonnegative",
    "loss_scale": "nonnegative", "effective_policy_tokens": "count",
}
_METRIC_DEFINITIONS = {
    "approx_kl": {"k1", "k3", "native_unspecified"},
    "reference_kl": {"k1", "k3", "native_unspecified"},
    "grad_norm": {"pre_clip", "post_clip", "native_unspecified"},
    "reduction": {"token_mean", "sequence_mean", "fixed_denominator", "native_unspecified"},
    "clip_fraction": {"ratio_outside_bounds", "objective_clipped", "native_unspecified"},
}
_ROLLOUT = {
    **{k: "id" for k in ("traj_id", "task_id", "sample_id", "trace_digest", "evaluation_id", "checkpoint_id")},
    "split": {"train", "eval", "audit"}, "outcome": "binary", "complete": "bool",
    "outcome_source": {"provided_outcome", "persisted_reward", "independent_verifier"},
    "training_valid": "bool", "process_valid": "bool", "qa_parse_ok": "bool",
    "citations_verified": "bool", "cost_unit": "id", "grounding_score": "ratio",
    "redundant_token_fraction": "ratio", "redundant_tokens": "nonnegative",
    **{k: "count" for k in ("gen_tokens", "tool_calls", "ctx_tokens", "judge_input_tokens",
                            "judge_output_tokens", "turns", "qa_error_count", "rollout_seed",
                            "recorded_tool_events", "measured_tool_events", "exact_repeat_events",
                            "measured_return_tokens", "unmarked_event_cost", "reasoning_tokens",
                            "reasoning_rounds", "reasoning_observed_rounds", "reasoning_derived_tokens",
                            "reasoning_derived_rounds")},
    "budget_exhausted": "bool", "explicit_abandon": "bool",
    "attempt_count": "positive_count", "cost": "nonnegative", "budget": "nonnegative",
    "wall_seconds": "nonnegative",
    "label_counts": {k: "count" for k in LABELS},
    "abstain_span_counts": {k: "count" for k in LABELS},
    "reward_eligible_span_counts": {k: "count" for k in LABELS},
    "judge_counts": {k: "count" for k in ("yes", "no", "uncertain", "error")},
    "api_usage": _API_USAGE,
    "decision_status": {"sufficient", "critical_gap", "conflict", "saturated", "incomplete"},
}
_ADVANTAGE = {
    **{k: "count" for k in ("trajectory_count", "group_count", "valid_row_count", "process_row_count",
                            "valid_group_count", "zero_signal_group_count", "all_wrong_group_count",
                            "invalid_training_group_count", "qa_disabled_group_count", "effective_policy_tokens",
                            "actual_changed_tokens", "r_changed_tokens", "d_changed_tokens",
                            "peer_gate_open_rows", "retained_budget_failures", "charged_events",
                            "charged_budget_events", "charged_policy_tokens", "grounding_observed")},
    **{k: "number" for k in ("batch_std", "batch_scale", "trajectory_mean_before_scale",
                             "conditional_efficiency_mean", "conditional_grounding_mean",
                             "r_downshift_mass", "d_downshift_mass", "charged_total", "ground_bonus_total")},
    **{k: _STATS for k in ("accuracy_advantage", "efficiency_advantage", "grounding_advantage",
                           "trajectory_advantage", "final_advantage", "local_downshift")},
    "phase": "id", "process_enabled": "bool", "grounding_available": "bool",
    "control": {"outcome", "targeted", "uniform", "shuffle", "shuffled", "trajectory"}, "control_seed": "count",
}
_EVALUATION = {
    **{k: "id" for k in ("evaluation_id", "checkpoint_id", "eval_manifest_id", "baseline_id", "pair_set_id", "cost_unit")},
    **{k: "count" for k in ("sample_count", "task_count", "success_count", "grounding_observed", "bootstrap_seed")},
    **{k: "ratio" for k in ("accuracy", "completion_rate", "grounding_coverage", "over_budget_rate")},
    **{k: "nonnegative" for k in ("mean_cost", "p90_cost", "p95_cost", "cost_per_success", "mean_gen_tokens")},
    "mean_grounding": "ratio", "paired_accuracy_delta": "number", "paired_cost_delta": "number",
    "paired_accuracy_ci": "interval", "paired_cost_ci": "interval",
}
_PAYLOADS = {
    "run.started": {
        "run_kind": {"training", "historical_real_trajectory_preflight", "frozen_rollout_audit"},
        **{k: "id" for k in ("model_id", "model_revision", "code_revision", "data_manifest_hash",
                              "judge_model", "judge_revision", "trainer_backend", "cost_unit")},
        "control": _ADVANTAGE["control"], "control_seed": "count", "process_enabled": "bool",
        "weights": {k: "nonnegative" for k in ("efficiency", "grounding", "eta", "delta_max", "beta", "D4")},
        "metric_definitions": _METRIC_DEFINITIONS,
    },
    "run.status": {
        "status": {"pending", "running", "completed", "failed", "unknown", "no_eligible_group"},
        "status_source": {"local_artifacts", "external_snapshot"},
        "artifact_state": {"missing", "partial", "complete", "partial_or_invalid"},
        **{k: "count" for k in ("trajectories_observed", "trajectories_expected", "qa_error_count",
                                "input_issue_count", "optimizer_steps_committed")},
        "api_usage": _API_USAGE,
        "wall_seconds": "nonnegative", "comparison_changed_tokens": "count",
        "comparison_max_absolute_delta": "nonnegative",
    },
    "rollout.scored": _ROLLOUT,
    "advantage.computed": _ADVANTAGE,
    "optimizer.result": {
        "update_id": "id", "status": {"committed", "skipped", "failed"},
        "source": {"optimizer_callback"}, "steps_before": "count", "steps_after": "count",
        "reason": {"amp_overflow", "nonfinite", "no_valid_rows", "zero_mask", "exception", "cancelled", "other"},
        "metrics": OPTIMIZER_METRICS, "metric_definitions": _METRIC_DEFINITIONS,
    },
    "evaluation.completed": _EVALUATION,
}


class EventConflictError(ValueError):
    """An existing event or logical sample has incompatible content."""


def _value(value, spec):
    if value is None:
        return None
    if isinstance(spec, dict):
        if not isinstance(value, Mapping):
            raise ValueError("event object field must be a mapping")
        return {key: _value(value[key], rule) for key, rule in spec.items() if key in value}
    if isinstance(spec, set):
        if not isinstance(value, str) or value not in spec:
            raise ValueError("event enum field has an unsupported value")
        return value
    if spec == "id":
        if not isinstance(value, str) or not value.strip() or len(value) > 512 or any(ord(c) < 32 for c in value):
            raise ValueError("event identifier must be a nonempty bounded string without controls")
        return value
    if spec == "bool":
        if type(value) is not bool:
            raise ValueError("event boolean field must be boolean")
        return value
    if spec in {"count", "positive_count"}:
        if type(value) is not int or value < (1 if spec == "positive_count" else 0):
            raise ValueError("event count must be a nonnegative integer")
        return value
    if spec == "interval":
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError("event interval requires two finite endpoints")
        interval = [_value(x, "number") for x in value]
        if None in interval or interval[0] > interval[1]:
            raise ValueError("event interval endpoints must be finite and ordered")
        return interval
    if type(value) not in (int, float):
        raise ValueError("event measurement must be numeric")
    if not math.isfinite(value):
        return None
    if (spec == "binary" and value not in (0, 1)) or (spec == "ratio" and not 0 <= value <= 1) or (spec == "nonnegative" and value < 0):
        raise ValueError("event measurement is out of range")
    return value


def sanitize_payload(event_type, payload):
    """Drop unknown fields at every level; reject wrong types, null nonfinite metrics."""
    if event_type not in _PAYLOADS:
        raise ValueError("unsupported event type")
    data = _value(payload, _PAYLOADS[event_type])
    if data is None:
        raise ValueError("event payload must be an object")
    required = {
        "run.status": ("status", "status_source", "artifact_state"),
        "rollout.scored": ("traj_id", "task_id", "sample_id", "split", "complete"),
        "optimizer.result": ("update_id", "status", "source", "steps_before", "steps_after"),
        "evaluation.completed": ("evaluation_id", "checkpoint_id", "eval_manifest_id"),
    }.get(event_type, ())
    if any(data.get(key) is None for key in required):
        raise ValueError("event payload is missing required fields")
    if event_type == "optimizer.result":
        expected = data["steps_before"] + int(data["status"] == "committed")
        if data["steps_after"] != expected:
            raise ValueError("optimizer result must report exactly one actual commit or no step change")
    if event_type == "rollout.scored":
        if data["split"] == "eval" and not data.get("evaluation_id"):
            raise ValueError("evaluation rollout requires evaluation_id")
        if data.get("process_valid") is False:
            for key in ("grounding_score", "redundant_tokens", "redundant_token_fraction"):
                data[key] = None
    return data


def _normalize_event(event):
    if not isinstance(event, Mapping) or event.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported event schema")
    result = {"schema_version": SCHEMA_VERSION}
    for key in ("event_id", "event_type", "run_id", "config_hash", "timestamp_utc"):
        result[key] = _value(event.get(key), "id")
        if result[key] is None:
            raise ValueError("event envelope is missing required identifiers")
    result["training_seed"] = _value(event.get("training_seed"), "count")
    for key in ("trainer_iteration", "optimizer_steps_committed"):
        result[key] = _value(event.get(key), "count")
    for key in ("batch_id", "policy_version"):
        result[key] = _value(event.get(key), "id")
    result["payload"] = sanitize_payload(result["event_type"], event.get("payload"))
    kind, payload = result["event_type"], result["payload"]
    if (kind == "advantage.computed" or kind == "rollout.scored" and payload["split"] in {"train", "audit"}) and not result["batch_id"]:
        raise ValueError("training events require a stable batch_id")
    if kind == "optimizer.result":
        if result["optimizer_steps_committed"] not in (None, payload["steps_after"]):
            raise ValueError("optimizer committed counter disagrees with callback")
        result["optimizer_steps_committed"] = payload["steps_after"]
    return result


def _canonical(event, *, logical=False):
    excluded = {"timestamp_utc"} | ({"event_id"} if logical else set())
    return json.dumps({k: v for k, v in event.items() if k not in excluded}, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _logical_key(event):
    kind, run, payload = event["event_type"], event["run_id"], event["payload"]
    if kind == "rollout.scored":
        namespace = payload.get("evaluation_id") if payload["split"] == "eval" else event["batch_id"]
        return run, kind, payload["split"], namespace, payload["task_id"], payload["sample_id"]
    if kind == "optimizer.result":
        return run, kind, payload["update_id"]
    if kind == "advantage.computed":
        return run, kind, event["batch_id"]
    if kind == "evaluation.completed":
        return run, kind, payload["evaluation_id"]
    if kind == "run.status":
        return run, kind, event["event_id"]
    return run, kind


class _EventIndex:
    def __init__(self):
        self.ids, self.logical, self.contexts, self.steps = {}, {}, {}, {}

    def check(self, event):
        run = event["run_id"]
        context = event["training_seed"], event["config_hash"]
        if run in self.contexts and self.contexts[run] != context:
            raise EventConflictError("run identity has conflicting seed or configuration")
        identity = run, event["event_id"]
        if identity in self.ids:
            if self.ids[identity] != _canonical(event):
                raise EventConflictError("event ID has conflicting content")
            return False
        key = _logical_key(event)
        if key in self.logical:
            if self.logical[key] != _canonical(event, logical=True):
                raise EventConflictError("logical event has conflicting content")
            return False
        if event["event_type"] == "optimizer.result" and run in self.steps:
            if event["payload"]["steps_before"] != self.steps[run]:
                raise EventConflictError("optimizer step history is discontinuous")
        return True

    def add(self, event):
        run = event["run_id"]
        self.contexts[run] = event["training_seed"], event["config_hash"]
        self.ids[run, event["event_id"]] = _canonical(event)
        self.logical[_logical_key(event)] = _canonical(event, logical=True)
        if event["event_type"] == "optimizer.result":
            self.steps[run] = event["payload"]["steps_after"]


def _unique_events(events):
    index, result = _EventIndex(), []
    for raw in events:
        event = _normalize_event(raw)
        if index.check(event):
            index.add(event)
            result.append(event)
    return result


def read_events(path, *, allow_incomplete_tail=False):
    """Read and validate unique events; live readers may ignore one partial tail."""
    path = Path(path)
    if not path.exists():
        return []
    lines = path.read_bytes().splitlines(keepends=True)
    events = []
    for number, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            if allow_incomplete_tail and number == len(lines) - 1 and not line.endswith(b"\n"):
                break
            raise ValueError("event log contains invalid JSON; refusing to hide corruption") from None
        events.append(event)
    return _unique_events(events)


class EventWriter:
    """Append sanitized events from one rank-zero process, with durable flushes.

    Reopening validates the complete existing log. Repair a truncated writer log
    explicitly; live renderers alone may ignore a partially written final line.
    """
    def __init__(self, path, *, run_id, training_seed, config_hash, rank=0):
        self.path = Path(path)
        self.rank = _value(rank, "count")
        self.run_id = _value(run_id, "id")
        self.training_seed = _value(training_seed, "count")
        self.config_hash = _value(config_hash, "id")
        if None in (self.rank, self.run_id, self.config_hash):
            raise ValueError("writer context cannot be null")
        self._index, self._lock = _EventIndex(), threading.Lock()
        if self.rank == 0:
            if self.path.exists() and self.path.stat().st_size:
                with self.path.open("rb") as stream:
                    stream.seek(-1, 2)
                    if stream.read(1) != b"\n":
                        raise ValueError("writer log has an unterminated final line; explicit repair required")
            for event in read_events(self.path):
                if (event["run_id"], event["training_seed"], event["config_hash"]) != (run_id, training_seed, config_hash):
                    raise EventConflictError("one writer file must belong to one run context")
                self._index.add(event)

    def emit(self, event_type, payload, *, event_id, trainer_iteration=None,
             batch_id=None, policy_version=None, optimizer_steps_committed=None):
        if self.rank != 0:
            return False
        event = _normalize_event({
            "schema_version": SCHEMA_VERSION, "event_type": event_type, "event_id": event_id,
            "run_id": self.run_id, "training_seed": self.training_seed, "config_hash": self.config_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(), "trainer_iteration": trainer_iteration,
            "batch_id": batch_id, "policy_version": policy_version,
            "optimizer_steps_committed": optimizer_steps_committed, "payload": payload,
        })
        with self._lock:
            if not self._index.check(event):
                return False
            encoded = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self._index.add(event)
        return True


def rollout_payload(trace, report, *, sample_id=None, split="train", evaluation_id=None,
                    cost=None, cost_unit="policy_tokens", extra_metrics=None,
                    enable_artifact_d4=False, d4_weight=.15):
    """Extract scalar observables from a report bound to this exact trajectory.

    Callers can supply measured costs/judge counts, never raw text. Eligibility
    here is per trajectory; group QA may still disable all process terms later.
    """
    from .pipeline import build_process_inputs
    inputs = build_process_inputs(trace, report, enable_artifact_d4=enable_artifact_d4, d4_weight=d4_weight)
    metrics, qa = report.get("metrics", {}), report["qa"]
    generated = sum(inputs["response_mask"])
    spans = report["spans"]
    counts = Counter(s["label"] for s in spans if not s.get("abstain"))
    abstains = Counter(s["label"] for s in spans if s.get("abstain"))
    eligible_labels = {"R1", "R2"} | ({"D4"} if enable_artifact_d4 else set())
    eligible = Counter(s["label"] for s in spans if inputs["process_valid"] and s.get("reward_eligible")
                       and not s.get("abstain") and s["label"] in eligible_labels)
    payload = {
        "traj_id": inputs["traj_id"], "task_id": inputs["task_id"], "sample_id": sample_id or inputs["traj_id"],
        "trace_digest": report["trace_digest"], "split": split, "evaluation_id": evaluation_id,
        "outcome": inputs["outcome"], "complete": inputs["training_valid"], "training_valid": inputs["training_valid"],
        "process_valid": inputs["process_valid"], "qa_parse_ok": qa.get("parse_ok"),
        "citations_verified": qa.get("citations_verified"), "qa_error_count": len(qa.get("errors", [])),
        "gen_tokens": generated, "turns": metrics.get("turns"), "tool_calls": metrics.get("tool_calls"),
        "grounding_score": inputs["grounding"] if inputs["process_valid"] else None,
        "redundant_tokens": sum(inputs["redundancy"]),
        "redundant_token_fraction": inputs["redundant_fraction"],
        "cost": generated if cost is None and cost_unit == "policy_tokens" else cost, "cost_unit": cost_unit,
        "attempt_count": 1, "label_counts": dict(counts), "abstain_span_counts": dict(abstains),
        "reward_eligible_span_counts": dict(eligible), "judge_counts": None,
    }
    # Only externally measured optional fields can supplement the bound report.
    extras = set(("ctx_tokens", "judge_input_tokens", "judge_output_tokens", "wall_seconds", "budget",
                  "attempt_count", "judge_counts", "api_usage", "rollout_seed", "checkpoint_id", "outcome_source",
                  "recorded_tool_events", "measured_tool_events", "exact_repeat_events", "measured_return_tokens",
                  "unmarked_event_cost", "reasoning_tokens", "reasoning_rounds", "reasoning_observed_rounds",
                  "reasoning_derived_tokens", "reasoning_derived_rounds", "budget_exhausted", "explicit_abandon"))
    if extra_metrics:
        payload.update({k: v for k, v in extra_metrics.items() if k in extras})
    if payload["attempt_count"] > 1 and cost is None:
        raise ValueError("retried samples require an explicit total cost including retries")
    return sanitize_payload("rollout.scored", payload)


def _tolist(value):
    return value.detach().cpu().tolist() if hasattr(value, "detach") else value


def _stats(values, total=None):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    ordered = sorted(values)
    def percentile(q):
        if not ordered:
            return None
        p = (len(ordered) - 1) * q
        lo, hi = math.floor(p), math.ceil(p)
        return ordered[lo] * (hi - p) + ordered[hi] * (p - lo) if lo != hi else ordered[lo]
    result = {"count": len(values), "mean": statistics.fmean(values) if values else None,
              "std": statistics.stdev(values) if len(values) > 1 else None,
              "min": min(values) if values else None, "max": max(values) if values else None,
              "sum": math.fsum(values), "p50": percentile(.5), "p90": percentile(.9), "p95": percentile(.95)}
    if total is not None:
        result["coverage"] = len(values) / total if total else 0.0
    return result


def advantage_payload(result, *, task_ids=None):
    """Summarize score_batch output with its effective mask; no optimizer claim.

    Current advantages expose only the combined local offset. R and D causal
    attributions are explicitly unavailable rather than inferred from labels.
    """
    metrics = result.get("metrics", {})
    payload = {k: metrics[k] for k in _ADVANTAGE if k in metrics}
    for source, target in (("all_wrong_groups", "all_wrong_group_count"),
                           ("invalid_training_groups", "invalid_training_group_count"),
                           ("qa_disabled_groups", "qa_disabled_group_count")):
        if source in metrics:
            payload[target] = len(metrics[source])
    rows = _tolist(result["valid_rows"])
    mask = _tolist(result["effective_response_mask"])
    advantages = _tolist(result["advantages"])
    base = _tolist(result["trajectory_advantage"])
    if not (len(rows) == len(mask) == len(advantages) == len(base)):
        raise ValueError("advantage observables have inconsistent batch shapes")
    if any(len(m) != len(a) for m, a in zip(mask, advantages)):
        raise ValueError("advantage observables have inconsistent token shapes")
    if any(any(m) and not valid for m, valid in zip(mask, rows)):
        raise ValueError("effective mask includes an invalid training row")
    valid_values = [a for m, arow in zip(mask, advantages) for keep, a in zip(m, arow) if keep]
    downshifts = [b - a for b, m, arow in zip(base, mask, advantages) for keep, a in zip(m, arow) if keep]
    payload.update(trajectory_count=len(rows), effective_policy_tokens=len(valid_values),
                   final_advantage=_stats(valid_values), local_downshift=_stats(downshifts),
                   actual_changed_tokens=sum(value != 0 for value in downshifts),
                   r_changed_tokens=None, d_changed_tokens=None, r_downshift_mass=None, d_downshift_mass=None)
    for key in ("accuracy_advantage", "efficiency_advantage", "grounding_advantage", "trajectory_advantage"):
        if key in result:
            values = _tolist(result[key])
            if len(values) != len(rows):
                raise ValueError("trajectory advantages have inconsistent batch shapes")
            payload[key] = _stats([v for v, valid in zip(values, rows) if valid])
    if task_ids is not None:
        if len(task_ids) != len(rows):
            raise ValueError("task_ids must match trajectory rows")
        valid_groups = {t for t, valid in zip(task_ids, rows) if valid}
        signal_groups = {t for t, m, a in zip(task_ids, mask, advantages) if any(k and v != 0 for k, v in zip(m, a))}
        payload.update(group_count=len(set(task_ids)), valid_group_count=len(valid_groups),
                       zero_signal_group_count=len(valid_groups - signal_groups))
    if "control" in result:
        payload["control"] = result["control"]
    return sanitize_payload("advantage.computed", payload)


def evaluation_payload(rows, *, evaluation_id, checkpoint_id, eval_manifest_id, cost_unit="policy_tokens"):
    """Descriptive fixed-evaluation summary; no automatic significance claim.

    Each row requires task_id and sample_id to reject pseudo-replication. Use
    evaluation.paired_bootstrap separately with an explicit pairing manifest.
    """
    from .evaluation import summarize_runs
    for field in ("run_id", "training_seed", "checkpoint_id", "evaluation_id"):
        values = {row[field] for row in rows if row.get(field) is not None}
        if len(values) > 1:
            raise ValueError("evaluation cannot pool different runs, seeds, checkpoints or evaluation IDs")
        if field in {"checkpoint_id", "evaluation_id"} and values:
            expected = checkpoint_id if field == "checkpoint_id" else evaluation_id
            if next(iter(values)) != expected:
                raise ValueError("evaluation context disagrees with sample context")
    seen = set()
    for row in rows:
        key = _value(row.get("task_id"), "id"), _value(row.get("sample_id"), "id")
        if None in key or key in seen:
            raise ValueError("evaluation requires unique task_id/sample_id pairs")
        seen.add(key)
    allowed = {"task_id", "outcome", "complete", "cost", "budget", "gen_tokens", "tool_calls", "ctx_tokens", "grounding_score"}
    safe_rows = []
    for row in rows:
        if row.get("cost_unit") not in (None, cost_unit):
            raise ValueError("evaluation costs must use one explicit unit")
        safe = {key: row[key] for key in allowed if key in row}
        if row.get("process_valid") is False:
            safe["grounding_score"] = None
        safe_rows.append(safe)
    summary = summarize_runs(safe_rows)
    grounding = summary["optional_fields"]["grounding_score"]
    return sanitize_payload("evaluation.completed", {
        "evaluation_id": evaluation_id, "checkpoint_id": checkpoint_id, "eval_manifest_id": eval_manifest_id,
        "cost_unit": cost_unit, "sample_count": summary["run_count"], "task_count": summary["task_count"],
        "success_count": summary["success_count"], "accuracy": summary["accuracy"],
        "completion_rate": summary["completion_rate"], "mean_cost": summary["cost"]["mean"],
        "p90_cost": summary["cost"]["p90"], "p95_cost": summary["cost"]["p95"],
        "cost_per_success": summary["cost_per_success"], "mean_grounding": grounding["mean"],
        "grounding_observed": grounding["count"], "grounding_coverage": grounding["coverage"],
        "mean_gen_tokens": summary["optional_fields"]["gen_tokens"]["mean"],
        "over_budget_rate": summary["over_budget_rate"],
    })


def _rollout_summary(rows):
    n = len(rows)
    known = [r["outcome"] for r in rows if r.get("outcome") is not None]
    successes = sum(known)
    costs = [r["cost"] for r in rows if r.get("cost") is not None]
    units = {r.get("cost_unit") for r in rows if r.get("cost") is not None}
    if len(units) > 1 or costs and None in units:
        raise ValueError("cannot pool costs with missing or different units")
    result = {"sample_count": n, "task_count": len({r["task_id"] for r in rows}),
              "success_count": successes, "accuracy": statistics.fmean(known) if known else None,
              "outcome_coverage": len(known) / n if n else 0.0,
              "completion_rate": statistics.fmean(r["complete"] for r in rows) if n else None,
              "cost": _stats(costs, n), "cost_unit": next(iter(units), None),
              "cost_per_success": sum(costs) / successes if successes and len(costs) == n and len(known) == n else None}
    for key in ("grounding_score", "redundant_token_fraction", "gen_tokens", "tool_calls",
                "ctx_tokens", "judge_input_tokens", "judge_output_tokens", "wall_seconds",
                "recorded_tool_events", "measured_tool_events", "exact_repeat_events", "measured_return_tokens",
                "unmarked_event_cost", "budget_exhausted", "explicit_abandon"):
        result[key] = _stats([r[key] for r in rows if r.get(key) is not None], n)
    from .evaluation import summarize_reasoning_usage
    reasoning = summarize_reasoning_usage(rows)
    result['reasoning_usage'] = reasoning
    result['reasoning_tokens_per_round'] = reasoning['reasoning_tokens_per_round']
    result['reasoning_tokens'] = _stats([r['reasoning_tokens'] for r in rows
                                         if r.get('reasoning_observed_rounds') and r.get('reasoning_tokens') is not None], n)
    valid = [r["process_valid"] for r in rows if r.get("process_valid") is not None]
    result["process_valid_rate"] = statistics.fmean(valid) if valid else None
    result["process_valid_coverage"] = len(valid) / n if n else 0.0
    for key, fields in (("label_counts", LABELS), ("abstain_span_counts", LABELS),
                        ("reward_eligible_span_counts", LABELS),
                        ("judge_counts", ("yes", "no", "uncertain", "error")), ("api_usage", tuple(_API_USAGE))):
        observed = [r[key] for r in rows if r.get(key) is not None]
        result[key] = {"totals": {field: sum(r.get(field) or 0 for r in observed) for field in fields},
                       "observed_rows": len(observed), "coverage": len(observed) / n if n else 0.0}
        if key == "api_usage":
            for field in fields:
                values = [r[field] for r in observed if r.get(field) is not None]
                result[key]["totals"][field] = sum(values) if values else None
            result[key]["field_coverage"] = {
                field: sum(r.get(field) is not None for r in observed) / n if n else 0.0 for field in fields}
    verdicts = result["judge_counts"]["totals"]
    decided = sum(verdicts[key] for key in ("yes", "no", "uncertain"))
    requests = decided + verdicts["error"]
    result["judge_abstention_rate"] = verdicts["uncertain"] / decided if decided else None
    result["judge_error_rate"] = verdicts["error"] / requests if requests else None
    result["qa_error_count"] = sum(r.get("qa_error_count") or 0 for r in rows)
    result["qa_error_coverage"] = sum(r.get("qa_error_count") is not None for r in rows) / n if n else 0.
    successful = [r for r in rows if r.get("outcome") == 1]
    result["successful_redundant_token_fraction"] = _stats(
        [r["redundant_token_fraction"] for r in successful if r.get("redundant_token_fraction") is not None], len(successful))
    return result


def summarize_events(events):
    """Per-run/seed summaries; never pool eval samples into training curves."""
    groups = defaultdict(list)
    for event in _unique_events(events):
        groups[event["run_id"]].append(event)
    runs = {}
    for run_id, items in groups.items():
        train, evaluations, audits = [], defaultdict(list), defaultdict(list)
        computed, optimizer, evaluation_reports = [], [], []
        statuses, starts = [], []
        for event in items:
            kind, payload = event["event_type"], event["payload"]
            if kind == "rollout.scored":
                if payload["split"] == "train":
                    train.append(payload)
                elif payload["split"] == "eval":
                    evaluations[payload["evaluation_id"]].append(payload)
                else:
                    audits[event["batch_id"]].append(payload)
            elif kind == "advantage.computed":
                computed.append(event)
            elif kind == "optimizer.result":
                optimizer.append(event)
            elif kind == "evaluation.completed":
                evaluation_reports.append(payload)
            elif kind == "run.status":
                statuses.append(payload)
            elif kind == "run.started":
                starts.append(payload)
        committed = [e for e in optimizer if e["payload"]["status"] == "committed"]
        runs[run_id] = {
            "training_seed": items[0]["training_seed"], "config_hash": items[0]["config_hash"],
            "event_count": len(items), "computed_batch_count": len(computed),
            "run_kind": starts[0].get("run_kind") if starts else None,
            "latest_status": statuses[-1] if statuses else None,
            "optimizer_committed_count": len(committed),
            "optimizer_skipped_count": sum(e["payload"]["status"] == "skipped" for e in optimizer),
            "optimizer_failed_count": sum(e["payload"]["status"] == "failed" for e in optimizer),
            "last_committed_step": committed[-1]["payload"]["steps_after"] if committed else None,
            "train": _rollout_summary(train),
            "evaluations": {key: _rollout_summary(rows) for key, rows in evaluations.items()},
            "audits": {key: _rollout_summary(rows) for key, rows in audits.items()},
            "evaluation_reports": evaluation_reports,
            "latest_advantage": computed[-1]["payload"] if computed else None,
            "latest_optimizer_metrics": optimizer[-1]["payload"].get("metrics", {}) if optimizer else {},
        }
    return {"schema_version": SCHEMA_VERSION, "runs": runs}


def _sparkline(points, title, x_label):
    points = [(x, y) for x, y in points if x is not None and y is not None and math.isfinite(y)]
    label = html.escape(title)
    if not points:
        return f'<article><h3>{label}</h3><p class="muted">暂无可用测量</p></article>'
    points.sort()
    xs, ys = zip(*points)
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    coords = [(40 + (x - xmin) / (xmax - xmin or 1) * 480, 150 - (y - ymin) / (ymax - ymin or 1) * 115) for x, y in points]
    poly = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    circles = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3"><title>{a}: {b:.6g}</title></circle>'
                      for (x, y), (a, b) in zip(coords, points))
    return (f'<article><h3>{label}</h3><svg viewBox="0 0 560 190" role="img" aria-label="{label}">'
            f'<path d="M40 25 V150 H530" class="axis"/><polyline points="{poly}"/>{circles}'
            f'<text x="2" y="30">{ymax:.4g}</text><text x="2" y="150">{ymin:.4g}</text>'
            f'<text x="40" y="172">{xmin}</text><text x="490" y="172">{xmax}</text></svg>'
            f'<p class="muted">横轴：{html.escape(x_label)} · {len(points)} 个观测点</p></article>')


def render_monitor(input_path, output_path, *, refresh_seconds=10):
    """Atomically regenerate an escaped static page; only scalar summaries shown."""
    if type(refresh_seconds) is not int or refresh_seconds < 0:
        raise ValueError("refresh_seconds must be a nonnegative integer")
    events = read_events(input_path, allow_incomplete_tail=True)
    summary = summarize_events(events)
    sections = []
    for run, data in summary["runs"].items():
        items = [e for e in events if e["run_id"] == run]
        batches = defaultdict(list)
        for event in items:
            if event["event_type"] == "rollout.scored" and event["payload"]["split"] == "train":
                batches[event["trainer_iteration"], event["batch_id"]].append(event["payload"])
        trends = [(iteration, _rollout_summary(rows)) for (iteration, _), rows in batches.items()]
        plots = []
        for title, key in (("训练采样正确率（描述性）", "accuracy"), ("每条轨迹成本", "cost"),
                           ("冗余 token 比例", "redundant_token_fraction"), ("Grounding（有效测量）", "grounding_score")):
            points = [(step, row[key]["mean"] if isinstance(row[key], dict) else row[key]) for step, row in trends]
            plots.append(_sparkline(points, title, "trainer iteration；不是已提交更新步"))
        updates = [e["payload"] for e in items if e["event_type"] == "optimizer.result" and e["payload"]["status"] == "committed"]
        for key in ("approx_kl", "reference_kl", "entropy", "clip_fraction", "grad_norm", "lr"):
            plots.append(_sparkline([(u["steps_after"], u.get("metrics", {}).get(key)) for u in updates],
                                    key, "实际 optimizer committed step"))
        cards = (f'已计算批次 <b>{data["computed_batch_count"]}</b> · 已提交更新 <b>{data["optimizer_committed_count"]}</b>'
                 f' · 跳过 <b>{data["optimizer_skipped_count"]}</b> · 失败 <b>{data["optimizer_failed_count"]}</b>'
                 f' · 去重训练样本 <b>{data["train"]["sample_count"]}</b>')
        if data["run_kind"] in {"historical_real_trajectory_preflight", "frozen_rollout_audit"}:
            cards += '<p>历史轨迹只读审计 / CPU 过程预检：未在这里执行训练更新，不能作为训练后收益。</p>'
        if data["latest_advantage"]:
            advantage = data["latest_advantage"]
            cards += (f'<p>有效训练行：{advantage.get("valid_row_count", "—")} · 启用过程项的行：{advantage.get("process_row_count", "—")}'
                      f' · QA 回退组：{advantage.get("qa_disabled_group_count", "—")} · 全错组：{advantage.get("all_wrong_group_count", "—")}</p>')
            if "charged_events" in advantage:
                cards += (f'<p>同伴门控开启：{advantage["peer_gate_open_rows"]} 条 · 计价事件：{advantage["charged_events"]}'
                          f' · 截断轨迹计价事件：{advantage["charged_budget_events"]} · 局部扣分 token：{advantage["charged_policy_tokens"]}</p>')
        if data["latest_status"]:
            status = data["latest_status"]
            cards += (f'<p>状态：<b>{html.escape(status["status"])}</b> · 状态来源：{html.escape(status["status_source"])}'
                      f' · 文件状态：{html.escape(status["artifact_state"])}'
                      f' · 已观测轨迹：{status.get("trajectories_observed", "—")} / {status.get("trajectories_expected", "—")}'
                      f' · QA 错误：{status.get("qa_error_count", "—")} · 待完整/异常文件：{status.get("input_issue_count", "—")}</p>')
            usage = status.get("api_usage")
            if usage:
                cards += (f'<p>API 请求：{usage.get("request_count", "—")} · 输入 tokens：{usage.get("prompt_tokens", "—")}'
                          f' · 输出 tokens：{usage.get("completion_tokens", "—")}（最终总量包含约束抽取；不会再叠加分轨迹用量）</p>')
        readable = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        sections.append(f'<section><h2>{html.escape(run)} · training seed {data["training_seed"]}</h2><p>{cards}</p>'
                        f'<div class="grid">{"".join(plots)}</div><details><summary>分母、覆盖率、QA 与评测摘要</summary>'
                        f'<pre>{html.escape(readable)}</pre></details></section>')
    refresh = f'<meta http-equiv="refresh" content="{refresh_seconds}">' if refresh_seconds else ""
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'{refresh}<title>Ledger-GRPO 训练观测</title><style>'
            'body{font:15px system-ui,sans-serif;color:#173154;background:#f5f7fb;margin:24px auto;max-width:1240px;padding:0 18px}'
            'h1,h2{font-weight:650}section{margin:24px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}'
            'article,details{background:white;padding:16px;border:1px solid #dbe3ee;border-radius:8px}h3{margin:0;font-size:15px}'
            'svg{width:100%;height:auto}polyline{fill:none;stroke:#2563a6;stroke-width:2}circle{fill:#2563a6}.axis{fill:none;stroke:#b4c0d0}'
            'text{font-size:11px;fill:#52647b}.muted{color:#52647b;font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
            'details{margin-top:16px}summary{cursor:pointer}</style><h1>Ledger-GRPO 训练观测</h1>'
            '<p>曲线用于训练诊断，不证明算法收益。正确率与成本的结论需固定任务配对评测及独立训练 seeds。'
            '缺失值不补零；不同 run/seed 不合并。已提交步仅采信 optimizer 回调。</p>'
            f'<p class="muted">更新于 {datetime.now(timezone.utc).isoformat()} · 使用 --watch 才会持续重新生成本页面。</p>'
            + ("".join(sections) or '<p>等待事件。尚无已观测训练结果。</p>') + '</html>')
    output = Path(output_path)
    if Path(input_path).resolve() == output.resolve():
        raise ValueError("HTML output cannot overwrite the event log")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            stream.write(page)
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render private-text-free Ledger-GRPO JSONL monitoring events")
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--refresh-seconds", type=int, default=10)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    if args.watch and args.refresh_seconds < 1:
        parser.error("--watch requires positive --refresh-seconds")
    try:
        while True:
            render_monitor(args.input, args.output, refresh_seconds=args.refresh_seconds)
            if not args.watch:
                return 0
            time.sleep(args.refresh_seconds)
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError):
        parser.exit(2, "monitor could not validate or render the event log; no raw event contents were printed\n")


if __name__ == "__main__":
    raise SystemExit(main())
