"""Construct neutral name batches and mark category-level wrong pursuits."""

from collections import defaultdict
from pathlib import Path
import sys

PARENT = Path(__file__).resolve().parent.parent
for leaf in ("ledger_judge_v41", "ledger_judge_v4", "ledger_judge_v2", "fpremise_probe"):
    if (PARENT / leaf).is_dir():
        sys.path.append(str(PARENT / leaf))

from flags import name_key
from matcher import resettle

CLASSES = ("person", "place", "work", "organization", "other")
IGNORED_NAMES = {"none", "unresolved", ""}


def name_batch(question, references, extracted):
    unique = {}
    for name in [*references, *extracted]:
        key = name_key(name)
        if key not in IGNORED_NAMES:
            unique.setdefault(key, name)
    return {"question": question, "names": [unique[key] for key in sorted(unique)]}


def rebuild(tid, units, conditions, names, outcome):
    masked = []
    for row in units:
        items = [{**item, "main_name": "none"} if item["status"] in ("non_proper_name", "name_type_unresolved")
                 else item for item in row["items"]] if row["items"] is not None else None
        masked.append({**row, "items": items})
    rows, _ = resettle(tid, masked, conditions, names, outcome)
    first, confirmed, outstanding, events = {}, set(), defaultdict(dict), []

    def create(kind, sid, item, start, qualified, key):
        window = {label: units[i]["searches"] if 0 <= i < len(units) else []
                  for label, i in (("before", sid-2), ("current", sid-1), ("after", sid))}
        var = item["var"]
        return {"trajectory_id": tid, "event": kind, "stage_id": sid, "var": var,
                "type": item["type"], "wrong_name": item["main_name"], "correct_name": names.get(var),
                "first_stage": start, "confirmation_stage": qualified, "key": list(key),
                "attribution_scope": item["attribution_scope"], "search_window": window}

    for index, (row, unit) in enumerate(zip(rows, units, strict=True), 1):
        if row["labels"]["invalid"]:
            continue
        row["items"] = unit["items"]
        row["labels"].update(F_new=False, F_corrected=False)
        for item in row["items"]:
            role = item["var"]
            if item["status"] != "correct" or role is None:
                continue
            group = item["type"], role
            for key, (wrong, start, qualified) in list(outstanding[group].items()):
                events.append(create("F_corrected", index, wrong, start, qualified, key))
                row["labels"]["F_corrected"] = True
                del outstanding[group][key]
        for item in row["items"]:
            if item["status"] != "wrong_candidate":
                continue
            key = item["type"], name_key(item["main_name"])
            start, original = first.setdefault(key, (index, item))
            if start == index or key in confirmed:
                continue
            confirmed.add(key)
            rows[start-1]["labels"]["F_new"] = True
            events.append(create("F_new", start, original, start, index, key))
            if original["var"] is not None:
                outstanding[(original["type"], original["var"])][key] = (original, start, index)
    return rows, sorted(events, key=lambda row: (row["stage_id"], row["event"], row["key"]))
