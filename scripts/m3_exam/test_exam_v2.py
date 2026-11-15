from run_exam_v2 import run_event, skip_second, verify_r1


def test_skips_lookup_with_explicit_reason():
    named = {"seeking": "which date", "entity": "X", "attribute": "date"}
    assert skip_second(None, ["P1"]) == "first_call_failed"
    assert skip_second({**named, "entity": None}, []) == "new_candidate"
    assert skip_second(named, []) == "no_prior_passages"
    assert skip_second(named, ["P1"]) is None


def test_r1_requires_true_and_all_valid_ids():
    assert verify_r1(True, ["P1"], {"P1"}) == (True, False)
    assert verify_r1(True, [], {"P1"}) == (False, True)
    assert verify_r1(True, ["P1", "P2"], {"P1"}) == (False, True)
    assert verify_r1(False, ["P1"], {"P1"}) == (False, True)
    assert verify_r1(False, [], {"P1"}) == (False, False)


def test_two_messages_exclude_question_and_use_first_parsed_values():
    calls = []
    intent = {"seeking": "search intent", "entity": "X", "attribute": "date"}

    def fake(step, payload, schema):
        calls.append((step, payload, schema))
        parsed = intent if step == "intent" else {"reason": "in text", "already_stated": True, "passage_ids": ["P9"]}
        return {"parsed": parsed, "failure": None}

    row = run_event({"event_id": "s:1", "query": "X date", "reasoning": "x"*1600,
                     "question": "must not be sent", "passages": [{"id": "P9", "text": "excerpt"}]}, fake)
    assert calls[0][1] == {"agent_reasoning_before_search": "x"*1500, "current_search_query": "X date"}
    assert calls[1][1] == {**intent, "current_search_query": "X date",
                           "previously_seen_passages": [{"id": "P9", "text": "excerpt"}]}
    assert calls[1][2]["properties"]["passage_ids"]["items"]["enum"] == ["P9"]
    assert row["new_r1"] and row["skip_reason"] is None


def test_first_failure_never_invokes_second():
    def fake(step, payload, schema):
        assert step == "intent"
        return {"parsed": None, "failure": "non_stop"}

    row = run_event({"event_id": "s:2", "query": "q", "reasoning": "", "passages": []}, fake)
    assert row["skip_reason"] == "first_call_failed"
    assert row["second"] is None and not row["new_r1"]
