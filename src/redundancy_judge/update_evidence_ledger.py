"""Apply validated tool evidence without importing actor assertions."""

from copy import deepcopy

from .common import JudgeFailure, candidate_name, exact_quote, identity, require

STATES = {"unknown", "partially_supported", "supported", "conflicted", "refuted"}


def support_key(candidate, constraint_id):
    return identity([candidate, constraint_id])


def refresh_gaps(task, after):
    risks = after.get("unresolved_evidence_risk", {}).get("by_support", {})
    for key, row in after["support"].items():
        if risks.get(key):
            row["unresolved_evidence_risk"] = risks[key]
    after["conflicts"] = [key for key, row in after["support"].items() if row["state"] == "conflicted"]
    constraints = [c["constraint_id"] for c in task["constraints"]]
    candidates = sorted({fact["candidate"] for fact in after["support"].values()})
    after["candidate_gaps"] = {candidate: [cid for cid in constraints
        if (after["support"].get(support_key(candidate, cid), {}).get("state") != "supported"
            or risks.get(support_key(candidate, cid)))]
        for candidate in candidates}
    after["open_gaps"] = [cid for cid in constraints if not any(
        row["constraint_id"] == cid and row["state"] == "supported"
        and not risks.get(support_key(row["candidate"], cid)) for row in after["support"].values())]


def _risk(after, delta, *, candidate, constraint_id, state, reason, event_id):
    """Record an unvalidated Judge row without promoting it to evidence."""
    potential_conflict = state in {"refuted", "conflicted"}
    record = {"candidate": candidate, "constraint_id": constraint_id, "state": state,
              "reason": reason, "event_id": event_id, "potential_conflict": potential_conflict}
    delta["rejected_evidence"].append(record)
    risks = after.setdefault("unresolved_evidence_risk", {"global": [], "by_support": {}})
    if candidate and constraint_id:
        key = support_key(candidate, constraint_id)
        risks["by_support"].setdefault(key, []).append(record)
        if key in after["support"]:
            after["support"][key]["unresolved_evidence_risk"] = risks["by_support"][key]
    else:
        risks["global"].append(record)


def merge_parallel_updates(task, before, branches):
    """Reconcile independently evaluated siblings at the next action boundary."""
    merged = deepcopy(before)
    alternatives = {}
    for after, delta in branches:
        merged.update(stage_id=after["stage_id"], visibility=after["visibility"])
        merged["attempts"].extend(after["attempts"][len(before["attempts"]):])
        merged["documents"] = sorted(set(merged["documents"]) | set(after["documents"]))
        for key in sorted({ref["support_key"] for ref in delta["evidence"]}):
            alternatives.setdefault(key, []).append(after["support"][key])
    for key, rows in sorted(alternatives.items()):
        evidence = {}
        for row in rows:
            for ref in row["evidence"]:
                evidence.setdefault((ref["document"], ref["quote"]), ref)
        states = {row["state"] for row in rows}
        state = ("conflicted" if "conflicted" in states or {"supported", "refuted"} <= states
                 else "supported" if "supported" in states else "refuted" if "refuted" in states
                 else "partially_supported")
        merged["support"][key] = {**rows[0], "state": state, "evidence": list(evidence.values())}
    for after, _ in branches:
        source = after.get("unresolved_evidence_risk", {})
        merged_risks = merged.setdefault("unresolved_evidence_risk", {"global": [], "by_support": {}})
        for row in source.get("global", []):
            if row not in merged_risks["global"]:
                merged_risks["global"].append(row)
        for key, rows in source.get("by_support", {}).items():
            dest = merged_risks["by_support"].setdefault(key, [])
            for row in rows:
                if row not in dest:
                    dest.append(row)
            if key in merged["support"]:
                merged["support"][key]["unresolved_evidence_risk"] = dest
    refresh_gaps(task, merged)
    return merged


