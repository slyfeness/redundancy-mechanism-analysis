"""Fold Stage events into a causal evidence ledger."""

from copy import deepcopy
from statistics import median


def repeat_flags(event, previous, seen):
    flags = []
    tool, digest = event["tool"], event["return_sha256"]
    same_tool = [prior for prior in previous if prior["tool"] == tool]
    exact = []
    if tool == "search" and event["query_norm"]:
        query = event["query_norm"]
        exact = [prior for prior in same_tool if prior["query_norm"] == query]
        if exact:
            flags.append("S_exact")
        elif any(_similar(query, prior["query_norm"]) for prior in same_tool):
            flags.append("S_near")
        docs = {row["docid"] for row in event["returned_docids"]}
        if docs and docs <= seen:
            flags.append("S_allseen")
    elif tool == "open" and event["opened_docid"] is not None:
        exact = [prior for prior in same_tool if (prior["opened_docid"], prior["open_offset"]) ==
                 (event["opened_docid"], event["open_offset"])]
        if exact:
            flags.append("O_exact")
        if event.get("body_sha256") and any(
                event["body_sha256"] == prior.get("body_sha256") for prior in same_tool):
            flags.append("O_samecontent")
    strict = bool(event["return_text"]) and any(prior["return_sha256"] == digest for prior in exact)
    return flags, strict


def _similar(a, b):
    a, b = set(a.split()), set(b.split())
    return bool(a | b) and len(a & b) / len(a | b) >= .7


def build_ledger(stages, claims, decisions, *, evidence_docs=(), gold_docs=()):
    claim_ids = {claim["id"] for claim in claims}
    by_id = {row["id"]: row for row in decisions}
    if len(by_id) != len(decisions) or set(by_id) != claim_ids or len(claim_ids) != len(claims):
        raise ValueError("condition decisions must match every frozen claim exactly once")
    known_units = {stage["unit_id"] for stage in stages}
    if any(unit is not None and unit not in known_units
           for row in decisions for unit in (row["first_supported"], row["first_partial"])):
        raise ValueError("unknown support unit")
    evidence_docs, gold_docs = set(evidence_docs), set(gold_docs)
    ledger = {
        "conditions": {claim["id"]: {"status": "unknown", "first_supported": None} for claim in claims},
        "evidence": {}, "attempts": [],
        "execution": {"used_calls": 0, "remaining_calls": 20, "generated_tokens": 0, "return_tokens": 0},
        "visibility": [], "candidates": [], "conflicts": [], "errors": [], "settled_claims": [],
    }

    def doc(docid):
        return ledger["evidence"].setdefault(docid, {"first_search": None, "first_open": None,
                                                     "open_ranges": [], "evidence_doc": docid in evidence_docs,
                                                     "answer_doc": docid in gold_docs})

    states, earlier = [], []
    for stage in stages:
        unit = stage["unit_id"]
        before = deepcopy(ledger)
        seen = set(before["evidence"])
        hashes = {event["return_sha256"] for event in earlier}
        attempts, new, condition_changes = [], [], []
        for event in stage["tool_events"]:
            flags, strict = repeat_flags(event, earlier, seen)
            documents = {row["docid"] for row in event["returned_docids"]}
            if event["opened_docid"] is not None:
                documents.add(event["opened_docid"])
            attempt = {key: event[key] for key in ("event_id", "tool", "query_norm", "returned_docids",
                                                    "opened_docid", "open_offset", "return_sha256", "status")}
            attempt.update(new_docids=len(documents - seen), seen_hash=event["return_sha256"] in hashes,
                           repeat_flags=flags, strict_repeat=strict)
            attempts.append(attempt)
            earlier.append(event)
            hashes.add(event["return_sha256"])
            if not event["visible_to_actor"]:
                continue
            seen.update(documents)
            for row in event["returned_docids"]:
                entry = doc(row["docid"])
                if entry["first_search"] is None:
                    entry["first_search"] = unit
            if event["opened_docid"] is not None and event["status"] == "ok":
                entry = doc(event["opened_docid"])
                if entry["first_open"] is None:
                    entry["first_open"] = unit
                entry["open_ranges"].append([event["open_offset"], event["open_end"]])
        for claim in claims:
            cid = claim["id"]
            state, decision = ledger["conditions"][cid], by_id[cid]
            if decision["first_supported"] == unit:
                state.update(status="supported", first_supported=unit)
                new.append(cid)
                condition_changes.append({"id": cid, "status": "supported"})
            elif state["status"] == "unknown" and decision["first_partial"] == unit:
                state["status"] = "partial"
                condition_changes.append({"id": cid, "status": "partial"})
        received = sum(event["obs_tokens"] for event in stage["tool_events"])
        execution = ledger["execution"]
        execution["used_calls"] += 1
        execution["remaining_calls"] -= 1
        execution["generated_tokens"] += stage["generated_tokens"]
        execution["return_tokens"] += received
        ledger["attempts"].extend(attempts)
        ledger["visibility"].append(unit)

        states.append({"unit_id": unit, "L_pre": before,
                       "E_t": {"attempts": attempts, "condition_changes": condition_changes},
                       "L_post": deepcopy(ledger), "C_new": new,
                       "z_pre": (sum(item["status"] == "supported" for item in before["conditions"].values())
                                 / len(claims) if claims else 0.0),
                       "b_pre": before["execution"]["remaining_calls"] / 20,
                       "unit_cost": stage["generated_tokens"] + received,
                       "strict_repeat": any(attempt["strict_repeat"] for attempt in attempts),
                       "repeat_flags": sorted({flag for attempt in attempts for flag in attempt["repeat_flags"]})})
    return states


def dry_run(states, rho_x, scale=None):
    if not 0 <= rho_x <= 1:
        raise ValueError("invalid question success fraction")
    if scale is None:
        scale = median(row["unit_cost"] for row in states) if states else 0
    denominator = scale if scale > 0 else 1
    for row in states:
        cost = min(2.0, row["unit_cost"] / denominator)
        idle = cost if row["strict_repeat"] else 0.0
        yield {"unit_id": row["unit_id"], "rho_x": rho_x, "c": cost,
               "idle": idle, "u": len(row["C_new"]) - 0.2 * rho_x * idle}
