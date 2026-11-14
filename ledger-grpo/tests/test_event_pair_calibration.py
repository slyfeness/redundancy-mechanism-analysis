import unittest

from ledger_grpo.evaluation import audit_event_labels
from ledger_grpo.event_pair_calibration import paired_calibration_row


class EventPairCalibrationTest(unittest.TestCase):
    def setUp(self):
        self.case = dict(case_id='sample/event', event_id='2', trajectory_sha256='1'*64, label='R1',
                         prediction='positive', human_verdict='necessary', original_correct=True,
                         guide_confounded=False)
        self.audit = dict(sample_id='sample', event_id='2', trajectory_sha256='1'*64, continuation_round=3,
                          normal_prompt_sha256='2'*64, delete_prompt_sha256='3'*64)
        self.branches = []
        for seed in (101, 102, 103, 104):
            for condition in ('normal', 'delete'):
                identity = dict(sample_id='sample', event_id='2', trajectory_sha256='1'*64,
                                condition=condition, seed=seed, continuation_round=3,
                                prefix_sha256=self.audit[f'{condition}_prompt_sha256'],
                                audit_sha256='4'*64, runtime_sha256='5'*64)
                self.branches.append((dict(identity=identity, terminal='MODEL_FINAL_STOP'), condition == 'normal'))

    def row(self):
        return paired_calibration_row(self.case, self.audit, '4'*64, self.branches)

    def test_positive_deletion_matches_pricing_audit(self):
        row = self.row()
        self.assertEqual(len(row['deletions']), 4)
        self.assertEqual(row['paired_counts']['normal_only_correct'], 4)
        metrics = audit_event_labels([row], require_event_binding=True)['R1']
        self.assertEqual(metrics['counts']['B_plus'], 1)

    def test_unstable_control_is_kept_out_of_deletion_metrics(self):
        self.branches[0] = (self.branches[0][0], False)
        self.branches[2] = (self.branches[2][0], False)
        row = self.row()
        self.assertTrue(all(not result['comparable'] for result in row['deletions']))
        self.assertEqual(row['paired_counts']['normal_only_correct'], 2)

    def test_mismatched_prefix_or_runtime_cannot_pair(self):
        identity = self.branches[-1][0]['identity']
        for field in ('prefix_sha256', 'runtime_sha256', 'seed'):
            previous = identity[field]
            identity[field] = 999 if field == 'seed' else '6'*64
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.row()
            identity[field] = previous

    def test_budget_stop_counts_as_failure_but_tool_fault_is_unresolved(self):
        branch, _ = self.branches[-1]
        branch['terminal'] = 'CONTEXT_LIMIT_STOP'
        self.branches[-1] = (branch, None)
        self.assertTrue(all(r['comparable'] for r in self.row()['deletions']))
        branch['terminal'] = 'RUNTIME_ERROR'
        self.assertTrue(all(not r['comparable'] for r in self.row()['deletions']))
