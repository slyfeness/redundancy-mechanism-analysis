from copy import deepcopy
import json
import unittest

from ledger_grpo.client import JudgeError, LocalJudge
from ledger_grpo.pipeline import analyze_trajectory, build_process_inputs


ANSWER = 'Sunday, January 12, 1997'
VALUE = 'sunday, january 12, 1997'


def trace_fixture():
    observation = {'document_id': 'doc', 'source_id': 'corpus',
                   'text': 'The episode happened on Sunday, January 12, 1997.', 'representation': 'snippet'}
    return {'traj_id': 't1', 'task_id': 'q1', 'task': 'On what date did the episode described by Eugene Amos happen?',
            'constraints': [{'cid': 'c1', 'text': 'date of the episode', 'required': True, 'kind': 'evidence'}],
            'response_mask': [1, 1, 1], 'outcome': 0, 'complete': True, 'submitted_candidate': None,
            'privileged': {'gold': 'never disclose'}, 'turns': [
                {'turn_id': 1, 'token_start': 0, 'token_end': 1,
                 'action': {'kind': 'search', 'query': 'episode date', 'method': 'search', 'target_id': 'c1'},
                 'observations': [dict(observation, evidence_id='e1')], 'conclusion': 'Inspect the returned event record.'},
                {'turn_id': 2, 'token_start': 1, 'token_end': 2,
                 'action': {'kind': 'search', 'query': 'episode date', 'method': 'search', 'target_id': 'c1', 'fact_id': 'f1'},
                 'observations': [dict(observation, evidence_id='e2')], 'conclusion': 'Recheck the same record.'},
                {'turn_id': 3, 'token_start': 2, 'token_end': 3, 'action': {'kind': 'submit'},
                 'observations': [], 'conclusion': f'Final wording only: Eugene Amos described it; the date was {ANSWER}.'},
            ]}


def resolved():
    return {'status': 'resolved', 'answer_text': ANSWER, 'quote': ANSWER,
            'candidate_id': VALUE, 'rationale': 'The final sentence explicitly submits this date.'}


class FakeJudge:
    model = 'offline-test'
    def __init__(self, candidate=VALUE, resolution=None):
        self.candidate = candidate
        self.resolution = resolved() if resolution is None else resolution
        self.calls = []

    def extract(self, payload):
        self.calls.append(('extract', deepcopy(payload)))
        if payload['turn']['turn_id'] != 1:
            return {'facts': []}
        return {'facts': [{'fid': 'f1', 'cid': 'c1', 'candidate_id': self.candidate,
                           'statement': 'The episode happened on Sunday, January 12, 1997.', 'state': 'supported',
                           'evidence': [{'evidence_id': 'e1', 'quote': ANSWER}]}]}

    def check(self, kind, payload):
        self.calls.append((kind, deepcopy(payload)))
        return {'verdict': 'yes', 'evidence_refs': ['e1', 'e2'] if kind == 'R1' else ['e1'],
                'rationale': 'The quoted observed relation establishes the claim.'}

    def resolve_submission(self, payload):
        self.calls.append(('resolve', deepcopy(payload)))
        return deepcopy(self.resolution)


