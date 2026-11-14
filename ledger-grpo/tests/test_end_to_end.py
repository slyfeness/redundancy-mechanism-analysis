import importlib
import unittest


class GradientContractTests(unittest.TestCase):
    def test_masked_policy_loss_has_local_credit_and_no_tool_gradients(self):
        import torch
        try:
            from ledger_grpo.examples import synthetic_examples
        except ImportError as exc:
            self.fail(f'end-to-end examples missing: {exc}')
        from ledger_grpo.advantages import AdvantageConfig
        from ledger_grpo.pipeline import analyze_trajectory, score_batch
        traces, deltas = synthetic_examples()
        traces = traces[:3]
        reports = [analyze_trajectory(t, deltas=deltas[t['traj_id']]) for t in traces]
        result = score_batch(traces, reports, config=AdvantageConfig(process_enabled=True))
        # A numerical derivative check, not a model training experiment.
        logits = torch.zeros_like(result['advantages'], requires_grad=True)
        mask = result['effective_response_mask']
        log_probs = torch.nn.functional.logsigmoid(logits)
        loss = -(log_probs * result['advantages'].detach() * mask).sum() / mask.sum()
        loss.backward()
        self.assertTrue(torch.all(logits.grad[mask == 0] == 0))
        self.assertLess(float(logits.grad[0, 0]), 0)
        self.assertTrue(torch.all(logits.grad[0, 4:6] == 0))
        self.assertGreater(float(logits.grad[2, 0]), 0)
        self.assertFalse(result['advantages'].requires_grad)


if __name__ == '__main__':
    unittest.main()
