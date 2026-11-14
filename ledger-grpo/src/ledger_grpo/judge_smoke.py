"""Interactive API smoke check on six repository-owned synthetic local relations.

This is not a benchmark, calibration set, training run, or test on user documents.
Connection details live only in this process unless DeepSeek --remember-key is
explicitly enabled for encrypted credential storage. The result preserves the structured
check response (not raw HTTP), with any echoed connection secrets redacted.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from .client import LocalJudge, _NoRedirect


INTERPRETATION = (
    'Synthetic API/local-relation smoke agreement only; not task performance or calibration. '
    'These six illustrative expectations are not evidence of redundancy-judge reliability. '
    'Usage contains client counters; a provider that omits usage may contribute zero.'
)


def synthetic_cases():
    """Return fresh fixtures; expected answers are never sent to the judge."""
    quote = 'Aster Observatory opened in 2012.'
    fact = {'fid': 'f-aster', 'cid': 'opening-year', 'candidate_id': 'aster',
            'statement': quote, 'state': 'supported'}
    prior = {'evidence_id': 'e-prior', 'source_id': 'official-archive', 'text': quote}
    support = []
    for name, expected, text in (
        ('support_direct', 'yes', quote),
        ('support_wrong_date', 'no', 'Construction began in 2012. Aster Observatory opened in 2015.'),
        ('support_ambiguous_subject', 'uncertain', 'It opened in 2012. The excerpt omits what "it" refers to.'),
    ):
        support.append({'case_id': name, 'kind': 'support', 'expected': expected,
                        'payload': {'task': 'Find the opening year of Aster Observatory.',
                                    'fact': dict(fact),
                                    'evidence': [{'evidence_id': 'e-support', 'text': text}]}})
    r1 = [
        {'case_id': 'r1_same_fact_same_source', 'kind': 'R1', 'expected': 'yes',
         'payload': {'task': 'Find the opening year from the official archive; one official source suffices.',
                     'fact': dict(fact), 'prior_evidence': [prior],
                     'action': {'query': 'Reopen the same official archive to confirm Aster opened in 2012 again.',
                                'target_id': 'opening-year', 'fact_id': 'f-aster',
                                'candidate_id': 'aster'},
                     'observations': [{'evidence_id': 'e-current', 'source_id': 'official-archive', 'text': quote}]}},
        {'case_id': 'r1_required_independent_source', 'kind': 'R1', 'expected': 'no',
         'payload': {'task': 'Verify the opening year using TWO independent sources; only one source has been checked.',
                     'fact': dict(fact), 'prior_evidence': [prior],
                     'action': {'query': 'Check the independent municipal archive for Aster opening year.',
                                'target_id': 'opening-year', 'fact_id': 'f-aster',
                                'candidate_id': 'aster'},
                     'observations': [{'evidence_id': 'e-current', 'source_id': 'municipal-archive', 'text': quote}]}},
        {'case_id': 'r1_unresolved_target', 'kind': 'R1', 'expected': 'uncertain',
         'payload': {'task': 'Find the opening years of Aster Observatory and Beacon Observatory.',
                     'fact': dict(fact), 'prior_evidence': [prior],
                     'action': {'query': 'Confirm its opening year.',
                                'target_context': 'The visible prefix does not identify which observatory "its" means.'},
                     'observations': []}},
    ]
    return deepcopy(support + r1)


class _Status:
    """Bounded lifecycle writes; at most three DeepSeek authentication attempts."""
    def __init__(self, path):
        self.path = path
        self.run_id = uuid4().hex
        self.write('started', create=True)

    def write(self, status, *, create=False, **details):
        data = {'run_id': self.run_id, 'status': status,
                'updated_at': datetime.now(timezone.utc).isoformat(), **details}
        text = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if create:
            with self.path.open('x', encoding='utf-8') as stream:
                stream.write(text)
            return
        if json.loads(self.path.read_text(encoding='utf-8')).get('run_id') != self.run_id:
            raise RuntimeError('status ownership changed')
        temporary = self.path.with_name(f'.status-{self.run_id}.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                stream.write(text)
            if json.loads(self.path.read_text(encoding='utf-8')).get('run_id') != self.run_id:
                raise RuntimeError('status ownership changed')
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


def _usage(judge):
    counters = getattr(judge, 'usage', {})
    return {name: counters.get(name, 0) if type(counters.get(name, 0)) is int
            and counters.get(name, 0) >= 0 else 0
            for name in ('prompt_tokens', 'completion_tokens')}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


def _valid_verdict(raw, payload, kind):
    allowed = {item['evidence_id'] for field in ('evidence', 'prior_evidence', 'observations')
               for item in payload.get(field, [])}
    if not isinstance(raw, dict) or set(raw) != {'verdict', 'evidence_refs', 'rationale'}:
        return False
    refs = raw['evidence_refs']
    valid = (raw['verdict'] in {'yes', 'no', 'uncertain'} and isinstance(refs, list)
             and all(isinstance(ref, str) and ref in allowed for ref in refs)
             and isinstance(raw['rationale'], str) and (raw['verdict'] != 'yes' or bool(refs)))
    if valid and kind == 'R1' and raw['verdict'] == 'yes':
        prior = {item['evidence_id'] for item in payload.get('prior_evidence', [])}
        current = {item['evidence_id'] for item in payload.get('observations', [])}
        return bool(set(refs) & prior) and bool(set(refs) & current)
    return valid


class AuthenticationError(RuntimeError):
    """Only safe status metadata; never includes response bodies or credentials."""
    def __init__(self, reason, http_status=None):
        super().__init__(reason)
        self.reason, self.http_status = reason, http_status


def check_deepseek_auth(key):
    """GET the fixed official /models endpoint without proxies or redirects."""
    request = Request('https://api.deepseek.com/models',
                      headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}, method='GET')
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=30) as response:
        code = response.status
        if code != 200:
            raise AuthenticationError('authentication_failed', code)
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise AuthenticationError('invalid_models_response', 200)
    envelope = json.loads(raw)
    if (not isinstance(envelope, dict) or not isinstance(envelope.get('data'), list)
            or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in envelope['data'])):
        raise AuthenticationError('invalid_models_response', 200)
    return [item['id'] for item in envelope['data']]


def run_smoke(output, *, provider='custom', remember_key=False, judge_factory=None,
              input_fn=None, getpass_fn=None, clock=None, auth_checker=None,
              key_loader=None, key_saver=None):
    """Prompt in the terminal, run six cases once, and create result + status.json.

    Both paths must be unused. Injection points substitute terminal/network/time
    boundaries for offline tests. No endpoint or plaintext credentials are written to disk;
    remember_key explicitly enables the DeepSeek encrypted credential store.
    no endpoint/key CLI flags or environment-variable credential lookup exist.
    A successful request with a wrong label is a completed check, not an API error.
    """
    if provider not in ('custom', 'deepseek'):
        raise ValueError('provider must be custom or deepseek')
    if type(remember_key) is not bool or (remember_key and provider != 'deepseek'):
        raise ValueError('remember_key requires the deepseek provider')
    output = Path(output).resolve()
    state_path = output.with_name('status.json')
    if output == state_path or output.exists() or state_path.exists():
        raise FileExistsError('result and status paths must be unused')
    output.parent.mkdir(parents=True, exist_ok=True)
    status = _Status(state_path)
    input_fn = input_fn or input
    getpass_fn = getpass_fn or getpass.getpass
    clock = clock or time.perf_counter
    judge_factory = judge_factory or LocalJudge
    auth_checker = auth_checker or check_deepseek_auth
    credential_saved, authentication = False, None
    try:
        status.write('waiting_for_input')
        print('Only six built-in synthetic cases will be sent. No user files are read.')
        print('Endpoint is not saved. The API key is encrypted locally only when --remember-key is enabled.')
        if provider == 'deepseek':
            endpoint, model = 'https://api.deepseek.com', 'deepseek-flash'
            print('DeepSeek official API / deepseek-flash / non-thinking JSON check. Only enter your API key below.')
        else:
            endpoint = input_fn('Judge API base URL (local or your chosen remote endpoint): ').strip()
            model = input_fn('Judge model name: ').strip()
        def read_key():
            while True:
                value = getpass_fn('API key (hidden; right-click paste the complete key, then Enter): ').strip()
                if value.isascii() and all(32 <= ord(char) < 127 for char in value) and (value or provider == 'custom'):
                    return value
                print('No valid printable key was received. Use right-click paste; exclude labels, control keys and line breaks.')
        key = None
        if remember_key:
            if key_loader is None or key_saver is None:
                from .credentials import load_deepseek_key, save_deepseek_key
                key_loader = key_loader or load_deepseek_key
                key_saver = key_saver or save_deepseek_key
            try:
                key = key_loader()
            except Exception as exc:
                print(f'Saved credential could not be loaded ({type(exc).__name__}); enter a replacement below.')
        if provider == 'deepseek':
            for attempt in range(1, 4):
                if key is None:
                    status.write('waiting_for_input', phase='authentication', attempt=attempt)
                    key = read_key()
                status.write('running', phase='authentication', attempt=attempt)
                try:
                    models = auth_checker(key)
                except HTTPError as exc:
                    code = exc.code
                    exc.close()
                    if code == 401 and attempt < 3:
                        print(f'Authentication returned HTTP 401. Re-enter the key in this window (attempt {attempt + 1}/3).')
                        key = None
                        continue
                    raise AuthenticationError('authentication_failed', code) from None
                if not isinstance(models, (list, tuple, set)) or 'deepseek-flash' not in models:
                    raise AuthenticationError('model_unavailable', 200)
                if remember_key:
                    key_saver(key)
                    credential_saved = True
                    print('Authentication confirmed; the key is saved in the local encrypted credential store.')
                authentication = {'http_status': 200, 'attempts': attempt, 'model_available': True}
                break
        else:
            key = read_key()
        options = {'thinking': 'disabled'} if provider == 'deepseek' else {}
        judge = judge_factory(endpoint, model, allow_remote=True, api_key=key, **options)
        status.write('running', case_count=6)
        results = []
        for case in synthetic_cases():
            before = _usage(judge)
            started = clock()
            raw, actual, error_type, error_details = None, None, None, None
            try:
                raw = judge.check(case['kind'], deepcopy(case['payload']))
                if _valid_verdict(raw, case['payload'], case['kind']):
                    actual = raw['verdict']
                else:
                    error_type = 'InvalidVerdict'
            except Exception as exc:
                # Exception text may contain URLs, response bodies, or credentials.
                error_type = type(exc).__name__
                cause = exc.__cause__
                error_details = {'cause_type': type(cause).__name__ if cause is not None else None}
                if isinstance(cause, HTTPError):
                    error_details['http_status'] = cause.code
            elapsed = max(0.0, clock() - started)
            after = _usage(judge)
            results.append({**case, 'actual': actual, 'matches_expected': actual == case['expected'],
                            'raw_verdict': _redact(raw, (key, endpoint)), 'error_type': error_type,
                            'error_details': error_details,
                            'elapsed_seconds': elapsed,
                            'usage': {name: max(0, after[name] - before[name]) for name in before}})
        errors = sum(item['error_type'] is not None for item in results)
        matched = sum(item['matches_expected'] for item in results)
        summary = {'case_count': len(results), 'matched_count': matched,
                   'match_rate': matched / len(results), 'error_count': errors,
                   'elapsed_seconds': sum(item['elapsed_seconds'] for item in results),
                   'usage': {name: sum(item['usage'][name] for item in results)
                             for name in ('prompt_tokens', 'completion_tokens')},
                   'interpretation': INTERPRETATION}
        report = {'schema_version': 1, 'run_id': status.run_id, 'model': _redact(model, (key, endpoint)),
                  'provider': provider, 'thinking': options.get('thinking', 'server_default'),
                  'credential_saved': credential_saved, 'authentication': authentication,
                  'source': 'repository_synthetic_cases', 'cases': results, 'summary': summary}
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
        status.write('error' if errors else 'completed', case_count=len(results),
                     matched_count=matched, error_count=errors, credential_saved=credential_saved)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        # Ownership is rechecked even on failure; never overwrite an unrelated status.
        details = {'error_type': type(exc).__name__, 'credential_saved': credential_saved}
        if isinstance(exc, AuthenticationError):
            details.update(http_status=exc.http_status, reason=exc.reason)
        status.write('error', **details)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New result JSON path; its directory must have no status.json.')
    parser.add_argument('--provider', choices=['custom', 'deepseek'], default='custom')
    parser.add_argument('--remember-key', action='store_true', help='DeepSeek only: reuse and save a validated key in encrypted local storage.')
    parser.add_argument('--input-mode', choices=['terminal', 'dialog'], default='terminal')
    args = parser.parse_args(argv)
    try:
        key_input = None
        if args.input_mode == 'dialog':
            from .credential_dialog import ask_key
            key_input = ask_key
        report = run_smoke(args.output, provider=args.provider, remember_key=args.remember_key, getpass_fn=key_input)
    except KeyboardInterrupt:
        print('Smoke check cancelled (KeyboardInterrupt).')
        return 130
    except Exception as exc:
        print(f'Smoke check stopped ({type(exc).__name__}); connection details were not logged.')
        if isinstance(exc, AuthenticationError):
            print(f'Authentication status: HTTP {exc.http_status}; {exc.reason}.')
        return 1
    summary = report['summary']
    print(f"Synthetic cases: {summary['matched_count']}/{summary['case_count']} matched; {summary['error_count']} API/format errors.")
    print(INTERPRETATION)
    print(f'Results: {Path(args.output).resolve()}')
    return 1 if summary['error_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
