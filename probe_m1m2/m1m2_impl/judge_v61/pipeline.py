"""Claim-only changes for v6.1. The frozen Judge lives in v6."""

from pathlib import Path
import re
import sys

_V6 = Path(__file__).resolve().parent.parent / "judge_v6"

sys.path.insert(0, str(_V6))
from claims import CLAIM_FIELDS, claim_flags, event, initial_parts, inspect as v6_inspect, name_pattern

HARD = {"capitalized_word_not_in_question_or_names", "number_not_in_question_or_names",
        "unresolved_entity", "span_not_verbatim"}
SUBJECT_RULE = """

For this version, return the claim body without repeating its subject's name if
that makes the wording simpler. Still declare the correct subject variable and
its concrete name and role in entities. The program supplies the subject heading
before judging. Keep other named entities in the entity table. Continue to
preserve question facts and verbatim question_span.
"""
REPAIR_RULE = """

The marked slots use v6.1 rules. Correct the flagged body and the entity table as
needed. You may omit the subject name in the body. Return the repair JSON schema
above, including a repairs list. A null condition or omitted slot leaves the
original available to the program. Do not repeat the first-pass schema.
"""


def flags(question, entities, row):
    if not isinstance(row, dict):
        return ["invalid_condition_fields"]
    text, span = row.get("claim"), row.get("question_span")
    # A capitalized pronoun is a reference problem, not a new proper name.
    checked = ({**row, "claim": re.sub(r"\b(?:it|they|same)\b", lambda match: match[0].lower(), text, flags=re.I)}
               if isinstance(text, str) else row)
    result = set(claim_flags(question, entities, checked)) - {"subject_name_missing"}
    subject = row.get("subject")
    if not isinstance(subject, str) or subject not in entities:
        result.add("unknown_subject")
    if isinstance(text, str) and text.strip():
        if not isinstance(span, str) or not span.strip() or span not in question:
            result.add("span_not_verbatim")
        # Run lexical checks even when unrelated required fields were malformed.
        if "invalid_condition_fields" in result:
            probe = {"id": "fallback", "subject": subject if isinstance(subject, str) and subject else "_missing",
                     "claim": checked["claim"], "question_span": span if isinstance(span, str) and span.strip()
                     else question, "type": "other"}
            result.update(set(claim_flags(question, entities, probe)) - {"subject_name_missing"})
    return sorted(result)


def inspect(qid, question, original):
    entities, _, old = initial_parts(original)
    baseline = v6_inspect(qid, question, original)
    marked = {}
    ids, texts = set(), set()
    for i, row in enumerate(old):
        issues = set(flags(question, entities, row))
        if isinstance(row, dict):
            ident, text = row.get("id"), row.get("claim")
            if isinstance(ident, str):
                if ident in ids:
                    issues.add("duplicate_id")
                ids.add(ident)
            if isinstance(text, str):
                key = " ".join(text.split()).casefold()
                if key in texts:
                    issues.add("duplicate_claim")
                texts.add(key)
        if i >= 10:
            issues.add("condition_count_above_10")
        if issues:
            marked[i] = sorted(issues)
    return {"record": baseline["record"], "claims": marked}


def usable_repair(value):
    return (isinstance(value, dict) and isinstance(value.get("repairs"), list)
            and all(isinstance(row, dict) and type(row.get("slot")) is int
                    and "condition" in row and (row["condition"] is None or isinstance(row["condition"], dict))
                    for row in value["repairs"])
            and isinstance(value.get("entities", []), list)
            and isinstance(value.get("additions", []), list))


