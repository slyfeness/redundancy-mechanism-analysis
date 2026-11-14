from copy import deepcopy
import unittest

from ledger_grpo.advantages import AdvantageConfig
from ledger_grpo.pipeline import analyze_trajectory, score_batch


def item(name, outcome, complete=True):
    return {"traj_id": name, "task_id": "same", "task": "Find A", "constraints": [{"cid": "c", "text": "A"}],
            "complete": complete, "outcome": outcome, "response_mask": [1, 1],
            "turns": [{"turn_id": 1, "token_start": 0, "token_end": 2, "action": {"kind": "other"}}]}


class BudgetFailureTests(unittest.TestCase):
    def score(self, traces, policy):
        reports = [analyze_trajectory(t, deltas={1: {"facts": []}}) for t in traces]
        return score_batch(traces, reports, config=AdvantageConfig(process_enabled=True), budget_failure_policy=policy)

    def test_explicit_budget_failure_keeps_failure_credit_but_disables_group_process(self):
        traces = [item("success", 1), dict(item("budget", 0, False), termination_reason="budget_exhausted", recording_complete=True)]
        self.assertEqual(self.score(traces, "exclude")["valid_rows"].sum().item(), 0)
        scored = self.score(traces, "outcome_only")
        self.assertEqual(scored["valid_rows"].tolist(), [True, True])
        self.assertLess(scored["advantages"][1, 0].item(), 0)
        self.assertEqual(scored["metrics"]["process_row_count"], 0)
        self.assertEqual(scored["metrics"]["retained_budget_failures"], ["budget"])
        self.assertFalse(traces[1]["complete"])

    def test_tool_failure_or_missing_recording_is_never_promoted(self):
        for reason, recorded in [("tool_error", True), ("budget_exhausted", False), ("unknown", True)]:
            with self.subTest(reason=reason):
                traces = [item("success", 1), dict(item("bad", 0, False), termination_reason=reason, recording_complete=recorded)]
                self.assertEqual(self.score(traces, "outcome_only")["valid_rows"].sum().item(), 0)

    def test_false_budget_success_is_rejected(self):
        traces = [dict(item("bad", 1, False), termination_reason="budget_exhausted", recording_complete=True)]
        with self.assertRaises(ValueError):
            self.score(traces, "outcome_only")


if __name__ == "__main__":
    unittest.main()
