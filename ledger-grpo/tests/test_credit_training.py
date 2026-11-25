"""Synthetic policy-loss and existing-worker integration checks."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch

from ledger_grpo.credit.training import credit_token_loss, fixed_loss_denominator
from ledger_grpo.credit.schema import Unit, Trajectory


class CreditTrainingTests(unittest.TestCase):
    def test_fixed_denominator_and_clipping_match_hand_calculation(self):
        current = torch.log(torch.tensor([1.5, .5, 1.], dtype=torch.float64)).requires_grad_()
        result = credit_token_loss(current, torch.zeros(3, dtype=torch.float64),
            torch.tensor([2., -2., 9.], dtype=torch.float64), torch.tensor([1, 1, 0]),
            loss_denominator=20, world_size=1)
        # min(1.5*2,1.2*2) + min(.5*-2,.8*-2) = .8
        self.assertAlmostEqual(float(result['loss'].detach()), -.04)
        self.assertEqual(fixed_loss_denominator(2, 10), 20)
        with self.assertRaises(ValueError):
            fixed_loss_denominator(2, 10, normalization='trajectory_mean')

    def test_zero_advantages_and_tool_positions_have_zero_policy_gradient(self):
        logits = torch.nn.Parameter(torch.zeros(4, 7))
        logp = logits.log_softmax(-1)[:, 1]
        result = credit_token_loss(logp, logp.detach().clone(), torch.tensor([1., 0., 4., -1.]),
                                  torch.tensor([1, 1, 0, 1]), loss_denominator=16)
        result['loss'].backward()
        self.assertEqual(float(logits.grad[1].abs().sum()), 0.)
        self.assertEqual(float(logits.grad[2].abs().sum()), 0.)
        self.assertGreater(float(logits.grad[0].abs().sum()), 0.)

    def test_sampling_correction_is_applied_after_ppo_clipping_and_nll(self):
        x = torch.tensor([0., 0.], requires_grad=True)
        result = credit_token_loss(x, torch.zeros(2), torch.tensor([2., 0.]), torch.ones(2),
            loss_denominator=10, baseline_advantages=torch.tensor([1., 1.]),
            ledger_selected=True, ledger_sample_q=.5, masked_nll_mask=torch.tensor([0, 1]), process_tau=.05)
        self.assertAlmostEqual(float(result['loss'].detach()), -.2)
        result['loss'].backward()
        torch.testing.assert_close(x.grad, torch.tensor([-.3, .09]))

    def test_score_payload_loads_into_existing_worker_with_native_fixed_targets(self):
        from ledger_grpo.credit.training import make_credit_score_payload
        from test_hf_pilot_train import worker, TinyScorer, LocalCollective
        native = [{'id': f'r{i}', 'query_id': 'q', 'segments': [
            {'prompt_ids': [1], 'completion_ids': [2 + i, 4 + i], 'vllm_logprobs': [0., 0.]}]} for i in range(2)]
        trajectories = [Trajectory('q', i, [Unit('F', [(0, 2)], 2)], {'Y': i == 0, 'submitted': True},
                                   response_mask=[1, 1], traj_id=f'r{i}') for i in range(2)]
        module = worker()
        with tempfile.TemporaryDirectory() as directory:
            path, scores = Path(directory)/'batch.json', Path(directory)/'scores.pt'
            path.write_text(json.dumps({'trajectories': native, 'policy_snapshot_sha256': 'synthetic'}))
            torch.save(make_credit_score_payload(path, trajectories, {'preset': 'A'}, max_generated_tokens=8), scores)
            prepared, manifest = module.load_step_inputs(path, scores)
        self.assertEqual(prepared['loss_denominator'], 16)
        self.assertTrue(prepared['credit_mode'])
        self.assertEqual(prepared['records'][0]['action_advantages'].tolist(), [1., 1.])
        before = [row['action_advantages'].clone() for row in prepared['records']]
        model = TinyScorer()
        result = module.run_update(prepared, model, torch.optim.AdamW(model.parameters(), lr=1e-6),
                                   LocalCollective(), batch_identity='credit-batch', update_index=1)
        self.assertEqual(result['state'], 'computed')
        self.assertEqual(result['loss_denominator'], 16)
        self.assertEqual(result['credit_metrics']['result']['accuracy'], .5)
        self.assertIsNotNone(result['credit_metrics']['policy']['entropy'])
        for a,row in zip(before, prepared['records']):
            torch.testing.assert_close(a, row['action_advantages'])

    def test_auxiliary_only_batch_updates_and_rank_padding_masks_auxiliary(self):
        from test_hf_pilot_train import worker, TinyScorer, LocalCollective, prepared
        module, batch = worker(), prepared()
        batch.update(credit_mode=True, credit_config={'process_tau': .05, 'ledger_sample_q': 1.,
                                                      'ledger_sample_correction': True}, loss_denominator=16)
        for row in batch['records']:
            row['action_advantages'].zero_()
            row.update(baseline_advantages=torch.zeros_like(row['action_advantages']),
                       masked_nll_mask=torch.ones_like(row['action_mask']), ledger_selected=True)
        padded = module.rank_records(batch, rank=3, world=4)[0]
        self.assertFalse(bool(padded['masked_nll_mask'].any()))
        model = TinyScorer()
        result = module.run_update(batch, model, torch.optim.AdamW(model.parameters(), lr=1e-6),
                                   LocalCollective(), batch_identity='nll-batch', update_index=1)
        self.assertEqual(result['state'], 'computed')
        self.assertGreater(float(model.weight[2].detach()), 0.)

    def test_group_correction_does_not_clip_an_averaged_advantage(self):
        x = torch.tensor([1.5]).log().requires_grad_()
        result = credit_token_loss(x, torch.zeros(1), torch.tensor([-2.]), torch.ones(1),
            loss_denominator=10, baseline_advantages=torch.tensor([1.]), ledger_sample_q=.5)
        self.assertAlmostEqual(float(result['loss'].detach()), .72, places=6)

    def test_all_presets_and_optional_paths_reach_native_backward(self):
        from ledger_grpo.credit.config import CreditConfig, PRESETS
        from ledger_grpo.credit.providers import MockLedgerProvider
        from ledger_grpo.credit.training import prepare_credit_native_records
        from test_hf_pilot_train import worker, TinyScorer, LocalCollective
        configs = [CreditConfig.from_preset(name) for name in PRESETS]
        configs += [CreditConfig(privileged=True), CreditConfig(process_sup='masked_nll'),
                    CreditConfig(process_sup='zero_sum'), CreditConfig(ledger_sample_q=.5)]
        native, trajectories = [], []
        for i in range(8):
            native.append({'id': f'r{i}', 'query_id': 'q', 'segments': [
                {'prompt_ids': [1], 'completion_ids': [2, 3], 'vllm_logprobs': [0., 0.]},
                {'prompt_ids': [1, 2, 3, 10], 'completion_ids': [4, 5], 'vllm_logprobs': [0., 0.]},
                {'prompt_ids': [1, 2, 3, 10, 4, 5, 11], 'completion_ids': [6, 7], 'vllm_logprobs': [0., 0.]}]})
            trajectories.append(Trajectory('q', i, [Unit(1, [(0, 2)], 2, 1), Unit(2, [(3, 5)], 2, 1),
                                                   Unit('F', [(6, 8)], 2)], {'Y': False, 'submitted': True},
                                           response_mask=[1, 1, 0, 1, 1, 0, 1, 1], traj_id=f'r{i}'))
        for config in configs:
            with self.subTest(config=config):
                prepared = prepare_credit_native_records(native, trajectories, MockLedgerProvider(), config,
                                                          max_generated_tokens=10)
                self.assertEqual(prepared['loss_denominator'], 80)
                if config.process_sup == 'masked_nll':
                    self.assertGreater(prepared['metrics']['process_selected_tokens'], 0)
                model = TinyScorer()
                worker().freeze_native_old_logprobs(prepared, model, LocalCollective())
                losses = [worker().record_loss(record, prepared, model, LocalCollective())[0]['loss']
                          for record in prepared['records']]
                sum(losses).backward()
                self.assertTrue(bool(torch.isfinite(model.weight.grad).all()))

    def test_two_optimizer_epochs_share_frozen_old_policy_and_credit(self):
        from test_hf_pilot_train import worker, TinyScorer, LocalCollective, prepared
        module, batch = worker(), prepared()
        batch.update(credit_mode=True, credit_config={'process_tau': .05, 'ledger_sample_q': 1.,
                                                      'ledger_sample_correction': True}, loss_denominator=16)
        for row in batch['records']:
            row.update(baseline_advantages=row['action_advantages'].clone(),
                       masked_nll_mask=torch.zeros_like(row['action_mask']), ledger_selected=True)
        model = TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        seen = []
        def receipt(_):
            seen.append([(r['old_logprobs'].clone(), r['action_advantages'].clone(), r['freeze_fingerprint']) for r in batch['records']])
        result = module.run_ppo_updates(batch, model, optimizer, LocalCollective(), batch_identity='epochs',
                                        update_index=1, ppo_epochs=2, on_optimizer_step=receipt)
        self.assertEqual(result['optimizer_steps_this_batch'], 2)
        self.assertEqual(result['persisted_optimizer_steps'], 0)
        self.assertEqual(int(optimizer.state[model.weight]['step']), 2)
        self.assertEqual(len(seen), 2)
        for first,second in zip(*seen):
            torch.testing.assert_close(first[0], second[0])
            torch.testing.assert_close(first[1], second[1])
            self.assertEqual(first[2], second[2])
        batch['records'][0]['old_logprobs'][0] = 3.
        with self.assertRaisesRegex(ValueError, 'frozen|fingerprint'):
            module.record_loss(batch['records'][0], batch, model, LocalCollective())

    def test_outcome_presets_ignore_preloaded_ledger_without_calling_provider(self):
        from ledger_grpo.credit.config import CreditConfig
        from ledger_grpo.credit.providers import MockLedgerProvider
        from ledger_grpo.credit.schema import Group
        from ledger_grpo.credit.training import prepare_credit_native_records
        trajectories = [Trajectory('q', i, [Unit(1, [(0, 2)], 2, 1), Unit('F', [(3, 5)], 2)],
                                   {'Y': i == 0, 'submitted': True}, response_mask=[1, 1, 0, 1, 1], traj_id=f'r{i}')
                        for i in range(2)]
        group = Group('q', trajectories)
        for tr, result in zip(trajectories, MockLedgerProvider().build(group)):
            tr.records, tr.derived, tr.conds, tr.confident = tuple(result)
        original = deepcopy(trajectories)
        native = [{'id': tr.traj_id, 'query_id': 'q', 'segments': [
            {'prompt_ids': [1], 'completion_ids': [2, 3], 'vllm_logprobs': [0., 0.]},
            {'prompt_ids': [1, 2, 3, 10], 'completion_ids': [4, 5], 'vllm_logprobs': [0., 0.]}]}
            for tr in trajectories]
        class ForbiddenProvider:
            def build(self, group):
                raise AssertionError('outcome-only presets must not request a ledger')
        for name, expected_utility in [('A', 1.), ('A_eff', .99)]:
            with self.subTest(preset=name):
                prepared = prepare_credit_native_records(native, [group], ForbiddenProvider(),
                    CreditConfig.from_preset(name), max_generated_tokens=8)
                self.assertAlmostEqual(prepared['credits'][0]['U'], expected_utility)
                for credit in prepared['credits']:
                    self.assertEqual(credit['role'], {1: 'K', 'F': 'F'})
                    self.assertEqual(credit['P'], {})
                    self.assertEqual(credit['R'], {})
                    self.assertTrue(all(a == credit['A_hat'] for a in credit['A'].values()))
        self.assertEqual(trajectories, original)


if __name__ == '__main__':
    unittest.main()
