"""Validated final-answer candidate extraction without a positional fallback."""

from .common import JudgeFailure, exact_quote, require


def extract_final_candidate(question, final_text, judge):
    """Return an auditable submitted candidate, or abstain when it is ambiguous.

    The Judge is allowed to identify a semantic submission anchor, but every
    emitted span remains mechanically checked against the final text.  Legacy
    unique quotes remain readable; duplicated text never receives a first/last
    occurrence fallback.
    """
    response = judge.ask("final_candidate", {"question": question, "final_text": final_text})
    quote = response.get("quote")
    if quote is None:
        require(response.get("start") is None and response.get("end") is None,
                "null final candidate must not carry a span")
        return None
    ref = exact_quote(final_text, response)
    anchor = response.get("anchor")
    require(isinstance(anchor, str) and anchor.strip(), "missing final submission anchor")
    return {"candidate": ref["quote"], "source": ref, "anchor": anchor,
            "protocol": "phase1.1.span_anchor"}
