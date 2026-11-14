"""Hand-computed evaluation fixtures, with task-cluster inference."""

import importlib
import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def run(task, cost, outcome=1, complete=True, **extra):
    return dict(task_id=task, cost=cost, outcome=outcome, complete=complete, **extra)


def annotation(task, turn, verdict, label="R1"):
    return dict(task_id=task, traj_id="t", turn_id=turn, label=label, verdict=verdict)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module("ledger_grpo.evaluation")
        except ModuleNotFoundError as exc:
            self.fail(f"Evaluation module is not yet implemented: {exc}")

    def test_summary_counts_failed_cost_and_missing_budget_coverage(self):
        rows = [run("a", 2, budget=2, gen_tokens=20), run("a", 6, 0, False, budget=3), run("b", 10, tool_calls=4)]
        got = self.module.summarize_runs(rows)
        self.assertEqual(got["accuracy"], 2 / 3)
        self.assertEqual(got["completion_rate"], 2 / 3)
        self.assertEqual(got["cost"]["mean"], 6)
        self.assertEqual(got["cost"]["median"], 6)
        self.assertEqual(got["cost"]["std"], 4)
        self.assertAlmostEqual(got["cost"]["p90"], 9.2)
        self.assertAlmostEqual(got["cost"]["p95"], 9.6)
        self.assertEqual(got["cost_per_success"], 9)
        self.assertEqual(got["budget_coverage"], 2 / 3)
        self.assertEqual(got["over_budget_rate"], .5)
        self.assertEqual(got["mean_relative_budget_error"], .5)
        self.assertEqual(got["mean_excess_when_over"], 3)
        self.assertAlmostEqual(got["within_task_cv"], math.sqrt(8) / 4)
        self.assertEqual(got["within_task_cv_task_count"], 1)
        self.assertEqual(got["optional_fields"]["gen_tokens"]["coverage"], 1 / 3)

    def test_empty_and_zero_success_have_defined_missing_values(self):
        empty = self.module.summarize_runs([])
        self.assertIsNone(empty["accuracy"])
        self.assertIsNone(empty["cost"]["std"])
        self.assertIsNone(empty["over_budget_rate"])
        self.assertEqual(empty["budget_coverage"], 0)
        got = self.module.summarize_runs([run("a", 0, 0), run("a", 0, 0)])
        self.assertIsNone(got["cost_per_success"])
        self.assertIsNone(got["within_task_cv"])
        self.assertEqual(got["cost"]["std"], 0)
        self.assertIsNone(self.module.summarize_runs([run("a", 1)])["cost"]["std"])

    def test_invalid_cost_budget_and_outcome_rejected(self):
        for row in (run("a", -1), run("a", float("nan")), run("a", 1, budget=0), run("a", 1, outcome=.5), run("a", 1, complete=1)):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.module.summarize_runs([row])

    def test_missing_outcome_withholds_full_set_accuracy_delta(self):
        baseline = [run('a',3,0,sample_id='a1'), run('b',4,1,sample_id='b1')]
        candidate = [run('a',5,0,sample_id='a1'), run('b',6,None,sample_id='b1')]
        result = self.module.paired_event_diagnostics(baseline,candidate,resamples=20)['delta']
        self.assertEqual(result['outcome']['task_count'],1)
        self.assertIsNone(result['outcome']['estimate'])
        self.assertIsNone(result['outcome']['ci95'])
        self.assertEqual(result['outcome']['missing_verdict_delta_bounds'],[-.5,0.])
        self.assertEqual(result['cost']['estimate'],2.)

    def test_gap_audit_matches_frozen_artifacts_and_keeps_missing_as_unknown(self):
        from ledger_grpo.cli import main

        def write(path, value):
            raw = json.dumps(value).encode()
            path.write_bytes(raw)
            return hashlib.sha256(raw).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            evaluation, requirements, review = (p/name for name in ('eval.json', 'requirements.json', 'review.json'))
            baseline, candidate, comparison = (p/name for name in ('before.json', 'after.json', 'diff.json'))
            evaluation_sha = write(evaluation, {'rows': [run('a', 3, 0, sample_id='a1'), run('b', 4, None, sample_id='b1')]})
            requirements_sha = write(requirements, {'a': {'gap1': 'first fact', 'gap2': 'second fact'}, 'b': {'gap1': 'test result'}})
            checks = [dict(task_id='a', sample_id='a1', gap_id='gap1', verdict='closed', evidence_refs=['return-1']),
                      dict(task_id='b', sample_id='b1', gap_id='gap1', verdict='open')]
            payload = dict(evaluation_sha256=evaluation_sha, requirements_sha256=requirements_sha,
                           protocol_id='review-v1', checks=checks)
            write(review, payload)

            def audit(output):
                return main(['audit-gaps', '--evaluation', str(evaluation), '--requirements', str(requirements),
                             '--reviews', str(review), '--output', str(output)])

            self.assertEqual(audit(baseline), 0)
            before = json.loads(baseline.read_bytes())
            self.assertEqual(before['gap_review']['observed'], 2)
            self.assertEqual(before['gap_review']['expected'], 3)
            self.assertIsNone(before['mean_necessary_gap_closure'])
            self.assertIsNone(before['rows'][0]['necessary_gap_closure'])
            self.assertEqual(before['rows'][0]['necessary_gap_closure_bounds'], [.5, 1.])
            self.assertEqual(before['rows'][0]['outcome'], 0)
            self.assertNotIn('return-1', baseline.read_text())
            checks.append(dict(task_id='a', sample_id='a1', gap_id='gap2', verdict='closed', evidence_refs=['return-2']))
            write(review, payload)
            self.assertEqual(audit(candidate), 0)
            self.assertEqual(json.loads(candidate.read_bytes())['mean_necessary_gap_closure'], .5)
            main(['compare-events', '--baseline', str(baseline), '--candidate', str(candidate), '--output', str(comparison)])
            comparison_result = json.loads(comparison.read_bytes())['delta']['necessary_gap_closure']
            self.assertIsNone(comparison_result['estimate'])
            self.assertEqual(comparison_result['missing_review_delta_bounds'], [0., .25])

            evaluation.write_bytes(evaluation.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError, 'evaluation SHA'):
                audit(p/'stale.json')
            evaluation.write_bytes(evaluation.read_bytes()[:-1])
            checks[-1]['evidence_refs'] = []
            write(review, payload)
            with self.assertRaisesRegex(ValueError, 'evidence'):
                audit(p/'unsupported.json')

    def test_reasoning_usage_never_treats_missing_native_usage_as_zero(self):
        raw = [{'response_received':True,'reasoning_tokens':None,'token_accounting':{
            'reasoning_field_retokenized_tokens':194,'reasoning_retokenized_is_derived_not_serving_usage':True}},
               {'response_received':True,'reasoning_tokens':None}]
        result = self.module.summarize_reasoning_usage([self.module.reasoning_usage(raw)])
        self.assertEqual(result['reasoning_rounds'],2)
        self.assertIsNone(result['reasoning_tokens_per_round'])
        self.assertEqual(result['reasoning_derived_rounds'],1)
        self.assertEqual(result['reasoning_derived_tokens_per_round'],194.)

    def test_annotation_abstention_and_task_macro_are_distinct_from_stage_pooling(self):
        gold = [annotation("a", 1, "positive"), annotation("a", 2, "positive"), annotation("b", 1, "negative"), annotation("c", 1, "uncertain")]
        pred = [annotation("a", 1, "positive"), annotation("b", 1, "positive"), annotation("c", 1, "positive")]
        got = self.module.evaluate_annotations(pred, gold)
        r1 = got["by_label"]["R1"]
        self.assertEqual(r1["confusion"], {"tp": 1, "fp": 1, "tn": 0, "fn": 0, "abstain_positive": 1, "abstain_negative": 0})
        self.assertEqual(r1["precision"], .5)
        self.assertEqual(r1["recall"], .5)
        self.assertEqual(r1["f1"], .5)
        self.assertEqual(r1["abstention_rate"], 1 / 3)
        self.assertEqual(r1["uncertain_gold_count"], 1)
        self.assertEqual(r1["task_count"], 2)
        self.assertEqual(r1["macro_by_task"]["precision"], .5)
        self.assertEqual(r1["macro_by_task"]["recall"], .5)
        self.assertEqual(got["by_family"]["R"]["precision"], .5)

    def test_annotation_keys_are_strict_and_missing_predictions_abstain(self):
        gold = [annotation("a", 1, "positive")]
        got = self.module.evaluate_annotations([], gold)["by_label"]["R1"]
        self.assertIsNone(got["precision"])
        self.assertEqual(got["recall"], 0)
        self.assertEqual(got["f1"], 0)
        self.assertEqual(got["abstention_rate"], 1)
        for pred, truth in ((gold + gold, gold), ([annotation("a", 2, "positive")], gold), (gold, gold + gold)):
            with self.subTest(pred=pred, truth=truth), self.assertRaises(ValueError):
                self.module.evaluate_annotations(pred, truth)

    def test_bootstrap_samples_tasks_not_individual_stages(self):
        base = [run("a", 10, 0)] + [run("b", 10, 0)] * 3
        candidate = [run("a", 6, 1)] + [run("b", 8, 0)] * 3
        got = self.module.paired_bootstrap(base, candidate, seed=9, resamples=200)
        self.assertEqual(got["accuracy_delta"]["estimate"], .5)
        self.assertEqual(got["cost_delta"]["estimate"], -3)
        self.assertEqual(got["accuracy_delta"]["ci95"], [0, 1])
        self.assertEqual(got["cost_delta"]["ci95"], [-4, -2])
        self.assertEqual(got, self.module.paired_bootstrap(base, candidate, seed=9, resamples=200))

    def test_bootstrap_rejects_unmatched_tasks_counts_and_sample_ids(self):
        for base, candidate in (
            ([run("a", 1)], [run("b", 1)]),
            ([run("a", 1)], [run("a", 1), run("a", 2)]),
            ([run("a", 1, sample_id="s1")], [run("a", 1, sample_id="s2")]),
            ([run("a", 1, sample_id="s1")], [run("a", 1)]),
        ):
            with self.subTest(base=base, candidate=candidate), self.assertRaises(ValueError):
                self.module.paired_bootstrap(base, candidate)
        with self.assertRaises(ValueError):
            self.module.paired_bootstrap([], [])

    def test_deletion_categories_are_outcome_stability_not_redundancy_labels(self):
        category = self.module.deletion_category
        self.assertEqual(category(True, [True, True, True, False]), "A")
        self.assertEqual(category(True, [False, False, False, True]), "B_plus")
        self.assertEqual(category(False, [True, True, True, False]), "B_minus")
        self.assertEqual(category(False, [False, False, False, False]), "gray")
        self.assertEqual(category(True, [True, True, False, False]), "gray")
        self.assertEqual(category(True, [True] * 4, guide_confounded=True), "confounded")
        with self.assertRaises(ValueError):
            category(True, [True] * 3, guide_confounded=True)
        with self.assertRaises(ValueError):
            category(True, [1, 1, 1, 1])


if __name__ == "__main__":
    unittest.main()
