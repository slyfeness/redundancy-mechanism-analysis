"""Prepare blinded, prefix-only records of charged and matched control events."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import secrets

import torch

from ledger_grpo.browsecomp_adapter import _recorded_search_response


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False)


def case_for_event(raw, event, question, documents):
    tool_messages = {(m['tool_call_id'], m['content'])
                     for row in raw['rounds'] if row['round_id'] <= event['round_id']
                     and row.get('request_sent') is True and row.get('response_received') is True
                     for m in row.get('actor_visible_messages', ()) if m.get('role') == 'tool'}
    prefix = [prior for prior in raw['tool_events'] if prior['round_id'] < event['round_id']
              and _recorded_search_response(prior) and (prior['tool_call_id'], prior['exact_result']) in tool_messages]

    def describe(item):
        records = json.loads(item['exact_result'])
        refs = []
        for doc in records:
            key = hashlib.sha256(json.dumps([doc['docid'], doc['snippet']], ensure_ascii=False).encode()).hexdigest()
            documents.setdefault(key, {'docid': str(doc['docid']), 'snippet': doc['snippet']})
            refs.append(key)
        return {'tool': item['tool_name'], 'arguments': json.loads(item['exact_arguments']), 'documents': refs}

    prior, current = [describe(item) for item in prefix], describe(event)
    current_docs = set(current['documents'])
    closest = sorted(enumerate(prior), key=lambda entry: (len(current_docs & set(entry[1]['documents'])), entry[0]),
                     reverse=True)[:2]
    return {'question': question, 'current': current, 'prior': prior,
            'closest_prior_indices': [i for i, _ in closest]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.run
    score_path = run/'scored/targeted-scores.pt'
    saved = torch.load(score_path, map_location='cpu', weights_only=True)
    if saved['control'] != 'targeted' or len(saved['charged']) != 10:
        raise ValueError('expected the ten original targeted training charges')
    selected = defaultdict(list)
    for receipt in saved['charged']:
        selected[receipt['traj_id']].append(receipt['event_id'])
    questions = {str(row['query_id']): row['question'] for row in read(run/'train-P0/sample_manifest.json')['selected']}
    cases, documents = [], {}
    for tid, charged in selected.items():
        raw_path = run/'train-P0/trajectories'/tid/'trajectory.json'
        source_bytes = raw_path.read_bytes()
        raw = json.loads(source_bytes)
        task = raw['metadata']['task']
        if task['run_id'] != tid:
            raise ValueError('recorded trajectory differs from the original debit')
        measured = {e['event_id']: e for e in read(run/'scored'/tid/'events.json')['events']}
        events = {str(event['event_id']): event for event in raw['tool_events']}
        controls = [key for key, event in measured.items() if event['label'] is None]
        for event_id in sorted(charged, key=lambda key: events[key]['round_id']):
            if measured[event_id]['label'] != 'R2b':
                raise ValueError('original debit lacks its R2b label')
            control = min(controls, key=lambda key: (abs(events[key]['round_id']-events[event_id]['round_id']), int(key)))
            controls.remove(control)
            for key, charged_flag in [(event_id, True), (control, False)]:
                record = events[key]
                case = case_for_event(raw, record, questions[str(task['query_id'])], documents)
                binding = {'sample_id': tid, 'task_id': str(task['query_id']), 'event_id': key, 'charged': charged_flag,
                           'trajectory_sha256': hashlib.sha256(source_bytes).hexdigest()}
                cases.append((case, binding))
    secrets.SystemRandom().shuffle(cases)
    args.output.mkdir(mode=0o700, exist_ok=False)
    packet, identities = {}, {}
    for i, (case, binding) in enumerate(cases, 1):
        identity = f'case-{i:02d}'
        packet[identity], identities[identity] = case, binding
    write(args.output/'PACKET.json', {'cases': packet, 'documents': documents})
    write(args.output/'IDENTITIES.json', {'source_run': str(run), 'cases': identities,
                                         'score_sha256': hashlib.sha256(score_path.read_bytes()).hexdigest()})
    print('blinded_cases', len(packet), 'trajectories', len(selected), flush=True)


if __name__ == '__main__':
    main()
