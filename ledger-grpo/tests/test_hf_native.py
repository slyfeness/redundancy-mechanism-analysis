import importlib
import math
import unittest

import torch


def native_fixture():
    return [
        {'id': 'a', 'query_id': 'q1', 'segments': [
            {'prompt_ids': [10, 11], 'completion_ids': [12, 13], 'vllm_logprobs': [-1., -2.]},
            {'prompt_ids': [10, 11, 12, 13, 99], 'completion_ids': [14], 'vllm_logprobs': [-3.]},
            {'prompt_ids': [20, 21], 'completion_ids': [22, 23], 'vllm_logprobs': [-4., -5.]},
        ]},
        {'id': 'b', 'query_id': 'q2', 'segments': [
            {'prompt_ids': [30], 'completion_ids': [31], 'vllm_logprobs': [-6.]},
        ]},
    ]


def score_fixture():
    return {'process_inputs': [
        {'traj_id': 'b', 'task_id': 'q2', 'response_mask': [1]},
        {'traj_id': 'a', 'task_id': 'q1', 'response_mask': [1, 1, 0, 1, 1, 1]},
    ], 'advantages': torch.tensor([[-2., 0., 0., 0., 0., 0.], [1., 2., 0., 3., 4., 5.]]),
        'effective_response_mask': torch.tensor([[1, 0, 0, 0, 0, 0], [1, 1, 0, 1, 1, 1]]),
        'valid_rows': torch.tensor([True, True])}


class NativeTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('ledger_grpo.hf_native')
        except ImportError as exc:
            self.fail(f'HF native adapter is missing: {exc}')

    def test_layout_preserves_every_call_action_and_excludes_observation_gap(self):
        layout = self.api().native_turn_layout(native_fixture()[0])
        self.assertEqual(layout['response_mask'], [1, 1, 0, 1, 1, 1])
        self.assertEqual([(t['call_index'], t['span_index'], t['token_start'], t['token_end'])
                          for t in layout['turns']], [(0, 0, 0, 2), (1, 0, 3, 4), (2, 1, 4, 6)])
        self.assertEqual([t['turn_id'] for t in layout['turns']], [1, 2, 3])
        self.assertEqual(layout['spans'][0]['prompt_ids'], [10, 11])
        self.assertEqual(layout['spans'][0]['completion_ids'], [12, 13, 99, 14])
        self.assertEqual(layout['spans'][0]['action_offsets'], [0, 1, 3])
        self.assertEqual(layout['spans'][0]['vllm_logprobs'], [-1., -2., -3.])

    def test_records_align_by_identity_and_flatten_action_advantages_exactly(self):
        result = self.api().prepare_native_records(native_fixture(), score_fixture())
        self.assertEqual(result['global_token_count'], 6)
        records = result['records']
        self.assertEqual([r['trajectory_id'] for r in records], ['a', 'a', 'b'])
        self.assertEqual([r['action_advantages'].tolist() for r in records], [[1., 2., 3.], [4., 5.], [-2.]])
        self.assertEqual([r['action_count'] for r in records], [5, 5, 1])
        self.assertEqual([r['action_mask'].tolist() for r in records], [[True] * 3, [True] * 2, [True]])
        self.assertEqual(result['trajectory_actions']['a']['advantages'].tolist(), [1., 2., 3., 4., 5.])

    def test_invalid_rows_are_removed_and_empty_batch_is_explicit(self):
        module = self.api()
        score = score_fixture()
        score['valid_rows'][0] = False
        score['effective_response_mask'][0] = 0
        score['advantages'][0] = 0
        result = module.prepare_native_records(native_fixture(), score)
        self.assertEqual(result['global_token_count'], 5)
        self.assertEqual(result['metrics']['dropped_trajectory_count'], 1)
        score['valid_rows'][:] = False
        score['effective_response_mask'][:] = 0
        score['advantages'][:] = 0
        result = module.prepare_native_records(native_fixture(), score)
        self.assertEqual(result['global_token_count'], 0)
        self.assertEqual(result['records'], [])
        self.assertTrue(result['skip_update'])

    def test_misaligned_masks_ids_probabilities_and_nonzero_tool_credit_are_rejected(self):
        module = self.api()
        for error in ('partial_mask', 'tool_credit', 'wrong_id', 'wrong_group', 'native_length', 'probability_length', 'nan'):
            with self.subTest(error=error):
                native, score = native_fixture(), score_fixture()
                if error == 'partial_mask':
                    score['effective_response_mask'][1, 1] = 0
                elif error == 'tool_credit':
                    score['advantages'][1, 2] = .1
                elif error == 'wrong_id':
                    score['process_inputs'][1]['traj_id'] = 'other'
                elif error == 'wrong_group':
                    score['process_inputs'][1]['task_id'] = 'q2'
                elif error == 'native_length':
                    native[0]['segments'][1]['prompt_ids'].append(99)
                elif error == 'probability_length':
                    native[0]['segments'][0]['vllm_logprobs'].pop()
                else:
                    score['advantages'][1, 0] = float('nan')
                with self.assertRaises(ValueError):
                    module.prepare_native_records(native, score)

    def test_global_token_mean_and_fsdp_scaling_match_hand_computed_gradient(self):
        module = self.api()
        current = torch.zeros(3, dtype=torch.float64, requires_grad=True)
        sampled = torch.tensor([0., -math.log(4), 0.], dtype=torch.float64)
        advantage = torch.tensor([2., -1., 99.], dtype=torch.float64, requires_grad=True)
        result = module.single_step_token_loss(current, sampled, advantage, torch.tensor([1, 1, 0]),
                                               global_token_count=5, world_size=4)
        self.assertAlmostEqual(result['loss_numerator'].item(), 0.)
        self.assertEqual(result['global_token_count'], 5)
        self.assertEqual(result['world_scale'], 4 / 5)
        result['loss'].backward()
        torch.testing.assert_close(current.grad, torch.tensor([-1.6, 1.6, 0.], dtype=torch.float64))
        self.assertIsNone(advantage.grad)
        self.assertEqual(result['diagnostics']['tis_cap_fraction'], .5)
        self.assertAlmostEqual(result['diagnostics']['sampled_logprob_abs_error_mean'], math.log(4) / 2)
        self.assertFalse(result['diagnostics']['ppo_ratio_is_stability_metric'])

    def test_unequal_rank_shards_average_to_global_loss_including_zero_padding(self):
        module = self.api()
        full = torch.zeros(4, dtype=torch.float64, requires_grad=True)
        adv = torch.tensor([1., 3., -2., 4.], dtype=torch.float64)
        whole = module.single_step_token_loss(full, torch.zeros(4), adv, torch.ones(4),
                                              global_token_count=4, world_size=1)['loss']
        a = module.single_step_token_loss(full[:3], torch.zeros(3), adv[:3], torch.ones(3),
                                          global_token_count=4, world_size=2)['loss']
        b = module.single_step_token_loss(full[3:], torch.zeros(1), adv[3:], torch.ones(1),
                                          global_token_count=4, world_size=2)['loss']
        padding = module.single_step_token_loss(full[:2], torch.zeros(2), adv[:2], torch.zeros(2),
                                                global_token_count=4, world_size=2)['loss']
        torch.testing.assert_close((a + b + padding) / 2, whole)
        torch.testing.assert_close(torch.autograd.grad((a + b + padding) / 2, full, retain_graph=True)[0],
                                   torch.autograd.grad(whole, full)[0])

    def test_loss_rejects_invalid_denominator_shape_and_nonfinite_logprobs(self):
        module = self.api()
        for kwargs in ({'global_token_count': 0, 'world_size': 4},
                       {'global_token_count': 1, 'world_size': 4},
                       {'global_token_count': 2, 'world_size': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                module.single_step_token_loss(torch.zeros(2), torch.zeros(2), torch.ones(2), torch.ones(2), **kwargs)
        with self.assertRaises(ValueError):
            module.single_step_token_loss(torch.zeros(2), torch.zeros(1), torch.ones(2), torch.ones(2),
                                           global_token_count=2, world_size=1)
        with self.assertRaises(ValueError):
            module.single_step_token_loss(torch.tensor([float('nan')]), torch.zeros(1), torch.ones(1), torch.ones(1),
                                           global_token_count=1, world_size=1)


if __name__ == '__main__':
    unittest.main()
