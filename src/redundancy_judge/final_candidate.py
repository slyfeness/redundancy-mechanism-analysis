"""Extract a submitted candidate and locate its source quote."""

import re

from .adapters.model import uses_lenient_quotes
from .common import exact_quote, require
from .quote_locator import QuoteLocator


LABEL = re.compile(r"(?im)(?:^|(?<=[.!?])[ \t]+)[ \t]*(?:\*\*)?(?:final[ \t]+)?answer(?:\*\*)?[ \t]*:(?:\*\*)?[ \t]*")
TAG = re.compile(r"(?i)</?answer>")
AMBIGUOUS_BODY = re.compile(
    r"\b(?:and|or|either|versus|vs|alternatively|maybe|possibly|perhaps|probably)\b"
    r"|[,;/|&\\\n\r:!?，、；／｜]|[.!?][ \t]", re.I)


def _answer_body(text):
    """Find one verifiable submission envelope in the final actor message."""
    markers, tags = list(LABEL.finditer(text)), list(TAG.finditer(text))
    if tags:
        require(not markers and [tag.group().lower() for tag in tags] == ["<answer>", "</answer>"]
                and not text[tags[1].end():].strip(), "ambiguous final submission structure")
        begin, start, end, finish = tags[0].start(), tags[0].end(), tags[1].start(), tags[1].end()
        require(not text[:begin].strip() or not text[:begin].split("\n")[-1].strip(),
                "invalid final submission structure")
    elif markers:
        require(len(markers) == 1, "ambiguous final submission structure")
        begin, start = markers[0].span()
        begin += len(markers[0].group()) - len(markers[0].group().lstrip())
        end = finish = len(text.rstrip())
    else:
        begin = start = len(text) - len(text.lstrip())
        end = finish = len(text.rstrip())
    prefix = text[:begin]
    if prefix.strip():
        require(prefix.rstrip().endswith((".", "!", "?")) and '"' not in prefix and "“" not in prefix
                and "```" not in prefix and "~~~" not in prefix and "`" not in prefix.split("\n")[-1],
                "quoted, illustrative or ambiguous final submission structure")
    body = text[start:end]
    start += len(body) - len(body.lstrip())
    end -= len(body) - len(body.rstrip())
    # Allow simple formatting and one terminal period, but never a list or a trailing second answer.
    if text[start:end].endswith("."):
        end -= 1
    for wrapper in ("**", "`"):
        if text[start:end].startswith(wrapper) and text[start:end].endswith(wrapper) and end - start > 2 * len(wrapper):
            start += len(wrapper)
            end -= len(wrapper)
            break
    require(start < end and not AMBIGUOUS_BODY.search(text[start:end]), "ambiguous final submission body")
    return (begin, finish), (start, end)


def extract_final_candidate(question, final_text, judge):
    """Return an auditable submitted candidate, or abstain when it is ambiguous.

    Check model spans against the entire mechanically recognized submission.
    A legacy quote needs a unique occurrence and the same submission check.
    """
    response = judge.ask("final_candidate", {"question": question, "final_text": final_text})
    require(isinstance(response, dict) and "quote" in response, "invalid final candidate response")
    if uses_lenient_quotes(judge):
        if response["quote"] is None:
            return None
        ref = QuoteLocator(final_text).locate(response["quote"], last=True)
        return {"candidate": ref["quote"], "source": ref, "protocol": "phase1.2.located_quote.v1"}
    if getattr(judge, "protocol_version", None):
        require({"quote", "start", "end", "anchor", "anchor_start", "anchor_end"} <= response.keys(),
                "versioned final candidate response is missing required fields")
    if response["quote"] is None:
        require(all(response.get(key) is None for key in ("start", "end", "anchor", "anchor_start", "anchor_end")),
                "null final candidate must not carry a span or anchor")
        return None
    modern = "anchor_start" in response or "anchor_end" in response
    if modern:
        require(all(type(response.get(key)) is int for key in ("start", "end", "anchor_start", "anchor_end")),
                "both final candidate and anchor must carry explicit character spans")
    else:
        exact_quote(final_text, {"quote": response["quote"]})
    ref = exact_quote(final_text, response)
    anchor = response.get("anchor")
    envelope, body = _answer_body(final_text)
    if not modern and "anchor" not in response:
        anchor = final_text[slice(*envelope)]
    require(isinstance(anchor, str) and anchor.strip(), "missing final submission anchor")
    anchor_ref = exact_quote(final_text, {"quote": anchor, "start": response.get("anchor_start"),
                                          "end": response.get("anchor_end")})
    require((anchor_ref["start"], anchor_ref["end"]) == envelope,
            "final anchor does not identify the complete submission structure")
    require((ref["start"], ref["end"]) == body, "final candidate span does not identify the single submitted answer")
    return {"candidate": ref["quote"], "source": ref, "anchor": anchor, "anchor_source": anchor_ref,
            "protocol": "phase1.1.span_anchor.v2" if modern else "legacy.unique_quote"}
