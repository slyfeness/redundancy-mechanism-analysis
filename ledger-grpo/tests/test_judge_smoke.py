import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


class FakeJudge:
    """A deterministic external-service substitute; no sockets or user files."""
    def __init__(self, callback=None):
        self.usage = {'prompt_tokens': 0, 'completion_tokens': 0}
        self.calls = []
        self.callback = callback

    def check(self, kind, payload):
        self.calls.append((kind, payload))
        self.usage['prompt_tokens'] += 10
        self.usage['completion_tokens'] += 4
        if self.callback:
            alternative = self.callback(len(self.calls), kind, payload)
            if alternative is not None:
                return alternative
        verdict = ('yes', 'no', 'uncertain', 'yes', 'no', 'uncertain')[len(self.calls) - 1]
        evidence = payload.get('evidence', payload.get('prior_evidence', []))
        refs = [evidence[0]['evidence_id']]
        if kind == 'R1' and verdict == 'yes':
            refs.append(payload['observations'][0]['evidence_id'])
        return {'verdict': verdict, 'evidence_refs': refs,
                'rationale': 'Observed relation in the synthetic prefix.'}


class SmokeTests(unittest.TestCase):
    def test_deepseek_preset_only_prompts_for_key(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            captured = {}
            def factory(endpoint, model, **kwargs):
                captured.update(endpoint=endpoint, model=model, **kwargs)
                return FakeJudge()
            report = module.run_smoke(Path(folder) / 'result.json', provider='deepseek',
                                      judge_factory=factory, input_fn=lambda _: self.fail('only key should be requested'),
                                      getpass_fn=lambda _: 'temporary-key',
                                      auth_checker=lambda _: ['deepseek-flash'])
            self.assertEqual(captured['endpoint'], 'https://api.deepseek.com')
            self.assertEqual(captured['model'], 'deepseek-flash')
            self.assertEqual(captured['thinking'], 'disabled')
            self.assertEqual(report['summary']['error_count'], 0)

    def test_remember_retries_401_in_same_prompt_and_only_saves_validated_key(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            entered = iter(['wrong-secret', 'valid-secret'])
            checked, saved, used = [], [], []
            def authenticate(key):
                checked.append(key)
                if key == 'wrong-secret':
                    raise HTTPError('https://api.deepseek.com/models', 401, 'wrong-secret', {}, None)
                return ['deepseek-flash']
            def factory(*args, **kwargs):
                used.append(kwargs['api_key'])
                return FakeJudge()
            report = module.run_smoke(output, provider='deepseek', remember_key=True,
                                      judge_factory=factory, auth_checker=authenticate,
                                      key_loader=lambda: None, key_saver=saved.append,
                                      getpass_fn=lambda _: next(entered))
            self.assertEqual(checked, ['wrong-secret', 'valid-secret'])
            self.assertEqual(saved, ['valid-secret'])
            self.assertEqual(used, ['valid-secret'])
            self.assertTrue(report['credential_saved'])
            self.assertEqual(report['authentication']['attempts'], 2)
            artifacts = output.read_text() + output.with_name('status.json').read_text() + self.captured_stdout.getvalue()
            self.assertNotIn('wrong-secret', artifacts)
            self.assertNotIn('valid-secret', artifacts)

    def test_saved_key_is_reused_without_prompting_and_storage_error_can_be_replaced(self):
        module = self.api()
        for broken in (False, True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as folder:
                saved, entered = [], []
                def load():
                    if broken:
                        raise RuntimeError('secret storage body')
                    return 'stored-secret'
                def prompt(_):
                    entered.append(True)
                    return 'replacement-secret'
                report = module.run_smoke(Path(folder) / 'result.json', provider='deepseek', remember_key=True,
                                          judge_factory=lambda *a, **k: FakeJudge(),
                                          auth_checker=lambda _: ['deepseek-flash'],
                                          key_loader=load, key_saver=saved.append, getpass_fn=prompt)
                self.assertEqual(len(entered), int(broken))
                self.assertEqual(saved, ['replacement-secret' if broken else 'stored-secret'])
                self.assertTrue(report['credential_saved'])
                self.assertNotIn('secret storage body', self.captured_stdout.getvalue())

    def test_auth_errors_stop_without_judge_calls_saving_or_unbounded_retries(self):
        module = self.api()
        for code, attempts in ((401, 3), (403, 1), (429, 1)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'result.json'
                checked = []
                def reject(key):
                    checked.append(key)
                    raise HTTPError('https://api.deepseek.com/models', code, 'never-log-this-body', {}, None)
                with self.assertRaises(Exception):
                    module.run_smoke(output, provider='deepseek', remember_key=True,
                                     judge_factory=lambda *a, **k: self.fail('must not judge before authentication'),
                                     auth_checker=reject, key_loader=lambda: None,
                                     key_saver=lambda _: self.fail('must not save rejected key'),
                                     getpass_fn=lambda _: 'rejected-secret')
                self.assertEqual(len(checked), attempts)
                state = json.loads(output.with_name('status.json').read_text())
                self.assertEqual(state['status'], 'error')
                self.assertEqual(state['http_status'], code)
                self.assertNotIn('never-log-this-body', self.captured_stdout.getvalue())
                self.assertFalse(output.exists())

    def test_missing_preset_model_and_custom_remember_are_rejected(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            with self.assertRaises(ValueError):
                module.run_smoke(output, remember_key=True,
                                 getpass_fn=lambda _: self.fail('custom persistence must fail before prompt'))
            with self.assertRaises(Exception):
                module.run_smoke(output, provider='deepseek', remember_key=True,
                                 judge_factory=lambda *a, **k: self.fail('no silent model substitution'),
                                 auth_checker=lambda _: ['unavailable-model'], key_loader=lambda: None,
                                 key_saver=lambda _: self.fail('must not save before model check'),
                                 getpass_fn=lambda _: 'valid-secret')
            self.assertEqual(json.loads(output.with_name('status.json').read_text())['reason'], 'model_unavailable')
    def setUp(self):
        self.captured_stdout = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.captured_stdout))

    def api(self):
        try:
            return importlib.import_module('ledger_grpo.judge_smoke')
        except ImportError as exc:
            self.fail(f'judge smoke implementation is missing: {exc}')

    def test_synthetic_checks_keep_expected_answers_out_of_request_and_report_usage(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            state_path = output.with_name('status.json')
            states = []
            answers = iter(['https://synthetic.example/v1', 'synthetic-model'])
            def input_fn(prompt):
                states.append(json.loads(state_path.read_text())['status'])
                return next(answers)
            def inspect_running(number, kind, payload):
                self.assertEqual(json.loads(state_path.read_text())['status'], 'running')
                self.assertNotIn('expected', json.dumps(payload))
            fake = FakeJudge(inspect_running)
            ticks = iter(index / 4 for index in range(30))
            report = module.run_smoke(output, judge_factory=lambda *a, **k: fake,
                                      input_fn=input_fn, getpass_fn=lambda _: 'secret-123',
                                      clock=lambda: next(ticks))
            self.assertEqual(states, ['waiting_for_input', 'waiting_for_input'])
            self.assertEqual([kind for kind, _ in fake.calls], ['support'] * 3 + ['R1'] * 3)
            self.assertEqual(report['summary']['case_count'], 6)
            self.assertEqual(report['model'], 'synthetic-model')
            self.assertEqual(report['summary']['matched_count'], 6)
            self.assertEqual(report['summary']['usage'], {'prompt_tokens': 60, 'completion_tokens': 24})
            self.assertEqual(report['cases'][0]['elapsed_seconds'], .25)
            self.assertEqual(report['cases'][0]['usage'], {'prompt_tokens': 10, 'completion_tokens': 4})
            self.assertEqual(report['cases'][0]['actual'], 'yes')
            self.assertEqual(report['cases'][0]['raw_verdict']['verdict'], 'yes')
            self.assertIn('not task performance or calibration', report['summary']['interpretation'])
            self.assertEqual(json.loads(output.read_text()), report)
            self.assertEqual(json.loads(state_path.read_text())['status'], 'completed')
            artifacts = output.read_text() + state_path.read_text()
            self.assertNotIn('secret-123', artifacts)
            self.assertNotIn('https://synthetic.example', artifacts)

    def test_main_reads_terminal_credentials_and_enter_allows_no_key(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            captured = {}
            def factory(endpoint, model, **kwargs):
                captured.update(endpoint=endpoint, model=model, **kwargs)
                return FakeJudge()
            with patch('builtins.input', side_effect=['http://127.0.0.1:8000/v1', 'local-m']), \
                    patch('getpass.getpass', return_value=''), \
                    patch.object(module, 'LocalJudge', side_effect=factory), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(['--output', str(output)]), 0)
            self.assertEqual(captured, {'endpoint': 'http://127.0.0.1:8000/v1',
                                       'model': 'local-m', 'allow_remote': True, 'api_key': ''})

    def test_errors_and_invalid_citations_are_not_valid_verdicts_or_secret_logs(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            def response(number, kind, payload):
                if number == 1:
                    return {'verdict': 'yes', 'evidence_refs': ['not-supplied'],
                            'rationale': 'secret-123 https://synthetic.example/v1'}
                if number == 2:
                    raise RuntimeError('secret-123 https://synthetic.example/v1?api_key=secret-123')
            answers = iter(['https://synthetic.example/v1', 'm'])
            report = module.run_smoke(output, judge_factory=lambda *a, **k: FakeJudge(response),
                                      input_fn=lambda _: next(answers),
                                      getpass_fn=lambda _: 'secret-123')
            self.assertEqual(report['summary']['error_count'], 2)
            self.assertIsNone(report['cases'][0]['actual'])
            self.assertIsNone(report['cases'][1]['actual'])
            self.assertEqual(report['cases'][1]['error_type'], 'RuntimeError')
            self.assertEqual(json.loads(output.with_name('status.json').read_text())['status'], 'error')
            self.assertNotIn('secret-123', output.read_text())
            self.assertNotIn('https://synthetic.example', output.read_text())

    def test_existing_output_or_status_is_not_overwritten_or_prompted(self):
        module = self.api()
        for occupied in ('result.json', 'status.json'):
            with self.subTest(occupied=occupied), tempfile.TemporaryDirectory() as folder:
                existing = Path(folder) / occupied
                existing.write_text('owned by another run')
                with self.assertRaises(FileExistsError):
                    module.run_smoke(Path(folder) / 'result.json',
                                     input_fn=lambda _: self.fail('must reject before input'))
                self.assertEqual(existing.read_text(), 'owned by another run')

    def test_changed_status_ownership_is_never_overwritten(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            status = output.with_name('status.json')
            def replace_status(number, kind, payload):
                if number == 1:
                    status.write_text('{"run_id":"someone-else","status":"running"}')
            with self.assertRaises(RuntimeError):
                module.run_smoke(output, judge_factory=lambda *a, **k: FakeJudge(replace_status),
                                 input_fn=lambda _: 'synthetic', getpass_fn=lambda _: '')
            self.assertEqual(json.loads(status.read_text())['run_id'], 'someone-else')

    def test_connection_initialization_error_sets_safe_terminal_state(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            def broken(*args, **kwargs):
                raise ValueError('DO-NOT-LOG-KEY')
            with self.assertRaises(ValueError):
                module.run_smoke(output, judge_factory=broken, input_fn=lambda _: 'synthetic',
                                 getpass_fn=lambda _: 'DO-NOT-LOG-KEY')
            state = output.with_name('status.json').read_text()
            self.assertEqual(json.loads(state)['status'], 'error')
            self.assertNotIn('DO-NOT-LOG-KEY', state)

    def test_label_disagreement_is_reported_without_being_called_an_api_error(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            def disagree(number, kind, payload):
                if number == 1:
                    return {'verdict': 'no', 'evidence_refs': [], 'rationale': 'Disagreed.'}
            report = module.run_smoke(output, judge_factory=lambda *a, **k: FakeJudge(disagree),
                                      input_fn=lambda _: 'synthetic', getpass_fn=lambda _: '')
            self.assertEqual(report['summary']['matched_count'], 5)
            self.assertEqual(report['summary']['error_count'], 0)
            self.assertEqual(json.loads(output.with_name('status.json').read_text())['status'], 'completed')

    def test_r1_yes_needs_prior_and_current_evidence_and_model_is_redacted(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            def incomplete(number, kind, payload):
                if number == 4:
                    return {'verdict': 'yes', 'evidence_refs': ['e-prior'], 'rationale': 'Prior evidence only.'}
            answers = iter(['https://synthetic.example/v1', 'model-secret-123'])
            report = module.run_smoke(output, judge_factory=lambda *a, **k: FakeJudge(incomplete),
                                      input_fn=lambda _: next(answers), getpass_fn=lambda _: 'secret-123')
            self.assertEqual(report['cases'][3]['error_type'], 'InvalidVerdict')
            self.assertIsNone(report['cases'][3]['actual'])
            self.assertEqual(report['model'], 'model-[REDACTED]')

    def test_launcher_sets_package_directory_and_pythonpath_without_network(self):
        shell = shutil.which('pwsh') or shutil.which('powershell')
        if shell is None:
            self.skipTest('PowerShell is unavailable on this platform')
        package = Path(__file__).resolve().parents[1]
        launcher = package / 'scripts' / 'judge-smoke.ps1'
        self.assertTrue(launcher.exists(), 'judge smoke launcher is missing')
        with tempfile.TemporaryDirectory(prefix='smoke fixture ') as folder:
            folder = Path(folder)
            fake = folder / 'fake python.ps1'
            recording = folder / 'invocation.json'
            output = folder / 'result.json'
            fake.write_text("@{cwd=(Get-Location).Path;pythonpath=$env:PYTHONPATH;args=@($args)} | "
                            "ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $env:SMOKE_TEST_RECORD -Encoding utf8\nexit 7\n")
            env = dict(os.environ, SMOKE_TEST_RECORD=str(recording))
            completed = subprocess.run([shell, '-NoProfile', '-File', str(launcher),
                                        '-Output', str(output), '-Python', str(fake)],
                                       cwd=folder, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 7, completed.stderr)
            invocation = json.loads(recording.read_text(encoding='utf-8-sig'))
            self.assertEqual(Path(invocation['cwd']).resolve(), package)
            self.assertEqual(Path(invocation['pythonpath']).resolve(), package / 'src')
            self.assertEqual(invocation['args'], ['-m', 'ledger_grpo.judge_smoke', '--output', str(output)])
            self.assertFalse(output.exists())
            completed = subprocess.run([shell, '-NoProfile', '-File', str(launcher),
                                        '-Output', str(output), '-Python', str(fake),
                                        '-Provider', 'deepseek', '-RememberKey'],
                                       cwd=folder, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 7, completed.stderr)
            invocation = json.loads(recording.read_text(encoding='utf-8-sig'))
            self.assertEqual(invocation['args'], ['-m', 'ledger_grpo.judge_smoke', '--output', str(output),
                                                 '--provider', 'deepseek', '--remember-key'])


if __name__ == '__main__':
    unittest.main()
