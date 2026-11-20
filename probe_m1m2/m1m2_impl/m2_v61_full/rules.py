"""The four authorized cleanup operations and the Judge retry merge."""

import re
import unicodedata

WORD = re.compile(r"[^\W_]+")


def normalized(text):
    return " ".join(WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def cleanup(qid, record, answers, *, drop_answer_subject=True):
    aliases = sorted({normalized(a) for a in answers if isinstance(a, str) and normalized(a)})
    entities = {entity["var"]: entity for entity in record["entities"]}
    names = {var: row["name"] for var, row in entities.items() if var and row["name"]}
    pattern = (re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, sorted(names, key=lambda x: (-len(x), x))))
                          + r")(?!\w)") if names else None)
    kept, audit, seen = [], [], set()

    def log(row, action, reason, before, after, **details):
        audit.append({"query_id": qid, "assertion_id": row["id"], "action": action, "reason": reason,
                      "before": before, "after": after, **details})

    def answer_in(text):
        return any(alias in normalized(text) for alias in aliases)

    for source in record["conditions"]:
        row = dict(source)
        body = row["claim"]
        subject = entities.get(row["subject"])
        if not subject:
            log(row, "drop", "unknown_subject", body, None)
            continue
        if drop_answer_subject and answer_in(subject["name"]):
            log(row, "drop", "answer_in_subject", body, None)
            continue
        if answer_in(body):
            log(row, "drop", "answer_in_claim", body, None)
            continue
        if pattern:
            replacements = [{"var": match[0], "name": names[match[0]], "offset": match.start()}
                            for match in pattern.finditer(body)]
            if replacements:
                changed = pattern.sub(lambda match: names[match[0]], body)
                if changed != body:
                    log(row, "replace", "entity_variable_replaced", body, changed, replacements=replacements)
                    row["claim"] = changed
                    body = changed
        if answer_in(body):
            log(row, "drop", "answer_in_claim", body, None)
            continue
        if body in seen:
            log(row, "drop", "duplicate_claim", body, None)
            continue
        seen.add(body)
        kept.append(row)
    return {**record, "conditions": kept}, audit


def failed_slots(decisions):
    return {row["id"] for row in decisions if not row["valid"]}


def resolve(first, retry):
    second = {row["id"]: row for row in retry}
    result = []
    for row in first:
        current = row if row["valid"] else second.get(row["id"], row)
        if not current["valid"]:
            current = {**current, "status": "invalid", "unit_id": None,
                       "sentences": [], "passage_count": 0}
        result.append(current)
    return result


def outcome_label(row):
    if row["status"] == "unknown" and re.search(r"\bdifferent\s+entity\b", row["reason"], re.I):
        return "different_entity"
    return row["status"]
