"""Validate Stage-local evidence and derive diagnostic flags."""

from collections import Counter, defaultdict
from pathlib import Path
import sys

PREVIOUS = Path(__file__).resolve().parent.parent / "fpremise_probe"
if PREVIOUS.is_dir():
    sys.path.append(str(PREVIOUS))

from flags import name_key

DIRECTIONS = ("on_track", "wrong_candidate", "contradicts_ledger")
REPEATS = ("new", "strict_repeat", "semantic_repeat", "justified_recheck")
RELATIONS = ("same", "different", "unknown")


def validate(row, stage, entities):
    if not isinstance(row, dict) or set(row) != {"stage_id", "direction", "repeat", "target", "evidence"}:
        return False
    if row["stage_id"] != stage["stage_id"] or row["direction"] not in DIRECTIONS or row["repeat"] not in REPEATS:
        return False
    target, evidence = row["target"], row["evidence"]
    if not isinstance(target, dict) or set(target) != {"role", "candidate", "relation"}:
        return False
    if not isinstance(evidence, dict) or set(evidence) != {"quote", "refs", "reason", "prior_search_id"}:
        return False
    role, candidate, relation = (target[key] for key in ("role", "candidate", "relation"))
    if role is not None and (not isinstance(role, str) or (role not in entities and role != "aux")):
        return False
    if relation not in RELATIONS or (candidate is not None and
            (not isinstance(candidate, str) or not name_key(candidate))):
        return False
    sources = [stage["thought_tail"], *stage["searches"]]
    if candidate and not any(f" {name_key(candidate)} " in f" {name_key(text)} " for text in sources):
        return False
    if relation != "unknown" and (not candidate or role is None):
        return False
    if role in entities and candidate and relation == "different" and name_key(candidate) == name_key(entities[role]):
        return False
    if row["direction"] == "wrong_candidate" and relation != "different":
        return False
    abnormal = row["direction"] != "on_track" or row["repeat"] != "new"
    refs, quote, reason, prior_search = (evidence[key] for key in ("refs", "quote", "reason", "prior_search_id"))
    if not isinstance(reason, str) or not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        return False
    if quote is not None and (not isinstance(quote, str) or not quote.strip() or len(quote.split()) > 40
                              or not any(quote in text for text in sources)):
        return False
    if abnormal and (not quote or not reason.strip()):
        return False
    history = stage["pre"]
    index = {item["id"]: item["stage_id"] for values in history.values() for item in values}
    if any(ref not in index or index[ref] >= stage["stage_id"] for ref in refs):
        return False
    earlier_searches = {item["id"] for item in history["searches"] if item["stage_id"] < stage["stage_id"]}
    if prior_search is not None and (not isinstance(prior_search, str) or prior_search not in earlier_searches
                                    or prior_search not in refs):
        return False
    if row["repeat"] != "new" and (not stage["searches"] or prior_search is None):
        return False
    return not (row["direction"] == "contradicts_ledger" and not refs)


def classify(response, stages, names):
    data = response.get("stages") if isinstance(response, dict) else None
    if not isinstance(data, list):
        return {}
    indexed = {row["stage_id"]: row for row in stages}
    listed = [row for row in data if isinstance(row, dict) and type(row.get("stage_id")) is int]
    counts = Counter(row["stage_id"] for row in listed)
    return {sid: row for row in listed if (sid := row["stage_id"]) in indexed and counts[sid] == 1
            and validate(row, indexed[sid], names)}


def flags(verdicts):
    first, corrections, seen = set(), {}, set()
    unresolved = defaultdict(list)
    for verdict in verdicts:
        sid, target = verdict["stage_id"], verdict["target"]
        role, candidate, relation = (target[key] for key in ("role", "candidate", "relation"))
        if verdict["direction"] == "wrong_candidate":
            key = role, name_key(candidate)
            if key not in seen:
                first.add(sid)
                seen.add(key)
                unresolved[role].append(sid)
        elif verdict["direction"] == "on_track" and relation == "same" and role not in (None, "aux") and verdict.get("correction_eligible", True):
            for earlier in unresolved.pop(role, ()):
                corrections[earlier] = sid
    return first, corrections
