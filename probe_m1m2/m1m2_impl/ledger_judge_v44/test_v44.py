import unittest

from rules_v44 import (AliasEvidence, Protection, classify, equivalent, repair, settle, signal)


def item(name, kind="person", status="wrong_candidate", var="P"):
    return {"main_name": name, "category": kind, "attribution": status, "var": var}


def stage(sid, items, searches=None, **labels):
    return {"trajectory_id": "fixture", "stage_id": sid, "searches": searches or [],
            "items": items, "labels": {"invalid": False, **labels}, "C_new": [],
            "new_docids": 0, "seen_docids": 1, "semantic_repeat_distances": []}


class NamesTest(unittest.TestCase):
    def test_case_articles_titles_and_hyphens(self):
        self.assertTrue(equivalent("«The Moonrise»", "Moonrise"))
        self.assertTrue(equivalent("Dr. Ada Gray", "Ada Gray"))
        self.assertTrue(equivalent("Chao Li-min", "Chao Limin"))
        self.assertFalse(equivalent("Avery Stone", "Avery Stoner"))

    def test_backfill_quotes_and_connectors_but_not_calendar_country_or_var(self):
        countries = {"united states"}
        value = repair("Q", "Q United States March Monday 1999 Calder Institute of Arts", {"Q"}, countries)
        self.assertEqual((value["discard_reason"], value["main_name"], value["backfilled"]),
                         ("variable_or_short", "Calder Institute of Arts", True))
        value = repair("none", 'author wrote "notes in winter" in 1999', set(), countries)
        self.assertEqual(value["main_name"], "notes in winter")
        self.assertEqual(repair("none", "United States March Monday 1999", set(), countries)["main_name"], "none")

    def test_positive_title_case_ignores_classifier_proper_name_flag(self):
        value = repair("Judge Ada Gray", "Judge Ada Gray records", set(), set())
        self.assertEqual((value["main_name"], value["discard_reason"], value["backfilled"]),
                         ("Judge Ada Gray", None, False))
        value = repair("ordinary text", "ordinary text about Darcy Lake", set(), set())
        self.assertEqual((value["main_name"], value["discard_reason"]), ("Darcy Lake", "non_proper_name"))

    def test_category_only_wrong_candidate_stays_unattributed(self):
        table = {"P": ("Ada Gray", "person"), "Q": ("Owen Cole", "person"),
                 "W": ("The Moonrise", "work")}
        aliases = AliasEvidence([{"names": {"A": "Lea Moss", "B": name}, "result": "no"}
                                 for name in ("Ada Gray", "Owen Cole")])
        row = {"main_name": "Lea Moss", "category": "person", "sought_condition": "none"}
        self.assertEqual(classify(row, table, {}, aliases)["attribution"], "unattributed")
        self.assertEqual(classify({**row, "sought_condition": "c1"}, table, {"c1": "Q"}, aliases)["var"], "Q")
        positive = classify({"main_name": "Moonrise", "category": "other", "sought_condition": "none"},
                            table, {}, aliases)
        self.assertEqual((positive["attribution"], positive["var"]), ("correct", "W"))

    def test_protection_uses_raw_earlier_queries_and_stage_boundary(self):
        history = Protection()
        self.assertFalse(history.add(["find lunar atlas, April 18 2001"]))
        self.assertFalse(history.add(["Find Lunar Atlas April 18 2001"]))
        self.assertTrue(history.add(["search about Dorian Hall", "Dorian Hall archives"]))
        self.assertFalse(history.add(["Dorian Hall archives"]))
        self.assertTrue(history.add(["'Dorian Atlas' archives"]))

    def test_protection_normalizes_apostrophes_and_hyphen_variants(self):
        history = Protection()
        self.assertTrue(history.add(["Dorian Hale-Smith, O'Brien"]))
        self.assertFalse(history.add(["Dorian HaleSmith, OBrien"], ["Dorian HaleSmith", "OBrien"]))

    def test_ambiguous_repeated_capital_run_does_not_create_new_name(self):
        history = Protection()
        self.assertTrue(history.add(["Dorian city hall Calder Museum"]))
        self.assertFalse(history.add(["Dorian Calder Calder Museum city hall"]))


class ReplayTest(unittest.TestCase):
    def test_hyphen_variants_share_one_candidate_event(self):
        units = [stage(1, [item("Hale Smith")]), stage(2, [item("Hale-Smith")]), stage(3, [item("HaleSmith")]),
                 stage(4, [item("HaleSmith")])]
        rows, events = settle(units, AliasEvidence([]), {"P": ("Ada Gray", "person")})
        self.assertEqual([(e["event"], e["stage_id"]) for e in events], [("F_new", 1)])
        self.assertTrue(rows[0]["labels"]["F_new"])

    def test_repeat_labels_protection_and_concrete_candidate_events(self):
        units = [
            stage(1, [item("Lea Moss")]), stage(2, [item("Lea Moss")]),
            stage(3, [item("Lea Moss")], ["Find Dorian Hall"]),
            stage(4, [item("Ada Gray", status="correct")], ["Dorian Hall and Alder Lane"], strict_repeat=True),
            stage(5, [item("Owen Cole", status="unattributed", var=None)]),
            stage(6, [item("Owen Cole", status="unattributed", var=None)]),
            stage(7, [item("none", kind=None, status="none", var=None)]),
            stage(8, [item("none", kind=None, status="none", var=None)], [], invalid=True),
        ]
        derived, events = settle(units, AliasEvidence([]), {"P": ("Ada Gray", "person")})
        self.assertEqual([(e["event"], e["stage_id"], e["var"]) for e in events],
                         [("F_new", 1, "P"), ("F_corrected", 4, "P")])
        self.assertEqual([r["idle_type"] for r in derived],
                         ["none", "semantic", "none", "strict", "none", "semantic", "semantic", "none"])
        self.assertTrue(derived[3]["labels"]["protected_new_hypothesis"])
        self.assertTrue(derived[7]["labels"]["invalid"])
        self.assertEqual(signal(derived[0], (123, 45))["F_new"], 1)
        self.assertEqual(signal(derived[0], (123, 45))["return_tokens"], 45)
