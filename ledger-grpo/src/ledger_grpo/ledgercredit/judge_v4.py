"""Sentence boundaries and literal checks for the opt-in M2 v4 run."""

import re
import unicodedata

from .judge_v3 import DASH_QUOTES, JUDGE_PROMPT as PREVIOUS_JUDGE_PROMPT, unescape

VERSION = "bcplus-round4-v4"
JUDGE_VERSION = "ledgercredit-sentence-judge-v4"
JUDGE_PROMPT = PREVIOUS_JUDGE_PROMPT + """
Treat minor spelling or title variants of the same entity as equivalent, including
case, articles, 'and' versus ':', and common aliases. Do not generalize across distinct
entities. Even for unknown, always include a one-sentence, nonempty reason and [].
"""
ENDS = re.compile(r"""[.!?。！？](?:["'’”)]*)(?=\s|$)""")
ABBREVIATION = re.compile(
    r"(?<![A-Za-z])(?:Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|No|vs|etc|e\.g|i\.e|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|m|b|d)\.$", re.I)
INITIAL = re.compile(r"(?<![A-Za-z])[A-Z]\.$")
THOUSANDS = re.compile(r"(?<=\d)[,，]\s*(?=\d)")
NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?:st|nd|rd|th)?(?!\d|[.]\d)", re.I)
WORD = r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ]+(?:[-’'][A-Za-zÀ-ÖØ-öø-ÿ]+)*"
NAMES = re.compile(rf"(?<!\w)(?:{WORD})(?:\s+(?:(?:of|the|and|de|van|von)\s+)*(?:{WORD}))*")
QUOTED = re.compile(r'''"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|(?<!\w)'([^'\n]+)'(?!\w)''')
FILLER = set("a an the it he she they its her his their this that these those in during on "
             "at from for after before according as by only between over under when while "
             "all each and there of here originally later formerly first both either whose "
             "which who with published founded released born died written recorded".split())
META_LINE = re.compile(
    r"^\s*(?:title|heading|byline|author|written by|publication|published|publication date|"
    r"date|source|last updated|updated|copyright|url|website)\s*[:=]", re.I)
META_DATE = re.compile(
    r"^\s*(?:\d{4}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z.]*\s+\d{1,2},?\s+\d{4})\s*[.]?\s*$", re.I)
PUBLICATION = re.compile(r"\b(?:author(?:ed|ship)?|written|wrote|byline|published|publication|date|"
                         r"before|after|released|appeared|journal|issue|edition|printed|publisher)\b|"
                         r"作者|出版|发表|刊登|日期|之前|之后", re.I)
PRONOUN = re.compile(r"\b(?:he|him|his|she|her|hers|it|its|they|their|them|this|that)\b", re.I)


def sentence_spans(text):
    """Return trimmed offsets in the original text, with no rewritten punctuation."""
    spans = []
    def append(start, end):
        value = text[start:end]
        if value.strip():
            spans.append((start + len(value) - len(value.lstrip()), start + len(value.rstrip())))

    for match in re.finditer(r"[^\r\n]+", text):
        line = match[0]
        offset, start = match.start(), 0
        ends = []
        for punctuation in ENDS.finditer(line):
            pos = punctuation.start()
            if line[pos] == ".":
                # The longest protected token and its preceding boundary fit here.
                leading = line[max(0, pos - 12):pos + 1]
                if ABBREVIATION.search(leading) or INITIAL.search(leading):
                    continue
            ends.append(punctuation.end())
        for end in ends + [len(line)]:
            if end <= start:
                continue
            cut = start
            if len(line[start:end].split()) > 80:
                for sep in re.finditer(r"[,;，；]", line[start:end]):
                    pos = start + sep.start()
                    if line[pos] in ",，" and pos and line[pos-1].isdigit() and re.match(r"\s*\d", line[pos+1:end]):
                        continue
                    append(offset + cut, offset + pos + 1)
                    cut = pos + 1
            append(offset + cut, offset + end)
            start = end
    return spans


def sentences(text, prefix):
    return [{"id": f"{prefix}.s{i}", "index": i, "start": a, "end": b, "text": text[a:b]}
            for i, (a, b) in enumerate(sentence_spans(text), 1)]


def canonical(text):
    text = unicodedata.normalize("NFKC", unescape(text)).translate(DASH_QUOTES).casefold()
    return THOUSANDS.sub("", text)


def compact(text):
    return "".join(canonical(text).split())


def named_terms(text):
    found = []
    for match in NAMES.finditer(text):
        words = match[0].split()
        while words and words[0].casefold() in FILLER:
            words.pop(0)
        if words:
            found.append(" ".join(words))
    return sorted(set(found))


def entity_check(text, subject, evidence, document, pronoun_allowed):
    source, normalized_claim = canonical(evidence), canonical(text)
    source_numbers = {n[0] for n in NUMBER.finditer(source)}
    missing_numbers = sorted({n[0] for n in NUMBER.finditer(normalized_claim)} - source_numbers)
    surface, doc = compact(evidence), compact(document)
    allow_subject = bool(subject and pronoun_allowed and PRONOUN.search(evidence) and compact(subject) in doc)
    sub = compact(subject)
    missing_names = [term for term in named_terms(text)
                     if compact(term) not in surface and not (allow_subject and compact(term) == sub)]
    missing_quotes = [q for m in QUOTED.finditer(text) for q in m.groups()
                      if q and compact(q) not in surface]
    return {"passed": not (missing_numbers or missing_names or missing_quotes),
            "missing_numbers": missing_numbers, "missing_names": missing_names,
            "missing_quotes": missing_quotes, "subject_pronoun_exception": allow_subject}


def metadata_only(excerpts):
    lines = [line for text in excerpts for line in text.splitlines() if line.strip()]
    return bool(lines) and all(META_LINE.match(line) or META_DATE.match(line) for line in lines)


def metadata_allowed(question_span):
    return bool(PUBLICATION.search(question_span))


def gate(entity_failures, valid_ids, citation_attempts, unknown_without_reason, unknown,
         covered, condition_count, generation_lost, unresolved):
    identifier_ok = citation_attempts > 0 and 100 * valid_ids >= 95 * citation_attempts
    unknown_ok = unknown_without_reason * 100 <= 2 * unknown
    coverage_ok = condition_count > 0 and 0 <= covered <= condition_count and generation_lost == unresolved == 0
    return {"entity": entity_failures == 0, "ids": identifier_ok, "unknown_reason": unknown_ok,
            "coverage": coverage_ok, "passed": entity_failures == 0 and identifier_ok and unknown_ok and coverage_ok}
