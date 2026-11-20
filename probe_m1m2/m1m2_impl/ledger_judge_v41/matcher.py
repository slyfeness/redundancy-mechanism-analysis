"""Compare all validated roles of the extracted type before declaring a miss."""

from pathlib import Path
import sys

PARENT = Path(__file__).resolve().parent.parent
for leaf in ("ledger_judge_v4", "ledger_judge_v2", "fpremise_probe"):
    if (PARENT / leaf).is_dir():
        sys.path.append(str(PARENT / leaf))

from program import alias_key, matching, settle
from flags import name_key

SCOPE_PREFIX = "@type:"


def candidates(item, names, inventory):
    same_type = [var for var in names if inventory.get(var) == item["type"]]
    direct = [role for role in same_type if matching(item["main_name"], names[role])]
    return same_type, direct


def classify(item, names, inventory, conflicts, owners, aliases):
    role, status, scope = None, "none", None
    reviewed = []
    target, kind = item["main_name"], item["type"]
    owner = owners.get(item["sought_condition"])
    if target != "none":
        eligible, direct = candidates(item, names, inventory)
        positives = direct
        if eligible and not direct:
            for var in eligible:
                row = aliases.get(alias_key(target, names[var]), {})
                reviewed.append({"var": var, "id": row.get("id"), "result": row.get("result"),
                                 "provenance": row.get("provenance")})
            positives = [check["var"] for check in reviewed if check["result"] == "yes"]
        if positives:
            exact = [var for var in positives if name_key(target) == name_key(names[var])]
            pool = exact or positives
            role, status, scope = (owner if owner in pool else pool[0]), "correct", "var"
        elif not eligible:
            status = "type_conflict" if kind in conflicts else "aux"
        elif any(check["result"] != "no" for check in reviewed):
            status = "alias_unresolved"
        elif kind in conflicts:
            status = "type_conflict"
        else:
            role = owner if owner in eligible else eligible[0] if len(eligible) == 1 else None
            status, scope = "wrong_candidate", "var" if role is not None else "type"
    alias = next((check for check in reviewed if check["var"] == role), None)
    return {**item, "var": role, "status": status, "alias": alias,
            "alias_reviews": reviewed, "attribution_scope": scope}


def resettle(tid, units, conditions, names, outcome):
    lookup = dict(names)
    adjusted = []
    for unit in units:
        if unit["items"] is None:
            adjusted.append(unit)
            continue
        items = []
        for item in unit["items"]:
            if item["attribution_scope"] == "type":
                key = SCOPE_PREFIX + item["type"]
                lookup[key] = None
                items.append({**item, "var": key})
            else:
                items.append(item)
        adjusted.append({**unit, "items": items})
    rows, events = settle(tid, adjusted, conditions, lookup, outcome)
    for row in rows:
        for item in row["items"] or []:
            if item.get("attribution_scope") == "type":
                item["var"] = None
        for candidate in row["ledger_after"]["candidates"]:
            var = candidate["var"]
            candidate["attribution_scope"] = "type" if var.startswith(SCOPE_PREFIX) else "var"
            if candidate["attribution_scope"] == "type":
                candidate["type"], candidate["var"] = var[len(SCOPE_PREFIX):], None
    for event in events:
        event["attribution_scope"] = "type" if event["var"].startswith(SCOPE_PREFIX) else "var"
        if event["attribution_scope"] == "type":
            event["var"] = None
            event["key"][0] = event["type"]
    return rows, events
