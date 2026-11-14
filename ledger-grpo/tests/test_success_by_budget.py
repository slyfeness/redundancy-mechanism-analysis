import unittest

from summarize_success_by_budget import apply_budget


class SuccessByBudgetTest(unittest.TestCase):
    def test_counts_observed_success_and_preserves_unknown(self):
        rows = [{'task_id': 'q', 'sample_id': str(i), 'outcome': outcome, 'tool_calls': cost}
                for i, (outcome, cost) in enumerate([(1,5), (1,6), (0,None), (None,5), (None,6), (1,None)])]
        actual = apply_budget(rows, 'tool_calls', 5)
        self.assertEqual([row['outcome'] for row in actual], [1,0,0,None,0,None])
        self.assertEqual([row['sample_id'] for row in actual], [row['sample_id'] for row in rows])
        self.assertEqual(rows[1]['outcome'], 1)
