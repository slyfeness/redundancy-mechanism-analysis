import unittest

from state import Ledger, parse, retries


class StateTest(unittest.TestCase):
    def test_guess_pair_then_correction_and_repeat_precedence(self):
        ledger = Ledger([{"var": "A", "name": "Cora Reed", "role": "writer"}], {})
        item = {"target_role": "A", "candidate": "Iris Vale", "stance": "guess", "gap": "new",
                "gap_description": "birthplace", "new_lead": "no"}
        self.assertFalse(ledger.apply(1, ["Birthplace? "], item)["F_new"])
        tags = ledger.apply(2, ["birthplace"], {**item, "gap": "g1"})
        self.assertTrue(tags["F_new"])
        self.assertTrue(tags["strict_repeat"])
        self.assertFalse(tags["semantic_repeat"])
        tags = ledger.apply(3, ["Where born"], {**item, "candidate": "Cora Reed", "stance": "assertion", "gap": "g1"})
        self.assertTrue(tags["F_corrected"])
        self.assertTrue(tags["semantic_repeat"])

    def test_invalid_preserves_only_observed_search_history(self):
        ledger = Ledger([], {})
        self.assertEqual(ledger.apply(1, ["Raw? query"], None), {"invalid": True})
        self.assertFalse(ledger.candidates)
        self.assertFalse(ledger.gaps)
        item = {"target_role": "none", "candidate": "none", "stance": "guess", "gap": "new",
                "gap_description": "site", "new_lead": "no"}
        self.assertTrue(ledger.apply(2, ["raw query"], item)["strict_repeat"])

    def test_parse_rejects_future_gap_and_unverifiable_quote(self):
        record = {"target_role": "A", "target_quote": "Iris Vale", "candidate": "Iris Vale", "stance": "assertion",
                  "gap": "g9", "gap_description": "none", "new_lead": "no", "lead_quote": "none"}
        self.assertIsNone(parse(record, {"A"}, {"g1"}, ["Iris Vale asks"], ""))
        self.assertIsNotNone(parse({**record, "gap": "g1"}, {"A"}, {"g1"}, ["Iris Vale asks"], ""))
        self.assertIsNone(parse({**record, "gap": "g1", "target_quote": "iris vale"},
                                {"A"}, {"g1"}, ["Iris Vale asks"], ""))

    def test_retry_budget_reserves_all_first_calls(self):
        selected = retries(["one", "two"], already=69, limit=500, stages=430)
        self.assertEqual(selected, ["one"])