class SubmissionTests(unittest.TestCase):
    def test_free_prose_submission_is_bound_to_actual_value_without_outcome_leak(self):
        trace, judge = trace_fixture(), FakeJudge()
        report = analyze_trajectory(trace, judge=judge)
        self.assertEqual(report['resolved_submission']['candidate_id'], VALUE)
        self.assertEqual(report['resolved_submission']['turn_id'], 3)
        self.assertEqual(report['metrics']['candidate_matching_fact_count'], 1)
        self.assertTrue(report['metrics']['candidate_match_available'])
        self.assertEqual(report['metrics']['grounding_score'], 1.)
        row = build_process_inputs(trace, report)
        self.assertTrue(row['process_valid'])
        self.assertEqual(row['outcome'], 0)
        self.assertIsNone(trace['submitted_candidate'])
        self.assertEqual(judge.calls[-1][0], 'resolve')
        payload = judge.calls[-1][1]
        self.assertEqual(set(payload), {'task', 'constraints', 'ledger', 'turn_id', 'final_text'})
        self.assertNotIn('never disclose', json.dumps(payload))

    def test_redundancy_judgement_cannot_see_later_submission_resolution(self):
        judge = FakeJudge()
        report = analyze_trajectory(trace_fixture(), judge=judge)
        self.assertTrue(any(span['label'] == 'R1' for span in report['spans']))
        for kind, payload in judge.calls[:-1]:
            self.assertNotIn('resolved_submission', payload)
            self.assertNotIn('outcome', payload)
            if kind == 'R1' or (kind == 'extract' and payload['turn']['turn_id'] < 3):
                self.assertNotIn('Final wording only', json.dumps(payload))

    def test_old_entity_id_and_unmatched_date_format_remain_unknown_not_grounding_zero(self):
        for candidate in ('eugene-amos', 'sunday 12 january 1997'):
            with self.subTest(candidate=candidate):
                trace = trace_fixture()
                report = analyze_trajectory(trace, judge=FakeJudge(candidate=candidate))
                self.assertEqual(report['ledger']['facts'][0]['candidate_id'], candidate)
                self.assertEqual(report['metrics']['candidate_matching_fact_count'], 0)
                self.assertFalse(report['metrics']['candidate_match_available'])
                self.assertIsNone(report['metrics']['grounding_score'])
                self.assertFalse(build_process_inputs(trace, report)['process_valid'])

    def test_uncertain_submission_does_not_guess_or_change_parse_qa(self):
        resolution = {'status': 'uncertain', 'answer_text': None, 'quote': None,
                      'candidate_id': None, 'rationale': 'Two alternatives remain without a committed answer.'}
        trace = trace_fixture()
        report = analyze_trajectory(trace, judge=FakeJudge(resolution=resolution))
        self.assertTrue(report['qa']['parse_ok'])
        self.assertIsNone(report['metrics']['grounding_score'])
        self.assertFalse(build_process_inputs(trace, report)['process_valid'])

    def test_forged_quote_candidate_or_nonfinal_turn_is_rejected_at_scoring(self):
        trace = trace_fixture()
        report = analyze_trajectory(trace, judge=FakeJudge())
        for field, value in (('quote', 'not actually submitted'), ('candidate_id', 'eugene-amos'), ('turn_id', 1)):
            with self.subTest(field=field):
                modified = deepcopy(report)
                modified['resolved_submission'][field] = value
                with self.assertRaises(ValueError):
                    build_process_inputs(trace, modified)

    def test_only_final_complete_submit_can_trigger_resolution(self):
        for variant in ('incomplete', 'not_submit'):
            with self.subTest(variant=variant):
                trace, judge = trace_fixture(), FakeJudge()
                if variant == 'incomplete':
                    trace['complete'] = False
                else:
                    trace['turns'][-1]['action']['kind'] = 'decision'
                report = analyze_trajectory(trace, judge=judge)
                self.assertFalse(any(kind == 'resolve' for kind, _ in judge.calls))
                self.assertIsNone(report['resolved_submission'])

    def test_invalid_resolution_uses_existing_qa_failure_gate(self):
        bad = resolved()
        bad['candidate_id'] = 'eugene-amos'
        trace = trace_fixture()
        report = analyze_trajectory(trace, judge=FakeJudge(resolution=bad))
        self.assertFalse(report['qa']['parse_ok'])
        self.assertFalse(build_process_inputs(trace, report)['process_valid'])
        self.assertFalse(any(span['reward_eligible'] for span in report['spans']))

    def test_local_client_validates_submission_and_normalizes_visible_candidate_values(self):
        judge = LocalJudge('http://127.0.0.1:1/v1', 'offline')
        self.assertTrue(callable(getattr(judge, 'resolve_submission', None)), 'submission method is missing')
        judge._request = lambda prompt, payload: resolved()
        result = judge.resolve_submission({'task': 'What date?', 'constraints': [], 'ledger': {},
                                            'turn_id': 3, 'final_text': 'It was ' + ANSWER + '.'})
        self.assertEqual(result['candidate_id'], VALUE)
        bad = resolved()
        bad['candidate_id'] = 'eugene-amos'
        judge._request = lambda prompt, payload: bad
        with self.assertRaises(JudgeError):
            judge.resolve_submission({'task': 'What date?', 'constraints': [], 'ledger': {},
                                       'turn_id': 3, 'final_text': 'It was ' + ANSWER + '.'})
        judge._request = lambda prompt, payload: {'facts': [{'candidate_id': '  Sunday,  January 12, 1997  '}],
                                                 'action_target': {'candidate_id': ' ＡＤＡ  Lovelace '}}
        delta = judge.extract({})
        self.assertEqual(delta['facts'][0]['candidate_id'], VALUE)
        self.assertEqual(delta['action_target']['candidate_id'], 'ada lovelace')

    def test_literal_normalization_preserves_answer_punctuation(self):
        from ledger_grpo.client import canonical_answer_value
        self.assertEqual(canonical_answer_value('  *  '), '*')
        self.assertEqual(canonical_answer_value(' Ａ  +  B '), 'a + b')


if __name__ == '__main__':
    unittest.main()
