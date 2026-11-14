"""Project measured sampler observations onto the common prefix ledger."""

import hashlib
import json

from .sampler_tool_adapter import _FIELDS
from .schema import validate_trajectory


_ACTIONS = {'search':'search', 'open':'read', 'read_code':'read', 'run_python':'test',
            'write_code':'write', 'submit_answer':'submit', 'submit_code':'submit'}


def _evidence(dataset, event, stage):
    result = event[_FIELDS[dataset][1]]
    name = event['name']
    if dataset == 'sage':
        documents = result.get('results', []) if name == 'search' else [result] if name == 'open' else []
        rows = []
        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                continue
            text = document.get('snippet') if name == 'search' else document.get('text')
            doc_id, corpus = document.get('doc_id'), document.get('corpus_id')
            if not isinstance(text, str) or type(doc_id) not in (str, int) or not isinstance(corpus, str) or not corpus:
                continue
            full = name == 'open' and document.get('offset') == 0 and document.get('total_text_characters') == len(text)
            rows.append({'evidence_id': f'{event["event_id"]}:doc{index}', 'document_id': str(doc_id),
                         'source_id': f'sage:{corpus}', 'text': text, 'version': hashlib.sha256(text.encode()).hexdigest(),
                         'representation': 'fulltext' if full else 'snippet'})
        return rows

    if name == 'read_code' and result.get('status') == 'OK':
        return [{'evidence_id': f'{event["event_id"]}:draft', 'document_id': 'draft',
                 'source_id': f'scicode:step-{stage}', 'text': result['current_code'], 'version': result['code_sha256']}]
    if name == 'run_python' and type(result.get('exit_code')) is int:
        # These are actor-authored test outputs. They do not establish that
        # an official test passed, and local filesystem paths stay private.
        return [{'evidence_id': f'{event["event_id"]}:{key}', 'document_id': f'{event["event_id"]}:{key}',
                 'source_id': f'scicode:step-{stage}:sandbox', 'text': result[key]}
                for key in ('stdout','stderr') if isinstance(result.get(key), str) and result[key]]
    return []


def project_sampler_process(dataset, stage, rounds, batches, layout, measured, constraints, *, traj_id, task_id):
    observed = [row for row in rounds if row.get('call_index') is not None]
    if not observed:
        return None
    first_request = next(row['request'] for row in rounds if row.get('response_received') is True)
    task_texts = [m['content'] for m in first_request['messages'] if m['role'] == 'user']
    if len(task_texts) != 1 or not isinstance(task_texts[0], str) or not task_texts[0].strip():
        raise ValueError('process projection requires the recorded visible task')
    task = task_texts[0]
    if (not isinstance(constraints, list) or not constraints
            or any(not isinstance(c, dict) or not isinstance(c.get('text'), str) or c['text'] not in task
                   for c in constraints)):
        raise ValueError('process constraints must quote this stage\'s visible task')
    offset = layout['turns'][observed[0]['call_index']]['token_start']
    end = layout['turns'][observed[-1]['call_index']]['token_end']
    turns, raw_events = [], []
    measured_ids = {row['event_id'] for row in measured}
    for row in observed:
        position = layout['turns'][row['call_index']]
        turn = position['turn_id']
        events = batches.get(row['round_id'], [])
        action = {'kind': 'decision' if not events else 'other'}
        if len(events) == 1:
            event, = events
            args = event['arguments']
            action = {'kind': _ACTIONS.get(event['name'], 'other'), 'method': event['name'],
                      'query': args['query'] if event['name']=='search' and isinstance(args.get('query'),str)
                      else json.dumps(args, sort_keys=True, ensure_ascii=False)}
        observations = [item for event in events if event['event_id'] in measured_ids
                        for item in _evidence(dataset, event, stage)]
        if action['kind'] == 'decision' and row['response']['choices'][0].get('finish_reason') == 'stop' and row is observed[-1]:
            content = row['response']['choices'][0]['message'].get('content')
            if dataset == 'sage' and isinstance(content, str) and content.strip():
                action = {'kind':'submit'}
        turns.append({'turn_id': turn, 'token_start': position['token_start']-offset,
                      'token_end': position['token_end']-offset, 'action': action, 'observations': observations,
                      'conclusion': row['response']['choices'][0]['message'].get('content') or ''})
        raw_events.extend({'event_id': event['event_id'], 'round_id': turn} for event in events)
    turn_ids = {turn['turn_id'] for turn in turns}
    trace = validate_trajectory({'traj_id': f'{traj_id}:stage-{stage}', 'task_id': task_id, 'task': task,
                                 'constraints': constraints, 'turns': turns, 'outcome': 0, 'complete': False,
                                 'response_mask': layout['response_mask'][offset:end]})
    return {'stage_index': stage, 'policy_token_offset': offset, 'trace': trace, 'tool_events': raw_events,
            'measured_events': [row for row in measured if row['turn_id'] in turn_ids], 'process_only': True}