def reconcile(qid, question, original, marked, reply, *, exhausted):
    entities, relation, old = initial_parts(original)
    reply = reply if usable_repair(reply) and not exhausted else {}
    updates, replacement_relation, _ = initial_parts(reply)
    protected = [row for i, row in enumerate(old) if i not in marked["claims"]]
    lock = {var: entity for var, entity in entities.items() if any(
        row["subject"] == var or re.search(name_pattern(entity["name"]), row["claim"], re.I) for row in protected)}
    entities = entities | updates | lock
    relation = relation or replacement_relation
    proposed = {}
    duplicates = set()
    for item in reply.get("repairs", []):
        slot = item["slot"]
        if slot in marked["claims"]:
            if slot in proposed:
                duplicates.add(slot)
            proposed[slot] = item["condition"]
    minimum = max(0, 2 - (len(old) - len(marked["claims"])))
    candidates = [(slot, row if slot in duplicates or proposed.get(slot) is None else proposed[slot])
                  for slot, row in enumerate(old)]
    candidates.extend((len(old) + offset, row) for offset, row in enumerate(reply.get("additions", [])[:minimum]))
    audit = []
    if marked["record"]:
        after = {"query_id": qid, "entities": list(entities.values()), "answer_relation": relation}
        audit.append(event(qid, "repair_record" if not exhausted else "retain_record", None,
                           marked["record"] + (["repair_unavailable"] if exhausted else []), original, after))
    result, ids, texts = [], set(), set()
    for slot, row in candidates:
        before = old[slot] if slot < len(old) else None
        issues = set(flags(question, entities, row))
        # A transport or parsing failure never authorizes dropping an existing row.
        if not exhausted and HARD & issues:
            audit.append(event(qid, "discard", slot, sorted(issues & HARD), before, row))
            continue
        if exhausted and slot in marked["claims"]:
            issues.add("repair_unavailable")
        if slot >= 10:
            issues.add("condition_count_above_10")
        if slot in duplicates:
            issues.add("duplicate_repair_slot")
        normalized = {key: row.get(key) if isinstance(row.get(key), str) else ""
                      for key in CLAIM_FIELDS} if isinstance(row, dict) else {key: "" for key in CLAIM_FIELDS}
        if not isinstance(row, dict) or row.keys() != CLAIM_FIELDS or not all(isinstance(v, str) for v in row.values()):
            normalized["original"] = row
        ident = normalized["id"]
        if not ident.strip() or ident in ids:
            issues.add("duplicate_id" if ident in ids else "missing_id")
            ident = f"v61-slot-{slot + 1}"
            while ident in ids:
                ident += "-r"
            normalized["id"] = ident
        sign = " ".join(normalized["claim"].split()).casefold()
        if sign and sign in texts:
            issues.add("duplicate_claim")
        ids.add(ident)
        texts.add(sign)
        normalized["flags"] = sorted(issues)
        result.append(normalized)
        if slot in marked["claims"] or slot >= len(old) or issues:
            phase = "retain_flagged" if issues else "repair"
            audit.append(event(qid, phase, slot, sorted(issues) or marked["claims"].get(slot, ["new_claim"]),
                               before, normalized))

    record_flags = []
    if not 2 <= len(result) <= 10:
        record_flags.append("condition_count_outside_2_to_10")
    if not relation:
        record_flags.append("answer_relation_missing")
    if not entities:
        record_flags.append("invalid_entity_table")
    if any(row["name"].upper() == "UNRESOLVED" for row in entities.values()):
        record_flags.append("unresolved_entity_table")
    if exhausted:
        record_flags.append("repair_unavailable")
    return {"query_id": qid, "entities": list(entities.values()), "conditions": result,
            "answer_relation": relation, "flags": sorted(record_flags)}, audit


def subject_text(condition, entities):
    subject = entities.get(condition["subject"], {"name": "UNRESOLVED", "role": "unknown subject"})
    return f'对象：{subject["name"]}（{subject["role"]}）。断言：{condition["claim"]}'


def build_payload(record, passages):
    entities = {row["var"]: row for row in record["entities"]}
    return {
        "claims": [{"id": row["id"], "text": subject_text(row, entities)} for row in record["conditions"]],
        "entities": [{key: row[key] for key in ("name", "role")} for row in record["entities"]],
        "passages": [{"sentences": [{key: row[key] for key in ("id", "text")} for row in passage["sentences"]]}
                     for passage in passages],
    }
