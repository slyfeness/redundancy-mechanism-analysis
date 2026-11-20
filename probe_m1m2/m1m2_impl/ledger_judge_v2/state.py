"""Program-owned causal state and exact extraction validation."""

from collections import defaultdict
from pathlib import Path
import sys
import unicodedata

PROBE = Path(__file__).resolve().parent.parent / "fpremise_probe"
if PROBE.is_dir():
    sys.path.append(str(PROBE))
from flags import name_key

KEYS = {"target_role", "target_quote", "candidate", "stance", "gap", "gap_description", "new_lead", "lead_quote"}


def query_key(query):
    # The frozen M1 search normalization.
    return " ".join("".join(c for c in query.lower() if not unicodedata.category(c).startswith("P")).split())


def parse(row, roles, gaps, sources, snapshot, *, searching=True):
    if not isinstance(row, dict) or row.keys() != KEYS or any(
            not isinstance(v, str) or not v.strip() for v in row.values()):
        return None
    role, candidate, gap = (row[key] for key in ("target_role", "candidate", "gap"))
    if role not in roles | {"aux", "none"} or row["stance"] not in ("assertion", "guess"):
        return None
    if gap not in gaps | {"new"} or row["new_lead"] not in ("yes", "no"):
        return None

    def citation(quote, available):
        return quote != "none" and len(quote.split()) <= 30 and any(quote in source for source in available)

    quote = row["target_quote"]
    if (quote == "none" and role != "none") or (quote != "none" and not citation(quote, sources)):
        return None
    if candidate != "none" and (not name_key(candidate) or not any(
            f" {name_key(candidate)} " in f" {name_key(text)} " for text in sources)):
        return None
    if gap == "new" and searching and row["gap_description"] == "none":
        return None
    lead = row["lead_quote"]
    if row["new_lead"] == "yes" and (gap == "new" or not citation(lead, [snapshot, *sources])):
        return None
    if row["new_lead"] == "no" and lead != "none":
        return None
    return row


def retries(pending, *, already, limit, stages):
    return pending[:max(0, limit - stages - already)]


class Ledger:
    def __init__(self, entities, aliases):
        self.entities = {row["var"]: row for row in entities}
        self.accepted = {role: {name_key(row["name"]), *(name_key(n) for n in aliases.get(role, []))}
                         for role, row in self.entities.items() if row["name"].strip().upper() not in ("", "UNRESOLVED")}
        self.candidates = {}
        self.gaps = {}
        self.last = {}
        self.searches = set()
        self.seen_wrong = set()
        self.unresolved = defaultdict(set)

    def apply(self, sid, queries, data):
        keys = {key for query in queries if (key := query_key(query))}
        strict = bool(keys & self.searches)
        self.searches.update(keys)
        if data is None:
            return {"invalid": True}
        role, name, stance, gap = (data[k] for k in ("target_role", "candidate", "stance", "gap"))
        tags = {"invalid": False, "strict_repeat": strict,
                "semantic_repeat": bool(queries and gap != "new" and data["new_lead"] == "no" and not strict),
                "wrong_candidate": False, "F_new": False, "F_corrected": False, "resolved": []}
        if role != "none" and name != "none":
            norm = name_key(name)
            repeated = self.last.get(role) == (sid - 1, norm)
            self.last[role] = (sid, norm)
            if stance == "assertion" or repeated:
                prior = self.candidates.get(role)
                if not prior or name_key(prior["name"]) != norm:
                    self.candidates[role] = {"name": name, "since": sid if stance == "assertion" else sid - 1,
                                             "stance": stance, "previous": prior["name"] if prior else None}
                elif stance == "assertion":
                    prior["stance"] = stance
                if role in self.accepted:
                    wrong = norm not in self.accepted[role]
                    tags["wrong_candidate"] = wrong
                    key = role, norm
                    if wrong and key not in self.seen_wrong:
                        self.seen_wrong.add(key)
                        self.unresolved[role].add(sid)
                        tags["F_new"] = True
                    if not wrong and self.unresolved[role]:
                        tags["resolved"] = sorted(self.unresolved.pop(role))
                        tags["F_corrected"] = True
        if queries:
            if gap == "new":
                ident = f"g{len(self.gaps) + 1}"
                self.gaps[ident] = {"description": data["gap_description"], "steps": [], "lead": False}
            else:
                ident = gap
            current = self.gaps[ident]
            current["steps"].append(sid)
            current["lead"] = data["new_lead"] == "yes"
        return tags

    def render(self, claims, proved, used, tok, *, maximum=400):
        """Shorten descriptions before hiding any older gaps."""
        def encode(text):
            return tok.encode(text, add_special_tokens=False)

        def text(value, max_tokens):
            normalized = " ".join(value.split())
            ids = encode(normalized)
            if len(ids) <= max_tokens:
                return normalized
            return tok.decode(ids[:max_tokens], skip_special_tokens=True).rstrip() + "…" if max_tokens else "…"

        def render_one(sizes, visible):
            claim_size, role_size, name_size, gap_size = sizes
            lines = [f"【条件】已证实 {len(proved)}/{len(claims)}"]
            for index, claim in enumerate(claims, 1):
                sid = proved.get(claim["id"])
                status = f"已证实@第{sid}步" if sid is not None else "待查"
                lines.append(f"c{index} {text(claim['claim'], claim_size)} {status}")
            lines.append("【候选】")
            for role, row in self.candidates.items():
                label = text(self.entities.get(role, {"role": role})["role"], role_size)
                name = text(row["name"], name_size)
                if row["previous"]:
                    name = f"{text(row['previous'], name_size)}→{name}"
                lines.append(f"{role}({label})：{name}（第{row['since']}步起，{row['stance']}）")
            lines.append("【已查缺口】")
            for gid in visible:
                gap = self.gaps[gid]
                steps = "、".join(map(str, gap["steps"]))
                lead = "有" if gap["lead"] else "无"
                lines.append(f"{gid} {text(gap['description'], gap_size)}：查过@第{steps}步；新线索{lead}")
            lines.append(f"【预算】已用 {used}/20")
            return "\n".join(lines)

        ids = list(self.gaps)
        for mode in ((13, 7, 16, 12), (8, 4, 12, 7), (5, 3, 8, 4), (2, 2, 5, 2)):
            ledger = render_one(mode, ids)
            count = len(encode(ledger))
            if count <= maximum:
                return ledger, count, set(ids)
        # Keep every condition and role, and the newest gaps, if even the compact view is too large.
        fresh = sorted(ids, key=lambda gid: self.gaps[gid]["steps"][-1], reverse=True)
        for size in range(len(fresh), -1, -1):
            visible = set(fresh[:size])
            ledger = render_one((2, 2, 5, 2), [gid for gid in ids if gid in visible])
            count = len(encode(ledger))
            if count <= maximum:
                return ledger, count, visible
        raise ValueError("minimal ledger exceeds the 400-token cap")
