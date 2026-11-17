import importlib
import json
from hashlib import sha256
from pathlib import Path
import sys

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "src"))
    return importlib.import_module("coexist_labels")


class ByteTokenizer:
    revision = "fixture"
    sha256 = "e" * 64

    @staticmethod
    def native_bytes(ids):
        return bytes(ids), {i: i for i in range(len(ids) + 1)}


@pytest.fixture
def original(tmp_path):
    question = "Who?"
    request = [{"role": "user", "content": question}]
    prefix = "PROMPT"
    rounds, events, expected_spans = [], [], []
    for index, query in enumerate((" SAME ", "same", "other"), 1):
        name, call_id = "search-server-search", f"call{index}"
        args = json.dumps({"query": query})
        call = {"id": call_id, "function": {"name": name, "arguments": args}}
        returned = '[{"docid":"4","snippet":"earlier"}]' if index < 3 else '[{"docid":"8","snippet":"current"}]'
        # Use a common native envelope with query whitespace outside the parameter value.
        envelope = f"<tool_call><function={name}><parameter=query>\n{query.strip()}\n</parameter></function></tool_call>"
        expected_spans.append([len(prefix)-6+3, len(prefix)-6+3+len(envelope)])
        complete = "ABC" + envelope + "Z"
        rounds.append(recorded_round(index, prefix, complete, request, [call],
                                     "discard me " + "a" * 1510 + " confirm"))
        events.append({"round_id": index, "batch_id": index, "event_id": index, "tool_call_id": call_id,
                       "tool_name": name, "tool_ordinal": 1, "dispatch_order": index, "return_order": index,
                       "exact_arguments": args, "exact_result": returned, "dispatch_utc": f"dispatch{index}",
                       "return_utc": f"return{index}", "raw_mcp_response": {"isError": False}})
        request = [*request, {"role": "tool", "tool_call_id": call_id, "content": returned}]
        prefix += complete + f"<tool_response>\n{returned}\n</tool_response>"
    rounds.append(recorded_round(4, prefix, "answer", request, []))
    raw = {"metadata": {"task": {"query_id": "1", "run_id": "fixture-run",
                                "question_sha256": sha256(question.encode()).hexdigest()},
                        "terminal_status": "MODEL_FINAL_STOP", "tokenizer_revision": "fixture"},
           "rounds": rounds, "tool_events": events}
    source = tmp_path / "trajectory.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    snapshot = tmp_path / "evidence.jsonl"
    snapshot.write_text('{"question_id":"1","evidence":["4","8","16"],"gold":["4"]}\n', encoding="utf-8")
    return source, snapshot, expected_spans


def recorded_round(index, prompt, completion, messages, calls, reasoning=None):
    prompt_ids, completion_ids = list(prompt.encode()), list(completion.encode())
    return {"round_id": index, "batch_id": index, "actor_visible_messages": messages,
            "request_sent": True, "response_received": True, "completion_tokens": len(completion_ids),
            "tool_calls": calls, "content": None if calls else completion, "reasoning_content": reasoning,
            "token_accounting": {"prompt_token_ids": prompt_ids, "completion_token_ids": completion_ids,
                                 "exact_prompt_token_ids_equal": True},
            "raw_response": {"prompt_token_ids": prompt_ids, "choices": [{"token_ids": completion_ids,
                "logprobs": {"content": [{"logprob": -1.} for _ in completion_ids]}}]}}


def project(module, original):
    source, snapshot, _ = original
    return module.label_trajectory(source, {"label": "C", "source": "independent"},
                                   module.load_evidence_snapshot(snapshot), ByteTokenizer(),
                                   environment={"id": "fixture-corpus", "deterministic_tools": ["search-server-search"]})


def test_scores_docid_repeat_on_exact_masked_native_tokens(module, original):
    labeled = project(module, original)
    row, causal = labeled["score_row"], labeled["causal"]
    start, stop = original[2][1]
    assert (row["outcome"], row["grounding"], row["recording_complete"]) == (1, 2 / 3, True)
    assert row["response_mask"][start - 4 : start - 3] == [0]
    assert row["response_mask"][start - 3 : stop + 1] == [1] * (stop - start + 4)
    assert row["response_mask"][stop + 1 : stop + 2] == [0]
    priced, = [e for e in row["events"] if e["label"]]
    assert priced["event_id"] == "fixture-run:2"
    assert priced["event_tokens"] == [start, stop]
    assert priced["event_cost"] == {"generated_tokens": stop-start,
                                   "returned_tokens": len('[{"docid":"4","snippet":"earlier"}]'), "tool_calls": 1}
    assert [e["result_label"] for e in causal["events"]] == ["effective", "repeat_query", "effective"]
    assert causal["documents"] == ["4", "8"]


