import unittest

from category_events import name_batch, rebuild


def item(name, var, *, status="wrong_candidate", kind="place"):
    return {"main_name": name, "var": var, "type": kind, "status": status,
            "sought_condition": "c1", "alias": None, "attribution_scope": "var" if var else None}


def stage(n, candidate):
    return {"stage_id": n, "searches": [f"search {n}"], "items": [candidate], "C_new": []}


class ReplayCases(unittest.TestCase):
    def test_one_name_list_hides_source_side(self):
        request = name_batch("Synthetic question", ["Ash Valley", "Cedar Vale"], ["ASH VALLEY", "Dora Bay", "none"])
        self.assertEqual(set(request), {"question", "names"})
        self.assertEqual(request["names"], ["Ash Valley", "Cedar Vale", "Dora Bay"])

    def test_wrong_key_is_category_even_with_different_roles(self):
        units = [stage(1, item("Ash Valley", "A")), stage(2, item("Ash Valley", "B")),
                 stage(3, item("Cedar Vale", "A", status="correct"))]
        rows, events = rebuild("mock", units, {"c1": {"id": "k1"}}, {"A": "Cedar Vale", "B": "Dora Bay"}, "incorrect")
        self.assertTrue(rows[0]["labels"]["F_new"])
        self.assertFalse(rows[1]["labels"]["F_new"])
        self.assertTrue(rows[2]["labels"]["F_corrected"])
        self.assertEqual(events[0]["key"], ["place", "ash valley"])

    def test_nonproper_text_cannot_create_semantic_repetition(self):
        units = [stage(i, item("plain text", None, status="non_proper_name")) for i in (1, 2)]
        rows, events = rebuild("mock", units, {"c1": {"id": "k1"}}, {}, "no_submission")
        self.assertFalse(rows[1]["labels"]["semantic_repeat"])
        self.assertFalse(rows[1]["ledger_after"]["searched"])
        self.assertEqual(rows[1]["items"][0]["main_name"], "plain text")
        self.assertFalse(events)
