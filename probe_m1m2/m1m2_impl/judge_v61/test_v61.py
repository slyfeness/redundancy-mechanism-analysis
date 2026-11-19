import unittest

from pipeline import build_payload, inspect, reconcile, usable_repair
from sampling import sample_unknown


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.q = "Which painter later made two portraits after visiting a city?"
        self.entities = [{"var": "P", "name": "Ada Wynn", "role": "painter"}]
        self.soft = {"id": "k1", "subject": "P", "question_span": "later made two portraits",
                     "claim": "They later made 2 portraits.", "type": "relation"}
        self.hard = {"id": "k2", "subject": "P", "question_span": "after visiting a city",
                     "claim": "Visited Zurich in 1992.", "type": "relation"}
        self.old = {"query_id": "q", "entities": self.entities,
                    "answer_relation": "Find the painter.", "conditions": [self.soft, self.hard]}

    def test_soft_flag_retained_and_replied_hard_flag_discarded(self):
        marked = inspect("q", self.q, self.old)
        final, audit = reconcile("q", self.q, self.old, marked, {"repairs": []}, exhausted=False)
        self.assertEqual(len(final["conditions"]), 1)
        self.assertEqual(final["conditions"][0]["claim"], self.soft["claim"])
        self.assertIn("unresolved_reference", final["conditions"][0]["flags"])
        self.assertTrue(any(r["phase"] == "discard" and r["slot"] == 1 for r in audit))

    def test_two_unusable_replies_preserve_even_hard_flagged_original(self):
        marked = inspect("q", self.q, self.old)
        final, audit = reconcile("q", self.q, self.old, marked, None, exhausted=True)
        self.assertEqual([r["claim"] for r in final["conditions"]], [self.soft["claim"], self.hard["claim"]])
        self.assertIn("repair_unavailable", final["conditions"][1]["flags"])
        self.assertFalse(any(r["phase"] == "discard" for r in audit))
        self.assertFalse(usable_repair({"wrong_field": []}))
        self.assertTrue(usable_repair({"repairs": []}))

    def test_subject_not_required_inside_body_and_formatted_for_judge(self):
        row = {**self.soft, "claim": "Later made 2 portraits."}
        original = {**self.old, "conditions": [row, self.hard]}
        marks = inspect("q", self.q, original)
        self.assertNotIn(0, marks["claims"])
        payload = build_payload(original, [])
        self.assertEqual(payload["claims"][0]["text"], "对象：Ada Wynn（painter）。断言：Later made 2 portraits.")
        self.assertEqual(payload["entities"], [{"name": "Ada Wynn", "role": "painter"}])


class SamplingTest(unittest.TestCase):
    def test_two_distinct_relevant_passages_and_excludes_entity_mismatches(self):
        from bounded import excerpt
        claim = {"id": "k1", "subject": "P", "claim": "Made a cobalt portrait."}
        records = {"q": {"entities": [{"var": "P", "name":"Ada Wynn", "role":"painter"}], "conditions": [claim]}}
        data = ["A cobalt portrait was on display.", "Snow fell all evening.", "Ada Wynn painted the portrait."]
        passages = [{"id": f"c{i}", "unit_id": i, "text": t, "sentences": [
            {"id": f"c{i}.s1", "start": 0, "end": len(t), "text": t}]} for i, t in enumerate(data, 1)]
        row = {"trajectory_id":"t", "assertion_id":"k1", "status":"unknown", "reason":"Missing corroboration"}
        result, count = sample_unknown([row], {"t":"q"}, records, {"t":passages}, excerpt, count=20)
        self.assertEqual(count, 1)
        self.assertEqual({p["passage_id"] for p in result[0]["passages"]}, {"c1","c3"})
        self.assertEqual(sample_unknown([{**row,"reason":"different entity"}], {"t":"q"},
                                       records, {"t":passages}, excerpt)[0], [])


class GoldRoutingTest(unittest.TestCase):
    def test_gold_warning_is_retained_and_gold_text_does_not_reach_trajectory(self):
        from argparse import Namespace
        from collections import Counter
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from judgement import JUDGE_PROMPT
        from run_v61 import judge_pass

        text = "An artificial observation for this fixture."
        def passage(pid):
            return {"id": pid, "unit_id": 1, "text": text, "docid": "synthetic-gold", "labels": ["gold"],
                    "sentences": [{"id": f"{pid}.s1", "start": 0, "end": len(text), "text": text}]}
        class Runner:
            def batch(_, url, prompt, jobs, max_tokens, output, tag, calls, *, ceiling):
                self.assertEqual(prompt, JUDGE_PROMPT)
                self.assertEqual([k for k, _ in jobs], [("gold", "q"), ("trajectory", "t")])
                self.assertEqual([next(iter(p["passages"]))["sentences"][0]["id"] for _, p in jobs],
                                 ["g1.s1", "c1.s1"])
                return {
                    ("gold", "q"): {"verdicts": [{"id": "a", "status": "unknown",
                                                  "reason": "A synthetic reason for this test.",
                                                  "sentence_ids": []}]},
                    ("trajectory", "t"): {"verdicts": [{"id": "a", "status": "supported",
                                                       "reason": "Valid synthetic trajectory evidence.",
                                                       "sentence_ids": ["c1.s1"]}]},
                }

            @staticmethod
            def emit(file, record):
                file.write(json.dumps(record) + "\n")

        record = {"conditions": [{"id": "a", "subject": "A", "claim": "Arrived before sunrise.", "flags": []}],
                  "entities": [{"var": "A", "name": "Fixture Artist", "role": "subject"}]}
        with TemporaryDirectory() as folder:
            totals = judge_pass(Runner(), Namespace(out=Path(folder), url="http://127.0.0.1"),
                                {"q": record}, {"t": [passage("c1")]}, {"q": [passage("g1")]},
                                {"trajectory_question": {"t": "q"}}, Counter())
            self.assertEqual(totals["supported"], 1)
            self.assertEqual(totals["gold_unknown"], 1)
            self.assertEqual(record["conditions"][0]["flags"], ["not_supported_by_gold"])