def test_m3_uses_only_visible_prefix_and_keeps_score_row_unchanged(module, original, tmp_path):
    from redundancy_judge.adapters.model import ModelJudge

    class ReplaySpeaker(ModelJudge):
        def ask_m3(self, step, payload, shape, event_id):
            self.calls.append((step, payload))
            if step == "intent":
                return {"seeking": "fact", "entity": "name", "attribute": "fact"}
            return {"reason": "known", "already_stated": True, "passage_ids": ["P4"]}

    labeled = project(module, original)
    before = json.dumps(labeled["score_row"])
    judge = ReplaySpeaker({"url": "http://127.0.0.1:1/v1", "model": "fixture"}, tmp_path,
                          tmp_path / "model_cache", {"policy_snapshot_sha256": "b" * 64})
    judge.calls = []
    path = tmp_path / "r1.json"
    receipt = module.record_m3(labeled, judge, policy_snapshot_sha256="b" * 64, output=path)
    assert json.loads(path.read_text(encoding="utf-8")) == receipt
    assert receipt["policy_snapshot_sha256"] == "b" * 64
    assert [step for step, _ in judge.calls] == ["intent", "intent", "verification", "intent", "verification"]
    assert judge.calls[-1][1]["previously_seen_passages"] == [{"id": "P4", "text": "earlier"}]
    assert judge.calls[-2][1]["agent_reasoning_before_search"] == "a" * 1492 + " confirm"
    assert all(event["r1"]["reward_eligible"] is False for event in receipt["events"])
    assert json.dumps(labeled["score_row"]) == before


def test_qrels_projection_binds_frozen_pilot_question_and_decodes_official_ids(module):
    from base64 import b64encode

    canary = 'CANARY = "frozen"'
    key = sha256(b"frozen").digest()

    def hide(text):
        return b64encode(bytes(b ^ key[i % len(key)] for i, b in enumerate(text.encode()))).decode()

    plan = {"training_ids": ["1"], "training_rows": [
        {"query_id": "1", "question": "Who?", "question_sha256": sha256(b"Who?").hexdigest()}]}
    row = {"query_id": 1, "query": hide("Who?"),
           "evidence_docs": [{"docid": hide("11")}, {"docid": "4"}, {"docid": "4"}],
           "gold_docs": [{"docid": hide("4")}]}
    decoder = module._official_decoder(canary)
    assert module._project_qrels(plan, [row], {"4", "11"}, decoder) == [
        {"question_id": "1", "evidence": ["4", "11"], "gold": ["4"]}]
    with pytest.raises(ValueError, match="question identity"):
        module._project_qrels(plan, [{**row, "query": hide("different")}], {"4", "11"}, decoder)


def test_compare_frozen_deterministic_labels_reports_event_identity_and_grounding(module, original):
    labeled = project(module, original)
    reference_results = {"fixture-run:1": "effective", "fixture-run:2": "repeat_query",
                         "fixture-run:3": "effective"}
    reference_judgments = {row["event_id"]: row["r2b"] for row in labeled["causal"]["events"]}
    reference_judgments["fixture-run:2"] = {**reference_judgments["fixture-run:2"], "decision": "negative"}
    errors = module._compare_code_labels(labeled, reference_results, reference_judgments, 1.0)
    assert [(row["check"], row["id"]) for row in errors] == [("R2b_187767", "fixture-run:2"),
                                                            ("g_187767", "fixture-run")]


def test_historical_docid_replay_handles_native_ids_without_sampling_logprobs(module, original):
    source, snapshot, _ = original
    raw = json.loads(source.read_text(encoding="utf-8"))
    for row in raw["rounds"]:
        row["raw_response"]["choices"][0]["logprobs"] = None
    source.write_text(json.dumps(raw), encoding="utf-8")
    option = {"environment": {"id": "fixture-corpus", "deterministic_tools": ["search-server-search"]}}
    evidence = module.load_evidence_snapshot(snapshot)
    result = module.replay_historical_trajectory(source, 1, evidence, ByteTokenizer(), **option)
    assert result["causal"]["grounding"] == 2 / 3
    assert result["causal"]["events"][1]["r2b"]["decision"] == "positive"
    assert "score_row" not in result


def test_compare_frozen_docid_state_detects_future_documents_in_prefix(module, original):
    labeled = project(module, original)
    row, = labeled["causal"]["events"][2:]
    snap = {"before": {"documents": ["4", "8"], "evidence_passages": {"4": "earlier"}},
            "after": {"documents": ["4", "8"], "evidence_passages": {"4": "earlier", "8": "current"}},
            "delta": row["ledger_delta"], "visible_before": ["1", "2"],
            "observation_verified_in_next_prompt": True}
    mismatches = module._compare_ledger_event(row, module._frozen_event_state(snap))
    assert mismatches == [{"check": "DocID_187767.docids_before", "id": "fixture-run:3",
                           "expected": ["4", "8"], "observed": ["4"]}]
