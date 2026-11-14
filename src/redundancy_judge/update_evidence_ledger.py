"""Apply validated tool evidence without importing actor assertions."""

from copy import deepcopy
import re

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


def unresolved_risks(ledger, *, candidate=None, constraint_ids=None, event_id=None, content_id=None):
    """Collect global risk and local risk relevant to the requested scope."""
    risks = ledger.get("unresolved_evidence_risk", {})
    selected = list(risks.get("global", []))
    keys = ({support_key(candidate, cid) for cid in constraint_ids}
            if candidate and constraint_ids is not None else None)
    for key, records in risks.get("by_support", {}).items():
        selected.extend(record for record in records if keys is None or key in keys
                        or (event_id is not None and record.get("event_id") == event_id)
                        or (content_id is not None and record.get("content_id") == content_id))
    return selected


def _risk(after, *, candidate, constraint_id, state, reason, source, valid_constraints):
    """Record an unvalidated Judge row without promoting it to evidence."""
    local = bool(candidate and isinstance(constraint_id, str) and constraint_id in valid_constraints)
    record = {"candidate": candidate, "constraint_id": constraint_id, "state": state,
              "reason": reason, **source, "scope": "support" if local else "global",
              "potential_conflict": not local or state not in {"supported", "partially_supported"}}
    risks = after.setdefault("unresolved_evidence_risk", {"global": [], "by_support": {}})
    if local:
        key = support_key(candidate, constraint_id)
        risks["by_support"].setdefault(key, []).append(record)
        if key in after["support"]:
            after["support"][key]["unresolved_evidence_risk"] = risks["by_support"][key]
    else:
        risks["global"].append(record)
    return record


def _mention(text, value):
    return value and re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text)


def _uncertainty_coordinates(text, scope, task, before):
    """Localize overall uncertainty only when the scope covers the whole observed return."""
    if not isinstance(scope, dict):
        return None, None
    candidate, constraint_id = candidate_name(scope.get("candidate")), scope.get("constraint_id")
    normalized = candidate_name(text) or ""
    mentioned = {row["constraint_id"] for row in task["constraints"]
                 if _mention(normalized, candidate_name(row.get("text")))}
    known_candidates = {row["candidate"] for row in before["support"].values()}
    if (candidate not in known_candidates or not isinstance(constraint_id, str) or mentioned != {constraint_id}
            or not _mention(normalized, candidate)
            or any(_mention(normalized, other) for other in known_candidates - {candidate})):
        return None, None
    start, end = len(text) - len(text.lstrip()), len(text.rstrip())
    if (type(scope.get("start")) is int and type(scope.get("end")) is int
            and (scope["start"], scope["end"]) == (start, end) and start < end
            and text[start:end] == scope.get("quote")):
        return candidate, constraint_id
    return None, None


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
    valid_constraints = {c["constraint_id"] for c in task["constraints"]}
    source = {"event_id": event_id, "content_id": content_id}
    uncertain_scope = (None, None)

    def reject(candidate, cid, state, reason):
        delta["rejected_evidence"].append(_risk(after, candidate=candidate, constraint_id=cid, state=state,
            reason=reason, source=source, valid_constraints=valid_constraints))

    try:
        if duplicate:
            updates = []
        else:
            response = judge.ask("evidence_update", {
                "task": task["constraints"], "returned_text": text,
                "prior": [{"candidate": row["candidate"], "constraint_id": row["constraint_id"],
                           "state": row["state"]} for row in before["support"].values()],
            })
            require(isinstance(response, dict) and isinstance(response.get("updates"), list)
                    and type(response.get("uncertain")) is bool,
                    "invalid evidence update")
            if response["uncertain"]:
                if not response["updates"]:
                    uncertain_scope = _uncertainty_coordinates(text, response.get("uncertainty_scope"), task, before)
                raise JudgeFailure("evidence extraction uncertain")
            if getattr(judge, "protocol_version", None):
                require("uncertainty_scope" in response, "versioned evidence update is missing uncertainty scope")
            require(response.get("uncertainty_scope") is None, "inconsistent evidence uncertainty scope")
            updates = []
            seen = set()
            for row in response["updates"]:
                if not isinstance(row, dict):
                    reject(None, None, "unknown", "invalid evidence update row")
                    continue
                candidate, cid, state = candidate_name(row.get("candidate")), row.get("constraint_id"), row.get("state")
                cid = cid if isinstance(cid, str) else None
                state = state if isinstance(state, str) else "unknown"
                if not (candidate and cid in valid_constraints and state in STATES - {"unknown"}):
                    reject(candidate, cid, state, "invalid support coordinates or state")
                    continue
                key = support_key(candidate, cid)
                if key in seen:
                    reject(candidate, cid, state, "duplicate candidate/constraint update")
                    continue
                seen.add(key)
                resolves = row.get("resolves_conflict", False)
                if type(resolves) is not bool:
                    reject(candidate, cid, state, "invalid conflict resolution field")
                    continue
                try:
                    ref = dict(exact_quote(text, row), event_id=event_id, content_id=content_id, support_key=key,
                               reference=event.get("return_ref"), document=document, state=state)
                except JudgeFailure as exc:
                    reject(candidate, cid, state, str(exc))
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
            if not delta["effective_gain"] or any(row["potential_conflict"] for row in delta["rejected_evidence"]):
                delta["effective_gain"] = None
    except (JudgeFailure, AttributeError, TypeError) as exc:
        candidate, cid = uncertain_scope
        _risk(after, candidate=candidate, constraint_id=cid, state="unknown", reason=str(exc),
              source=source, valid_constraints=valid_constraints)
        delta.update(status="annotation_error", effective_gain=None, error=str(exc))
    after["attempts"].append({"stage_id": stage["stage_id"], "event_id": event_id,
                              "action": stage.get("action"), "content_id": content_id,
                              "status": delta["status"], "gain": delta["effective_gain"],
                              "error": event.get("error")})
    refresh_gaps(task, after)
    return after, delta
