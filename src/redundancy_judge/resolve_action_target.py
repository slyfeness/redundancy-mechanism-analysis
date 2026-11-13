"""Resolve intent using the information available before dispatch."""

from .common import JudgeFailure, candidate_name, require

INTENTS = {"explore", "verify", "fill_gap", "resolve_conflict", "strengthen",
           "open_fulltext", "recover", "retry", "unknown"}


def resolve_action_target(task, before, stage, judge, *, threshold=0.8):
    unknown = {"state": "unknown", "candidate": None, "constraint_id": None,
               "intent": "unknown", "confidence": None}
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
        confidence, intent = value.get("confidence"), value.get("intent")
        require(type(confidence) in (int, float) and 0 <= confidence <= 1 and intent in INTENTS,
                "invalid action target")
        cid, candidate = value.get("constraint_id"), candidate_name(value.get("candidate"))
        if intent == "unknown" or confidence < threshold or not candidate or cid not in {
                c["constraint_id"] for c in task["constraints"]}:
            return dict(unknown, confidence=confidence, reason="uncertain_target")
        return {"state": "resolved", "candidate": candidate, "constraint_id": cid, "intent": intent,
                "confidence": confidence, "basis": ["pre_action_ledger", "arguments", "strategy"]}
    except (JudgeFailure, AttributeError, TypeError) as exc:
        return dict(unknown, error=str(exc))
