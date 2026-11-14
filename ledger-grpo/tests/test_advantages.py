"""CPU-only numeric contracts; no model, network, or experiment execution."""

import importlib
import math
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class AdvantageTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module("ledger_grpo.advantages")
        except ModuleNotFoundError as exc:
            self.fail(f"The requested advantage module is not implemented: {exc}")

    def run_case(self, outcomes, *, groups=None, mask=None, red=None, gnd=None,
                 dev=None, process_valid=None, training_valid=None, **options):
        y = torch.tensor(outcomes, dtype=torch.float64)
        b = len(outcomes)
        mask = torch.ones((b, 2), dtype=torch.bool) if mask is None else torch.tensor(mask, dtype=torch.bool)
        red = torch.zeros_like(mask, dtype=torch.float64) if red is None else torch.tensor(red, dtype=torch.float64)
        dev = torch.zeros_like(red) if dev is None else torch.tensor(dev, dtype=torch.float64)
        opts = dict(process_enabled=True, batch_scale=False, epsilon=1e-12)
        opts.update(options)
        return self.module.compute_advantages(
            y, groups or ["q"] * b, mask, red,
            None if gnd is None else torch.tensor(gnd, dtype=torch.float64), dev,
            process_valid=None if process_valid is None else torch.tensor(process_valid, dtype=torch.bool),
            training_valid=None if training_valid is None else torch.tensor(training_valid, dtype=torch.bool),
            config=self.module.AdvantageConfig(**opts),
        )

    def test_mixed_group_hand_calculation_and_tool_mask(self):
        # Detects population-std substitution, wrong success subset, or tool credit.
        result = self.run_case(
            [1, 1, 0, 0], mask=[[1, 0, 1]] * 4,
            red=[[1, 1, 0], [0, 0, 0], [1, 1, 1], [0, 0, 0]],
            gnd=[0.5, 1, 0, 1],
        )
        expected = torch.tensor([
            [0, 0, 0.6892487085], [1.0428020991, 0, 1.0428020991],
            [-0.8660254038, 0, -0.8660254038], [-0.8660254038, 0, -0.8660254038],
        ], dtype=torch.float64)
        torch.testing.assert_close(result["advantages"], expected, atol=1e-9, rtol=0)
        self.assertTrue(bool(result["valid_rows"].all()))

    def test_one_success_has_no_conditional_process_advantage(self):
        result = self.run_case([1, 0, 0, 0], gnd=[0, 1, 1, 1])
        torch.testing.assert_close(result["trajectory_advantage"], torch.tensor([1.5, -.5, -.5, -.5], dtype=torch.float64))
        self.assertEqual(float(result["grounding_advantage"].abs().sum()), 0)
        self.assertEqual(float(result["efficiency_advantage"].abs().sum()), 0)

    def test_all_correct_can_have_negative_advantage_even_with_beta_zero(self):
        result = self.run_case([1, 1], red=[[0, 0], [1, 1]], dev=[[.15, .15], [.15, .15]], grounding_weight=0)
        self.assertEqual(float(result["advantages"][0, 0]), 0)
        self.assertAlmostEqual(float(result["advantages"][1, 0]), -.15 / math.sqrt(2), places=9)
        self.assertTrue(bool(result["valid_rows"].all()))

    def test_all_wrong_dropped_before_deviation_offsets(self):
        result = self.run_case([0, 0], red=[[1, 1]] * 2, dev=[[10, 10]] * 2, batch_scale=True)
        self.assertFalse(bool(result["valid_rows"].any()))
        self.assertEqual(float(result["advantages"].abs().sum()), 0)
        self.assertTrue(bool(torch.isfinite(result["advantages"]).all()))

    def test_singleton_has_zero_advantage(self):
        result = self.run_case([1], gnd=[1], dev=[[1, 1]], batch_scale=True)
        self.assertEqual(float(result["advantages"].abs().sum()), 0)

    def test_qa_failure_disables_entire_group_but_not_other_groups(self):
        result = self.run_case(
            [1, 1, 0, 0, 1, 1], groups=["q"] * 4 + ["other"] * 2,
            red=[[1, 1], [0, 0], [0, 0], [0, 0], [1, 1], [0, 0]],
            gnd=[0, 1, 1, 0, 0, 1], dev=[[1, 1]] * 6,
            process_valid=[1, 0, 1, 1, 1, 1],
        )
        self.assertAlmostEqual(float(result["advantages"][0, 0]), math.sqrt(3) / 2, places=9)
        self.assertEqual(float(result["efficiency_advantage"][:4].abs().sum()), 0)
        self.assertGreater(float(result["efficiency_advantage"][4:].abs().sum()), 0)

    def test_truncation_invalidates_complete_group(self):
        result = self.run_case([1, 0, 1, 0], groups=["a", "a", "b", "b"], training_valid=[1, 0, 1, 1])
        self.assertEqual(result["valid_rows"].tolist(), [False, False, True, True])
        self.assertEqual(float(result["advantages"][:2].abs().sum()), 0)
        self.assertGreater(float(result["advantages"][2:].abs().sum()), 0)

    def test_process_disabled_is_outcome_only(self):
        result = self.run_case([1, 0], red=[[1, 1]] * 2, dev=[[100, 100]] * 2, gnd=[0, 1], process_enabled=False)
        expected = torch.tensor([[1, 1], [-1, -1]], dtype=torch.float64) / math.sqrt(2)
        torch.testing.assert_close(result["advantages"], expected)

    def test_redundancy_and_deviation_do_not_cross_zero_twice(self):
        result = self.run_case([1, 0], red=[[1, 1], [1, 1]], dev=[[100, 100], [100, 100]])
        self.assertEqual(result["advantages"][0].tolist(), [0, 0])
        self.assertAlmostEqual(float(result["advantages"][1, 0]), -1 / math.sqrt(2) - .3, places=9)

    def test_success_deviation_beta_bounds_new_negative_offset(self):
        result = self.run_case([1, 0], red=[[1, 1], [0, 0]], dev=[[100, 100], [0, 0]], beta=.1)
        self.assertAlmostEqual(float(result["advantages"][0, 0]), -.1, places=9)

    def test_clipped_conditional_scores_are_not_silently_recentered(self):
        result = self.run_case([1, 1, 1], red=[[1, 1], [1, 1], [0, 0]], grounding_weight=0, eta=0)
        expected = torch.tensor([-1 / math.sqrt(3), -1 / math.sqrt(3), 1], dtype=torch.float64)
        torch.testing.assert_close(result["efficiency_advantage"], expected)
        self.assertLess(float(result["efficiency_advantage"].mean()), 0)

    def test_batch_scale_counts_trajectories_not_tokens_and_preserves_sign(self):
        result = self.run_case([1, 0], mask=[[1, 0, 0], [1, 1, 1]], batch_scale=True, process_enabled=False)
        torch.testing.assert_close(result["trajectory_advantage"], torch.tensor([1, -1], dtype=torch.float64) / math.sqrt(2))

    def test_identical_scores_zero_variance_no_nan(self):
        result = self.run_case([1, 1], gnd=[.5, .5], red=[[0, 0], [0, 0]], batch_scale=True)
        self.assertEqual(float(result["advantages"].abs().sum()), 0)
        self.assertTrue(bool(torch.isfinite(result["advantages"]).all()))

    def test_sign_anchor_rejects_default_weights_at_group_size_sixteen(self):
        with self.assertRaisesRegex(ValueError, "sign.anchor"):
            self.run_case([1] * 15 + [0], gnd=[1] * 16)
        self.run_case([1] * 7 + [0], gnd=[1] * 8)

    def test_outputs_detached_and_inputs_unmodified(self):
        y = torch.tensor([1., 0.], requires_grad=True)
        red = torch.zeros(2, 2, requires_grad=True)
        result = self.module.compute_advantages(y, ["q", "q"], torch.ones(2, 2, dtype=torch.bool), red, None, torch.zeros(2, 2))
        self.assertFalse(result["advantages"].requires_grad)
        self.assertEqual(y.tolist(), [1, 0])
        self.assertEqual(red.tolist(), [[0, 0], [0, 0]])

    def test_invalid_values_rejected(self):
        for kwargs in ({"eta": 1.1}, {"beta": -.1}, {"efficiency_weight": -.1}, {"epsilon": 0}, {"delta_max": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_case([1, 0], **kwargs)
        for kwargs in ({"red": [[1.1, 0], [0, 0]]}, {"gnd": [float("nan"), 0]}, {"dev": [[-1, 0], [0, 0]]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_case([1, 0], **kwargs)
        with self.assertRaises(ValueError):
            self.run_case([.5, 0])

    def test_controls_preserve_adjustment_mass_and_exclude_tools(self):
        base = torch.tensor([1., -1.])
        mask = torch.tensor([[1, 0, 1, 1], [1, 1, 0, 0]], dtype=torch.bool)
        adjusted = torch.tensor([[0., 0, .5, 1], [-1.3, -1, 0, 0]])
        for mode in ("targeted", "uniform", "shuffle"):
            with self.subTest(mode=mode):
                actual = self.module.apply_control(adjusted, base, mask, mode=mode, seed=7)
                torch.testing.assert_close(actual.sum(-1), adjusted.sum(-1))
                self.assertEqual(float(actual[~mask].abs().sum()), 0)
        uniform = self.module.apply_control(adjusted, base, mask, mode="uniform")
        torch.testing.assert_close(uniform, torch.tensor([[.5, 0, .5, .5], [-1.15, -1.15, 0, 0]]))
        pure = self.module.apply_control(adjusted, base, mask, mode="trajectory")
        torch.testing.assert_close(pure, base[:, None] * mask)

    def test_shuffle_is_reproducible_and_preserves_delta_multiset(self):
        base = torch.tensor([1.])
        mask = torch.tensor([[1, 0, 1, 1, 1, 1]], dtype=torch.bool)
        adjusted = torch.tensor([[0., 0, .2, .4, .6, .8]])
        first = self.module.apply_control(adjusted, base, mask, mode="shuffle", seed=7)
        second = self.module.apply_control(adjusted, base, mask, mode="shuffle", seed=7)
        torch.testing.assert_close(first, second)
        torch.testing.assert_close(first[mask].sort().values, adjusted[mask].sort().values)


if __name__ == "__main__":
    unittest.main()
