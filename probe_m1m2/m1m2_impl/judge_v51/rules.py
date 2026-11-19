"""Named-claim validation and entity context for the v5.1 trial."""

from collections import Counter
import re

from bounded import PROMPT as V5_PROMPT, validate as validate_v5

PROMPT = V5_PROMPT + """

For v5.1, include every object mentioned by the question in entities, including
intermediate people, works, organizations, productions, directors, publications,
species, and other objects. Supply a concrete name for each. If the name cannot
be determined from the supplied inputs, set name exactly to UNRESOLVED and include
a short reason after the question role in that entity's role field. Do not guess.

Start every claim with the exact name of its subject. When a claim involves
two objects, explicitly write both names (or UNRESOLVED for an unresolved one).
Once names are resolved, every other part of the claim must come from the question.
Preserve the precision of the original wording, including vague times and ranges.
Do not add a precise year, award, person, publication, or other external detail.
Each capitalized word and numeric expression in a claim must appear in the
question or in an entity name. An exact question_span may be used at most twice.
"""

JUDGE_ENTITY_RULE = """

Use the entity name/role table to disambiguate each claim. If a passage refers
to a different person or object, including a different name or identity, return
unknown with an empty sentence_ids list and reason exactly "different entity".
This applies even if the passage states the same kind of relationship or property.
Keep the existing single-passage sentence-ID and reason requirements.
"""

WORD = re.compile(r"[^\W\d_]+")
NUMBER = re.compile(r"\d+(?:[,.]\d+)*(?:st|nd|rd|th|s)?", re.IGNORECASE)


def validate(qid, question, row):
    issues = set(validate_v5(qid, question, row))
    if issues:
        return sorted(issues)
    names = {entity["var"]: entity["name"] for entity in row["entities"]}
    sources = [question, *names.values()]
    allowed_words = {word.casefold() for text in sources for word in WORD.findall(text)}
    allowed_numbers = {token.casefold() for text in sources for token in NUMBER.findall(text)}
    spans = Counter(condition["question_span"] for condition in row["conditions"])
    if any(n > 2 for n in spans.values()):
        issues.add("question_span_used_more_than_twice")
    for condition in row["conditions"]:
        claim = condition["claim"]
        name = names[condition["subject"]]
        if not re.match(re.escape(name) + r"(?!\w)", claim):
            issues.add("claim_does_not_start_with_subject_name")
        if any(word[0].isupper() and word.casefold() not in allowed_words for word in WORD.findall(claim)):
            issues.add("capitalized_word_not_in_question_or_names")
        if any(token.casefold() not in allowed_numbers for token in NUMBER.findall(claim)):
            issues.add("number_not_in_question_or_names")
    return sorted(issues)


def judge_payload(frozen, block, *, base_payload):
    return {**base_payload(frozen["conditions"], block),
            "entities": [{key: entity[key] for key in ("name", "role")} for entity in frozen["entities"]]}
