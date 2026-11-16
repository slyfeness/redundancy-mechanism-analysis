"""Resolve intent using the information available before dispatch."""

from .common import JudgeFailure, candidate_name, require
from .m3_docid import resolve_docid_target

INTENTS = {"explore", "verify", "fill_gap", "resolve_conflict", "strengthen",
           "open_fulltext", "recover", "retry", "unknown"}


def resolve_action_target(task, before, stage, judge, *, threshold=0.8):
    unknown = {"state": "unknown", "candidate": None, "constraint_id": None,
               "gap_id": None, "intent": "unknown", "confidence": None, "evidence_basis": []}
    if task.get("phase1_mode") == "docid":
        return resolve_docid_target(before, stage, judge, unknown)
    action = stage.get("action")
    if not action or task["uncertain"]:
        return unknown
    visible = set(stage.get("visible_return_ids", ()))
    facts = [{"candidate": row["candidate"], "constraint_id": row["constraint_id"],
              "state": row["state"], "visible": any(ref["event_id"] in visible for ref in row["evidence"])}
             for row in before["support"].values()]
    try:
        value = judge.ask("action_target", {"task": task["constraints"], "facts": facts,
                          "tool_name": action["tool_name"], "arguments": action["arguments"],
                          "strategy": stage.get("strategy_text", "")})
        if task.get("constraint_source") == "frozen_v4":
            # Preserve the raw candidate-presence flag before unresolved fields are nulled.
            unknown["candidate_present_in_response"] = bool(candidate_name(value.get("candidate")))
        confidence, intent = value.get("confidence"), value.get("intent")
        require(type(confidence) in (int, float) and 0 <= confidence <= 1 and intent in INTENTS,
                "invalid action target")
        cid, candidate, gap_id = value.get("constraint_id"), candidate_name(value.get("candidate")), value.get("gap_id")
        valid_constraints = {c["constraint_id"] for c in task["constraints"]}
        basis = value.get("evidence_basis", [])
        require(isinstance(basis, list) and all(isinstance(item, str) for item in basis),
                "invalid action target evidence basis")
        if intent == "unknown" or confidence < threshold:
            return dict(unknown, confidence=confidence, reason="uncertain_target")
        if not candidate or cid not in valid_constraints:
            if intent == "explore" and gap_id in valid_constraints:
                return {"state": "gap_resolved", "candidate": None, "constraint_id": None, "gap_id": gap_id,
                        "intent": intent, "confidence": confidence, "evidence_basis": basis,
                        **{key: unknown[key] for key in ("candidate_present_in_response",) if key in unknown}}
            return dict(unknown, confidence=confidence, reason="uncertain_target")
        return {"state": "resolved", "candidate": candidate, "constraint_id": cid, "intent": intent,
                "gap_id": gap_id if gap_id in valid_constraints else None,
                "confidence": confidence, "evidence_basis": basis or ["pre_action_ledger", "arguments", "strategy"]}
    except (JudgeFailure, AttributeError, TypeError) as exc:
        return dict(unknown, error=str(exc))
