import unittest

from matcher import classify, resettle, alias_key


ITEM = {"main_name": "Ash Valley", "type": "city", "sought_condition": "c1"}


class MatchingCases(unittest.TestCase):
    def test_alias_matches_any_same_type_role_instead_of_owner(self):
        names = {"A": "Ivy Brook", "B": "Cedar Vale"}
        aliases = {alias_key("Ash Valley", "Ivy Brook"): {"id": "a", "result": "no"},
                   alias_key("Ash Valley", "Cedar Vale"): {"id": "b", "result": "yes"}}
        hit = classify(ITEM, names, {"A": "city", "B": "city"}, set(), {"c1": "A"}, aliases)
        self.assertEqual((hit["status"], hit["var"]), ("correct", "B"))

    def test_missing_alias_cannot_make_a_wrong_candidate(self):
        names = {"A": "Ivy Brook", "B": "Cedar Vale"}
        hit = classify(ITEM, names, {"A": "city", "B": "city"}, set(), {"c1": "A"}, {})
        self.assertEqual(hit["status"], "alias_unresolved")

    def test_type_only_event_counts_without_inventing_a_role(self):
        names = {"A": "Ivy Brook", "B": "Cedar Vale"}
        aliases = {alias_key("Ash Valley", v): {"id": k, "result": "no"} for k, v in names.items()}
        hit = classify(ITEM, names, {"A": "city", "B": "city"}, set(), {}, aliases)
        self.assertEqual((hit["status"], hit["var"], hit["attribution_scope"]), ("wrong_candidate", None, "type"))
        units = [{"stage_id": sid, "searches": [f"query {sid}"], "items": [hit], "C_new": []} for sid in (1, 2)]
        stages, events = resettle("mock", units, {"c1": {"id": "k1"}}, names, "incorrect")
        self.assertTrue(stages[0]["labels"]["F_new"])
        self.assertEqual(events[0]["key"], ["city", "ash valley"])
        self.assertIsNone(events[0]["correct_name"])
