import unittest

from rules import cleanup, failed_slots, outcome_label, resolve


class CleanupTest(unittest.TestCase):
    def test_applies_all_four_rules_and_records_substitution(self):
        entities = [{"var": "A2021", "name": "Ｎｅｂｕｌａ Kite", "role": "invented artist"},
                    {"var": "B", "name": "Reed Vale", "role": "invented subject"}]
        claims = [{"id": "1", "subject": "B", "claim": "Contacted A2021."},
                  {"id": "2", "subject": "B", "claim": "Contacted a kite."},
                  {"id": "3", "subject": "B", "claim": "Contacted a kite."},
                  {"id": "4", "subject": "C", "claim": "Claim has no corresponding actor."},
                  {"id": "5", "subject": "A2021", "claim": "A synthetic claim."},
                  {"id": "6", "subject": "B", "claim": "A20210 was mentioned."}]
        result, log = cleanup("q", {"entities": entities, "conditions": claims}, ["nebula-kite"])
        self.assertEqual([r["id"] for r in result["conditions"]], ["2", "6"])
        self.assertEqual(result["conditions"][1]["claim"], "A20210 was mentioned.")
        self.assertEqual({r["reason"] for r in log},
                         {"answer_in_claim", "answer_in_subject", "duplicate_claim",
                          "unknown_subject", "entity_variable_replaced"})
        self.assertIn("Contacted Ｎｅｂｕｌａ Kite.", [r["after"] for r in log if r["action"] == "replace"])

    def test_matching_is_normalized_substring_without_empty_alias(self):
        row = {"entities": [{"var": "P", "name": "Artist", "role": "fixture"}],
               "conditions": [{"id": "a", "subject": "P", "claim": "Talked about BLUE–SUNrise."}]}
        result, audit = cleanup("q", row, ["", "blue sun"])
        self.assertFalse(result["conditions"])
        self.assertEqual(audit[0]["reason"], "answer_in_claim")


class JudgeRetryTest(unittest.TestCase):
    def test_preserve_first_valid_and_do_not_count_remaining_invalid_as_unknown(self):
        good = {"id": "a", "status": "unknown", "reason": "different entity", "valid": True}
        bad = {"id": "b", "status": "unknown", "reason": "schema problem", "valid": False}
        retry = [{**good, "status": "supported"}, bad]
        merged = resolve([good, bad], retry)
        self.assertEqual(failed_slots([good, bad]), {"b"})
        self.assertEqual([outcome_label(r) for r in merged], ["different_entity", "invalid"])
        self.assertEqual(merged[0], good)
        self.assertEqual(merged[1]["status"], "invalid")

    def test_retry_can_recover_missing_slot(self):
        bad = {"id": "b", "status": "unknown", "reason": "bad record", "valid": False}
        fixed = {**bad, "status": "partial", "valid": True}
        self.assertEqual(resolve([bad], [fixed]), [fixed])


class OverflowTest(unittest.TestCase):
    def test_preserves_one_per_document_before_filling_by_rank(self):
        from context import choose

        ranked = [{"id": f"d:{n}", "docid": "d"} for n in range(4)] + [{"id": "e:1", "docid": "e"}]
        size, kept = choose(ranked, len, document_ids=("d", "e"), limit=3)
        self.assertEqual((size, [b["id"] for b in kept]), (3, ["d:0", "d:1", "e:1"]))
        self.assertEqual(choose(ranked, len, limit=2), (2, ranked[:2]))

    def test_gold_flag_denominators_include_only_retained_claims(self):
        from settlement import condition_counts

        questions = {"a": {}, "b": {}, "c": {}}
        records = {"a": {"conditions": [{}]}, "b": {"conditions": [{}, {}]}, "c": {"conditions": []}}
        gold = [{"query_id": "a", "not_supported_by_gold": True},
                {"query_id": "b", "not_supported_by_gold": False},
                {"query_id": "b", "not_supported_by_gold": False}]
        summary = condition_counts(questions, records, gold, [{"query_id": "a", "phase": "assertion"}])
        self.assertEqual(summary["overflow"]["under_two"], 1)
        self.assertEqual(summary["overflow"]["gold_marked"], 1)
        self.assertEqual(summary["complete_input"]["assertions"], 2)
        self.assertEqual(summary["complete_input"]["under_two"], 1)
