import unittest
from dataclasses import replace

import torch

from ledger_grpo.coexist_handoff import score_coexist_handoff
from ledger_grpo.event_price import EventPriceConfig
from ledger_grpo.hf_native import prepare_native_records


SNAPSHOT = '1' * 64
CONFIG = EventPriceConfig(group_size=2, loss_denominator=16, median_event_cost=10.)


def sample(identity, outcome, *, task='q', label=None, complete=True):
    native = dict(id=identity, query_id=task, reward=outcome, segments=[
        dict(prompt_ids=[11], completion_ids=[12, 13], vllm_logprobs=[-.5, -.5]),
        dict(prompt_ids=[11, 12, 13, 14], completion_ids=[15, 16], vllm_logprobs=[-.5, -.5]),
    ])
    row = dict(traj_id=identity, task_id=task, outcome=outcome, recording_complete=complete,
               termination_reason='normal' if outcome else 'budget_exhausted',
               response_mask=[1, 1, 0, 1, 1], grounding=.5 if outcome else None,
               policy_snapshot_id=SNAPSHOT,
               labeler_versions=dict(judge_model='judge-v1', prompt_hashes={'r1': 'a' * 64}, code_commit='b' * 40),
               events=[dict(event_id='repeat', turn_id=2, known_at=2, event_tokens=[3, 5], label=label,
                            event_cost=dict(generated_tokens=2, returned_tokens=7, tool_calls=1))])
    return row, native


def score(rows, native, config=CONFIG, *, diagnostics=(), snapshot=SNAPSHOT, **batch_metadata):
    batch = dict(trajectories=native, **(batch_metadata or {'policy_snapshot_sha256': SNAPSHOT}))
    return score_coexist_handoff(rows, config, native_batch=batch, expected_policy_snapshot_id=snapshot,
                                r1_diagnostics=diagnostics)


def r1(identity, event, prediction='positive'):
    return dict(traj_id=identity, task_id='q', policy_snapshot_id=SNAPSHOT, event_id=event,
                turn_id=2, known_at=2, prediction=prediction, reason='prefix_observation')


