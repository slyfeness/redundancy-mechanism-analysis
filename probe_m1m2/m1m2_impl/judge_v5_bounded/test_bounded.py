import copy
import unittest

from bounded import excerpt, select_tracks, validate


class BoundedTest(unittest.TestCase):
    def setUp(self):
        self.raw = {
            "query_id": "q",
            "entities": [{"var": "P", "name": "Entity Alpha", "role": "the object"}],
            "conditions": [{"id": "k1", "question_span": "under cold conditions",
                            "subject": "P", "claim": "Entity Alpha was measured under cold conditions.",
                            "type": "other"}],
            "answer_relation": "Identify the object.",
        }
        self.question = "Which object was measured under cold conditions?"

    def test_strict_span_and_declared_subject(self):
        self.assertEqual(validate("q", self.question, self.raw), [])
        altered = copy.deepcopy(self.raw)
        altered["conditions"][0].update(question_span="under Cold conditions", subject="X")
        self.assertEqual(set(validate("q", self.question, altered)), {"span_not_verbatim", "unknown_subject"})

    def test_select_exact_track_count_and_bound_calls(self):
        old = [f"a{i}" for i in range(10)]
        candidates = [f"n{i}" for i in range(15)]
        costs = {key: 2 for key in old} | {key: 1 for key in candidates}
        one, two = (select_tracks(old, candidates[::-1], costs, required={"n5"}) for _ in range(2))
        self.assertEqual(one, two)
        self.assertEqual(len(set(one)), 10)
        self.assertIn("n5", one)
        self.assertLessEqual(sum(costs[key] for key in old + one) + 20, 60)

    def test_context_is_bounded_around_exact_original(self):
        prefix = " ".join(f"before{i}" for i in range(75)) + " "
        target = "Keep this ORIGINAL sentence."
        source = prefix + target + " " + " ".join(f"after{i}" for i in range(71))
        row = excerpt(source, {"id":"c1.s1", "start":len(prefix), "end":len(prefix) + len(target), "text":target})
        self.assertEqual(row["text"], target)
        self.assertEqual(len(row["before"].split()), 50)
        self.assertEqual(len(row["after"].split()), 50)
        self.assertNotIn("before0", row["before"])
