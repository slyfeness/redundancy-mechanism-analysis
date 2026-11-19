import unittest

from ledger_grpo.ledgercredit.judge_v4 import (
    entity_check, gate, metadata_only, sentence_spans,
)


class V4Tests(unittest.TestCase):
    def parts(self, text):
        return [text[start:end] for start, end in sentence_spans(text)]

    def test_six_reported_boundaries_in_synthetic_text(self):
        for text in [
            "Mr. Calder left at dawn.",
            "N. Quinn (m. 11 May 1891) moved.",
            "The Northport-St. Helen route reopened.",
            "The train left on Jan. 24.",
            "The town's old population (51,496) was recorded.",
            "The new census lists 7, 015 inhabitants.",
        ]:
            self.assertEqual(self.parts(text + " It was noted."), [text, "It was noted."])

    def test_abbreviations_initials_and_decimal(self):
        self.assertEqual(self.parts("Dr. P. R. Vale (b. 1901, d. 1988) noted 2.71 in Dec. 1942. Enough."),
                         ["Dr. P. R. Vale (b. 1901, d. 1988) noted 2.71 in Dec. 1942.", "Enough."])

    def test_long_lines_preserve_numeric_commas_and_keep_offsets(self):
        line = " ".join(["item"] * 45) + " 8, 005, " + " ".join(["part"] * 45) + " 29,123."
        self.assertEqual(len(self.parts(line)), 2)
        self.assertIn("8, 005,", self.parts(line)[0])
        self.assertTrue(self.parts(line)[1].endswith("29,123."))
        self.assertEqual(self.parts("start: 2.71\nhead: 5, 246"), ["start: 2.71", "head: 5, 246"])

    def test_named_subject_exception_is_for_subject_only(self):
        self.assertTrue(entity_check("Mira Voss sold 6,005 books.", "Mira Voss",
                                     "She sold 6005 books.", "Mira Voss. She sold 6005 books.", True)["passed"])
        checked = entity_check("Mira Voss sold 6005 books in Delta City.", "Mira Voss",
                               "She sold 6005 books.", "Mira Voss later saw Delta City.", True)
        self.assertEqual(checked["missing_names"], ["Delta City"])

    def test_numbers_and_quoted_words_must_match_selected_text(self):
        self.assertFalse(entity_check('The text says "remote village" in 1871.', "",
                                     "The text describes a village in 1872.", "", False)["passed"])
        self.assertTrue(entity_check("It held 41,596 books.", "", "It held 41,596 books.", "", False)["passed"])

    def test_metadata_gate_and_pilot_gates(self):
        self.assertTrue(metadata_only(["Title: Fictional Notes", "Author: Quinn", "2024"]) )
        self.assertFalse(metadata_only(["Founded: 1904"]))
        self.assertTrue(gate(0, 95, 100, 2, 100, 8, 10, 0, 0)["passed"])
        self.assertFalse(gate(0, 100, 100, 0, 20, 8, 10, 1, 0)["passed"])
