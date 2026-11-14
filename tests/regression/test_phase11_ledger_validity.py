"""Phase 1.1 regressions: localization is mandatory for new Judge protocol rows."""

from redundancy_judge.common import exact_quote
from redundancy_judge.final_candidate import extract_final_candidate
from redundancy_judge.init_task_ledger import init_task_ledger
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.resolve_action_target import resolve_action_target
from redundancy_judge.summarize_trajectory import summarize_trajectory
from redundancy_judge.update_evidence_ledger import update_evidence_ledger


class Judge:
    synthetic = True

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def ask(self, kind, payload):
        self.calls.append((kind, payload))
        value = self.responses[kind]
        return value(payload) if callable(value) else value


def task_and_ledger(judge):
    return init_task_ledger("Find Ada X", judge)


def stage(index=1, *, visible=()):
    return {"stage_id": f"s{index}", "stage_type": "tool", "parse_status": "ok",
            "visible_return_ids": list(visible), "charge_token_spans": [[1, 2]],
            "cost": {"policy_tokens": 1, "return_tokens": 1},
            "action": {"tool_name": "search", "arguments": {"query": "Ada X"},
                       "environment": "frozen", "deterministic": True}}


def event(index=1, text="Ada has X."):
    return {"event_id": str(index), "return_text": text, "return_time": index,
            "visible_next": True, "source_id": "doc"}


def constraints():
    return {"uncertain": False, "constraints": [{"quote": "Find Ada X", "start": 0, "end": 10}]}


def test_explicit_span_disambiguates_repeated_final_candidate_without_first_or_last_fallback():
    text = "Ada was considered. Final answer: Ada."
    assert exact_quote(text, {"quote": "Ada", "start": 34, "end": 37})["start"] == 34
    try:
        exact_quote(text, {"quote": "Ada"})
    except ValueError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous legacy quote must not select first or last occurrence")


def test_final_candidate_requires_a_submission_anchor_and_never_uses_ambiguous_text_fallback():
    final = "Ada was considered. Final answer: Ada."
    judge = Judge({"final_candidate": {"quote": "Ada", "start": 34, "end": 37,
                                       "anchor": "Final answer: Ada."}})
    candidate = extract_final_candidate("Find Ada", final, judge)
    assert candidate["candidate"] == "Ada" and candidate["source"]["start"] == 34
    bad = Judge({"final_candidate": {"quote": "Ada", "start": 34, "end": 37, "anchor": None}})
    try:
        extract_final_candidate("Find Ada", final, bad)
    except ValueError as exc:
        assert "anchor" in str(exc)
    else:
        raise AssertionError("unanchored final-candidate selection must abstain/fail visibly")


def test_final_candidate_abstains_when_two_distinct_answers_are_submitted():
    judge = Judge({"final_candidate": {"quote": None, "start": None, "end": None, "anchor": None}})
    assert extract_final_candidate("Find Ada", "Final answer: Ada or Bert.", judge) is None


def test_valid_row_survives_invalid_row_and_rejected_refutation_creates_local_risk():
    judge = Judge({
        "task_constraints": constraints(),
        "evidence_update": {"uncertain": False, "updates": [
            {"candidate": "Ada", "constraint_id": "C1", "state": "supported",
             "quote": "Ada has X", "start": 0, "end": 9, "resolves_conflict": False},
            {"candidate": "Ada", "constraint_id": "C1", "state": "refuted",
             "quote": "rewritten contradiction", "start": 0, "end": 21, "resolves_conflict": False},
        ]},
    })
    task, before = task_and_ledger(judge)
    after, delta = update_evidence_ledger(task, before, stage(), event(), judge)
    fact = next(iter(after["support"].values()))
    assert fact["state"] == "supported"
    assert delta["status"] == "partial_annotation"
    assert fact["unresolved_evidence_risk"]
    assert delta["effective_gain"] is None
    assert delta["rejected_evidence"][0]["potential_conflict"] is True


