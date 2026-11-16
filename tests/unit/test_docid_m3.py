import pytest

from redundancy_judge.resolve_action_target import resolve_action_target
from test_docid_mode import decide, fixture


class TwoReplies:
    def __init__(self, entity="named", stated=True, ids=("P4",)):
        self.calls = []
        self.entity, self.stated, self.ids = entity, stated, list(ids)

    def ask_m3(self, step, payload, schema, event_id):
        self.calls.append((step, payload))
        return {"seeking": "specific", "entity": self.entity, "attribute": "relation"} if step == "intent" else {
            "reason": "reason", "already_stated": self.stated, "passage_ids": self.ids,
        }


def make_target(task, before, stage, fake):
    return resolve_action_target(task, before, {**stage, "m3_event_id": "t:1", "m3_reasoning": "a"*1600}, fake)


def test_pipeline_m3_skip_is_auditable_and_requests_exclude_question():
    t, state, st, event = fixture([("4", "evidence")])
    fake = TwoReplies()
    assert make_target(t, state, st, fake)["skip_reason"] == "no_prior_passages"
    assert fake.calls == [("intent", {"agent_reasoning_before_search": "a"*1500,
                                      "current_search_query": "Ａ  Search"})]
    fake = TwoReplies(entity=None)
    assert make_target(t, state, st, fake)["skip_reason"] == "new_candidate"


@pytest.mark.parametrize("truth,ids,expected", [(True, ("P4",), "positive"), (False, (), "negative"),
                                                (True, ("P5",), "negative")])
def test_pipeline_m3_r1_and_record_only(truth, ids, expected):
    from redundancy_judge.judge_stage import judge_stage
    from redundancy_judge.update_evidence_ledger import update_evidence_ledger
    t, state, st, event = fixture([("8", "other")])
    state.update(evidence_passages={"4": "evidence"}, documents=["4"])
    fake = TwoReplies(stated=truth, ids=ids)
    target = make_target(t, state, st, fake)
    after, delta = update_evidence_ledger(t, state, st, event, fake)
    j = judge_stage(t, state, after, st, event, target, delta, fake)
    r1 = next(row for row in j["labels"] if row["label"] == "R1")
    assert r1["decision"] == expected and not r1["reward_eligible"]
    assert j["price_label"] is None
    assert ("question" not in fake.calls[1][1]) and fake.calls[1][1]["previously_seen_passages"] == [
        {"id": "P4", "text": "evidence"}]


def test_docid_r1_abstention_and_r2b_higher_priority():
    from redundancy_judge.judge_stage import judge_stage
    from redundancy_judge.update_evidence_ledger import update_evidence_ledger
    t, state, st, event = fixture([("4", "text")])
    st.update(m3_event_id="t:1", m3_reasoning=None)
    fake = TwoReplies(entity=None)
    target = make_target(t, state, st, fake)
    after, delta = update_evidence_ledger(t, state, st, event, fake)
    j = judge_stage(t, state, after, st, event, target, delta, fake)
    assert j["labels"][1]["decision"] == "abstain" and j["labels"][1]["abstention_reason"] == "new_candidate"
    after["attempts"][0]["event_id"] = "earlier"
    fake = TwoReplies()
    target = make_target(t, after, st, fake)
    later, diff = update_evidence_ledger(t, after, st, event, fake)
    j = judge_stage(t, after, later, st, event, target, diff, fake)
    assert j["price_label"] == "R2b" and j["labels"][1]["decision"] == "negative"
