from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from chain_extractor_v2 import audit_quote, judge
from chain_extractor_whole import run_whole, whole_payload


class WholeChainTests(unittest.TestCase):
    def setUp(self):
        self.data = {"question": "A question", "rings": [
            {"type": "start", "thinking": "Start with the painter."},
            {"type": "call", "stage": 1, "thinking_before": "Start with the painter.",
             "thinking_after": "New clue **CONFIRMED**.", "calls": [
                 {"query": "a query", "returned": [{"docid": "synthetic", "snippet": "Painter Mira."}]}]},
            {"type": "final", "thinking": "I cannot tell.", "formal_answer": "\u672a\u4ea4\u5377",
             "termination_reason": "synthetic stop"}
        ]}
        self.conditions = [{"id": "c1", "text": "A question"}]
        self.cfg = {"url": "http://127.0.0.1:8000/v1", "model": "stub", "temperature": 0,
                    "seed": 7, "reasoning_effort": "medium", "max_tokens": 16384,
                    "timeout_seconds": 1, "whole_max_tokens": 32768}

    def test_preserves_ordered_queries_and_followup_thought(self):
        payload = whole_payload(self.data, self.conditions)
        self.assertEqual(list(payload), ["question", "conditions", "start_thinking", "steps", "terminal"])
        self.assertEqual(payload["steps"][0]["step"], 1)
        self.assertEqual(payload["steps"][0]["queries"], ["a query"])
        self.assertEqual(payload["steps"][0]["thinking_after"], "New clue **CONFIRMED**.")
        self.assertNotIn("question", payload["terminal"])

    def test_length_gets_one_expanded_attempt(self):
        caps = []
        def post(url, body):
            caps.append(body["max_tokens"])
            return 200, json.dumps({"choices": [{"finish_reason": "length",
                                                "message": {"content": "{"}}]})
        with TemporaryDirectory() as base:
            result, error, attempts = judge(Path(base), "W", "synthetic", {}, self.cfg,
                                            post=post, extended_max_tokens=32768)
        self.assertEqual(caps, [16384, 32768])
        self.assertIsNone(result)
        self.assertEqual(error, "output_length_limit")
        self.assertEqual(len(attempts), 2)

    def test_invalid_step_ids_are_reported_without_retry(self):
        output = {"start": {}, "steps": [{"step": 1}, {"step": 1}, {"step": 2}], "final": {}}
        raw = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]})
        with TemporaryDirectory() as base, patch("chain_extractor_v2.direct_post", return_value=(200, raw)) as post:
            result = run_whole(self.data, self.conditions, "synthetic", self.cfg, Path(base))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(result["step_check"]["duplicate_ids"], [1])
            self.assertEqual(result["step_check"]["missing_ids"], [1])
            self.assertEqual(result["step_check"]["out_of_range_ids"], [2])
            views = (Path(base)/"STATE.jsonl").read_bytes().splitlines()
            self.assertEqual(len(views), 3)
            self.assertTrue(json.loads(views[1])["state_carried_due_to_failure"])

    def test_shared_quote_normalization(self):
        self.assertEqual(audit_quote("new  clue confirmed", "New clue **CONFIRMED**.", True)["status"], "pass")
        self.assertEqual(audit_quote("from final thought", ("From final thought.", "Other answer."), True)["status"], "pass")
        self.assertEqual(audit_quote("first second", ("first", "second"), True)["status"], "reject")