def test_unscoped_bad_evidence_keeps_global_risk_and_blocks_g():
    judge = Judge({
        "task_constraints": constraints(),
        "evidence_update": {"uncertain": False, "updates": [
            {"candidate": "Ada", "constraint_id": "C1", "state": "supported",
             "quote": "Ada has X", "start": 0, "end": 9, "resolves_conflict": False},
            {"candidate": "", "constraint_id": "C1", "state": "refuted",
             "quote": "bad", "start": 0, "end": 3, "resolves_conflict": False},
        ]},
    })
    task, before = task_and_ledger(judge)
    after, _ = update_evidence_ledger(task, before, stage(), event(), judge)
    assert after["unresolved_evidence_risk"]["global"]
    row = summarize_trajectory({"trajectory_id": "t", "question_id": "q", "result": "C"}, task, after,
                               [stage()], [], submitted_candidate="Ada")
    assert row["g"] is None and row["grounding_issue"] == "unresolved_evidence_risk"


def test_unrelated_rejected_evidence_does_not_poison_final_candidate_g():
    judge = Judge({
        "task_constraints": constraints(),
        "evidence_update": {"uncertain": False, "updates": [
            {"candidate": "Ada", "constraint_id": "C1", "state": "supported",
             "quote": "Ada has X", "start": 0, "end": 9, "resolves_conflict": False},
            {"candidate": "Bert", "constraint_id": "C1", "state": "supported",
             "quote": "fabricated", "start": 0, "end": 10, "resolves_conflict": False},
        ]},
    })
    task, before = task_and_ledger(judge)
    after, _ = update_evidence_ledger(task, before, stage(), event(), judge)
    row = summarize_trajectory({"trajectory_id": "t", "question_id": "q", "result": "C"}, task, after,
                               [stage()], [], submitted_candidate="Ada")
    assert row["g"] == 1


def test_name_similarity_does_not_merge_distinct_entities_without_explicit_alias_evidence():
    judge = Judge({
        "task_constraints": constraints(),
        "evidence_update": {"uncertain": False, "updates": [
            {"candidate": "Ada Lovelace", "constraint_id": "C1", "state": "supported",
             "quote": "Ada has X", "start": 0, "end": 9, "resolves_conflict": False},
        ]},
    })
    task, before = task_and_ledger(judge)
    after, _ = update_evidence_ledger(task, before, stage(), event(), judge)
    assert {row["candidate"] for row in after["support"].values()} == {"ada lovelace"}
    row = summarize_trajectory({"trajectory_id": "t", "question_id": "q", "result": "C"}, task, after,
                               [stage()], [], submitted_candidate="Ada")
    assert row["g"] == 0 and row["supported_constraints"] == []


def test_open_exploration_can_resolve_gap_but_cannot_become_r1_target():
    judge = Judge({
        "task_constraints": constraints(),
        "action_target": {"candidate": None, "constraint_id": None, "gap_id": "C1",
                          "intent": "explore", "confidence": 0.95,
                          "evidence_basis": ["arguments"]},
    })
    task, before = task_and_ledger(judge)
    target = resolve_action_target(task, before, stage(), judge)
    assert target["state"] == "gap_resolved" and target["gap_id"] == "C1"
    assert target["candidate"] is None and target["constraint_id"] is None


def test_r1_funnel_distinguishes_not_invoked_from_real_low_confidence():
    judge = Judge({
        "task_constraints": constraints(),
        "r1_verification": {"confirmed": True, "confidence": 0.2, "protection": None},
    })
    task, before = task_and_ledger(judge)
    unknown = {"state": "unknown", "candidate": None, "constraint_id": None,
               "intent": "unknown", "confidence": None}
    result = judge_stage(task, before, before, stage(), event(), unknown,
                         {"status": "ok", "effective_gain": False, "new_documents": []}, judge)
    r1 = next(row for row in result["labels"] if row["label"] == "R1")
    assert r1["decision"] == "abstain"
    assert result["diagnostics"]["r1_funnel"]["outcome"] == "not_invoked"
    assert not [call for call in judge.calls if call[0] == "r1_verification"]
