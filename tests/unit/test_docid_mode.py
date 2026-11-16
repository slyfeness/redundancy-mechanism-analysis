import json

from redundancy_judge.docid import bind_labels, passages_from_return
from redundancy_judge.init_task_ledger import initial_ledger
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.resolve_action_target import resolve_action_target
from redundancy_judge.summarize_trajectory import summarize_trajectory
from redundancy_judge.update_evidence_ledger import update_evidence_ledger


class NoModel:
    def ask(self, *_):
        raise AssertionError("model called in the deterministic baseline")


def fixture(docs, query="Ａ  Search"):
    action = {"tool_name": "search-server-search", "arguments": {"query": query},
              "deterministic": True, "environment": "frozen"}
    stage = {"stage_type": "tool", "stage_id": "s", "parse_status": "ok", "action": action,
             "visible_return_ids": ["earlier"], "charge_token_spans": [[0, 1]], "cost": {}}
    event = {"event_id": "current", "document_ids": [d for d, _ in docs], "visible_next": True,
             "return_text": json.dumps([{"docid": d, "snippet": p} for d, p in docs]), "return_time": "t"}
    task = bind_labels({"constraints": [], "uncertain": False}, {"evidence": ["4", "6"], "gold": ["4"]})
    state = initial_ledger(task)
    return task, state, stage, event


def decide(task, before, stage, event):
    target = {"intent": "explore", "skip_reason": "no_prior_passages"}
    after, delta = update_evidence_ledger(task, before, stage, event, NoModel())
    j = judge_stage(task, before, after, stage, event, target, delta, NoModel())
    return {row["label"]: row for row in j["labels"]}, j, after, delta


def test_docids_preserve_return_order():
    assert list(passages_from_return('[{"docid":9,"snippet":"z"},{"docid":"2","snippet":"y"}]')) == ["9", "2"]


def test_docid_missing_labels_yield_missing_grounding():
    t = bind_labels({"constraints": [], "uncertain": False}, None)
    assert t["evidence_labels_missing"]
    r = summarize_trajectory({}, t, initial_ledger(t), [], [])
    assert r["g"] is None and r["grounding_issue"] == "evidence_labels_missing"


def test_docid_ledger_tracks_gain_and_prefix_passages_and_omits_model():
    t, state, st, event = fixture([("4", "evidence"), ("5", "other")])
    labels, j, after, delta = decide(t, state, st, event)
    assert delta["new_evidence"] == ["4"] and delta["effective_gain"]
    assert after["support"] == {} and after["evidence_passages"] == {"4": "evidence"}
    assert state.get("evidence_passages", {}) == {}
    assert labels["R1"]["abstention_reason"] == "no_prior_passages"
    assert j["diagnostics"]["result_label"] == "effective"
    r = summarize_trajectory({}, t, after, [], [])
    assert r["g"] == .5 and r["g_definition"] == "evidence_coverage"


def test_docid_normalized_repeats_need_same_set_and_protections():
    t, before, st, event = fixture([("4", "x"), ("8", "y")])
    _, _, before, _ = decide(t, before, st, event)
    before["attempts"][0]["event_id"] = "earlier"
    _, _, st, event = fixture([("8", "y"), ("4", "x")], query="a search")
    labels, j, _, _ = decide(t, before, st, event)
    assert labels["R2b"]["decision"] == "positive" and j["price_label"] == "R2b"
    assert j["diagnostics"]["result_label"] == "repeat_query"
    st["visible_return_ids"] = []
    labels, j, _, _ = decide(t, before, st, event)
    assert labels["R2b"]["decision"] == "negative" and "restore_invisible_evidence" in j["protections"]


def test_docid_r2a_subtypes_and_protection_from_new_evidence():
    t, before, st, event = fixture([("4", "x"), ("8", "y")])
    _, _, before, _ = decide(t, before, st, event)
    for docs, subtype, decision in [
        ([("4", "x")], "zero_new_info", "positive"),
        ([("4", "x"), ("5", "new non-evidence")], "repeated_evidence", "positive"),
        ([("4", "x"), ("6", "new evidence")], None, "negative"),
    ]:
        _, _, st, event = fixture(docs, query="different")
        labels, j, _, _ = decide(t, before, st, event)
        assert labels["R2a"]["decision"] == decision
        assert not labels["R2a"]["reward_eligible"]
        assert j["diagnostics"]["r2a_subtype"] == subtype
