"""V3.1 preserves the v3 assertions and binds all repairs to original IDs and text."""

import re
import unicodedata

from .judge_v3 import DASH_QUOTES, unescape
from .judge_v4 import FILLER, NAMES, QUOTED, sentences

VERSION = "bcplus-round4-v3.1"
WORDS = re.compile(r"[^\W_]+", re.UNICODE)
NUMBER = re.compile(r"(?<![\d.])\d+(?:[,，]\s*\d{3}(?!\d))*(?:\.\d+)?(?:st|nd|rd|th)?(?!\d|[.]\d)", re.I)
SEPARATORS = re.compile(r"(?<=\d)[,，]\s*(?=\d)")
SUBJECT_START = re.compile(r"^\s*(?:(?:the|a|an)\s+)?", re.I)
SUBJECT_VERB = re.compile(
    r"\s+(?:is|was|were|are|has|had|became|served|won|published|founded|opened|"
    r"died|wrote|made|released|studied|joined|moved|worked|reported|researched|received|"
    r"played|married|directed|established|created|held|owned|went)\b", re.I)
CONNECTORS = {"a", "an", "the", "and"}
ALIASES = (
    ("USA", "U.S.A.", "U.S.", "US", "United States", "United States of America"),
    ("UK", "U.K.", "United Kingdom"),
    ("UN", "U.N.", "United Nations"),
    ("EU", "E.U.", "European Union"),
    ("NYC", "New York City"),
    ("USSR", "U.S.S.R.", "Soviet Union", "Union of Soviet Socialist Republics"),
)


def normalize(text):
    value = unicodedata.normalize("NFKC", unescape(text)).translate(DASH_QUOTES).casefold()
    return " ".join(value.split())


def entity_key(text):
    text = re.sub(r"\b(US|UN)\b", lambda match: ".".join(match[0]) + ".", text)
    value = unicodedata.normalize("NFKD", normalize(text))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    variants = {"st": "saint", "mt": "mount", "ft": "fort"}
    return tuple(variants.get(word, word) for word in WORDS.findall(value) if word not in CONNECTORS)


ALIAS_KEYS = {key: tuple(map(entity_key, group)) for group in ALIASES for key in map(entity_key, group)}


def key_contains(source, target):
    return bool(target) and any(source[i:i + len(target)] == target
                                for i in range(len(source) - len(target) + 1))


def _matches_alias(key, section):
    return any(key_contains(section, variant) for variant in ALIAS_KEYS.get(key, (key,)))


def same_entity(name, evidence):
    return _matches_alias(entity_key(name), entity_key(evidence))


def aligned_evidence(reference, old_index, document, *, new=None):
    ids = reference["sentence_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 3 or len(set(ids)) != len(ids):
        raise ValueError("invalid v3 citation shape")
    previous = [old_index[k] for k in ids]
    prefix = ids[0].rsplit(".s", 1)[0]
    if any(r["docid"] != reference["docid"] or document[r["start"]:r["end"]] != r["text"] for r in previous):
        raise ValueError("v3 citation fails original source offsets")
    if new is None:
        new = sentences(document, prefix)
    selected = [r for r in new if any(r["start"] < old["end"] and old["start"] < r["end"] for old in previous)]
    if not 1 <= len(selected) <= 3 or any(
        any(not document[i].isspace() and not any(r["start"] <= i < r["end"] for r in selected)
            for i in range(old["start"], old["end"])) for old in previous):
        raise ValueError("v3 citation does not fit 1–3 aligned v4 sentences")
    return {"docid": reference["docid"], "sentence_ids": [r["id"] for r in selected],
            "text": "\n".join(r["text"] for r in selected),
            "v3_sentence_ids": ids, "offsets": [[r["start"], r["end"]] for r in selected]}


def subject_start(text):
    start = SUBJECT_START.match(text).end()
    verb = SUBJECT_VERB.search(text, start)
    if verb and 0 < verb.start() - start <= 90:
        candidate = text[start:verb.start()].strip()
        if candidate and candidate[0].isupper() and "," not in candidate and NAMES.match(candidate):
            return candidate
    name = NAMES.match(text, start)
    return name[0].strip() if name and name[0].casefold() not in FILLER else ""


def names(text):
    found = set()
    for match in NAMES.finditer(text):
        words = match[0].split()
        while words and words[0].casefold() in FILLER:
            words.pop(0)
        if words:
            found.add(" ".join(words))
    return sorted(found)


def numeric_key(token):
    return SEPARATORS.sub("", normalize(token))


def entity_check(claim, evidence, document):
    seen = {numeric_key(m[0]) for m in NUMBER.finditer(unicodedata.normalize("NFKC", evidence))}
    missing_numbers = [m[0] for m in NUMBER.finditer(claim) if numeric_key(m[0]) not in seen]
    # Normalize names on separate sentence and document scopes. Only the whole
    # leading subject phrase may use a match outside the cited passage.
    subject = subject_start(claim)
    skey, ekey = entity_key(subject), entity_key(evidence)
    doc_match = bool(skey) and (_matches_alias(skey, ekey) or _matches_alias(skey, entity_key(document)))
    missing_names = [name for name in names(claim)
                     if not _matches_alias(entity_key(name), ekey)
                     and not (doc_match and key_contains(skey, entity_key(name)))]
    literal = "".join(normalize(evidence).split())
    missing_quotes = [q for m in QUOTED.finditer(claim) for q in m.groups()
                      if q and "".join(normalize(q).split()) not in literal and not same_entity(q, evidence)]
    return {"passed": not (missing_names or missing_numbers or missing_quotes),
            "missing_names": missing_names, "missing_numbers": sorted(set(missing_numbers)),
            "missing_quotes": sorted(set(missing_quotes)), "subject": subject,
            "subject_document_match": doc_match}


def apply_targeted_edits(text, edits, missing):
    allowed = {term for key in ("missing_names", "missing_numbers", "missing_quotes") for term in missing[key]}
    if not isinstance(edits, list) or not edits:
        raise ValueError("expected at least one requested edit")
    replacements = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError("invalid edit shape")
        old, new = edit.get("old"), edit.get("new")
        if not isinstance(old, str) or old not in allowed or not isinstance(new, str) or "\n" in new or len(new) > 180:
            raise ValueError("edit touches a term outside the flagged set")
        if text.count(old) != 1:
            raise ValueError("edit is not bound to one literal location")
        position = text.index(old)
        replacements.append((position, position + len(old), new))
    output, end = [], 0
    for start, stop, new in sorted(replacements):
        if start < end:
            raise ValueError("edits overlap")
        output.extend((text[end:start], new))
        end = stop
    result = ("".join(output) + text[end:]).strip()
    if not result or result == text:
        raise ValueError("edit produces no revised assertion")
    return result


def question_span(question, indices):
    words = list(re.finditer(r"\S+", question))
    if not isinstance(indices, list) or len(indices) != 2 or any(type(x) is not int for x in indices):
        return None
    start, end = indices
    if 1 <= start <= end <= len(words):
        return question[words[start-1].start():words[end-1].end()]
    return None


def gate(entity_failures, parent_missing, zero_questions, valid_ids, attempts, no_reason, unknown):
    checks = {"entity": entity_failures == 0, "parents": parent_missing == 0,
              "zero_questions": zero_questions <= 2,
              "sentence_ids": attempts > 0 and valid_ids * 100 >= attempts * 95,
              "unknown_reason": no_reason * 100 <= unknown * 2}
    return {**checks, "passed": all(checks.values())}
