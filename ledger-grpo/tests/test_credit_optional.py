"""Synthetic contracts for optional credit modules; no external services."""
import unittest
from types import SimpleNamespace

from ledger_grpo.credit import process_sup, sampling, continuation


class OptionalCreditTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(process_sup='masked_nll', process_tau=.05,
                                      alpha_zs=.1, kappa=3.)
        self.trajs = [{'outcome': {'Y': False, 'submitted': True}, 'qid': 'toy'}] * 2
        self.credit = {'A_hat': -.2, 'role': {1: 'C', 2: 'R', 3: 'C', 4: 'C', 'F': 'F'},
                       'P': {1: [(.1, '采纳E1')], 3: [(.1, '取到E2(未被用)')],
                             4: [(.1, '取到E3')], 'F': [(.1, '采纳E4')]},
                       'R': {2: [(.1, '没用E5')]},
                       'e': {1: .1, 2: .1, 3: .1, 4: .1, 'F': 0.},
                       'nu': {1: .2, 2: .2, 3: .2, 4: .2, 'F': .2}}

    def test_masked_nll_only_verified_pure_contributors(self):
        selected = process_sup.select_masked_nll_units(self.trajs, [self.credit] * 2, self.config)
        self.assertEqual(selected, [{1, 4}, {1, 4}])
        mixed = [{'outcome': {'Y': True}}, {'outcome': {'Y': False}}]
        self.assertEqual(process_sup.select_masked_nll_units(mixed, [self.credit] * 2, self.config),
                         [set(), set()])
        zero = dict(self.credit, A_hat=0.)
        self.assertEqual(process_sup.select_masked_nll_units(mixed, [zero] * 2, self.config),
                         [{1, 4}, {1, 4}])

    def test_zero_sum_has_equal_mass_and_token_cap(self):
        signals, log = process_sup.zero_sum_for_trajectory(self.credit, self.config)
        self.assertAlmostEqual(sum(self.credit['nu'][u] * s for u, s in signals.items()), 0.)
        self.assertLessEqual(max(abs(s) for s in signals.values()), .300000000000001)
        self.assertEqual(signals['F'], 0.)
        self.assertAlmostEqual(log['positive_mass'], .06)
        self.assertAlmostEqual(log['negative_mass'], .06)
        one = dict(self.credit, role={u: 'C' for u in self.credit['role']})
        self.assertEqual(set(process_sup.zero_sum_for_trajectory(one, self.config)[0].values()), {0.})

    def test_sampling_is_whole_group_deterministic_and_corrected_in_expectation(self):
        self.assertTrue(sampling.select_group('toy', 1, 1., 7))
        draws = [sampling.select_group(str(i), 3, .25, 11) for i in range(10000)]
        self.assertEqual(draws, [sampling.select_group(str(i), 3, .25, 11) for i in range(10000)])
        mean = sum(sampling.corrected_loss(2., 5., d, .25, True) for d in draws) / len(draws)
        self.assertAlmostEqual(mean, 5., delta=.15)
        self.assertEqual(sampling.corrected_loss(2., 5., True, 1., True), 5.)
        self.assertEqual(sampling.corrected_loss(2., None, False, .25, True), 2.)
        self.assertEqual(sampling.corrected_loss(2., 5., True, .25, False), 5.)

    def test_continuation_uses_eo_not_waste_and_loo(self):
        plan = continuation.choose_branch(self.trajs, [self.credit] * 2)
        self.assertEqual(plan.unit_id, 2)
        self.assertEqual(plan.rollout_index, 0)
        self.assertEqual(continuation.branch_advantages([1., 0., 0.]), [1., -.5, -.5])
        waste = dict(self.credit, R={2: [(.9, '浪费:严格重复')]})
        self.assertIsNone(continuation.choose_branch(self.trajs, [waste] * 2))
        with self.assertRaises(NotImplementedError):
            continuation.sample_continuations(plan)

    def test_review_priority_and_disagreement(self):
        rows = [{'unit': 1, 'tokens': 100, 'delta_advantage': .2, 'error_rate': .5},
                {'unit': 2, 'tokens': 5, 'delta_advantage': .1, 'error_rate': .1}]
        self.assertEqual(sampling.select_review_units(rows, .5, 0., seed=1), [1])
        self.assertEqual(sampling.merge_review_confidence({1: {'x': 1}, 2: {'x': 2}},
                                                        {1: {'x': 3}}), {1: False, 2: True})


if __name__ == '__main__':
    unittest.main()
