"""Tiny synthetic fixtures for interface checks, never empirical task results."""
from copy import deepcopy


def synthetic_examples():
    traces, deltas = [], {}
    for index, (outcome, repeat) in enumerate([(1, True), (1, False), (0, True)]):
        trace = {'traj_id': f'evidence-{index}', 'task_id': 'synthetic-evidence',
                 'task': 'Find the year Ada joined the club; cite the archive.',
                 'constraints': [{'cid': 'c1', 'text': 'The joining year must be supported by the archive.'}],
                 'outcome': outcome, 'submitted_candidate': 'ada', 'complete': True,
                 'budget_tokens': 5, 'response_mask': [], 'turns': []}
        for turn_id in range(1, 3 if repeat else 2):
            start = len(trace['response_mask'])
            trace['response_mask'].extend([1, 1, 0, 0])
            trace['turns'].append({'turn_id': turn_id, 'token_start': start, 'token_end': start + 4,
                                   'action': {'kind': 'search', 'target_id': 'c1', 'query': 'Ada club joining year'},
                                   'observations': [{'evidence_id': f'e{turn_id}', 'document_id': 'archive-page',
                                                     'source_id': 'club-archive', 'text': 'Ada is listed as a club member.'}]})
        start = len(trace['response_mask'])
        trace['response_mask'].extend([1, 1, 0, 0])
        trace['turns'].append({'turn_id': 5, 'token_start': start, 'token_end': start + 4,
                               'action': {'kind': 'read', 'target_id': 'c1', 'query': 'membership register'},
                               'observations': [{'evidence_id': 'e3', 'document_id': 'membership-register',
                                                 'source_id': 'club-archive', 'text': 'Ada joined in 1994.'}]})
        start = len(trace['response_mask'])
        trace['response_mask'].extend([1, 1])
        trace['turns'].append({'turn_id': 7, 'token_start': start, 'token_end': start + 2,
                               'action': {'kind': 'submit'}, 'observations': []})
        fact = {'fid': 'f1', 'cid': 'c1', 'candidate_id': 'ada', 'statement': 'Ada joined in 1994.',
                'state': 'supported', 'evidence': [{'evidence_id': 'e3', 'quote': 'Ada joined in 1994.'}]}
        deltas[trace['traj_id']] = {str(t['turn_id']): {'facts': [deepcopy(fact)] if t['turn_id'] == 5 else []} for t in trace['turns']}
        traces.append(trace)
    for index, (outcome, submitted) in enumerate([(1, 'v2'), (1, 'v1'), (0, 'v2')]):
        trace = {'traj_id': f'artifact-{index}', 'task_id': 'synthetic-artifact',
                 'task': 'Submit the implementation version that passed the specified test.',
                 'constraints': [{'cid': 'a1', 'text': 'Submit a tested version', 'kind': 'artifact', 'artifact_id': 'program'}],
                 'outcome': outcome, 'complete': True, 'response_mask': [1, 1, 1, 1, 1, 1],
                 'turns': []}
        for tid, (kind, version) in enumerate([('write', 'v1'), ('test', 'v1'), ('submit', submitted)], 1):
            event = {'artifact_id': 'program', 'version': version, 'operation': kind}
            if kind == 'test':
                event['passed'] = True
            trace['turns'].append({'turn_id': tid, 'token_start': (tid - 1) * 2, 'token_end': tid * 2,
                                   'action': {'kind': kind, 'target_id': 'a1'}, 'artifact': event, 'observations': []})
        deltas[trace['traj_id']] = {str(t['turn_id']): {'facts': []} for t in trace['turns']}
        traces.append(trace)
    return traces, deltas
