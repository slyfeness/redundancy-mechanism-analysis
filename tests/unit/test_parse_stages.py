import hashlib
import json

from redundancy_judge.adapters.trace import NativeByteTokenizer, load_trajectory
from redundancy_judge.parse_stages import parse_stages


def tool_call(call_id, argument):
    return {"id": call_id, "type": "function",
            "function": {"name": "search", "arguments": json.dumps({"query": argument})}}


def native_round(index, *, text="", calls=(), history=(), native=(33, 34), reasoning="思考"):
    history = [{"role": "user", "content": "What is the city?"}, *history]
    return {"round_id": index, "batch_id": f"B{index:03}", "request_sent": True, "response_received": True,
            "content": text, "reasoning_content": reasoning, "tool_calls": list(calls),
            "actor_visible_messages": history, "completion_tokens": len(native),
            "raw_response": {"prompt_token_ids": [10], "choices": [{"message": {
                "content": text, "reasoning_content": reasoning, "tool_calls": list(calls)},
                "token_ids": list(native), "finish_reason": "tool_calls" if calls else "stop"}]},
            "token_accounting": {"completion_token_ids": list(native), "prompt_token_ids": [10],
                                 "exact_prompt_token_ids_equal": True}}


def native_event(call, index, *, round_id=1, ordinal=1, returned=True):
    value = {"round_id": round_id, "batch_id": f"B{round_id:03}", "tool_ordinal": ordinal,
             "tool_name": "search", "tool_call_id": call["id"], "event_id": index, "dispatch_order": index,
             "dispatch_utc": f"dispatch-{index}", "exact_arguments": call["function"]["arguments"]}
    if returned:
        value.update(exact_result='[{"docid":"city","snippet":"Evidence"}]', return_order=index,
                     return_utc=f"return-{index}", raw_mcp_response={"isError": False})
    return value


def visibility(event):
    return {"role": "tool", "tool_call_id": event["tool_call_id"], "content": event["exact_result"]}


def record(tmp_path, rounds, events, stop="MODEL_FINAL_STOP"):
    raw = {"metadata": {"task": {"query_id": "q", "run_id": "q__rep1",
                                "question_sha256": hashlib.sha256(b"What is the city?").hexdigest()},
                        "terminal_status": stop, "model": "model", "model_revision": "rev",
                        "tokenizer_revision": "rev"}, "rounds": rounds, "tool_events": events,
           "unsent_guard_attempts": []}
    path = tmp_path / "trajectory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_trajectory(path, result={"label": "C", "source": "independent"},
                           environment={"id": "fixed", "deterministic_tools": ["search"]})


def test_serial_return_has_one_owner_even_when_visible_in_two_later_prompts(tmp_path):
    call1, call2 = tool_call("c1", "first"), tool_call("c2", "second")
    e1, e2 = native_event(call1, 1), native_event(call2, 2, round_id=2)
    trace = record(tmp_path, [native_round(1, calls=[call1]), native_round(2, calls=[call2], history=[visibility(e1)]),
                             native_round(3, text="Paris", history=[visibility(e1), visibility(e2)])], [e1, e2])
    parsed = parse_stages(trace)
    first, second, final = parsed["stages"]
    assert [first["stage_type"], second["stage_type"], final["stage_type"]] == ["tool", "tool", "final"]
    assert [stage["policy_token_spans"] for stage in parsed["stages"]] == [[[0, 2]], [[2, 4]], [[4, 6]]]
    assert [stage["visible_return_ids"] for stage in parsed["stages"]] == [[], ["1"], ["1", "2"]]
    assert [stage["event_ids"] for stage in parsed["stages"]] == [["1"], ["2"], []]
    assert parsed["tool_events"][0]["return_text"] == e1["exact_result"]
    assert parsed["tool_events"][0]["document_ids"] == ["city"]
    assert first["action"]["deterministic"] is True
    assert final["final_text"] == "Paris"
    assert first["charge_token_spans"] == []
    assert parsed["policy_token_count"] == 6
    assert parsed["token_alignment_status"] == "verified"
    assert parsed["recording_complete"] is True


def test_parallel_calls_have_shared_stage_and_never_get_charge_tokens(tmp_path):
    first, second = tool_call("c1", "first"), tool_call("c2", "second")
    e1, e2 = native_event(first, 1), native_event(second, 2, ordinal=2)
    trace = record(tmp_path, [native_round(1, calls=[first, second]),
                             native_round(2, text="Paris", history=[visibility(e1), visibility(e2)])], [e1, e2])
    parsed = parse_stages(trace)
    stage = parsed["stages"][0]
    assert stage["call_ids"] == ["c1", "c2"]
    assert stage["parallel_group_id"]
    assert stage["charge_token_spans"] == []
    assert stage["action"] is None
    assert [event["parallel_group_id"] for event in parsed["tool_events"]] == [stage["parallel_group_id"]] * 2