def update_evidence_ledger(task, before, stage, event, judge):
    after = deepcopy(before)
    after.update(stage_id=stage["stage_id"], visibility=list(stage.get("visible_return_ids", ())))
    text = event.get("return_text")
    event_id = event["event_id"]
    delta = {"status": "unavailable", "effective_gain": None, "new_documents": [],
             "new_support": [], "strengthening": [], "conflicts": [], "resolved_conflicts": [],
             "evidence": [], "rejected_evidence": []}
    if (event.get("error") or stage.get("parse_status") != "ok"
            or not isinstance(text, str) or not event.get("visible_next")):
        after["attempts"].append({"stage_id": stage["stage_id"], "event_id": event_id,
                                  "action": stage.get("action"), "content_id": None,
                                  "status": "unavailable", "gain": None, "error": event.get("error")})
        return after, delta
    content_id = identity(text)
    document = event.get("source_id") or content_id
    seen_documents = set(event.get("document_ids") or [document])
    delta["new_documents"] = sorted(seen_documents - set(after["documents"]))
    after["documents"] = sorted(set(after["documents"]) | seen_documents)
    duplicate = next((item for item in before["attempts"] if item["content_id"] == content_id
                      and item["status"] == "ok"), None)
    try:
        if duplicate:
            updates = []
        else:
            response = judge.ask("evidence_update", {
                "task": task["constraints"], "returned_text": text,
                "prior": [{"candidate": row["candidate"], "constraint_id": row["constraint_id"],
                           "state": row["state"]} for row in before["support"].values()],
            })
            require(isinstance(response.get("updates"), list) and type(response.get("uncertain")) is bool,
                    "invalid evidence update")
            require(not response["uncertain"], "evidence extraction uncertain")
            updates = []
            seen = set()
            for row in response["updates"]:
                candidate, cid, state = candidate_name(row.get("candidate")), row.get("constraint_id"), row.get("state")
                if not (candidate and cid in {c["constraint_id"] for c in task["constraints"]}
                        and state in STATES - {"unknown"}):
                    _risk(after, delta, candidate=candidate, constraint_id=cid if isinstance(cid, str) else None,
                          state=state if isinstance(state, str) else "unknown",
                          reason="invalid support coordinates or state", event_id=event_id)
                    continue
                key = support_key(candidate, cid)
                if key in seen:
                    _risk(after, delta, candidate=candidate, constraint_id=cid, state=state,
                          reason="duplicate candidate/constraint update", event_id=event_id)
                    continue
                seen.add(key)
                resolves = row.get("resolves_conflict", False)
                if type(resolves) is not bool:
                    _risk(after, delta, candidate=candidate, constraint_id=cid, state=state,
                          reason="invalid conflict resolution field", event_id=event_id)
                    continue
                try:
                    ref = dict(exact_quote(text, row), event_id=event_id, content_id=content_id, support_key=key,
                               reference=event.get("return_ref"), document=document, state=state)
                except JudgeFailure as exc:
                    _risk(after, delta, candidate=candidate, constraint_id=cid, state=state,
                          reason=str(exc), event_id=event_id)
                    continue
                updates.append((key, candidate, cid, state, ref, resolves))
        for key, candidate, cid, state, ref, resolves in updates:
            old = after["support"].get(key)
            prior_state = old["state"] if old else "unknown"
            contradictory = {prior_state, state} == {"supported", "refuted"}
            if (contradictory or prior_state == "conflicted") and not resolves:
                state = "conflicted"
            if state == "partially_supported" and prior_state in {"supported", "refuted"}:
                state = prior_state
            evidence = (old["evidence"][:] if old else [])
            delta["evidence"].append(ref)
            is_new = not any((item["document"], item["quote"]) == (ref["document"], ref["quote"])
                             for item in evidence)
            if is_new:
                evidence.append(ref)
            after["support"][key] = {"candidate": candidate, "constraint_id": cid, "state": state,
                                     "evidence": evidence}
            if state == "conflicted" and prior_state != state:
                delta["conflicts"].append(key)
            elif prior_state == "conflicted" and state != prior_state:
                delta["resolved_conflicts"].append(key)
            elif state != prior_state:
                delta["new_support"].append(key)
            elif is_new and state in {"supported", "partially_supported"}:
                delta["strengthening"].append(key)
        delta.update(status="ok", effective_gain=any(delta[k] for k in
                     ("new_support", "strengthening", "conflicts", "resolved_conflicts")))
        if delta["rejected_evidence"]:
            delta["status"] = "partial_annotation"
            # A rejected possible refutation cannot be priced as harmless.
            # An unrelated malformed support row does not erase a separately
            # validated update, but remains visible through its scoped risk.
            if any(row["potential_conflict"] for row in delta["rejected_evidence"]):
                delta["effective_gain"] = None
    except (JudgeFailure, AttributeError, TypeError) as exc:
        delta.update(status="annotation_error", error=str(exc))
    after["attempts"].append({"stage_id": stage["stage_id"], "event_id": event_id,
                              "action": stage.get("action"), "content_id": content_id,
                              "status": delta["status"], "gain": delta["effective_gain"],
                              "error": event.get("error")})
    refresh_gaps(task, after)
    return after, delta
