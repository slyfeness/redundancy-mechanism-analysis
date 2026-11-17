"""Keep online/offline label checks separate from the timed load."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from redundancy_judge.cli import jsonl, write_jsonl
from redundancy_judge.common import atomic_json


def ask_frozen(url, body):
    request = Request(url + "/v1/chat/completions", data=json.dumps(body, ensure_ascii=False).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    receipt = {"request": body, "raw_response": None, "parsed": None, "failure": None}
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=900) as stream:
            receipt["raw_response"] = stream.read().decode("utf-8")
        packet = json.loads(receipt["raw_response"])
        sentence = packet["choices"][0]
        if packet["model"] != body["model"] or sentence["finish_reason"] != "stop":
            raise ValueError("invalid_model_or_finish")
        receipt["parsed"] = json.loads(sentence["message"]["content"])
    except (HTTPError, URLError, ValueError, TypeError, KeyError, IndexError, TimeoutError) as err:
        receipt["failure"] = type(err).__name__
    return receipt


def missing_entity(value):
    return value is None or isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a", "unknown"}


def verify_m3(archived, judge, prompt_hashes, output):
    samples = jsonl(archived)
    assert len(samples) == 532 and len({row["event_id"] for row in samples}) == 532

    def compare(row):
        first_reference, second_reference = row["first"], row["second"]
        first_request = first_reference["request"]
        messages = first_request["messages"]
        assert len(messages) == 2 and sha256(messages[0]["content"].encode()).hexdigest() == prompt_hashes["m3v3_intent"]
        intent_input = json.loads(messages[1]["content"])
        assert set(intent_input) == {"agent_reasoning_before_search", "current_search_query"}
        assert len(intent_input["agent_reasoning_before_search"] or "") <= 1500
        first = ask_frozen(judge.url, first_request)
        first_value, reference_value = first["parsed"], first_reference["parsed"]
        second = None
        discrepancies = []
        if first_value is None or reference_value is None:
            discrepancies.append({"field": "entity", "reason": "missing_valid_intent_reply"})
        elif first_value["entity"] != reference_value["entity"]:
            discrepancies.append({"field": "entity", "reason": "different_reply_on_identical_archived_input"})
        if second_reference and first_value and not missing_entity(first_value["entity"]):
            request = second_reference["request"]
            second_messages = request["messages"]
            assert sha256(second_messages[0]["content"].encode()).hexdigest() == prompt_hashes["m3v3_verification"]
            prior = json.loads(second_messages[1]["content"])
            assert list(p["id"] for p in prior["previously_seen_passages"]) == row["provided_passage_ids"]
            assert set(prior) == {"seeking", "entity", "attribute", "current_search_query", "previously_seen_passages"}
            payload = {**first_value, "current_search_query": intent_input["current_search_query"],
                       "previously_seen_passages": prior["previously_seen_passages"]}
            assert set(payload) == set(prior)
            second = ask_frozen(judge.url, {**request, "messages": [second_messages[0],
                                   {**second_messages[1], "content": json.dumps(payload, ensure_ascii=False)}]})
            second_value = second["parsed"]
            if second_value is None or second_reference["parsed"] is None:
                discrepancies.append({"field": "already_stated", "reason": "missing_valid_verification_reply"})
            elif second_value["already_stated"] != second_reference["parsed"]["already_stated"]:
                discrepancies.append({"field": "already_stated", "reason": (
                    "changed_intent_in_verification_input" if payload != prior else
                    "different_reply_on_identical_archived_input")})
        elif second_reference:
            discrepancies.append({"field": "already_stated", "reason":
                                  "verification_now_skipped_missing_entity" if first_value else "intent_failed"})
        elif first_value and not missing_entity(first_value["entity"]) and row.get("prior_passage_ids"):
            discrepancies.append({"field": "verification_availability", "reason":
                                  "archived_second_request_absent_no_comparable_payload"})
        return {"event_id": row["event_id"], "first": first, "second": second, "differences": discrepancies}

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(compare, samples))
    write_jsonl(output/"m3-frozen-receipts.jsonl", results)
    summary = {
        "reference_job": 187743, "entity_comparisons": len(samples),
        "entity_agreements": sum(not any(d["field"] == "entity" for d in row["differences"]) for row in results),
        "expected_verification_calls": sum(bool(row["second"]) for row in samples),
        "actual_verification_calls": sum(bool(row["second"]) for row in results),
        "verified_pairs_with_valid_replies": sum(bool(row["second"] and row["second"]["parsed"]) for row in results),
        "already_stated_agreements": sum(bool(row["second"] and row["second"]["parsed"]) and
              not any(d["field"] == "already_stated" for d in row["differences"]) for row in results),
        "mismatches": [{"event_id": row["event_id"], "differences": row["differences"]}
                        for row in results if row["differences"]],
    }
    atomic_json(output/"m3-frozen-comparison.json", summary)
    return summary


def compare_all(config, judge, common, output):
    from coexist_labels import load_evidence_snapshot, validate_frozen_labels

    pure = validate_frozen_labels(Path(config["phase1_manifest"]).parent, Path(config["frozen_result_labels"]),
                                  common["tokenizer"], load_evidence_snapshot(config["frozen_labels"]))
    atomic_json(output/"pure-frozen-comparison.json", pure)
    m3 = verify_m3(config["m3_exam_calls"], judge, common["labeler_versions"]["prompt_hashes"], output)
    return {"pure": pure, "m3": {key: value for key, value in m3.items() if key != "mismatches"}}
