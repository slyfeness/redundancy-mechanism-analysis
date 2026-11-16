"""Two-step M3 resolver for the DocID ledger."""

from .common import JudgeFailure, require


def object_schema(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def resolve_docid_target(before, stage, judge, base):
    target = {**base, "intent": "explore", "seeking": None, "entity": None, "attribute": None,
              "already_stated": None, "passage_ids": [], "skip_reason": None,
              "provided_passage_ids": [], "format_conflict": False}
    action = stage.get("action") or {}
    args = action.get("arguments")
    query = args.get("query") if isinstance(args, dict) else None
    if stage.get("parse_status") != "ok" or not isinstance(query, str) or not stage.get("m3_event_id"):
        return dict(target, skip_reason="protocol_error")
    eid = stage["m3_event_id"]
    reasoning = (stage.get("m3_reasoning") or "")[-1500:]
    try:
        first = judge.ask_m3("intent", {"agent_reasoning_before_search": reasoning, "current_search_query": query},
                            object_schema({"seeking": {"type": "string"}, "entity": {"type": ["string", "null"]},
                                           "attribute": {"type": "string"}}), eid)
        require(set(first) == {"seeking", "entity", "attribute"} and isinstance(first["seeking"], str)
                and isinstance(first["attribute"], str) and (first["entity"] is None or isinstance(first["entity"], str)),
                "invalid M3 intent response")
    except (JudgeFailure, AttributeError, TypeError) as exc:
        return dict(target, skip_reason="first_call_failed", error=str(exc))
    target.update(first)
    entity = first["entity"]
    if entity is None or entity.strip().lower() in {"", "null", "none", "n/a", "unknown"}:
        return dict(target, entity=None, skip_reason="new_candidate")
    target.update(state="resolved", candidate=entity, candidate_present_in_response=bool(entity))
    prior = [{"id": "P" + docid, "text": text} for docid, text in before.get("evidence_passages", {}).items()]
    if not prior:
        return dict(target, skip_reason="no_prior_passages")
    ids = [row["id"] for row in prior]
    target["provided_passage_ids"] = ids
    try:
        second = judge.ask_m3("verification", {**first, "current_search_query": query, "previously_seen_passages": prior},
                             object_schema({"reason": {"type": "string"}, "already_stated": {"type": "boolean"},
                                            "passage_ids": {"type": "array", "items": {"type": "string", "enum": ids}}}),
                             eid)
        require(set(second) == {"reason", "already_stated", "passage_ids"} and isinstance(second["reason"], str)
                and type(second["already_stated"]) is bool and isinstance(second["passage_ids"], list)
                and all(isinstance(pid, str) for pid in second["passage_ids"]), "invalid M3 verification response")
    except (JudgeFailure, AttributeError, TypeError) as exc:
        return dict(target, skip_reason="second_call_failed", error=str(exc))
    stated, selected = second["already_stated"], second["passage_ids"]
    conflict = (stated and (not selected or not set(selected) <= set(ids))) or (not stated and bool(selected))
    accepted = stated and not conflict
    target.update(already_stated=stated, passage_ids=selected, format_conflict=conflict,
                  intent="verify" if accepted else "explore", evidence_basis=selected if accepted else [])
    return target
