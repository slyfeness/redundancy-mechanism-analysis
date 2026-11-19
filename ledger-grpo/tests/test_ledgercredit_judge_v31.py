import unittest

from ledger_grpo.ledgercredit.judge_v31 import (
    aligned_evidence, apply_targeted_edits, entity_check, gate, question_span, same_entity,
)


class V31Tests(unittest.TestCase):
    def test_realign_merge_without_copying_text(self):
        text = "Mr. Calder lived here. Then he left."
        old = {"d1.s1": {"start": 0, "end": 3, "text": "Mr.", "docid": "doc"},
               "d1.s2": {"start": 4, "end": 22, "text": "Calder lived here.", "docid": "doc"}}
        ref = aligned_evidence({"docid": "doc", "sentence_ids": ["d1.s1", "d1.s2"]}, old, text)
        self.assertEqual(ref["sentence_ids"], ["d1.s1"])
        self.assertEqual(ref["text"], "Mr. Calder lived here.")
        self.assertRaises(ValueError, aligned_evidence,
                          {"docid": "other", "sentence_ids": ["d1.s1"]}, old, text)

    def test_title_variant_and_common_alias(self):
        self.assertTrue(same_entity("Silver Gate: Clock Tower", "In Silver Gate and the Clock Tower."))
        self.assertTrue(same_entity("USA", "The United States hosted the event."))
        self.assertFalse(same_entity("Silver Gate: Clock Tower", "Silver Gate: Stone Tower"))

    def test_only_subject_gets_doc_wide_exception(self):
        checked = entity_check("Lena Mora researched Eta Bay.", "She researched the bay.",
                               "Lena Mora was a researcher. She researched the bay. Eta Bay is elsewhere.")
        self.assertEqual(checked["missing_names"], ["Eta Bay"])
        self.assertTrue(checked["subject_document_match"])
        self.assertFalse(entity_check("Lena Mora moved in 1915.", "She moved in 1916.",
                                      "Lena Mora lived here in 1915.")["passed"])

    def test_only_flagged_terms_can_be_edited(self):
        text = "Lena Mora won in 1915."
        missing = {"missing_names": [], "missing_numbers": ["1915"], "missing_quotes": []}
        self.assertEqual(apply_targeted_edits(text, [{"old": "1915", "new": "1916"}], missing),
                         "Lena Mora won in 1916.")
        self.assertRaises(ValueError, apply_targeted_edits, text, [{"old": "won", "new": "lost"}], missing)
        self.assertRaises(ValueError, apply_targeted_edits, text,
                          [{"old": "1915", "new": "1916"}, {"old": "1915", "new": "1917"}], missing)
        self.assertIsNone(question_span("Who left in 1956?", [False, 4]))
        self.assertEqual(question_span("Who left in 1956?", [3, 4]), "in 1956?")

    def test_gate_has_four_quality_checks_and_parent_integrity(self):
        self.assertTrue(gate(0, 0, 2, 95, 100, 2, 100)["passed"])
        self.assertFalse(gate(0, 1, 2, 99, 100, 0, 100)["passed"])
        self.assertFalse(gate(0, 0, 3, 99, 100, 0, 100)["passed"])
        self.assertFalse(gate(0, 0, 1, 94, 100, 0, 100)["passed"])
        self.assertFalse(gate(0, 0, 1, 99, 100, 3, 100)["passed"])
