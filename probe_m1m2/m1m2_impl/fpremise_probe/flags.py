"""Validate query labels and mark the first sustained wrong premise per role."""

from collections import Counter, defaultdict
import re
import unicodedata

WORD = re.compile(r"[^\W_]+")
STATUSES = ("same", "different", "none")


def name_key(text):
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(WORD.findall("".join(c for c in decomposed if not unicodedata.combining(c))))


def classify(parsed, queries, entities):
    items = parsed.get("verdicts") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return {}
    listed = [row for row in items if isinstance(row, dict) and type(row.get("id")) is int]
    counts = Counter(row["id"] for row in listed)
    texts = {q["id"]: name_key(q["text"]) for q in queries}
    valid = {}
    for row in listed:
        qid = row["id"]
        if qid not in texts or counts[qid] != 1 or set(row) != {"id", "role", "candidate", "match"}:
            continue
        role, candidate, match = (row[key] for key in ("role", "candidate", "match"))
        if role is not None and (not isinstance(role, str) or role not in entities):
            continue
        if match not in STATUSES:
            continue
        if match == "none":
            if candidate is not None:
                continue
        elif not isinstance(candidate, str) or not name_key(candidate) or (
                f" {name_key(candidate)} " not in f" {texts[qid]} "):
            continue
        if role is not None and match == "different" and name_key(candidate) == name_key(entities[role]):
            continue
        valid[qid] = row
    return valid


def mark(searches, entities):
    active, seen, open_events, events = {}, set(), defaultdict(list), []
    for q in searches:
        role, match, candidate = q["role"], q["match"], q["candidate"]
        if match == "invalid":
            active.clear()
            continue
        if role is None or match == "none" or entities[role].strip().upper() in {"", "UNRESOLVED"}:
            continue
        if match == "same":
            active.pop(role, None)
            for event in open_events.pop(role, ()):
                event.update(corrected=True, correction_stage_id=q["stage_id"])
            continue
        key = role, name_key(candidate)
        current = active.get(role)
        if not current or current["key"] != key:
            active[role] = {"key": key, "first": q, "length": 1, "event": None}
            continue
        current["length"] += 1
        if key not in seen:
            first = current["first"]
            event = {"role": role, "candidate": first["candidate"], "correct_name": entities[role],
                     "stage_id": first["stage_id"], "consecutive_queries": current["length"],
                     "corrected": False, "correction_stage_id": None}
            seen.add(key)
            events.append(event)
            open_events[role].append(event)
            current["event"] = event
        if current["event"] is not None:
            current["event"]["consecutive_queries"] = current["length"]
    return events
