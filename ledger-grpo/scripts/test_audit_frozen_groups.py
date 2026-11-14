import importlib.util
from pathlib import Path
import unittest


class AuditTests(unittest.TestCase):
    def api(self):
        path = Path(__file__).with_name('audit_frozen_groups.py')
        self.assertTrue(path.exists(), 'audit implementation is missing')
        spec = importlib.util.spec_from_file_location('audit_frozen_groups', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_group_exclusion_precedes_outcome_signal(self):
        groups = {
            'mixed': [dict(complete=True, outcome=i % 2, native_ok=True) for i in range(8)],
            'correct': [dict(complete=True, outcome=1, native_ok=True) for _ in range(8)],
            'wrong': [dict(complete=True, outcome=0, native_ok=True) for _ in range(8)],
            'partial': [dict(complete=i > 0, outcome=i % 2, native_ok=True) for i in range(8)],
        }
        rows = self.api().group_summary(groups)
        self.assertEqual(sum(r['retained'] for r in rows), 2)
        self.assertEqual(sum(r['outcome_signal'] for r in rows), 1)
        self.assertEqual(sum(r['exact8_complete'] for r in rows), 3)
        self.assertEqual(next(r for r in rows if r['task_id'] == 'partial')['drop_reason'], 'incomplete_or_invalid_group')

    def test_schema_never_serializes_values(self):
        value = {'content': 'SECRET_COT', 'calls': [{'function': {'name': 'SECRET_NAME', 'arguments': 'SECRET_QUERY'}}]}
        result = str(self.api().schema(value))
        self.assertNotIn('SECRET', result)
        self.assertIn('arguments', result)

    def test_unknown_outcome_and_incomplete_cardinality_are_dropped(self):
        m = self.api()
        rows = m.group_summary({'a': [dict(complete=True, outcome=None, native_ok=True)] * 8,
                                'b': [dict(complete=True, outcome=1, native_ok=True)] * 7})
        self.assertTrue(all(not r['retained'] for r in rows))


if __name__ == '__main__':
    unittest.main()
