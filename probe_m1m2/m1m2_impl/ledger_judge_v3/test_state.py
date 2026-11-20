import unittest

from state_v3 import StageLedger, extract


def mention(name, role="A", same=False, stance="guess"):
    return {"name": name, "role": role, "same_as_table": same, "stance": stance, "quote": name}


def row(mentions=(), targets=(), leads=()):
    return {"mentions": list(mentions), "targets": list(targets), "new_lead": list(leads)}


class StateTest(unittest.TestCase):
    def ledger(self):
        return StageLedger([{"var": "A", "name": "Cora Reed", "role": "writer"}], {})

    def test_copied_name_is_dropped_without_invalidating_other_mentions(self):
        data, discarded = extract(row([mention("Reed Vale"), mention("Hidden Alias")]),
                                  {"A"}, {"c1"}, ["Reed Vale biography"], "")
        self.assertEqual([item["name"] for item in data["mentions"]], ["Reed Vale"])
        self.assertEqual(discarded[0]["reason"], "name_not_in_stage")

    def test_guess_pair_and_true_alias_assertion_are_distinct_events(self):
        ledger = self.ledger()
        data = row([mention("Iris Vale")])
        tags, _ = ledger.apply(1, ["search one"], data)
        self.assertFalse(tags["F_new"])
        tags, events = ledger.apply(2, ["search two"], data)
        self.assertTrue(tags["wrong_candidate"] and tags["F_new"])
        self.assertEqual(events[0]["stage_id"], 2)
        tags, events = ledger.apply(3, ["search three"], row([mention("C. Reed", same=True, stance="assertion")]))
        self.assertTrue(tags["F_corrected"])
        self.assertEqual(events[0]["resolves"], ["F2.1"])

    def test_same_condition_is_insufficient_for_duplicate_target(self):
        ledger = self.ledger()
        def step(name):
            return row(targets=[{"candidate": name, "condition": "c1"}], leads=[{"value": "no", "quote": "none"}])
        self.assertFalse(ledger.apply(1, ["one"], step("Iris Vale"))[0]["semantic_repeat"])
        self.assertFalse(ledger.apply(2, ["two"], step("Dora Bay"))[0]["semantic_repeat"])
        self.assertTrue(ledger.apply(3, ["three"], step("Iris Vale"))[0]["semantic_repeat"])
        self.assertTrue(ledger.apply(4, ["THREE? "], step("Iris Vale"))[0]["strict_repeat"])
        self.assertFalse(ledger.apply(5, ["three"], step("Iris Vale"))[0]["semantic_repeat"])

    def test_invalid_and_aux_do_not_create_wrong_candidate_events(self):
        ledger = self.ledger()
        self.assertEqual(ledger.apply(1, ["one"], None), ({"invalid": True}, []))
        tags, _ = ledger.apply(2, ["two"], row([mention("Stage Name", role="aux", stance="assertion")]))
        self.assertFalse(tags["wrong_candidate"])


    def test_true_alias_shares_target_history_with_canonical_name(self):
        ledger = self.ledger()
        first = row(targets=[{"candidate": "Cora Reed", "condition": "c1"}], leads=[{"value": "no", "quote": "none"}])
        ledger.apply(1, ["one"], first)
        later = row([mention("C. Reed", same=True)], [{"candidate": "C. Reed", "condition": "c1"}],
                    [{"value": "no", "quote": "none"}])
        tags, _ = ledger.apply(2, ["two"], later)
        self.assertTrue(tags["semantic_repeat"])
        self.assertEqual(len(ledger.gaps), 1)
