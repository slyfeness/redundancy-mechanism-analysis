import unittest

from rules_v45 import AliasEvidence, classify, containment, pending_key, proper, repair, replay_stage


class NameRules(unittest.TestCase):
    def test_quoted_lowercase_is_not_a_name(self):
        self.assertFalse(proper('"plain and ordinary"'))
        self.assertTrue(proper("Library of Northern Arts"))
        self.assertEqual(repair("none", 'look for "plain and ordinary"', set(), set())["main_name"], "none")

    def test_containment_is_contiguous_and_respects_single_word_reference(self):
        self.assertTrue(containment("Ada Gray Computer", "Ada Gray"))
        self.assertFalse(containment("Ada Computer Gray", "Ada Gray"))
        self.assertFalse(containment("Ada Computer", "Ada"))
        self.assertTrue(containment("The Ada", "Ada"))

    def test_containment_possession_overrides_type_and_backfill_gate(self):
        result = classify(self.item("Ada Gray Computer", backfilled=True, category="work"),
                          {"P": ("Ada Gray", "person")}, {}, AliasEvidence([]))
        self.assertEqual((result["attribution"], result["var"], result["containment_match"]), ("correct", "P", True))
        result = classify(self.item("New Actor", backfilled=True),
                          {"P": ("Ada Gray", "person")}, {},
                          AliasEvidence([{"names": {"A": "New Actor", "B": "Ada Gray"}, "result": "no"}]))
        self.assertEqual((result["attribution"], result["decision_reason"]), ("aux", "backfilled"))

    def test_role_review_uses_question_and_role_scope(self):
        item = self.item("Ada Gray")
        self.assertNotEqual(pending_key("1", item), pending_key("2", item))
        self.assertEqual(pending_key("1", self.item("Dr. Ada Gray")), pending_key("1", item))

    def test_old_strict_and_newer_protection_coexist(self):
        baseline = {"invalid": False, "strict_repeat": True, "semantic_repeat": False, "stale_return": False}
        row = {"searches": ['"dark and bright"'], "items": [self.item("none")], "labels": baseline,
               "stage_id": 1, "new_docids": 0, "seen_docids": 1, "C_new": []}
        result = replay_stage([row], AliasEvidence([]))[0]
        self.assertEqual(result["idle_type"], "strict")
        self.assertFalse(result["labels"]["protected_new_hypothesis"])

    @staticmethod
    def item(name, *, backfilled=False, category="person"):
        return {"main_name": name, "sought_condition": "none", "category": category,
                "var": "P", "backfilled": backfilled}
