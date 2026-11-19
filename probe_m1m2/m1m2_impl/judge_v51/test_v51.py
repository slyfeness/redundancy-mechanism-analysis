import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "judge_v5_bounded"))
from rules import judge_payload, validate


class NamedClaimsTest(unittest.TestCase):
    def setUp(self):
        self.question = "Which photographer worked with an editor in the early 1980s?"
        self.response = {"query_id": "q", "answer_relation": "Identify the photographer.",
                         "entities": [{"var": "P", "name": "Ada Vale", "role": "the photographer"},
                                      {"var": "E", "name": "Orin Lake", "role": "the editor"}],
                         "conditions": [{"id": "k1", "subject": "P", "type": "relation",
                                         "question_span": "worked with an editor in the early 1980s",
                                         "claim": "Ada Vale worked with Orin Lake in the early 1980s."}]}

    def test_allows_names_and_preserves_vague_year(self):
        self.assertEqual(validate("q", self.question, self.response), [])
        changed = copy.deepcopy(self.response)
        changed["conditions"][0]["claim"] = "Ada Vale worked with Orin Lake in 1980 in Paris."
        self.assertEqual(set(validate("q", self.question, changed)),
                         {"capitalized_word_not_in_question_or_names", "number_not_in_question_or_names"})

    def test_maximum_two_uses_of_exact_span(self):
        span = self.response["conditions"][0]
        self.response["conditions"] += [{**span, "id": "k2"}]
        self.assertEqual(validate("q", self.question, self.response), [])
        self.response["conditions"] += [{**span, "id": "k3"}]
        self.assertEqual(validate("q", self.question, self.response), ["question_span_used_more_than_twice"])

    def test_subject_name_must_start_claim(self):
        self.response["conditions"][0]["claim"] = "Orin Lake worked with Ada Vale in the early 1980s."
        self.assertEqual(validate("q", self.question, self.response), ["claim_does_not_start_with_subject_name"])

    def test_payload_only_adds_names_and_roles(self):
        frozen = {"conditions": [{"id": "k1", "text": "Ada Vale worked with Orin Lake.",
                                   "support_rule": "The relation is explicit."}],
                  "entities": self.response["entities"]}
        block = [{"sentences": [{"id": "c1.s1", "text": "Synthetic evidence.", "start": 0}]}]
        def v4_payload(claims, passages):
            self.assertIs(claims, frozen["conditions"])
            self.assertIs(passages, block)
            return {"claims": claims, "passages": passages}
        result = judge_payload(frozen, block, base_payload=v4_payload)
        self.assertEqual(result["entities"], [{"name": "Ada Vale", "role": "the photographer"},
                                              {"name": "Orin Lake", "role": "the editor"}])
        self.assertIs(result["passages"], block)
