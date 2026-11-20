import unittest

from checks import flags, validate


def target(role, name, relation):
    return {"role": role, "candidate": name, "relation": relation}


def stage(sid, thought, prior=()):
    return {"stage_id": sid, "thought_tail": thought, "searches": [],
            "pre": {"conditions": [], "searches": list(prior), "strict_repeats": []}}


class ChecksTest(unittest.TestCase):
    def test_semantic_repeat_requires_prior_search_and_explanation(self):
        previous = {"id": "S1", "stage_id": 1, "query": "fixture"}
        st = stage(2, "Search this fixture again", [previous])
        st["searches"] = ["Search this fixture again"]
        row = {"stage_id": 2, "direction": "on_track", "repeat": "semantic_repeat",
               "target": target(None, None, "unknown"),
               "evidence": {"quote": "Search this fixture again", "refs": ["S1"],
                            "prior_search_id": "S1", "reason": "Same gap and no intervening clue."}}
        self.assertTrue(validate(row, st, {}))
        row["evidence"]["prior_search_id"] = "S2"
        self.assertFalse(validate(row, st, {}))

    def test_evidence_is_verbatim_and_has_a_cap(self):
        st = stage(1, "Known candidate")
        row = {"stage_id": 1, "direction": "on_track", "repeat": "new",
               "target": target(None, None, "unknown"),
               "evidence": {"quote": "known candidate", "refs": [], "prior_search_id": None, "reason": ""}}
        self.assertFalse(validate(row, st, {}))
        text = "word " * 41
        st["thought_tail"] = text
        row["evidence"]["quote"] = text.strip()
        self.assertFalse(validate(row, st, {}))

    def test_correction_matches_only_the_same_identifiable_role(self):
        verdicts = [{"stage_id": 1, "direction": "wrong_candidate", "target": target("A", "Reed Vale", "different")},
                    {"stage_id": 2, "direction": "wrong_candidate", "target": target("A", "REED VALE", "different")},
                    {"stage_id": 3, "direction": "on_track", "target": target("B", "Tess Ray", "same")},
                    {"stage_id": 4, "direction": "on_track", "target": target("A", "Cora Reed", "same")}]
        first, corrections = flags(verdicts)
        self.assertEqual(first, {1})
        self.assertEqual(corrections, {1: 4})
