"""The v4.5 name rules and offline repeat replay."""

from pathlib import Path
import sys

OLD = Path(__file__).resolve().parent.parent / "ledger_judge_v44"
if OLD.is_dir():
    sys.path.append(str(OLD))
from rules_v44 import (AliasEvidence, CONNECTORS, DAYS, MONTHS, QUOTED, TOKEN, YEAR,
                       Protection, cap_spans, classify as classify_v44, name_key, normalized, quoted_names)


def proper(name):
    words = TOKEN.findall(name)
    return any(word[0].isupper() for word in words) and all(
        word[0].isupper() or word in CONNECTORS for word in words)


def repair(original, query, variables, countries):
    name, reason = original, None
    keys = {name_key(var) for var in variables}
    if name != "none":
        key = name_key(name)
        if len(key.replace(" ", "")) <= 2 or key in keys:
            reason = "variable_or_short"
        elif not proper(name):
            reason = "non_proper_name"
    backfilled = False
    if name == "none" or reason:
        candidates = [part for part in [*quoted_names(query), *cap_spans(query, MONTHS | DAYS)]
                      if proper(part) and len(normalized(part).replace(" ", "")) > 2
                      and name_key(part) not in keys and normalized(part) not in countries | MONTHS | DAYS
                      and not YEAR.fullmatch(part.strip())]
        name = max(candidates, key=len, default="none")
        backfilled = name != "none"
    return {"judge_main_name": original, "main_name": name, "normalized_name": normalized(name) if name != "none" else None,
            "discard_reason": reason, "backfilled": backfilled}


def containment(name, reference):
    needle = normalized(reference).split()
    haystack = normalized(name).split()
    if len(needle) == 1:
        return needle == haystack
    return bool(needle) and any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def classify(item, table, owners, aliases):
    name = item["main_name"]
    included = [] if name == "none" else [var for var, (reference, _) in table.items() if containment(name, reference)]
    if included:
        exact = [var for var in included if normalized(name) == normalized(table[var][0])]
        longest = max(len(normalized(table[var][0]).split()) for var in included)
        pool = exact or [var for var in included if len(normalized(table[var][0]).split()) == longest]
        owner = owners.get(item["sought_condition"])
        var = owner if owner in pool else pool[0]
        reason = "exact" if var in exact else "containment"
        return {**item, "var": var, "attribution": "correct", "decision_reason": reason,
                "normalized_match": name_key(name) != name_key(table[var][0]), "containment_match": reason == "containment"}
    result = classify_v44(item, table, owners, aliases)
    if result["attribution"] == "wrong_candidate" and item["backfilled"]:
        result.update(attribution="aux", decision_reason="backfilled")
    else:
        result["decision_reason"] = result["attribution"]
    return {**result, "containment_match": False}


def pending_key(qid, item):
    return qid, item["var"], normalized(item["main_name"])


def apply_eligibility(item, review):
    result = review["result"]
    revised = {"yes": "wrong_candidate", "no": "aux", None: "eligibility_unresolved"}
    reasons = {"yes": "eligible", "no": "eligibility_no", None: "eligibility_invalid"}
    return {**item, "attribution": revised[result], "decision_reason": reasons[result], "eligibility_check": review["id"]}


def replay_stage(units, aliases):
    """Keep v4.4 repeat semantics, removing capitalization-invalid quoted spans from protection."""
    protection, earlier = Protection(), []
    output = []
    for source in units:
        sid = source["stage_id"]
        labels = dict(source["labels"])
        items = source["items"]
        names = {item["main_name"] for item in items if item["main_name"] not in (None, "none")}

        def unquote(match):
            part = next(value for value in match.groups() if value is not None)
            # Keep a punctuation boundary so adjacent capitalized terms do not merge.
            return match[0] if proper(part) else f"({part})"

        searches = [QUOTED.sub(unquote, query) for query in source["searches"]]
        protected = protection.add(searches, names)
        strict = labels.get("strict_repeat", False)
        eligible = not labels["invalid"] and not protected and not strict and not source["C_new"] and (
            source["seen_docids"] > 0 and source["new_docids"] == 0)
        distances = []
        if eligible:
            for name in sorted(names):
                matches = [step for prior, step in earlier if aliases.same(name, prior)]
                if matches:
                    distances.append(sid - max(matches))
        labels.update(protected_new_hypothesis=protected, semantic_repeat=bool(distances),
                      stale_return=eligible and bool(items) and not names)
        if not labels["invalid"]:
            earlier.extend((name, sid) for name in sorted(names))
        idle_type = "strict" if strict else "semantic" if labels["semantic_repeat"] or labels["stale_return"] else "none"
        output.append({**source, "labels": labels, "idle_type": idle_type, "semantic_repeat_distances": distances})
    return output
