import unittest

from replay_v47 import subset_match, update_item


class SubsetRules(unittest.TestCase):
    def test_titles_and_word_order(self):
        self.assertTrue(subset_match("Dr. Gray", "Avery Jane Gray"))
        self.assertTrue(subset_match("Gray Avery", "Avery Jane Gray"))
        self.assertTrue(subset_match("Prof. Avery", "Mr. Avery Jane Gray"))
        self.assertFalse(subset_match("Gray Jr", "Avery Jane Gray"))
        self.assertFalse(subset_match("Aver", "Avery Jane Gray"))
        self.assertFalse(subset_match("", "Avery Jane Gray"))

    def test_preserves_earlier_correct_decisions_and_invalid_slots(self):
        refs = {"P": ("Avery Jane Gray", "person")}
        prior = {"main_name": "Gray", "attribution": "correct", "var": "P", "decision_reason": "correct"}
        invalid = {"main_name": None, "attribution": "invalid", "var": None, "decision_reason": "invalid"}
        self.assertEqual(update_item(prior, refs), prior)
        self.assertEqual(update_item(invalid, refs), invalid)

    def test_fix_names_with_concrete_reference(self):
        refs = {"P": ("Avery Jane Gray", "person"), "Q": ("Owen Jay Gray", "person"),
                "U": ("UNRESOLVED", "other")}
        source = {"main_name": "Dr. Gray", "attribution": "wrong_candidate", "var": "Q",
                  "decision_reason": "wrong_candidate", "normalized_match": False, "containment_match": False}
        result = update_item(source, refs)
        self.assertEqual((result["attribution"], result["var"], result["decision_reason"]), ("correct", "Q", "subset"))
        self.assertTrue(result["normalized_match"])
        self.assertFalse(result["containment_match"])
        self.assertEqual(source["attribution"], "wrong_candidate")
        other = {**source, "main_name": "UNRESOLVED"}
        self.assertEqual(update_item(other, refs), other)
