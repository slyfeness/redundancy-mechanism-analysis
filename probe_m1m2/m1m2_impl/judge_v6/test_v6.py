import unittest

from claims import inspect, reconcile
from judgement import check_verdicts


class ClaimRepairTest(unittest.TestCase):
    def setUp(self):
        self.question = "Which writer finished two novels and was their editor's seventh child?"
        self.entities = [{"var": "W", "name": "Ada Finch", "role": "writer"},
                         {"var": "E", "name": "Tomas Thorn", "role": "editor"}]
        self.good = {"id": "k1", "question_span": "finished two novels", "subject": "W",
                     "claim": "Ada Finch finished 2 novels.", "type": "number"}
        self.bad = {"id": "k2", "question_span": "was their editor's seventh child", "subject": "W",
                    "claim": "They were the 7th child.", "type": "relation"}
        self.old = {"query_id": "q", "entities": self.entities, "conditions": [self.good, self.bad],
                    "answer_relation": "Identify the writer."}

    def test_repairs_only_flagged_slot(self):
        marked = inspect("q", self.question, self.old)
        self.assertEqual(set(marked["claims"]), {1})
        corrected = {**self.bad, "claim": "Ada Finch was Tomas Thorn's 7th child."}
        reply = {"entities": self.entities, "answer_relation": "Another relation.",
                 "repairs": [{"slot": 0, "condition": self.bad}, {"slot": 1, "condition": corrected}],
                 "additions": []}
        final, audit = reconcile("q", self.question, self.old, marked, reply)
        self.assertEqual(final["conditions"], [self.good, corrected])
        self.assertEqual(final["answer_relation"], self.old["answer_relation"])
        self.assertEqual(audit[-1]["before"], self.bad)
        self.assertEqual(audit[-1]["after"], corrected)

    def test_bad_repair_drops_one_claim_and_keeps_valid_claim(self):
        marked = inspect("q", self.question, self.old)
        reply = {"entities": self.entities, "repairs": [{"slot": 1, "condition": self.bad}], "additions": []}
        final, audit = reconcile("q", self.question, self.old, marked, reply)
        self.assertEqual(final["conditions"], [self.good])
        self.assertTrue(any(row["phase"] == "discard" and row["slot"] == 1 for row in audit))

    def test_numeric_conversion_does_not_make_decade_into_exact_year(self):
        changed = {**self.good, "claim": "Ada Finch finished 2 novels in 1980."}
        original = {**self.old, "conditions": [changed, self.bad]}
        mark = inspect("q", self.question + " It happened in the early 1980s.", original)
        self.assertIn("number_not_in_question_or_names", mark["claims"][0])


class JudgeTest(unittest.TestCase):
    def test_two_passages_credit_later_unit_irrespective_of_citation_order(self):
        claims = [{"id": "k1"}]
        passages = [
            {"id": "c1", "unit_id": 3, "sentences": [{"id": "c1.s1", "text": "one fact"}]},
            {"id": "c2", "unit_id": 8, "sentences": [{"id": "c2.s1", "text": "other fact"}]},
            {"id": "c3", "unit_id": 9, "sentences": [{"id": "c3.s1", "text": "third fact"}]},
        ]
        result = {"verdicts": [{"id": "k1", "status": "supported", "reason": "Both facts.",
                               "sentence_ids": ["c2.s1", "c1.s1"]}]}
        row = check_verdicts(claims, passages, result)[0]
        self.assertEqual((row["status"], row["unit_id"], row["passage_count"]), ("supported", 8, 2))
        result["verdicts"][0]["sentence_ids"].append("c3.s1")
        self.assertEqual(check_verdicts(claims, passages, result)[0]["status"], "unknown")
        result["verdicts"][0]["sentence_ids"] = ["c8.s1"]
        self.assertEqual(check_verdicts(claims, passages, result)[0]["status"], "unknown")

    def test_preserves_different_entity_unknown_reason(self):
        result = {"verdicts": [{"id": "k1", "status": "unknown", "reason": "different entity",
                                "sentence_ids": []}]}
        row = check_verdicts([{"id": "k1"}], [], result)[0]
        self.assertEqual((row["status"], row["reason"], row["unit_id"]), ("unknown", "different entity", None))
