import unittest

from replay_v46 import replay, update_item


def item(attribution, reason, *, backfilled=False, name="Wrong Park", check=None):
    row = {"main_name": name, "attribution": attribution, "decision_reason": reason,
           "var": "P", "category": "place", "backfilled": backfilled}
    if check:
        row["eligibility_check"] = check
    return row


class EligibilityRemovalTest(unittest.TestCase):
    def test_removes_only_eligibility_decisions(self):
        rejected = update_item(item("aux", "eligibility_no", check="e001"))
        self.assertEqual(rejected["attribution"], "wrong_candidate")
        self.assertEqual(rejected["decision_reason"], "wrong_candidate")
        self.assertNotIn("eligibility_check", rejected)
        for attribution, reason in (("wrong_candidate", "eligible"), ("eligibility_unresolved", "eligibility_invalid")):
            self.assertEqual(update_item(item(attribution, reason, check="e001")), rejected)
        for example in (item("aux", "backfilled", backfilled=True), item("correct", "containment", backfilled=True),
                        item("none", "none", name="none"), item("aux", "aux")):
            self.assertEqual(update_item(example), example)

    def test_fold_events_preserves_repeat_costs_and_sample_slots(self):
        rows, signals = [], []
        for step, found in enumerate((item("aux", "eligibility_no", check="e001"),
                                      item("aux", "eligibility_no", check="e001"),
                                      item("correct", "exact", name="Right Park")), 1):
            record = {"trajectory_id": "demo__rep1", "stage_id": step, "C_new": ["claim"] if step == 3 else [],
                      "items": [found], "searches": [f"search {step}"], "judge_raw": [{"raw": "fixture"}],
                      "new_docids": 0, "seen_docids": 2, "idle_type": "semantic", "semantic_repeat_distances": [13],
                      "labels": {"invalid": False, "strict_repeat": False, "semantic_repeat": True,
                                 "stale_return": False, "protected_new_hypothesis": False,
                                 "F_new": False, "F_corrected": False, "wrong_candidate": False}}
            rows.append(record)
            signals.append({k: record[k] for k in ("trajectory_id", "stage_id", "C_new", "idle_type")} |
                           {"F_new": 0, "F_corrected": 0, "gen_tokens": 40, "return_tokens": 12, "invalid": False,
                            "protected_new_hypothesis": False})
        sample = [{**rows[i]["items"][0], "trajectory_id": rows[i]["trajectory_id"], "stage_id": i+1,
                   "query_index": 1, "query": rows[i]["searches"][0], "judge_raw": rows[i]["judge_raw"]} for i in (2, 0)]
        updated, costs, events, refreshed = replay(rows, signals, sample, {"demo": {"P": ("Right Park", "place")}})
        self.assertEqual([(event["event"], event["stage_id"]) for event in events], [("F_new", 1), ("F_corrected", 3)])
        self.assertEqual([row["semantic_repeat_distances"] for row in updated], [[13], [13], [13]])
        self.assertEqual([row["idle_type"] for row in costs], ["semantic"] * 3)
        self.assertEqual([row["return_tokens"] for row in costs], [12] * 3)
        self.assertEqual([row["query"] for row in refreshed], ["search 3", "search 1"])
        self.assertEqual([row["attribution"] for row in refreshed], ["correct", "wrong_candidate"])
        self.assertTrue(refreshed[1]["labels"]["F_new"])
