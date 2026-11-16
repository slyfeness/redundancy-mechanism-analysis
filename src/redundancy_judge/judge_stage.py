"""Label a completed action using only its prefix and observed return."""

from .adapters.model import uses_lenient_quotes
from .common import JudgeFailure, candidate_name, identity, require
from .docid import judge_docid_stage, normalize_query
from .update_evidence_ledger import support_key, unresolved_risks


def comparable_action(action, *, docid=False):
    args = action.get("arguments")
    if not isinstance(args, dict) or not action.get("deterministic") or not action.get("environment"):
        return None
    if "search" in action["tool_name"].casefold():
        if set(args) != {"query"} or not isinstance(args["query"], str) or not args["query"].strip():
            return None
        if docid:
            args = {"query": normalize_query(args["query"])}
    return identity([action["tool_name"], action["environment"], args])


def judge_stage(task, before, after, stage, event, target, delta, judge, *, threshold=0.8, previous_targets=None):
    if task.get("phase1_mode") == "docid":
        return judge_docid_stage(task, before, stage, event, target, delta, comparable_action)
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
    valid_ids = {item["constraint_id"] for item in task["constraints"]}
    risk_candidate = candidate_name(target["candidate"]) if confirmations and target["constraint_id"] in valid_ids else None
    risk_refs = {}
    for ledger in (before, after):
        for risk in unresolved_risks(ledger, candidate=risk_candidate, constraint_ids=[target["constraint_id"]],
                                     event_id=event["event_id"], content_id=content_id):
            risk_refs[identity(risk)] = risk
    risk_blocked = bool(risk_refs)
    r1_risk_blocked = risk_blocked
    if uses_lenient_quotes(judge):
        r1_risk_blocked = any(risk.get("scope") == "support"
                              and risk["candidate"] == risk_candidate
                              and risk["constraint_id"] == target["constraint_id"] for risk in risk_refs.values())
    risk_reason = None
    if risk_refs:
        if any(r.get("scope", "global") == "global" for r in risk_refs.values()):
            risk_reason = "global_unresolved_evidence"
        else:
            risk_reason = "related_unresolved_evidence" if risk_candidate else "unresolved_evidence_target_unknown"
    problems = []
    r2b = ("positive" if exact and not protections else "negative") if has_return and action_key else "abstain"
    r1 = "abstain"
    verification = None
    r1_funnel = {"outcome": "not_invoked", "reason": None}
    if risk_blocked:
        r2b = "abstain"
    if r1_risk_blocked:
        r1_funnel = {"outcome": "not_invoked", "reason": "unresolved_evidence_risk"}
    elif has_return and confirmations and delta.get("status") == "ok":
        if not matching or target["intent"] != "verify" or protections:
            r1 = "negative"
            r1_funnel = {"outcome": "not_invoked", "reason": "precondition_not_met"}
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
                if confidence < threshold:
                    r1_funnel = {"outcome": "low_confidence", "reason": "judge_below_threshold"}
                elif not value["confirmed"]:
                    r1_funnel = {"outcome": "negative", "reason": "judge_not_confirmed"}
                else:
                    r1_funnel = {"outcome": "positive", "reason": "judge_confirmed"}
                if confidence >= threshold:
                    r1 = "positive" if value["confirmed"] and not protections else "negative"
            except (JudgeFailure, AttributeError, TypeError) as exc:
                problems.append(str(exc))
                r1_funnel = {"outcome": "error", "reason": str(exc)}
    elif not has_return:
        r1_funnel = {"outcome": "not_invoked", "reason": "no_visible_return"}
    elif not confirmations:
        r1_funnel = {"outcome": "not_invoked", "reason": "action_target_uncertain"}
    elif delta.get("status") != "ok":
        r1_funnel = {"outcome": "not_invoked", "reason": "evidence_update_unavailable"}
    if protections and r2b == "positive":
        r2b = "negative"
    if stage.get("parse_status") != "ok":
        r1 = r2b = "abstain"

    similarity, similar = 0.0, []
    previous_targets = previous_targets or {}
    query = (action.get("arguments") or {}).get("query") if isinstance(action.get("arguments"), dict) else None
    unresolved_gap = fact.get("state") not in {"supported", "refuted"} and target["intent"] in {"fill_gap", "explore"}
    if confirmations and unresolved_gap and isinstance(query, str):
        query_words = set(query.casefold().split())
        for row in historical:
            prior = previous_targets.get(row["event_id"], {})
            if ((prior.get("candidate"), prior.get("constraint_id")) != (target["candidate"], target["constraint_id"])
                    or prior.get("intent") not in {"fill_gap", "explore"}):
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
           ) if (not risk_blocked and confirmations and has_return and stage.get("parse_status") == "ok"
                 and delta["effective_gain"] is not None) else "abstain"
    eligible_stage = (stage["stage_type"] == "tool" and stage.get("parse_status") == "ok"
                      and not stage.get("parallel_group_id") and bool(spans))
    evidence = fact.get("evidence", [])
    known_at = event.get("return_time") if has_return else None
    labels = [
        {"label": label, "decision": decision, "protected": bool(protections),
         "reward_eligible": bool(label != "R2a" and decision == "positive" and eligible_stage
                                 and not protections and not label_risk),
         "known_at": known_at, "decision_time": "after_return" if known_at is not None else "unavailable",
         "abstention_reason": (None if decision != "abstain" else
             "protocol_error" if stage.get("parse_status") != "ok" else
             "successful_visible_return_missing" if not has_return else
             "unresolved_evidence_risk" if label_risk else
             "comparison_environment_or_arguments_unverified" if label == "R2b" else
             "action_target_uncertain" if not confirmations else
             "evidence_update_unavailable" if delta["effective_gain"] is None else
             "verification_error" if problems else
             "low_verification_confidence" if r1_funnel["outcome"] == "low_confidence" else
             "r1_not_invoked"),
         "evidence": evidence if label == "R1" else [r["event_id"] for r in exact if r["event_id"] in visible]
         if label == "R2b" else similar}
        for label, decision in (("R2b", r2b), ("R1", r1), ("R2a", r2a))
        for label_risk in (r1_risk_blocked if label == "R1" else risk_blocked,)
    ]
    price_label = next((row["label"] for row in labels if row["reward_eligible"]), None)
    return {"stage_id": stage["stage_id"], "event_id": event["event_id"], "labels": labels,
            "price_label": price_label, "protections": sorted(set(protections)),
            "risk_guard_reason": risk_reason, "risk_guard_refs": list(risk_refs.values()),
            "pricing_blocked_by_risk": risk_blocked and r1_risk_blocked,
            "charge_token_spans": spans if price_label else [],
            "position_strategy": "verified_call_envelope" if price_label else "unpriced",
            "diagnostics": {"r1_check": verification, "r2a_similarity": similarity,
                            "same_gap_attempts": similar, "effective_gain": delta["effective_gain"],
                            "exact_repeat_ids": [r["event_id"] for r in exact],
                            "r1_funnel": r1_funnel},
            "errors": problems}