class CoexistHandoffTests(unittest.TestCase):
    def setUp(self):
        self.success, self.native_success = sample('success', 1)
        self.budget, self.native_budget = sample('budget', 0, label='R2b')
        self.rows = [self.success, self.budget]
        self.native = [self.native_success, self.native_budget]

    def test_native_order_preserves_existing_cost_grounding_and_budget_credit(self):
        result = score([self.budget, self.success], self.native)
        scores = result['scores']
        self.assertEqual([row['traj_id'] for row in scores['process_inputs']], ['success', 'budget'])
        self.assertEqual([row['r2b_event_ids'] for row in result['dispositions']], [[], ['repeat']])
        expected = torch.tensor([[1.05, 1.05, 0, 1.05, 1.05], [-1.05, -1.05, 0, -1.15, -1.15]])
        torch.testing.assert_close(scores['advantages'], expected)
        self.assertEqual(scores['charged'], [dict(traj_id='budget', event_id='repeat', event_tokens=[3, 5], price=.1)])
        self.assertEqual(scores['loss_denominator'], 16)
        self.assertEqual(prepare_native_records(self.native, scores)['global_token_count'], 8)

    def test_batch_identity_guards_reject_missing_extra_duplicate_wrong_task_and_outcome(self):
        extra, _ = sample('unexpected', 0)
        for rows in ([self.success], self.rows + [extra], [self.success, self.success],
                     [self.success, dict(self.budget, task_id='other')],
                     [self.success, dict(self.budget, outcome=1)]):
            with self.subTest(rows=[row['traj_id'] for row in rows]), self.assertRaises(ValueError):
                score(rows, self.native)
        with self.assertRaises(ValueError):
            score(self.rows, [self.native_success, self.native_success])

    def test_snapshot_guards_reject_stale_unbound_and_conflicting_inputs(self):
        other_snapshot = '2' * 64
        with self.assertRaises(ValueError):
            score([self.success, dict(self.budget, policy_snapshot_id=other_snapshot)], self.native)
        with self.assertRaises(ValueError):
            score(self.rows, self.native, policy_snapshot_sha256=other_snapshot, policy_snapshot_id=SNAPSHOT)
        with self.assertRaises(ValueError):
            rows = [dict(row, policy_snapshot_id='malformed') for row in self.rows]
            score(rows, self.native, snapshot='malformed', policy_snapshot_sha256='malformed')
        with self.assertRaises(ValueError):
            score(self.rows, self.native, unbound=True)

    def test_labeler_versions_are_required_and_preserved(self):
        result = score(self.rows, self.native)
        self.assertEqual(result['dispositions'][0]['labeler_versions'], self.success['labeler_versions'])
        for key in ('judge_model', 'prompt_hashes', 'code_commit'):
            versions = {k: v for k, v in self.budget['labeler_versions'].items() if k != key}
            with self.subTest(key=key), self.assertRaises(ValueError):
                score([self.success, dict(self.budget, labeler_versions=versions)], self.native)

    def test_exclusion_covers_explicit_exclusion_and_its_native_peers(self):
        result = score([self.success, dict(self.budget, exclusion_reason='native_receipt_unavailable')], self.native)
        self.assertEqual(result['scores']['valid_rows'].tolist(), [False, False])
        self.assertEqual([(row['status'], row['reason']) for row in result['dispositions']], [
            ('excluded', 'peer_trajectory_excluded'), ('excluded', 'native_receipt_unavailable')])
        self.assertEqual(result['scores']['charged'], [])

    def test_incomplete_recording_excludes_its_native_group(self):
        result = score([self.success, dict(self.budget, recording_complete=False)], self.native)
        self.assertEqual(result['scores']['valid_rows'].tolist(), [False, False])
        self.assertEqual([row['reason'] for row in result['dispositions']],
                         ['peer_trajectory_excluded', 'recording_incomplete'])

    def test_unresolved_native_outcome_is_excluded_and_kept_in_its_group(self):
        rows = [self.success, dict(self.budget, outcome=None)]
        native = [self.native_success, dict(self.native_budget, reward=None)]
        result = score(rows, native)
        self.assertEqual(result['scores']['valid_rows'].tolist(), [False, False])
        self.assertEqual([row['reason'] for row in result['dispositions']],
                         ['peer_trajectory_excluded', 'unresolved_outcome'])

    def test_retains_binary_rewards_serialized_as_floats_by_the_native_recorder(self):
        native = [dict(self.native_success, reward=1.0), dict(self.native_budget, reward=0.0)]
        self.assertEqual(score(self.rows, native)['scores']['valid_rows'].tolist(), [True, True])

    def test_rejects_non_native_mask_and_future_or_invalid_event_coordinates(self):
        with self.assertRaises(ValueError):
            score([self.success, dict(self.budget, response_mask=[1, 1, 1, 1, 1])], self.native)
        for fields in (dict(known_at=3), dict(known_at=True), dict(event_tokens=[2, 4]),
                       dict(event_cost=dict(generated_tokens=1, returned_tokens=7, tool_calls=1))):
            changed = dict(self.budget['events'][0], **fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                score([self.success, dict(self.budget, events=[changed])], self.native)

    def test_rejects_semantic_labels_or_prices_in_pricing_inputs(self):
        for label in ('R1', 'R2a'):
            changed = dict(self.budget['events'][0], label=label)
            with self.subTest(label=label), self.assertRaises(ValueError):
                score([self.success, dict(self.budget, events=[changed])], self.native)
        for config in (replace(CONFIG, r1_price=.1), replace(CONFIG, r2a_price=.1)):
            with self.subTest(config=config), self.assertRaises(ValueError):
                score(self.rows, self.native, config)

    def test_r1_sidecar_preserves_unmeasured_observations_without_changing_scores(self):
        baseline = score(self.rows, self.native)['scores']
        for prediction in ('positive', 'negative'):
            diagnostics = [r1('budget', 'repeat', prediction), r1('success', 'unmeasured', 'uncertain')]
            result = score(self.rows, self.native, diagnostics=diagnostics)
            torch.testing.assert_close(result['scores']['advantages'], baseline['advantages'])
            self.assertEqual(result['scores']['charged'], baseline['charged'])
            self.assertEqual(result['scores']['metrics'], baseline['metrics'])
            self.assertEqual(result['r1_sidecar']['policy_snapshot_id'], SNAPSHOT)
            self.assertEqual([(row['event_id'], row['prediction']) for row in result['r1_sidecar']['diagnostics']],
                             [('unmeasured', 'uncertain'), ('repeat', prediction)])

    def test_r1_sidecar_checks_snapshot_native_binding_and_causal_boundary(self):
        diagnostic = r1('budget', 'repeat')
        for fields in (dict(policy_snapshot_id='2' * 64), dict(traj_id='missing'), dict(task_id='other'),
                       dict(known_at=3), dict(turn_id=1, known_at=1)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                score(self.rows, self.native, diagnostics=[dict(diagnostic, **fields)])
