import pytest

from snippet import hits, stability, select_ids, passage_key
from snippet_pilot import LocalJudge, account, classify, support_schema, target_schema, validate_response


def test_snippets_preserve_agent_text_and_hash_only_normalized_content():
    row = hits('[{"docid":"27","snippet":"Ａbc\\t FOX"}]')[0]
    assert row == ("27", "Ａbc\t FOX")
    assert passage_key("3", *row) == passage_key("3", "27", "abc fox")
    assert passage_key("4", *row) != passage_key("3", *row)
    assert stability({("1", "27"): {"a", "b"}, ("2", "27"): {"b"}})["multiple"] == 1
    assert select_ids(["8", "7", "6"], 2) == select_ids(["6", "7", "8"], 2)


def event(eid, round_id, ids=(), query="red fox", visible=True):
    return {"id": eid, "round": round_id, "passages": list(ids), "query": query, "visible": visible}


def test_accounting_is_round_causal_and_distinguishes_passage_repetition():
    events = [event("e1", 1, ["p1"]), event("e2", 1, ["p1"]),
              event("e3", 2, ["p1"]), event("e4", 2, ["p2"]),
              event("e5", 3, ["p1", "p2"]), event("e6", 4, ["p3"], visible=False),
              event("e7", 5, ["p0", "p1"])]
    data = account(events, {"p1": {"C1"}, "p2": {"C1"}, "p3": {"C2"}, "p0": None},
                   {"C1": ["red fox"], "C2": ["blue fox"]})
    assert data["first"] == {"C1": 1}
    tagged = {row["id"]: row for row in data["events"]}
    assert tagged["e1"]["a"] is None and tagged["e2"]["confirmed"] == []
    assert tagged["e3"]["a"] == "same"
    assert tagged["e4"]["a"] == "different"
    assert tagged["e5"]["a"] == "same"
    assert tagged["e7"]["a"] is None and tagged["e7"]["a_incomplete"]
    assert tagged["e3"]["keyword"] == "r1" and not tagged["e1"]["keyword"]


def test_target_comparison_handles_empty_unknown_and_pending():
    assert classify({"C1"}, [], "pending") == (False, False)
    assert classify({"C1"}, ["C1"], "pending") == (True, True)
    assert classify({"C1"}, ["C1"], "neither") == (True, False)
    assert classify({"C1"}, ["C2"], "r1") == (False, True)
    assert classify({"C1"}, None, "pending") == (None, False)


def test_semantic_response_schema_uses_question_enum_and_reason_first():
    item = support_schema(["C1"])["properties"]["supports"]["items"]
    assert list(item["properties"]) == ["reason", "constraint_id"]
    assert item["properties"]["constraint_id"]["enum"] == ["C1"]
    assert target_schema(["C1"])["properties"]["targets"]["items"]["enum"] == ["C1"]


def test_response_validation_rejects_unlisted_constraints_and_nonlocal_model(tmp_path):
    with pytest.raises(ValueError):
        validate_response("targets", {"reason": "fixture", "targets": ["C9"]}, {"C1"})
    with pytest.raises(ValueError):
        LocalJudge({"endpoint": "http://example.test:8000/v1"}, tmp_path, {})
    assert validate_response("supports", {"supports": [{"reason": "fixture", "constraint_id": "C1"}]}, {"C1"}) == ["C1"]
