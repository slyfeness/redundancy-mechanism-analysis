import pytest
from redundancy_judge.init_task_ledger import init_task_ledger
from redundancy_judge.resolve_action_target import resolve_action_target
from redundancy_judge.update_evidence_ledger import merge_parallel_updates, update_evidence_ledger
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.summarize_trajectory import summarize_trajectory


class FixtureJudge:
    synthetic = True

    def __init__(self):
        self.seen = []

    def ask(self, kind, payload):
        self.seen.append((kind, payload))
        if kind == "task_constraints":
            return {"constraints": [{"start": 0, "end": 10, "quote": "Find Ada X"}], "uncertain": False}
        if kind == "action_target":
            return {"candidate": "Ada", "constraint_id": "C1", "intent": "verify", "confidence": 1.0}
        if kind == "evidence_update":
            text = payload["returned_text"]
            return {"updates": [{"candidate": "Ada", "constraint_id": "C1", "state": "supported",
                                 "quote": text, "start": 0, "end": len(text)}], "uncertain": False}
        return {"confirmed": True, "confidence": 1.0, "protection": None}


def stage(index, visible=()):
    return {"stage_id": f"s{index}", "stage_type": "tool", "parse_status": "ok",
            "event_ids": [str(index)], "visible_return_ids": list(visible), "strategy_text": "I already confirmed it",
            "charge_token_spans": [[index * 2, index * 2 + 1]], "cost": {"policy_tokens": 2, "return_tokens": 3},
            "action": {"event_id": str(index), "tool_name": "search", "arguments": {"query": "Ada X"},
                       "environment": "frozen", "deterministic": True}}


def event(index, text="Ada: X"):
    return {"event_id": str(index), "return_text": text, "return_time": index, "error": None,
            "source_id": "same-page", "visible_next": True}


def test_first_evidence_later_duplicate_both_labels_one_price():
    model = FixtureJudge()
    task, before = init_task_ledger("Find Ada X", model)
    first, second = stage(1), stage(2, ["1"])
    target = resolve_action_target(task, before, first, model)
    assert "Ada: X" not in str(model.seen[-1])
    after, delta = update_evidence_ledger(task, before, first, event(1), model)
    assert before["support"] == {}
    assert delta["effective_gain"] is True
    one = judge_stage(task, before, after, first, event(1), target, delta, model)
    again = resolve_action_target(task, after, second, model)
    final, delta = update_evidence_ledger(task, after, second, event(2), model)
    assert delta["effective_gain"] is False
    two = judge_stage(task, after, final, second, event(2), again, delta, model)
    assert one["price_label"] is None
    assert two["price_label"] == "R2b"
    assert {r["label"] for r in two["labels"] if r["decision"] == "positive"} >= {"R1", "R2b"}
    assert all(r["known_at"] == 2 for r in two["labels"])
    row = summarize_trajectory({"trajectory_id": "t", "question_id": "q", "result": "C"},
                               task, final, [first, second], [one, two], submitted_candidate="Ada")
    assert row["g"] == 1 and len(row["events"]) == 1
    assert row["events"][0]["charge_token_spans"] == [[4, 5]]


def test_false_quote_cannot_support_claim_and_future_is_not_in_target():
    model = FixtureJudge()
    task, before = init_task_ledger("Find Ada X", model)
    current = stage(1)
    current["future_answer"] = "SECRET FUTURE"
    current["tool_return"] = "SECRET FUTURE"
    resolve_action_target(task, before, current, model)
    assert "SECRET FUTURE" not in str(model.seen[-1])
    after, delta = update_evidence_ledger(task, before, current, event(1, None), model)
    assert after["support"] == {} and delta["status"] == "unavailable"


def test_one_invalid_quote_cannot_remove_an_independent_valid_update():
    class MixedJudge(FixtureJudge):
        def ask(self, kind, payload):
            response = super().ask(kind, payload)
            if kind == "evidence_update":
                response["updates"].append({"candidate": "other", "constraint_id": "C1",
                                            "state": "supported", "quote": "fabrication"})
            return response

    judge = MixedJudge()
    task, before = init_task_ledger("Find Ada X", judge)
    after, delta = update_evidence_ledger(task, before, stage(1), event(1), judge)
    assert {row["candidate"] for row in after["support"].values()} == {"ada"}
    assert delta["status"] == "partial_annotation"
    assert delta["effective_gain"]
    assert len(delta["rejected_evidence"]) == 1


def test_parallel_siblings_cannot_see_each_other_and_conflicts_survive_merge():
    class ConflictJudge(FixtureJudge):
        def ask(self, kind, payload):
            result = super().ask(kind, payload)
            if kind == "evidence_update" and "not" in payload["returned_text"]:
                result["updates"][0]["state"] = "refuted"
            return result

    model = ConflictJudge()
    task, before = init_task_ledger("Find Ada X", model)
    current = stage(1)
    left = update_evidence_ledger(task, before, current, event(1), model)
    right = update_evidence_ledger(task, before, current, event(2, "Ada: not X"), model)
    merged = merge_parallel_updates(task, before, [left, right])
    swapped = merge_parallel_updates(task, before, [right, left])
    assert [payload["prior"] for kind, payload in model.seen if kind == "evidence_update"] == [[], []]
    assert list(merged["support"].values())[0]["state"] == "conflicted"
    assert list(swapped["support"].values())[0]["state"] == "conflicted"
    assert merged["open_gaps"] == swapped["open_gaps"] == ["C1"]
    assert {row["event_id"] for row in merged["attempts"]} == {"1", "2"}


def test_hidden_prior_observation_is_protected():
    model = FixtureJudge()
    task, before = init_task_ledger("Find Ada X", model)
    after, _ = update_evidence_ledger(task, before, stage(1), event(1), model)
    hidden = stage(2)
    target = resolve_action_target(task, after, hidden, model)
    last, delta = update_evidence_ledger(task, after, hidden, event(2), model)
    result = judge_stage(task, after, last, hidden, event(2), target, delta, model)
    assert result["price_label"] is None
    assert "restore_invisible_evidence" in result["protections"]
