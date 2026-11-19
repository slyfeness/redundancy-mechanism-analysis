from argparse import Namespace
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from ledger_grpo.ledgercredit.__main__ import ledger_pass
from ledger_grpo.ledgercredit.conditions import freeze, indexed_evidence, resolve_evidence
from ledger_grpo.ledgercredit.evidence_judge import citations, judge_payload, request_once, settle
from ledger_grpo.ledgercredit.ledger import build_ledger, dry_run
from ledger_grpo.ledgercredit.stages import parse_stages, tool_event
from ledger_grpo.ledgercredit.validate import validate_ledger, validate_stages


THINK_END = 248069
CALL_START = 248058
CALL_END = 248059


def call(cid, query="what"):
    return {"id": cid, "function": {"name": "search", "arguments": '{"query":"'+query+'"}'}}


def event(cid, index, text, **extra):
    return {"event_id": cid, "round_id": index, "tool_call_id": cid, "tool_name": "search",
            "dispatch_order": int(cid[1:]), "exact_arguments": call(cid)["function"]["arguments"],
            "exact_result": text, **extra}


def row(index, prompt, tokens, calls=(), *, content="", finish="stop"):
    msg = {"content": content, "tool_calls": list(calls)}
    raw = {"prompt_token_ids": prompt, "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(tokens)},
           "choices": [{"token_ids": tokens, "finish_reason": finish, "message": msg,
                        "logprobs": {"content": [{"logprob": -.2}] * len(tokens)}}]}
    return {"round_id": index, "response_received": True, "raw_response": raw,
            "token_accounting": {"exact_prompt_token_ids_equal": True,
                                 "prompt_token_ids": prompt, "completion_token_ids": tokens},
            "actor_visible_messages": [], "tool_calls": list(calls)}