def test_unreturned_call_keeps_native_tokens_but_never_fabricates_final(tmp_path):
    call = tool_call("c1", "first")
    trace = record(tmp_path, [native_round(1, calls=[call])], [native_event(call, 1, returned=False)],
                   "SAFETY_CEILING_STOP")
    parsed = parse_stages(trace)
    assert len(parsed["stages"]) == 1
    assert parsed["stages"][0]["parse_status"] == "incomplete"
    assert parsed["tool_events"][0]["return_text"] is None
    assert parsed["stages"][0]["final_text"] is None
    assert parsed["recording_complete"] is False
    assert "missing_return" in [row["code"] for row in parsed["anomalies"]]


def test_missing_native_provenance_has_no_global_policy_spans(tmp_path):
    round1 = native_round(1, text="Paris")
    round1["raw_response"]["choices"][0]["token_ids"] = None
    parsed = parse_stages(record(tmp_path, [round1], []))
    assert parsed["token_alignment_status"] == "unverified"
    assert parsed["policy_token_spans"] == []
    assert parsed["policy_token_count"] is None
    assert parsed["stages"][0]["strategy_text"] == "思考"
    assert parsed["stages"][0]["cost"]["policy_tokens"] == 2


def test_future_prompt_replays_checked_but_future_model_reasoning_is_not_used(tmp_path):
    call = tool_call("c1", "first")
    event = native_event(call, 1)
    first = native_round(1, calls=[call])
    second = native_round(2, text="Paris")
    a = parse_stages(record(tmp_path, [first, second], [event]))
    second["reasoning_content"] = "EXTRA FUTURE CONTENT"
    b = parse_stages(record(tmp_path, [first, second], [event]))
    assert a["stages"][0] == b["stages"][0]
    assert a["tool_events"][0]["return_text"] is None
    assert a["tool_events"][0]["visible_next"] is False
    assert a["tool_events"][0]["return_ref"]["source_pointer"] == "/tool_events/0/exact_result"


def test_frozen_legacy_overlap_requires_source_hash_characters_and_original_ids(tmp_path):
    trace = record(tmp_path, [native_round(1, text="Paris")], [])
    legacy = {"uid": "token15", "rollout_id": "q__rep1", "round_id": 1, "source_sha256": trace["input_sha256"],
              "source_field": "reasoning_content", "start_char": 0, "end_char": 2,
              "sha256": hashlib.sha256("思考".encode()).hexdigest(),
              "native_start_token": 0, "native_end_token": 1, "native_token_ids": [33]}
    parsed = parse_stages(trace, legacy_blocks=[legacy])
    assert parsed["stages"][0]["legacy_mapping"][0]["legacy_block_id"] == "token15"
    assert parsed["stages"][0]["legacy_mapping"][0]["overlap_policy_spans"] == [[0, 1]]
    wrong = parse_stages(trace, legacy_blocks=[{**legacy, "source_sha256": "wrong"}])
    assert wrong["stages"][0]["legacy_mapping"] == []
    assert wrong["stages"][0]["legacy_mapping_status"] == "unavailable"


def test_exact_native_tool_envelope_only_is_chargeable_and_return_cost_is_owned_once(tmp_path):
    call = tool_call("c1", "Paris")
    event = native_event(call, 1)
    completion_pieces = ["Think first.", "<tool_call>", "\n<function=search>\n<parameter=query>\nParis\n"
                         "</parameter>\n</function>\n", "</tool_call>", "<|im_end|>"]
    prompt_pieces = ["<tool_response>\n", event["exact_result"], "\n</tool_response>"]
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer_path.write_text(json.dumps({"decoder": {"type": "ByteLevel"}, "model": {"type": "BPE", "vocab": {}},
        "added_tokens": [{"id": i, "content": value} for i, value in enumerate(completion_pieces + prompt_pieces)]}),
        encoding="utf-8")
    tokenizer = NativeByteTokenizer(tokenizer_path, "rev")
    r1 = native_round(1, calls=[call], native=range(5))
    r2 = native_round(2, text="Paris", history=[visibility(event)], native=[0])
    r2["token_accounting"]["prompt_token_ids"] = r2["raw_response"]["prompt_token_ids"] = [5, 6, 7]
    parsed = parse_stages(record(tmp_path, [r1, r2], [event]), {"tokenizer": tokenizer})
    tool, final = parsed["stages"]
    assert tool["charge_token_spans"] == [[1, 4]]
    assert tool["charge_strategy"] == "native_call_only"
    assert parsed["tool_events"][0]["visibility_basis"] == "native_prompt_verified"
    assert tool["cost"] == {"policy_tokens": 5, "return_tokens": 1, "tool_calls": 1}
    assert final["cost"]["return_tokens"] == 0
    assert final["charge_token_spans"] == []
    r2["token_accounting"]["prompt_token_ids"] = r2["raw_response"]["prompt_token_ids"] = [5, 0, 7]
    tampered = parse_stages(record(tmp_path, [r1, r2], [event]), {"tokenizer": tokenizer})
    assert tampered["stages"][0]["charge_token_spans"] == []
    assert tampered["tool_events"][0]["return_text"] is None


