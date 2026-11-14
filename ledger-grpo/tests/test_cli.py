import importlib
import json
from pathlib import Path
import tempfile
import unittest


class CommandTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('ledger_grpo.cli')
        except ImportError as exc:
            self.fail(f'command interface missing: {exc}')

    def test_demo_runs_entire_offline_pipeline_and_writes_inspectable_artifacts(self):
        cli = self.api()
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'demo'
            self.assertEqual(cli.main(['demo', '--output-dir', str(out)]), 0)
            scores = json.loads((out / 'scores.json').read_text(encoding='utf-8'))
            reports = [json.loads(line) for line in (out / 'reports.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertTrue(all(r['qa']['parse_ok'] for r in reports))
            self.assertEqual(scores['metrics']['valid_row_count'], 6)
            self.assertEqual(scores['config']['process_enabled'], True)
            self.assertEqual(scores['process_inputs'][0]['redundancy'][4:6], [1, 1])
            self.assertEqual(scores['advantages'][0][4:6], [0, 0])
            self.assertFalse(scores['skip_update'])
            self.assertEqual(cli.main(['evaluate', '--runs', str(out / 'runs.jsonl'), '--output', str(out / 'evaluation.json')]), 0)
            self.assertEqual(json.loads((out / 'evaluation.json').read_text())['run_count'], 6)

    def test_replay_cli_and_outcome_only_default(self):
        cli = self.api()
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'demo'
            cli.main(['demo', '--output-dir', str(out)])
            args = ['analyze', '--trajectories', str(out / 'trajectories.jsonl'), '--deltas', str(out / 'deltas.json'), '--output', str(out / 'replay.jsonl')]
            self.assertEqual(cli.main(args), 0)
            self.assertEqual(cli.main(['score', '--trajectories', str(out / 'trajectories.jsonl'), '--reports', str(out / 'replay.jsonl'), '--output', str(out / 'baseline.json')]), 0)
            result = json.loads((out / 'baseline.json').read_text())
            self.assertFalse(result['config']['process_enabled'])
            self.assertEqual(result['advantages'][0][0], result['advantages'][0][4])

    def test_existing_outputs_are_not_silently_replaced(self):
        cli = self.api()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'keep.json'
            path.write_text('keep', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                cli.write_json(path, {})
            self.assertEqual(path.read_text(), 'keep')

    def test_audit_does_not_swap_predictions_and_gold(self):
        cli = self.api()
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            unit = {'task_id': 'q', 'traj_id': 't', 'turn_id': 1, 'label': 'R2', 'verdict': 'positive'}
            cli.write_json(out / 'gold.jsonl', [unit, dict(unit, turn_id=2, verdict='negative')], lines=True)
            cli.write_json(out / 'pred.jsonl', [unit], lines=True)
            self.assertEqual(cli.main(['audit', '--gold', str(out / 'gold.jsonl'), '--predictions', str(out / 'pred.jsonl'), '--output', str(out / 'audit.json')]), 0)
            result = json.loads((out / 'audit.json').read_text())
            self.assertEqual(result['missing_prediction_count'], 1)


if __name__ == '__main__':
    unittest.main()
