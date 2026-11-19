import unittest

from ledger_grpo.ledgercredit.judge_v3 import (
    audit_rule_first, blocks, check_verdicts, freeze_question, gate, merge_verdicts,
    normalize_for_match, quote_match, sentence_spans,
)


class SentenceJudgeTests(unittest.TestCase):
    def test_literal_matching_normalizes_encoding_and_spacing(self):
        self.assertEqual(normalize_for_match(r"Title:  P‑Q &rsquo; \u2014 X"), "title:p-q'-x")
        self.assertTrue(quote_match("Title:The Blue‑River", "Title: The Blue-River"))

    def test_ellipsis_matches_in_order_inside_one_source(self):
        self.assertTrue(quote_match("Blue river … silver bridge", "Blue river beside a silver bridge"))
        self.assertFalse(quote_match("silver bridge … blue river", "blue river beside a silver bridge"))
        self.assertFalse(quote_match("bridge … bridge", "one bridge"))

    def test_sentence_spans_roundtrip_and_resplit_long_sentence(self):
        text = "section: first\nitem: second. Third sentence? " + "a " * 45 + ", " + "b " * 45 + "."
        spans = sentence_spans(text)
        self.assertEqual([text[a:b] for a, b in spans[:3]],
                         ["section: first", "item: second.", "Third sentence?"])
        self.assertEqual(len(spans), 5)
        self.assertIn(",", text[spans[3][0]:spans[3][1]])

    def test_only_fed_returns_and_five_unit_chunks(self):
        def event(fed):
            return {"status": "ok", "tool": "search", "fed_to_model": fed,
                    "return_text": '[{"docid": 1, "snippet":"Blue river. Silver bridge."}]'}
        stages = [{"unit_id": n, "tool_events": [event(n != 3)]} for n in range(1, 8)]
        grouped = blocks(stages)
        self.assertEqual([len(block) for block in grouped], [5, 1])
        self.assertEqual(grouped[0][0]["sentences"][1]["id"], "c1.s2")
        self.assertNotIn(3, {row["unit_id"] for group in grouped for row in group})

    def test_cross_snippet_and_duplicate_ids_are_invalid(self):
        sentence = lambda cid: {"id": cid, "text": "Blue river."}
        snippets = [{"unit_id": 1, "sentences": [sentence("c1.s1")]},
                    {"unit_id": 1, "sentences": [sentence("c2.s1")]}]
        claims = [{"id": "k"}]
        for ids in (["c1.s1", "c2.s1"], ["c1.s1", "c1.s1"], ["c9.s1"]):
            parsed = {"verdicts": [{"id":"k", "status":"supported", "sentence_ids":ids, "reason":"fixture"}]}
            rows, count = check_verdicts(claims, snippets, parsed)
            self.assertEqual(rows[0]["status"], "unknown")
            self.assertEqual(count["invalid_refs"], 1)

    def test_merge_prefers_earliest_supported_without_rule_credit(self):
        claims = [{"id": "k"}, {"id": "other"}]
        raw = lambda status, unit: {"id": "k", "status": status, "unit_id": unit}
        decisions, picks = merge_verdicts(claims, [[raw("supported", 7)], [raw("partial", 2)],
                                                  [raw("supported", 4)]])
        self.assertEqual(decisions[0]["first_supported"], 4)
        self.assertEqual(decisions[0]["first_partial"], 2)
        self.assertEqual(decisions[1]["status"], "unknown")
        self.assertEqual(picks["k"]["unit_id"], 4)

    def test_rules_require_entire_frozen_evidence_in_one_snippet(self):
        claim = {"evidence":[{"text":"Blue river.\nSilver bridge."}]}
        grouped = [[{"unit_id": 1, "text": "Blue river."}, {"unit_id": 1, "text": "Silver bridge."},
                    {"unit_id": 2, "text": "Blue river. Nearby. Silver bridge."}]]
        self.assertEqual(audit_rule_first(claim, grouped)["unit_id"], 2)

    def test_split_children_must_be_atomic_and_covered_in_one_doc(self):
        original = {"question_id":"q", "conditions":[{"id":"a"}]}
        child = {"text":"One fact.", "support_rule":"Fact present.", "atomic_check":"atomic",
                 "coverage_check":"complete", "reason":"Fixture."}
        options = {"d1.s1":{"docid":"d1","text":"One fact.","index":1},
                   "d2.s1":{"docid":"d2","text":"Another source.","index":1}}
        body = {"parents":[{"parent_id":"a","atomic_check":"compound","children":[
            dict(child, sentence_ids=["d1.s1"]), dict(child, sentence_ids=["d1.s1", "d2.s1"])]}]}
        row, audit = freeze_question(original, options, body)
        self.assertEqual(row["conditions"][0]["parent_id"], "a")
        self.assertEqual(row["conditions"][0]["evidence"][0]["text"], "One fact.")
        self.assertEqual(audit["rejected"], {"cross_document": 1})

    def test_full_run_gate_uses_both_thresholds(self):
        self.assertTrue(gate(95, 100, 10)["passed"])
        self.assertFalse(gate(94, 100, 9)["passed"])
        self.assertFalse(gate(100, 100, 11)["passed"])