class StageTest(unittest.TestCase):
    def test_parallel_shared_span_and_native_gap(self):
        c1, c2 = call("c1"), call("c2")
        tokens = [11, THINK_END, CALL_START, 12, CALL_END, CALL_START, 13, CALL_END]
        a = row(1, [1], tokens, [c1, c2])
        b = row(2, [1] + tokens + [20, 91, 21, 20, 92, 21], [14, THINK_END, 15], content="Synthetic final")
        events = [event("c1", 1, "[]"), event("c2", 1, "[]")]
        b["actor_visible_messages"] = [{"role": "tool", "tool_call_id": e["tool_call_id"],
                                        "content": e["exact_result"]} for e in events]
        parsed = parse_stages("q", "t", [a, b], events, count_tokens=lambda _: 7,
                              observation_markers=(20, 21), terminal_status="MODEL_FINAL_STOP")
        stages = parsed["stages"]
        self.assertEqual([s["unit_type"] for s in stages], ["tool_stage", "final"])
        self.assertEqual([s["generated_tokens"] for s in stages], [8, 3])
        self.assertEqual(stages[0]["think_range"], [[0, 2]])
        self.assertEqual(stages[0]["call_range"], [[2, 5], [5, 8]])
        self.assertEqual(parsed["stage_ids"][0]["stage_ids"], [1]*8 + [-1]*6 + [2]*3)
        self.assertEqual([e["obs_tokens"] for e in stages[0]["tool_events"]], [1, 1])
        self.assertEqual(validate_stages(parsed), {"native_action_tokens": 11, "spans": 1})

    def test_serial_call_across_native_span_boundary(self):
        selected = call("c1")
        tokens = [7, THINK_END, CALL_START, 8, CALL_END]
        a = row(1, [1], tokens, [selected])
        b = row(2, [99, 20, 13, 14, 21], [THINK_END, 42], content="Synthetic result")
        events = [event("c1", 1, '[{"docid":"invented-doc"}]')]
        b["actor_visible_messages"] = [{"role": "tool", "tool_call_id": "c1",
                                        "content": events[0]["exact_result"]}]
        parsed = parse_stages("q", "t", [a, b], events, count_tokens=len, observation_markers=(20, 21))
        self.assertEqual(validate_stages(parsed), {"native_action_tokens": 7, "spans": 2})
        self.assertEqual([r["stage_ids"] for r in parsed["stage_ids"]], [[1] * 5, [2] * 2])
        item = parsed["stages"][0]["tool_events"][0]
        self.assertEqual(item["returned_docids"], [{"docid": "invented-doc", "rank": 1}])
        self.assertEqual(item["obs_tokens"], 2)

    def test_model_stop_can_contain_tool_like_reasoning(self):
        a = row(1, [1], [11, CALL_START, 44, CALL_END])
        a["raw_response"]["choices"][0]["message"]["reasoning"] = "Synthetic reasoning only"
        a["stop_classification"] = "EMPTY_MODEL_STOP"
        parsed = parse_stages("q", "t", [a], [], count_tokens=len)
        self.assertEqual(parsed["stages"][0]["unit_type"], "empty")
        self.assertEqual(parsed["stages"][0]["tool_events"], [])
        self.assertEqual(parsed["stages"][0]["think_range"], [[0, 4]])
        self.assertEqual(parsed["stages"][0]["answer_range"], [])
        self.assertEqual(validate_stages(parsed)["native_action_tokens"], 4)

    def test_reserved_markers_in_final_text_preserve_native_targets(self):
        a = row(1, [1], [11, THINK_END, 44, THINK_END, 19], content="Synthetic final")
        parsed = parse_stages("q", "t", [a], [], count_tokens=len, terminal_status="MODEL_FINAL_STOP")
        final = parsed["stages"][0]
        self.assertEqual(final["think_range"], [[0, 2]])
        self.assertEqual(final["answer_range"], [[2, 5]])
        self.assertEqual(validate_stages(parsed)["native_action_tokens"], 5)

    def test_unfinished_empty_and_incomplete_call(self):
        a = row(1, [1], [12, 13], finish="length")
        self.assertEqual(parse_stages("q","t",[a],[],count_tokens=len)["stages"][0]["unit_type"],"unfinished")
        b = row(1, [1], [])
        self.assertEqual(parse_stages("q","t",[b],[],count_tokens=len)["stages"][0]["unit_type"],"empty")
        c = row(1, [1], [THINK_END,CALL_START,13], finish="length")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parse_stages("q","t",[c],[],count_tokens=len)

    def test_timeout_and_unfed_return_at_ceiling(self):
        c = call("c1")
        rows = [row(20,[1],[THINK_END,CALL_START,15,CALL_END],[c])]
        events = [event("c1",20,"tool request timed out",status="timeout")]
        stage = parse_stages("q","t",rows,events,count_tokens=lambda _:4)["stages"][0]
        self.assertEqual(stage["unit_type"],"tool_stage")
        self.assertEqual(stage["tool_events"][0]["status"],"timeout")
        self.assertEqual(stage["tool_events"][0]["obs_tokens_source"],"estimated")
        self.assertEqual(citations([stage]), [])


def stage(i,text,visible=True):
    return {"unit_id":i,"generated_tokens":2,"tool_events":[
        {"event_id":f"c{i}","visible_to_actor":visible,"fed_to_model":visible,
         "return_text":json.dumps([{"docid":"d","snippet":text}]),"status":"ok",
         "tool":"search","query_norm":"example","obs_tokens":1,"return_sha256":text,
         "returned_docids":[{"docid":"d","rank":1}],"opened_docid":None,"open_offset":None}]}


