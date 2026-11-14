"""Incremental, citation-checked belief ledger, never a ground-truth oracle."""
from copy import deepcopy
from .schema import document_key


class CitationError(ValueError):
    pass


def initial_ledger(trace):
    return {"constraints": deepcopy(trace["constraints"]), "facts": [], "attempts": [],
            "decisions": [], "artifacts": {}, "seen_documents": [], "seen_evidence": [],
            "revision": 0, "last_gain_turn": None, "gaps": [
                {"gid": c["cid"], "about": c["cid"], "status": "open", "attempts": []}
                for c in trace["constraints"] if c["required"]]}


def verify_citation(citation, registry, cutoff):
    if not isinstance(citation, dict):
        raise CitationError("citation must be an object")
    eid, quote = citation.get("evidence_id"), citation.get("quote")
    if eid not in registry or registry[eid]["turn_id"] > cutoff:
        raise CitationError(f"citation {eid!r} is missing or not yet visible")
    if not isinstance(quote, str) or not quote or quote not in registry[eid]["text"]:
        raise CitationError(f"citation {eid!r} does not quote the original observation")
    if "start" in citation or "end" in citation:
        start, end = citation.get("start"), citation.get("end")
        text = registry[eid]["text"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or text[start:end] != quote:
            raise CitationError("citation offsets (Unicode code points) do not match the quote")


def _fact_signature(fact, registry):
    # Re-fetching the same content cannot manufacture fresh evidence or new lineage.
    sources = sorted({(document_key(registry[c["evidence_id"]]), c["quote"]) for c in fact["evidence"]})
    return (fact["cid"], fact["candidate_id"], fact["statement"], fact["state"], sources)


def apply_delta(before, turn, delta, registry):
    """Apply one validated delta atomically; a failed delta changes no semantic facts."""
    if not isinstance(delta, dict) or not isinstance(delta.get("facts"), list):
        raise ValueError("ledger delta requires a facts list (empty means explicitly no new facts)")
    if set(delta) - {"facts", "new_reasoning", "action_target"}:
        raise ValueError("unknown ledger delta fields")
    if "new_reasoning" in delta and type(delta["new_reasoning"]) is not bool:
        raise ValueError("new_reasoning must be a boolean")
    after = deepcopy(before)
    by_id = {f["fid"]: f for f in after["facts"]}
    constraints = {c["cid"] for c in before["constraints"]}
    tid = turn["turn_id"]
    semantic_gain = bool(delta.get("new_reasoning", False))
    updated = set()
    for raw in delta["facts"]:
        fact = deepcopy(raw)
        if not isinstance(fact, dict) or set(fact) - {"fid", "cid", "candidate_id", "statement", "state", "evidence"}:
            raise ValueError("unexpected fact fields; computed fields cannot be supplied by the judge")
        for key in ("fid", "cid", "candidate_id", "statement"):
            if not isinstance(fact.get(key), str) or not fact[key]:
                raise ValueError(f"fact.{key} must be a nonempty string")
        if fact["fid"] in updated or fact["cid"] not in constraints:
            raise ValueError("duplicate fact delta or unknown constraint")
        updated.add(fact["fid"])
        if fact.get("state") not in {"supported", "refuted", "unknown", "assumed"}:
            raise ValueError("invalid fact state")
        if not isinstance(fact.get("evidence"), list):
            raise CitationError("fact evidence must be a list")
        if fact["state"] in {"supported", "refuted"} and not fact["evidence"]:
            raise CitationError("supported/refuted facts require original observations")
        for cite in fact["evidence"]:
            verify_citation(cite, registry, tid)
        old = by_id.get(fact["fid"])
        if old and (old["cid"], old["candidate_id"]) != (fact["cid"], fact["candidate_id"]):
            raise ValueError("a fact ID cannot be reassigned to another constraint or candidate")
        changed = old is None or _fact_signature(old, registry) != _fact_signature(fact, registry)
        semantic_gain |= changed
        # Support provenance survives unchanged refreshes but is reset after a refutation.
        fact["first_supported_turn"] = (old.get("first_supported_turn") if old and old["state"] == "supported"
                                         else tid) if fact["state"] == "supported" else None
        fact["independent_sources"] = len({registry[c["evidence_id"]]["source_id"] for c in fact["evidence"]
                                           if registry[c["evidence_id"]]["source_id"]})
        fact["evidence_refs"] = list(dict.fromkeys(c["evidence_id"] for c in fact["evidence"]))
        by_id[fact["fid"]] = fact
    after["facts"] = list(by_id.values())
    return record_turn(after, turn, semantic_gain, before)


def record_turn(after, turn, semantic_gain, before):
    """Record observed events even when semantic extraction is unknown."""
    keys = list(dict.fromkeys(document_key(o) for o in turn["observations"]))
    new_docs = set(keys) - set(before["seen_documents"])
    after["seen_documents"] = list(dict.fromkeys(before["seen_documents"] + keys))
    after["seen_evidence"] = list(dict.fromkeys(before["seen_evidence"] + [o["evidence_id"] for o in turn["observations"]]))
    artifact_gain = False
    a = turn.get("artifact")
    if a:
        record = after["artifacts"].setdefault(a["artifact_id"], {})
        previous = deepcopy(record)
        if a["operation"] == "write":
            record["current_version"] = a["version"]
        elif a["operation"] == "test":
            record["last_tested_version"] = a["version"]
            record["last_test_passed"] = a["passed"]
            if a["passed"]:
                record["last_verified_version"] = a["version"]
                record["test_turn"] = turn["turn_id"]
        elif a["operation"] == "submit":
            record["submitted_version"] = a["version"]
            record["submit_turn"] = turn["turn_id"]
        artifact_gain = record != previous
    gain = None if semantic_gain is None else bool(semantic_gain or new_docs or artifact_gain)
    if gain:
        after["revision"] = before["revision"] + 1
        after["last_gain_turn"] = turn["turn_id"]
    action = turn["action"]
    attempt = {"turn": turn["turn_id"], "kind": action["kind"], "target_id": action.get("target_id"),
               "candidate_id": action.get("candidate_id"),
               "query": action.get("query", ""), "method": action.get("method", ""),
               "document_keys": keys, "gain": gain}
    if action["kind"] not in {"decision", "submit"}:
        after["attempts"].append(attempt)
    if action["kind"] == "decision":
        after["decisions"].append({"turn": turn["turn_id"], "key": action.get("decision_key", ""),
                                   "summary": turn["conclusion"], "revision": after["revision"]})
    for gap in after["gaps"]:
        facts = [f for f in after["facts"] if f["cid"] == gap["about"]]
        # Conflicts are retained rather than silently replaced by the newest claim.
        gap["status"] = ("conflicted" if any(f["state"] == "refuted" for f in facts) else
                         "resolved" if any(f["state"] == "supported" and f["independent_sources"] for f in facts) else "open")
        gap["attempts"] = [a for a in after["attempts"] if a["target_id"] == gap["about"]]
    return after


def grounding_score(trace, ledger):
    required = [c for c in trace["constraints"] if c["required"]]
    if not required:
        return None
    supported = 0
    for constraint in required:
        if constraint["kind"] == "artifact":
            a = ledger["artifacts"].get(constraint["artifact_id"], {})
            version = a.get("submitted_version")
            supported += bool(
                version
                and version == a.get("last_verified_version")
                and version == a.get("last_tested_version")
                and a.get("last_test_passed") is True
                and (not a.get("current_version") or version == a["current_version"])
            )
        else:
            candidate = trace["submitted_candidate"]
            if candidate is None:
                return None
            facts = [f for f in ledger["facts"] if f["cid"] == constraint["cid"] and f["candidate_id"] == candidate]
            supported += bool(any(f["state"] == "supported" and f["independent_sources"] >= 1 for f in facts)
                              and not any(f["state"] == "refuted" for f in facts))
    return supported / len(required)