def test_parallel_return_order_is_preserved_without_inventing_serial_substages(tmp_path):
    first, second = tool_call("c1", "first"), tool_call("c2", "second")
    e1, e2 = native_event(first, 1), native_event(second, 2, ordinal=2)
    e1["return_order"], e2["return_order"] = 2, 1
    trace = record(tmp_path, [native_round(1, calls=[first, second]),
                             native_round(2, text="Paris", history=[visibility(e2), visibility(e1)])], [e1, e2])
    parsed = parse_stages(trace)
    assert parsed["stages"][0]["parse_status"] == "ok"
    assert [event["dispatch_order"] for event in parsed["tool_events"]] == [1, 2]
    assert [event["return_order"] for event in parsed["tool_events"]] == [2, 1]
    assert parsed["stages"][0]["event_ids"] == ["1", "2"]


def test_duplicate_round_identity_cannot_duplicate_tool_return_ownership(tmp_path):
    call = tool_call("c1", "city")
    event = native_event(call, 1)
    first, duplicate = native_round(1, calls=[call]), native_round(1, calls=[call])
    parsed = parse_stages(record(tmp_path, [first, duplicate], [event]))
    assert sum(stage["event_ids"].count("1") for stage in parsed["stages"]) == 1
    assert parsed["token_alignment_status"] == "unverified"
    assert "round_order_unverified" in [row["code"] for row in parsed["anomalies"]]


def test_repeated_prompt_marker_cannot_prove_return_position(tmp_path):
    call = tool_call("c1", "city")
    event = native_event(call, 1)
    text = event["exact_result"]
    marker = f"<tool_response>\n{text}\n</tool_response>"
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer_path.write_text(json.dumps({"decoder": {"type": "ByteLevel"}, "model": {"type": "BPE", "vocab": {}},
        "added_tokens": [{"id": 0, "content": marker}]}), encoding="utf-8")
    r2 = native_round(2, text="Paris", history=[visibility(event)])
    r2["token_accounting"]["prompt_token_ids"] = r2["raw_response"]["prompt_token_ids"] = [0, 0]
    parsed = parse_stages(record(tmp_path, [native_round(1, calls=[call]), r2], [event]),
                          {"tokenizer": NativeByteTokenizer(tokenizer_path, "rev")})
    assert parsed["tool_events"][0]["return_tokens"] is None
    assert not parsed["tool_events"][0]["visible_next"]


def test_one_original_token_cannot_be_counted_for_two_returns(tmp_path):
    c1, c2 = tool_call("c1", "first"), tool_call("c2", "second")
    e1, e2 = native_event(c1, 1), native_event(c2, 2, ordinal=2)
    text = e1["exact_result"]
    marker = f"<tool_response>\n{text}\n</tool_response>"
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer_path.write_text(json.dumps({"decoder": {"type": "ByteLevel"}, "model": {"type": "BPE", "vocab": {}},
        "added_tokens": [{"id": 0, "content": marker + marker}]}), encoding="utf-8")
    r2 = native_round(2, text="Paris", history=[visibility(e1), visibility(e2)])
    r2["token_accounting"]["prompt_token_ids"] = r2["raw_response"]["prompt_token_ids"] = [0]
    parsed = parse_stages(record(tmp_path, [native_round(1, calls=[c1, c2]), r2], [e1, e2]),
                          {"tokenizer": NativeByteTokenizer(tokenizer_path, "rev")})
    assert [event["return_tokens"] for event in parsed["tool_events"]] == [None, None]
    assert all(event["visible_next"] for event in parsed["tool_events"])