class EvidenceAndLedgerTest(unittest.TestCase):
    def setUp(self):
        self.claim = {"id":"a","text":"Two dates jointly establish the result.","support_rule":"Both dates.",
                      "evidence":[{"docid":"d","quote":"Second date."}]}

    def test_partial_then_joint_support_and_no_future_or_duplicate_credit(self):
        stages = [stage(1,"First date."),stage(2,"Second date."),stage(3,"Second date.")]
        verdict = {"id":"a","status":"supported","citation_id":2,"quote":"SECOND   DATE.",
                   "reason":"The two dates are explicit.",
                   "prior_partial":[{"citation_id":1,"quote":"First date."}]}
        results, _ = settle([self.claim],citations(stages),[verdict])
        states = build_ledger(stages,[self.claim],results)
        self.assertEqual([s["C_new"] for s in states],[[],["a"],[]])
        self.assertEqual([s["z_pre"] for s in states],[0,0,1])
        self.assertEqual(states[0]["L_pre"]["conditions"]["a"]["status"],"unknown")
        self.assertEqual(states[1]["L_pre"]["conditions"]["a"]["status"],"partial")
        self.assertEqual(states[1]["L_post"],states[2]["L_pre"])
        self.assertTrue(states[2]["strict_repeat"])
        self.assertEqual(states[0]["L_pre"]["evidence"], {})

    def test_only_visible_and_quote_must_match_its_citation(self):
        refs = citations([stage(1,"First date."),stage(2,"Second date.",False)])
        wrong = {"id":"a","status":"supported","citation_id":1,"quote":"Second date.","reason":"Assertion."}
        results, audit = settle([self.claim],refs,[wrong])
        self.assertEqual(results[0]["status"],"unknown")
        self.assertFalse(audit[0]["quote_passed"])
        self.assertEqual(len(refs),1)

    def test_single_local_request_and_no_unit_ids_in_payload(self):
        refs = citations([stage(1, "First date."), stage(2, "Not observed.", False)])
        raw = {"choices": [{"finish_reason": "stop", "message": {"content": '{"verdicts":[]}'}}]}
        with patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(json.dumps(raw).encode())) as open_:
            result, captured, error = request_once("http://127.0.0.1:2048/v1", "local", "prompt",
                                                   judge_payload([self.claim], refs))
        self.assertEqual((result, captured, error), ({"verdicts": []}, raw, None))
        open_.assert_called_once()
        request = open_.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:2048/v1/chat/completions")
        payload = json.loads(json.loads(request.data)["messages"][1]["content"])
        self.assertEqual(payload["citations"], [{"citation_id": 1, "text": "First date."}])
        self.assertNotIn("evidence", payload["claims"][0])

    def test_indexed_sources_yield_only_original_contiguous_quotes(self):
        text = " ".join(f"word{n}" for n in range(100)) + " A rare synthetic attribute appears."
        documents = {"d": text}
        payload, available = indexed_evidence("Where is the rare attribute?", [], documents,
                                              count_tokens=lambda value: len(value.split()), budget=65)
        self.assertLess(len(payload["evidence_excerpts"]), available)
        quote = payload["evidence_excerpts"][0]
        self.assertIn("rare synthetic attribute", quote["text"])
        self.assertLessEqual(len(quote["text"].split()), 40)
        claims = {"answer_relation": "Find an attribute.", "conditions": [
            {**self.claim, "id": 1, "evidence": [{"quote_id": quote["quote_id"]}]},
            {**self.claim, "id": 2, "text": "Another synthetic claim.", "evidence": [{"quote_id": 999}]}]}
        resolved = resolve_evidence(claims, payload["evidence_excerpts"])
        frozen, audit = freeze("synthetic", resolved, documents, revision="v2")
        self.assertEqual(len(frozen["conditions"]), 1)
        self.assertEqual(frozen["conditions"][0]["id"], "1")
        self.assertEqual(frozen["conditions"][0]["evidence"], [{"docid": "d", "quote": quote["text"]}])
        self.assertEqual(audit["rejected"], [{"position": 1, "reason": "invalid_evidence_quote"}])

    def test_freeze_validates_quote_before_hashing(self):
        proposals = {"answer_relation": "Resolve an invented attribute.",
                     "conditions": [self.claim, {**self.claim, "id": "b", "text": "Fabricated assertion.",
                                                  "evidence": [{"docid": "d", "quote": "Fake quote."}]}]}
        document = {"d": "SECOND   date."}
        frozen, audit = freeze("synthetic", proposals, document, revision="v1")
        self.assertEqual(frozen["conditions"], [self.claim])
        self.assertEqual(audit["rejected"], [{"position": 1, "reason": "invalid_evidence_quote"}])
        self.assertEqual(freeze("synthetic", proposals, document, revision="v1")[0], frozen)
        self.assertNotEqual(freeze("synthetic", proposals, document, revision="v2")[0]["content_sha256"],
                            frozen["content_sha256"])

    def test_private_archive_replay_uses_frozen_receipts_without_new_call(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            m1, archive, prepared, output = (folder / name for name in ("m1", "archive", "prepared", "output"))
            for sub in (m1, archive, prepared):
                sub.mkdir()

            def save(path, value):
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")

            label = {"id": "q", "question": "Synthesized prompt", "answers": ["Synthesized answer"],
                     "evidence_docs": ["d"], "gold_docs": ["d"]}
            documents = {"d": "Second date."}
            outcome = {"trajectory_id": "t", "question_id": "q", "correct": True, "submitted": True,
                       "terminal_status": "MODEL_FINAL_STOP"}
            recorded_stage = {**stage(1, "Second date."), "trajectory_id": "t", "question_id": "q"}
            save(prepared / "evidence_docs.json", documents)
            save(folder / "task_manifest.json", {"tasks": [{"query_id": "q"}]})
            save(m1 / "stages.jsonl", recorded_stage)
            save(m1 / "trajectory_results.jsonl", outcome)
            (m1 / "rollouts_ref.jsonl").touch()
            frozen, _ = freeze("q", {"answer_relation": "Find a fact", "conditions": [self.claim]},
                               documents, revision="v1")
            save(archive / "conditions.jsonl", frozen)
            for name in ("CONDITIONS_SUMMARY.json", "condition_extraction_records.jsonl",
                         "outcome_recheck_records.jsonl"):
                (archive / name).touch()
            save(archive / "M2_SUMMARY.json", {"supplemental_outcome_calls": 0})
            save(archive / "trajectory_results.jsonl", outcome)
            verdict = {"id": "a", "status": "supported", "citation_id": 1,
                       "quote": "Second date.", "reason": "Synthetic proof."}
            save(archive / "judge_records.jsonl", {**outcome, "model": "local", "model_revision": "rev",
                 "prompt_version": "ledgercredit-c3-v1", "conditions_sha256": frozen["content_sha256"],
                 "citation_units": {"1": 1}, "error": None, "raw_output": {
                     "choices": [{"message": {"content": json.dumps({"verdicts": [verdict]})}}]}})
            args = Namespace(selection=folder, prepared=prepared, output=output, m1=m1, workers=1,
                             reuse_results=archive, conditions_version="v1", model="local", model_revision="rev")
            cli = "ledger_grpo.ledgercredit.__main__"
            with patch(f"{cli}.selection", return_value=([label], {"q"})), patch(f"{cli}.model_call") as call_:
                ledger_pass(args)
            call_.assert_not_called()
            result = json.loads((output / "M2_SUMMARY.json").read_text(encoding="utf-8"))
            self.assertEqual((result["replayed_judge_receipts"], result["both"], result["dry_run_missing"]),
                             (1, 1, 0))
            packet = json.loads((output / "PRIVATE_REVIEW_PACKET.json").read_text(encoding="utf-8"))
            self.assertEqual(packet["supported"][0]["judge_verdict"], verdict)
            computed = json.loads((output / "ledger_states.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(validate_ledger([recorded_stage], [computed],
                                             expected_rho={"q": 1}, cost_median=3)["validated_units"], 1)
            computed["L_pre"]["visibility"] = [99]
            with self.assertRaisesRegex(ValueError, "future information"):
                validate_ledger([recorded_stage], [computed], expected_rho={"q": 1}, cost_median=3)

    def test_repeat_within_shared_decision_does_not_leak_into_pre_state(self):
        shared = stage(1, "Some return.")
        parallel = stage(2, "Some return.")
        shared["tool_events"].extend(parallel["tool_events"])
        result = build_ledger([shared], [], [])[0]
        self.assertEqual(result["L_pre"]["attempts"], [])
        self.assertEqual([row["new_docids"] for row in result["L_post"]["attempts"]], [1, 0])
        self.assertEqual([row["strict_repeat"] for row in result["L_post"]["attempts"]], [False, True])
        self.assertTrue(result["strict_repeat"])

    def test_utility_penalizes_only_exact_same_return(self):
        stages = [stage(1, "First."), stage(2, "Different."), stage(3, "Different.")]
        states = build_ledger(stages, [], [])
        self.assertEqual([row["strict_repeat"] for row in states], [False, False, True])
        self.assertEqual([row["u"] for row in dry_run(states, .5, scale=1)], [0, 0, -.2])


def search(unit, fed, snippet="A synthetic fact appears."):
    raw = {"event_id": f"e{unit}", "tool_name": "search", "exact_arguments": '{"query":"synthetic"}',
           "exact_result": json.dumps([{"docid": "1", "score": 2.5, "snippet": snippet}])}
    return {"unit_id": unit, "generated_tokens": 8, "tool_events": [tool_event(raw, 5, fed)]}


def decision(support=None, partial=None):
    return {"id": "a", "first_supported": support, "first_partial": partial}


class SupplementTest(unittest.TestCase):
    def test_unfed_quoted_evidence_never_settles_but_cost_is_counted(self):
        stage = search(1, False)
        event = stage["tool_events"][0]
        self.assertIs(event["fed_to_model"], False)
        self.assertEqual(citations([stage]), [])
        state = build_ledger([stage], [{"id": "a"}], [decision(1)], evidence_docs=["1"])[0]
        self.assertEqual(state["C_new"], [])
        self.assertEqual(state["L_post"]["evidence"], {})
        self.assertEqual(state["unit_cost"], 13)
        self.assertEqual(state["unfed_return_tokens"], 5)

    def test_return_not_fed_is_neither_target_nor_source_for_repetition(self):
        stages = [search(1, False), search(2, True), search(3, False), search(4, True)]
        states = build_ledger(stages, [{"id": "a"}], [decision(2)], evidence_docs=["1"])
        self.assertEqual([s["strict_repeat"] for s in states], [False, False, False, True])
        self.assertEqual([s["z_pre"] for s in states], [0, 0, 1, 1])
        self.assertEqual([s["z_pre_docid"] for s in states], [0, 0, 1, 1])
        self.assertEqual(states[2]["L_pre"], states[1]["L_post"])

    def test_citations_only_contain_visible_snippet_strings(self):
        refs = citations([search(1, True), search(2, False, "Never entered context.")])
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["text"], "A synthetic fact appears.")

    def test_final_unit_requires_final_stop_and_nonempty_answer(self):
        tokens = [8]
        message = {"content": "Synthetic candidate."}
        row = {"round_id": 1, "response_received": True, "actor_visible_messages": [],
               "raw_response": {"prompt_token_ids": [1], "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                                "choices": [{"token_ids": tokens, "message": message, "finish_reason": "stop",
                                             "logprobs": {"content": [{"logprob": -.1}]}}]},
               "token_accounting": {"exact_prompt_token_ids_equal": True,
                                    "prompt_token_ids": [1], "completion_token_ids": tokens}}
        for status in ("CONTEXT_LIMIT_STOP", "GENERATION_LENGTH_STOP", "SAFETY_CEILING_STOP", "EMPTY_MODEL_STOP"):
            with self.subTest(status=status):
                stage = parse_stages("q", "t", [row], [], count_tokens=len, terminal_status=status)
                self.assertNotEqual(stage["stages"][0]["unit_type"], "final")
        stage = parse_stages("q", "t", [row], [], count_tokens=len, terminal_status="MODEL_FINAL_STOP")
        self.assertEqual(stage["stages"][0]["unit_type"], "final")
        message["content"] = "  "
        stage = parse_stages("q", "t", [row], [], count_tokens=len, terminal_status="MODEL_FINAL_STOP")
        self.assertNotEqual(stage["stages"][0]["unit_type"], "final")


if __name__ == "__main__":
    unittest.main()
