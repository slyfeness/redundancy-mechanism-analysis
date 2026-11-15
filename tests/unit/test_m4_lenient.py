import pytest

from redundancy_judge.adapters.model import ModelJudge, RESPONSE_SCHEMAS
from redundancy_judge.common import JudgeFailure
from redundancy_judge.final_candidate import extract_final_candidate
from redundancy_judge.init_task_ledger import initial_ledger
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.summarize_trajectory import summarize_trajectory
from redundancy_judge.update_evidence_ledger import update_evidence_ledger


TASK = {"constraints": [{"constraint_id": "C1", "text": "founded in 2000"}], "uncertain": False}
ACTION = {"tool_name": "Search", "arguments": {"query": "Alpha"}, "deterministic": True, "environment": "test"}
STAGE = {"stage_id": "s1", "stage_type": "tool", "action": ACTION, "visible_return_ids": [], "parse_status": "ok"}
ROW = {"candidate": "Alpha", "constraint_id": "C1", "state": "supported", "quote": "Alpha opened."}
TARGET = {"state": "resolved", "candidate": "alpha", "constraint_id": "C1", "intent": "verify"}


class Judge:
    protocol_version = ModelJudge.protocol_version

    def __init__(self, *, updates=(), uncertain=False, quote=None):
        self.results = {
            "evidence_update": {"uncertain": uncertain, "updates": list(updates)},
            "final_candidate": {"quote": quote},
            "r1_verification": {"confidence": 1, "confirmed": True, "protection": None},
        }
        self.calls = []

    def ask(self, kind, payload):
        self.calls.append(kind)
        return self.results[kind]


def event(text, eid="e1"):
    return {"event_id": eid, "return_text": text, "visible_next": True}


@pytest.mark.parametrize("source,quote,kind,raw,count", [
    ("x Alpha opened.", "Alpha opened.", "exact", "Alpha opened.", 1),
    ("x Ａlpha\u00a0\nopened.", "Alpha opened.", "normalized", "Ａlpha\u00a0\nopened.", 1),
    ("Alpha opened. Alpha opened.", "Alpha opened.", "multi", "Alpha opened.", 2),
    ("x A\u030a\topen.", "Å open.", "normalized", "A\u030a\topen.", 1),
    ("x 각 open.", "각 open.", "normalized", "각 open.", 1),
    ("x ﬃ.", "fi", "absent", None, None),
    ("unrelated", "Alpha opened.", "absent", None, None),
])
def test_m4_quote_locations(source, quote, kind, raw, count):
    after, delta = update_evidence_ledger(TASK, initial_ledger(TASK), STAGE, event(source),
                                          Judge(updates=[{**ROW, "quote": quote}]))
    assert delta["quote_locations"][kind] == 1
    if kind == "absent":
        assert delta["rejected_evidence"][0]["scope"] == "support"
        assert not after["support"]
    else:
        ref = delta["evidence"][0]
        assert ref["quote"] == source[ref["start"]:ref["end"]] == raw
        assert ref["occurrences"] == count
        assert ref["start"] == source.find(raw)
        assert delta["new_candidates"] == ["alpha"]


def test_unknown_counts_without_risk_and_uncertain_warns_without_erasing_support():
    initial = initial_ledger(TASK)
    result, delta = update_evidence_ledger(TASK, initial, STAGE, event("Alpha opened."),
                                           Judge(updates=[{**ROW, "state": "unknown"}]))
    assert delta["unknown_dropped"] == 1
    assert not delta["rejected_evidence"] and not result["support"]
    assert not result["unresolved_evidence_risk"]["global"]
    supported, _ = update_evidence_ledger(TASK, initial, STAGE, event("Alpha opened."), Judge(updates=[ROW]))
    after, warning = update_evidence_ledger(TASK, supported, STAGE, event("incomplete", "e2"),
                                             Judge(uncertain=True))
    assert warning["status"] == "ok" and warning["uncertain"]
    assert len(after["unresolved_evidence_risk"]["global"]) == 1
    assert after["support"] == supported["support"]


def test_global_warning_does_not_block_r1_or_g_but_matching_local_risk_still_does():
    judge = Judge(updates=[ROW])
    before, _ = update_evidence_ledger(TASK, initial_ledger(TASK), STAGE, event("Alpha opened."), judge)
    next_stage = {**STAGE, "stage_id": "s2", "visible_return_ids": ["e1"]}
    second = event("unclear", "e2")
    after, delta = update_evidence_ledger(TASK, before, next_stage, second, Judge(uncertain=True))
    judge_stage(TASK, before, after, next_stage, second, TARGET, delta, judge)
    assert judge.calls[-1] == "r1_verification"
    trace = {"provenance": {"judge_protocol_version": judge.protocol_version}}
    summary = summarize_trajectory(trace, TASK, after, [], [], submitted_candidate="Alpha")
    assert summary["g"] == 1.0 and summary["global_risk_count"] == 1
    invalid, _ = update_evidence_ledger(TASK, after, next_stage, event("No quote", "e3"), Judge(updates=[ROW]))
    judge.calls.clear()
    judgment = judge_stage(TASK, invalid, invalid, next_stage, second, TARGET, delta, judge)
    assert not judge.calls and judgment["risk_guard_reason"]
    assert summarize_trajectory(trace, TASK, invalid, [], [], submitted_candidate="Alpha")["g"] is None


def test_lenient_final_uses_last_occurrence_and_exact_source():
    text = "Ada was considered. The actual answer: Ada."
    result = extract_final_candidate("Who?", text, Judge(quote="Ada"))
    assert result["source"]["start"] == text.rfind("Ada")
    assert result["source"]["occurrences"] == 2
    assert "anchor" not in result
    assert extract_final_candidate("Who?", "none", Judge()) is None
    assert extract_final_candidate("Who?", "Ａda", Judge(quote="Ada"))["source"]["quote"] == "Ａda"
    with pytest.raises(JudgeFailure, match="not found"):
        extract_final_candidate("Who?", text, Judge(quote="Bea"))


def test_new_response_schema_uses_quote_without_offsets_or_anchor():
    evidence = RESPONSE_SCHEMAS["evidence_update"]
    assert set(evidence["required"]) == {"uncertain", "updates"}
    assert set(evidence["properties"]["updates"]["items"]["required"]) == {
        "candidate", "constraint_id", "state", "quote", "resolves_conflict"}
    assert RESPONSE_SCHEMAS["final_candidate"]["required"] == ["quote"]
