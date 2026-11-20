"""Extract grounded mentions and update the v2 ledger from Stage-local data."""

from collections import defaultdict
from pathlib import Path
import sys

PARENT = Path(__file__).resolve().parent.parent
for leaf in ("ledger_judge_v2", "fpremise_probe"):
    if (PARENT / leaf).is_dir():
        sys.path.append(str(PARENT / leaf))

from flags import name_key
from state import Ledger, query_key


def extract(raw, roles, conditions, sources, snapshot):
    if not isinstance(raw, dict) or raw.keys() != {"mentions", "targets", "new_lead"}:
        return None, []
    if any(not isinstance(value, list) for value in raw.values()) or len(raw["targets"]) != len(raw["new_lead"]):
        return None, []
    checked_sources = [name_key(s) for s in sources]
    seen, keep, discarded = set(), [], []
    for row in raw["mentions"]:
        if (not isinstance(row, dict) or row.keys() != {"name", "role", "same_as_table", "stance", "quote"}
                or any(not isinstance(row[key], str) or not row[key].strip() for key in ("name", "role", "stance", "quote"))
                or row["role"] not in roles | {"aux"} or row["stance"] not in ("guess", "assertion")
                or type(row["same_as_table"]) is not bool):
            return None, []
        name = name_key(row["name"])
        key = row["role"], name
        if not name or not any(name in source for source in checked_sources):
            discarded.append({"mention": row, "reason": "name_not_in_stage"})
        elif key in seen:
            discarded.append({"mention": row, "reason": "duplicate_mention"})
        else:
            seen.add(key)
            keep.append(row)
    for target, lead in zip(raw["targets"], raw["new_lead"], strict=True):
        if (not isinstance(target, dict) or target.keys() != {"candidate", "condition"}
                or not isinstance(target["candidate"], str) or not name_key(target["candidate"])
                or not isinstance(target["condition"], str) or target["condition"] not in conditions):
            return None, discarded
        if (not isinstance(lead, dict) or lead.keys() != {"value", "quote"} or lead["value"] not in ("yes", "no")
                or not isinstance(lead["quote"], str) or not lead["quote"].strip()):
            return None, discarded
        if lead["value"] == "yes" and (lead["quote"] == "none" or not any(
                lead["quote"] in source for source in [snapshot, *sources])):
            return None, discarded
    return {"mentions": keep, "targets": raw["targets"], "new_lead": raw["new_lead"]}, discarded


class StageLedger(Ledger):
    def __init__(self, entities, aliases):
        super().__init__(entities, aliases)
        self.target_ids = {}
        self.learned_names = defaultdict(set)

    def canonical(self, name):
        key = name_key(name)
        possible = {name_key(self.entities[role]["name"]) for role, variants in self.accepted.items()
                    if key in variants or key in self.learned_names[role]}
        return next(iter(possible)) if len(possible) == 1 else key

    def apply(self, sid, queries, data):
        keys = {key for query in queries if (key := query_key(query))}
        strict = bool(keys & self.searches)
        self.searches.update(keys)
        if data is None:
            return {"invalid": True}, []
        tags = {"invalid": False, "strict_repeat": strict, "semantic_repeat": False,
                "wrong_candidate": False, "F_new": False, "F_corrected": False}
        events = []
        appearances = {}
        active = {}
        for item in data["mentions"]:
            role, name = item["role"], item["name"]
            key = role, name_key(name)
            repeated = self.last.get(key) == sid - 1
            appearances[key] = sid
            if item["same_as_table"] and role in self.accepted:
                self.learned_names[role].add(key[1])
            if item["stance"] == "assertion" or repeated:
                former = active.get(role)
                if former is None or item["stance"] == "assertion" or former[0]["stance"] != "assertion":
                    active[role] = (item, key[1], repeated)
            if role not in self.accepted:
                continue
            if not item["same_as_table"] and (item["stance"] == "assertion" or repeated):
                tags["wrong_candidate"] = True
                if key not in self.seen_wrong:
                    eid = f"F{sid}.{len(events) + 1}"
                    self.seen_wrong.add(key)
                    self.unresolved[role].add((sid, eid))
                    events.append({"event": "F_new", "stage_id": sid, "id": eid, "role": role,
                                   "candidate": name, "stance": item["stance"], "resolves": []})
                    tags["F_new"] = True
            elif item["same_as_table"] and item["stance"] == "assertion":
                prior_wrong = {entry for entry in self.unresolved[role] if entry[0] < sid}
                if prior_wrong:
                    self.unresolved[role].difference_update(prior_wrong)
                    events.append({"event": "F_corrected", "stage_id": sid, "id": f"F{sid}.{len(events) + 1}",
                                   "role": role, "candidate": name, "stance": item["stance"],
                                   "resolves": [eid for _, eid in sorted(prior_wrong)]})
                    tags["F_corrected"] = True
        self.last = appearances
        for role, (item, key, repeated) in active.items():
            previous = self.candidates.get(role)
            if previous and name_key(previous["name"]) == key:
                if item["stance"] == "assertion":
                    previous["stance"] = "assertion"
                continue
            self.candidates[role] = {"name": item["name"],
                                     "since": sid - 1 if repeated and item["stance"] == "guess" else sid,
                                     "stance": item["stance"], "previous": previous["name"] if previous else None}

        # Aliases can be learned after a target was first checked. Compare both using information available now.
        prior_targets = {(self.canonical(row["candidate"]), row["condition"]): gid
                         for gid, row in self.gaps.items()}
        seen = set()
        for target, lead in zip(data["targets"], data["new_lead"], strict=True) if queries else ():
            candidate, condition = target["candidate"], target["condition"]
            pair = self.canonical(candidate), condition
            if pair in seen:
                continue
            seen.add(pair)
            gid = prior_targets.get(pair)
            if gid is None:
                gid = f"g{len(self.gaps) + 1}"
                self.gaps[gid] = {"candidate": candidate, "condition": condition,
                                  "description": f"{condition} {candidate}", "steps": [], "lead": False}
            else:
                tags["semantic_repeat"] |= not strict and lead["value"] == "no"
            self.gaps[gid]["steps"].append(sid)
            self.gaps[gid]["lead"] = lead["value"] == "yes"
        return tags, events
