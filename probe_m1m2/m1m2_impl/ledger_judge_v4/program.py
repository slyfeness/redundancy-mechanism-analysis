"""Deterministic ownership, name matching, causal credit and repetition."""

from collections import defaultdict
import re
from pathlib import Path
import sys

PARENT = Path(__file__).resolve().parent.parent
for leaf in ("ledger_judge_v2", "fpremise_probe"):
    if (PARENT / leaf).is_dir():
        sys.path.append(str(PARENT / leaf))

from flags import name_key
from state import query_key

TYPES = ("city", "country", "person", "university", "organization", "film", "tv_show", "album",
         "song", "book", "artwork", "building", "event", "other")
LABELS = ("strict_repeat", "semantic_repeat", "wrong_candidate", "F_new", "F_corrected")
WORD = re.compile(r"[^\W_]+")


def scrub(text, aliases):
    """Mask complete frozen names across case, accent and punctuation variants."""
    words = list(WORD.finditer(text))
    keys = [name_key(w[0]) for w in words]
    patterns = sorted({(tuple(name_key(n).split()), var) for var, names in aliases.items()
                       for n in names if name_key(n)}, key=lambda item: (-len(item[0]), item))
    result, cursor, pos = [], 0, 0
    while pos < len(words):
        for tokens, var in patterns:
            last = pos + len(tokens)
            if tuple(keys[pos:last]) != tokens:
                continue
            result.extend((text[cursor:words[pos].start()], f"[{var}]"))
            cursor = words[last - 1].end()
            pos = last
            break
        else:
            pos += 1
    result.append(text[cursor:])
    return "".join(result)


def matching(first, second):
    a, b = name_key(first), name_key(second)
    if not a or not b:
        return False
    shared = set(a.split()) & set(b.split())
    return a == b or ((a in b or b in a) and len(shared) >= 2)


def assign(kind, condition, types, owners):
    eligible = [var for var, value in types.items() if value == kind]
    if len(eligible) == 1:
        return eligible[0], None
    if not eligible:
        return None, "aux"
    owner = owners.get(condition)
    if owner in eligible:
        return owner, None
    return None, "ambiguous"


def alias_key(first, second):
    return tuple(sorted((name_key(first), name_key(second))))


def settle(tid, units, conditions, names, outcome):
    search_history, credited, first_wrong = set(), {}, {}
    candidates, checked = {}, {}
    pending = defaultdict(dict)
    evaluated, events = {}, []
    condition_ids = {item["id"]: code for code, item in conditions.items()}

    def event(kind, sid, item, first, now, key):
        window = {label: units[index]["searches"] if 0 <= index < len(units) else []
                  for label, index in (("before", sid-2), ("current", sid-1), ("after", sid))}
        return {"trajectory_id": tid, "event": kind, "stage_id": sid, "var": item["var"],
                "type": item["type"], "wrong_name": item["main_name"], "correct_name": names[item["var"]],
                "first_stage": first, "confirmation_stage": now, "key": list(key), "search_window": window}

    for sid, row in enumerate(units, 1):
        assert row["stage_id"] == sid
        query = {key for raw in row["searches"] if (key := query_key(raw))}
        strict = bool(query & search_history)
        search_history.update(query)
        tags, distances, targets = {"invalid": row["items"] is None}, [], set()
        if row["items"] is not None:
            tags.update({key: False for key in LABELS})
            tags["strict_repeat"] = strict
            # Correction follows the confirming wrong Stage, never a parallel query within it.
            for item in row["items"]:
                role = item["var"]
                if item["status"] != "correct":
                    continue
                for key, (wrong, first, now) in list(pending[role].items()):
                    events.append(event("F_corrected", sid, wrong, first, now, key))
                    tags["F_corrected"] = True
                    del pending[role][key]
            for item in row["items"]:
                raw, role, status = item["main_name"], item["var"], item["status"]
                name = name_key(raw)
                if role is not None and raw != "none":
                    key = role, name
                    hit = candidates.setdefault(key, {"var": role, "name": raw, "status": status, "stages": []})
                    if not hit["stages"] or hit["stages"][-1] != sid:
                        hit["stages"].append(sid)
                if status == "wrong_candidate":
                    tags["wrong_candidate"] = True
                    key = role, name
                    first = first_wrong.setdefault(key, sid)
                    if first != sid and not any(e["event"] == "F_new" and e["key"] == list(key) for e in events):
                        # Earlier snapshots stay causal. Only the retrospective label is amended.
                        evaluated[first]["labels"]["F_new"] = True
                        pending[role][key] = (item, first, sid)
                        events.append(event("F_new", first, item, first, sid, key))
                condition = item["sought_condition"]
                pair = name, condition
                if raw == "none" or condition == "none" or pair in targets:
                    continue
                targets.add(pair)
                gap = checked.setdefault(pair, {"name": raw, "condition": condition, "stages": []})
                if gap["stages"]:
                    prior = gap["stages"][-1]
                    confirmed = credited.get(condition)
                    progress = confirmed is not None and prior <= confirmed < sid
                    if not strict and not row["C_new"] and not progress:
                        tags["semantic_repeat"] = True
                        distances.append(sid - prior)
                gap["stages"].append(sid)
        for cid in row["C_new"]:
            condition = condition_ids[cid]
            if condition in credited:
                raise ValueError("frozen M2 settled a condition twice")
            credited[condition] = sid
        snapshot = {
            "conditions": [{"condition": code, "confirmed_at": credited.get(code)} for code in conditions],
            "candidates": [{**hit, "stages": list(hit["stages"])} for hit in candidates.values()],
            "searched": [{**hit, "stages": list(hit["stages"]), "progress_since_last":
                          credited.get(hit["condition"], 0) >= hit["stages"][-1]} for hit in checked.values()],
            "budget_used": sid,
        }
        evaluated[sid] = {"trajectory_id": tid, **row, "ledger_after": snapshot, "labels": tags,
                          "semantic_repeat_distances": distances, "outcome": outcome}
    return list(evaluated.values()), sorted(events, key=lambda e: (e["stage_id"], e["event"], e["var"], e["wrong_name"]))
