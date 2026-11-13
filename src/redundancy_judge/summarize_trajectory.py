"""Summarize evidence coverage and emit candidate local price events."""

from collections import Counter

from .common import candidate_name
from .update_evidence_ledger import support_key


def summarize_trajectory(trajectory, task, ledger, stages, judgments, *, submitted_candidate=None):
    candidate = candidate_name(submitted_candidate)
    constraints = [item["constraint_id"] for item in task["constraints"]]
    supported = [cid for cid in constraints if candidate and
                 ledger["support"].get(support_key(candidate, cid), {}).get("state") == "supported"]
    evidence_incomplete = any(attempt["status"] == "annotation_error" for attempt in ledger["attempts"])
    g = (len(supported) / len(constraints)
         if candidate and constraints and not task["uncertain"] and not evidence_incomplete else None)
    stages_by_id = {row["stage_id"]: row for row in stages}
    counts, priced_cost = Counter(), Counter()
    events = []
    for judgment in judgments:
        counts.update(f"{row['label']}:{row['decision']}" for row in judgment["labels"])
        label = judgment["price_label"]
        if label:
            stage = stages_by_id[judgment["stage_id"]]
            cost = stage["cost"]
            events.append({"event_id": judgment["event_id"], "stage_type": stage["stage_type"],
                           "label": label, "decision": "positive", "reward_eligible": True,
                           "charge_token_spans": judgment["charge_token_spans"],
                           "event_cost": {"generated_tokens": cost.get("policy_tokens"),
                                          "returned_tokens": cost.get("return_tokens"),
                                          "tool_calls": cost.get("tool_calls", 1)},
                           "provenance": judgment.get("provenance", trajectory.get("provenance"))})
            priced_cost.update({key: value for key, value in cost.items() if type(value) is int})
    total_cost = Counter()
    for stage in stages:
        total_cost.update({key: value for key, value in stage.get("cost", {}).items() if type(value) is int})
    known_cost_keys = {key for key in total_cost if all(
        stage.get("cost", {}).get(key) is not None for stage in stages)}
    tools = sum(stage["stage_type"] == "tool" for stage in stages)
    return {**{key: trajectory[key] for key in (
                "question_id", "trajectory_id", "result", "Y", "result_source", "termination_reason",
                "raw_termination_reason", "recording_complete", "policy_token_count", "policy_token_spans",
                "token_alignment_status", "synthetic", "provenance", "split") if key in trajectory},
            "counts": dict(counts), "stage_count": len(stages), "tool_stage_count": tools,
            "judgment_coverage": len({row["stage_id"] for row in judgments}) / tools if tools else None,
            "abstentions": sum(v for k, v in counts.items() if k.endswith(":abstain")),
            "anomalies": len(trajectory.get("anomalies", ())),
            "cost": {k: v if k in known_cost_keys else None for k, v in total_cost.items()},
            "unpriced_cost": {k: v - priced_cost[k] if k in known_cost_keys else None
                              for k, v in total_cost.items()},
            "thought_lengths": trajectory.get("thought_lengths", []),
            "g": g, "grounding_status": "valid" if g is not None else "invalid",
            "grounding_issue": "missing_or_ambiguous_submitted_candidate" if not candidate else
            "uncertain_task" if task["uncertain"] or not constraints else
            "incomplete_evidence_updates" if evidence_incomplete else None,
            "supported_constraints": supported,
            "unresolved_constraints": [cid for cid in constraints if cid not in supported],
            "events": events}
