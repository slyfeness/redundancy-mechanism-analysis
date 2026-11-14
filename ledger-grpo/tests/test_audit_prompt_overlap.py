import unittest

from audit_prompt_overlap import prompt_overlap


def row(task, sample, outcome, prompt=None):
    return {"task_id": task, "sample_id": sample, "outcome": outcome, "prompt": prompt}


class PromptOverlapTests(unittest.TestCase):
    def test_tying_identical_ungraded_prompts_cancels_only_the_matching_mass(self):
        evaluations = {
            "outcome": [row("a", "a1", None, "same"), row("a", "a2", None, "other"), row("b", "b1", 1.0, "k")],
            "targeted": [row("a", "a1", None, "same"), row("a", "a2", 1.0, "positive"), row("b", "b1", 1.0, "k")],
        }
        report = prompt_overlap(evaluations, candidate="targeted")
        comparison = report["comparisons"]["targeted_minus_outcome"]
        self.assertEqual(comparison["unconstrained_delta_bounds"], [-.25, .5])
        self.assertEqual(comparison["tied_missing_prompt_delta_bounds"], [0., .25])
        self.assertEqual(report["missing_prompt_count"], 2)

    def test_only_unanimous_identical_prompt_receipts_serve_as_anchors(self):
        evaluations = {
            "P0": [row("a", "a1", 1, "unanimous"), row("a", "a2", 1, "conflict"), row("a", "a3", 0, "conflict")],
            "outcome": [row("a", "a1", None, "unanimous"), row("a", "a2", None, "conflict"), row("a", "a3", 0)],
            "targeted": [row("a", "a1", 0), row("a", "a2", None, "new"), row("a", "a3", 0)],
        }
        report = prompt_overlap(evaluations, candidate="targeted")
        self.assertEqual(report["conflicting_observed_prompt_count"], 1)
        self.assertEqual(report["arms"]["outcome"]["missing_with_unanimous_observed_prompt"], 1)
        self.assertEqual(report["arms"]["outcome"]["missing_with_conflicting_observed_prompt"], 1)
        self.assertEqual(report["comparisons"]["targeted_minus_outcome"]["anchored_prompt_delta_bounds"], [-2 / 3, 0.])
        self.assertIsNone(evaluations["outcome"][0]["outcome"])

    def test_identical_prompts_only_tie_results_within_the_same_task(self):
        evaluations = {
            "outcome": [row("a", "a1", None, "p"), row("b", "b1", 0)],
            "targeted": [row("a", "a1", 0), row("b", "b1", None, "p")],
        }
        report = prompt_overlap(evaluations, candidate="targeted")
        self.assertEqual(report["comparisons"]["targeted_minus_outcome"]["tied_missing_prompt_delta_bounds"], [-.5, .5])
