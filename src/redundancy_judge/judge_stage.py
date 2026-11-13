"""Label a completed action using only its prefix and observed return."""

from .common import JudgeFailure, identity, require
from .update_evidence_ledger import support_key


def comparable_action(action):
    args = action.get("arguments")
    if not isinstance(args, dict) or not action.get("deterministic") or not action.get("environment"):
        return None
    if "search" in action["tool_name"].casefold():
        if set(args) != {"query"} or not isinstance(args["query"], str) or not args["query"].strip():
            return None
    return identity([action["tool_name"], action["environment"], args])


def judge_stage(task, before, after, stage, event, target, delta, judge, *, threshold=0.8, previous_targets=None):
    action = stage.get("action") or {}
    spans = stage.get("charge_token_spans") or []
    visible = set(stage.get("visible_return_ids", ()))
    historical = before["attempts"]
    confirmations = target["state"] == "resolved"
    fact = before["support"].get(support_key(target["candidate"], target["constraint_id"]), {})
    matching = fact.get("state") == "supported"
    supported_visible = any(ref["event_id"] in visible for ref in fact.get("evidence", ()))
    if not supported_visible and fact:
        visible_contents = {row["content_id"] for row in historical if row["event_id"] in visible}
        supported_visible = any(ref["content_id"] in visible_contents for ref in fact["evidence"])
    protections = []
    if target.get("intent") in {"resolve_conflict", "strengthen", "open_fulltext", "recover", "retry"}:
        protections.append({"resolve_conflict": "resolve_conflict", "strengthen": "independent_support",
                            "open_fulltext": "summary_to_fulltext", "recover": "restore_invisible_evidence",
                            "retry": "tool_failure_retry"}[target["intent"]])
    if matching and not supported_visible:
        protections.append("restore_invisible_evidence")
    if fact.get("state") == "conflicted":
        protections.append("resolve_conflict")
    if delta.get("effective_gain"):
        protections.append("first_evidence" if not historical else "effective_evidence")

    action_key = comparable_action(action)
    returned = event.get("return_text")
    content_id = identity(returned) if isinstance(returned, str) and event.get("visible_next") else None
    repeats = [row for row in historical if action_key and comparable_action(row.get("action") or {}) == action_key]
    if repeats and repeats[-1].get("error"):
        protections.append("tool_failure_retry")
    exact = [row for row in repeats if content_id and row["content_id"] == content_id and not row.get("error")]
    if exact and not any(row["event_id"] in visible for row in exact):
        protections.append("restore_invisible_evidence")
    has_return = content_id is not None and not event.get("error")
    problems = []
    r2b = ("positive" if exact and not protections else "negative") if has_return and action_key else "abstain"
    r1 = "abstain"
    verification = None
    if has_return and confirmations and delta.get("status") == "ok":
        if not matching or target["intent"] != "verify" or protections:
            r1 = "negative"
        else:
            try:
                value = judge.ask("r1_verification", {
                    "constraint": next(c for c in task["constraints"] if c["constraint_id"] == target["constraint_id"]),
                    "target": target, "parameters": action["arguments"],
                    "prior_evidence": [ref for ref in fact["evidence"] if ref["event_id"] in visible],
                    "returned_text": returned, "new_documents": delta["new_documents"],
                })
                confidence = value.get("confidence")
                require(type(confidence) in (int, float) and 0 <= confidence <= 1
                        and type(value.get("confirmed")) is bool, "invalid R1 verification")
                protection = value.get("protection")
                require(protection in (None, "first_evidence", "resolve_conflict", "independent_support",
                           "summary_to_fulltext", "restore_invisible_evidence", "tool_failure_retry"),
                        "unknown R1 protection")
                if protection:
                    protections.append(protection)
                verification = {"confidence": confidence, "confirmed": value["confirmed"],
                                "protection": protection}
                if confidence >= threshold:
                    r1 = "positive" if value["confirmed"] and not protections else "negative"
            except (JudgeFailure, AttributeError, TypeError) as exc:
                problems.append(str(exc))
    if protections and r2b == "positive":
        r2b = "negative"

    similarity, similar = 0.0, []
    previous_targets = previous_targets or {}
    query = (action.get("arguments") or {}).get("query") if isinstance(action.get("arguments"), dict) else None
    if confirmations and isinstance(query, str):
        query_words = set(query.casefold().split())
        for row in historical:
            prior = previous_targets.get(row["stage_id"], {})
            if (prior.get("candidate"), prior.get("constraint_id")) != (target["candidate"], target["constraint_id"]):
                continue
            args = (row.get("action") or {}).get("arguments")
            other = args.get("query") if isinstance(args, dict) else None
            if isinstance(other, str):
                words = set(other.casefold().split())
                score = len(query_words & words) / max(len(query_words | words), 1)
                similarity = max(similarity, score)
                if score >= 0.6 and other != query:
                    similar.append(row["event_id"])
    r2a = ("positive" if similar and delta["effective_gain"] is False and not protections else "negative"
           ) if confirmations and has_return and delta["effective_gain"] is not None else "abstain"
    eligible_stage = (stage["stage_type"] == "tool" and stage.get("parse_status") == "ok"
                      and not stage.get("parallel_group_id") and bool(spans))
    evidence = fact.get("evidence", [])
    known_at = event.get("return_time")
    labels = [
        {"label": label, "decision": decision, "protected": bool(protections),
         "reward_eligible": bool(label != "R2a" and decision == "positive" and eligible_stage and not protections),
         "known_at": known_at, "decision_time": "after_return" if known_at is not None else "unavailable",
         "evidence": evidence if label == "R1" else [r["event_id"] for r in exact if r["event_id"] in visible]
         if label == "R2b" else similar}
        for label, decision in (("R2b", r2b), ("R1", r1), ("R2a", r2a))
    ]
    price_label = next((row["label"] for row in labels if row["reward_eligible"]), None)
    return {"stage_id": stage["stage_id"], "event_id": event["event_id"], "labels": labels,
            "price_label": price_label, "protections": sorted(set(protections)),
            "charge_token_spans": spans if price_label else [],
            "position_strategy": "verified_call_envelope" if price_label else "unpriced",
            "diagnostics": {"r1_check": verification, "r2a_similarity": similarity,
                            "same_gap_attempts": similar, "effective_gain": delta["effective_gain"],
                            "exact_repeat_ids": [r["event_id"] for r in exact]},
            "errors": problems}
