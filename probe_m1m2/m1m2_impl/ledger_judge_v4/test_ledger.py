import unittest

from program import assign, matching, scrub, settle


def unit(stage, name, state, *, query=None, credit=(), cond="c1"):
    q = name if query is None else query
    return {"stage_id": stage, "searches": [q], "C_new": list(credit),
            "items": [{"main_name": name, "type": "city", "sought_condition": cond,
                       "var": "A" if name != "none" else None, "status": state, "alias": None}]}


class LedgerCases(unittest.TestCase):
    def test_mask_known_names_outside_search_input(self):
        self.assertEqual(scrub("Visit MÉRIDA, Mexico and Merida Mexico.", {"A": ["Mérida Mexico"]}),
                         "Visit [A] and [A].")

    def test_substrings_require_two_shared_words(self):
        self.assertTrue(matching("Rill Copper", "Rill Copper Haven"))
        self.assertFalse(matching("Copper", "Rill Copper Haven"))

    def test_type_tie_uses_condition_owner(self):
        inventory = {"A": "city", "B": "city", "C": "person"}
        self.assertEqual(assign("city", "c1", inventory, {"c1": "B"}), ("B", None))
        self.assertEqual(assign("city", "none", inventory, {}), (None, "ambiguous"))

    def test_wrong_pursuit_is_anchored_to_first_distinct_stage(self):
        units = [unit(1, "Iris Bay", "wrong_candidate"), unit(2, "none", "none"),
                 unit(3, "Iris Bay", "wrong_candidate", query="Iris Bay history"),
                 unit(4, "Cora Bay", "correct")]
        rows, events = settle("demo", units, {"c1": {"id": "k1"}}, {"A": "Cora Bay"}, "correct")
        self.assertTrue(rows[0]["labels"]["F_new"])
        self.assertTrue(rows[3]["labels"]["F_corrected"])
        self.assertEqual([e["stage_id"] for e in events], [1, 4])

    def test_credit_at_previous_search_blocks_semantic_repeat(self):
        units = [unit(1, "Iris Bay", "wrong_candidate", credit=["k1"]),
                 unit(2, "Iris Bay", "wrong_candidate", query="Iris Bay port"),
                 unit(3, "Iris Bay", "wrong_candidate", query="port of Iris Bay")]
        rows, _ = settle("demo", units, {"c1": {"id": "k1"}}, {"A": "Cora Bay"}, "correct")
        self.assertFalse(rows[1]["labels"]["semantic_repeat"])
        self.assertTrue(rows[2]["labels"]["semantic_repeat"])
        self.assertEqual(rows[2]["semantic_repeat_distances"], [1])
