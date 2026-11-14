"""Reconcile frozen R2b labels against visible tool returns on the saved pilot."""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from ledger_grpo.browsecomp_adapter import _recorded_search_response
from ledger_grpo.browsecomp_events import exact_repeat_witnesses


def read(path):
    return json.loads(path.read_bytes())


def audit(raw):
    positions = {r['round_id']: i for i, r in enumerate(raw['rounds'])}
    appearances = defaultdict(list)
    for i, row in enumerate(raw['rounds']):
        if row.get('request_sent') is True and row.get('response_received') is True:
            for msg in row.get('actor_visible_messages') or []:
                if msg.get('role') == 'tool' and isinstance(msg.get('content'), str):
                    appearances[msg.get('tool_call_id'), msg['content']].append(i)

    groups = defaultdict(list)
    rounds = defaultdict(list)
    call_counts = Counter()
    for event in raw['tool_events']:
        rounds[event['round_id']].append(event)
        call_counts[event['tool_call_id']] += 1
        if event['tool_name'] == 'search-server-search' and _recorded_search_response(event):
            key = json.dumps(json.loads(event['exact_arguments']), sort_keys=True), event['exact_result']
            groups[key].append(event)

    legacy, reference = set(), set()
    for events in groups.values():
        for current in events:
            here = positions[current['round_id']]
            identity = str(current['event_id'])
            for prior in events:
                earlier = positions[prior['round_id']]
                if earlier >= here:
                    continue
                legacy.add(identity)
                times = appearances[prior['tool_call_id'], prior['exact_result']]
                first = bisect_right(times, earlier)
                if first < len(times) and times[first] <= here:
                    reference.add(identity)
                    break
    actual = exact_repeat_witnesses(raw['rounds'], rounds)
    has_duplicate_calls = any(count > 1 for count in call_counts.values())
    if not has_duplicate_calls and set(actual) != reference:
        raise ValueError('prefix witness implementation differs from the independent timestamp check')
    if not set(actual) <= legacy:
        raise ValueError('visibility rule marked an event without a recorded exact repeat')
    return legacy, actual, has_duplicate_calls


def audit_folder(summary, folder, *, training_scores=None, scored=None):
    counts, differences = Counter(), []
    for row in summary:
        tid, qid = row['sample_id'], row['task_id']
        raw = read(folder/'trajectories'/tid/'trajectory.json')
        task = raw['metadata']['task']
        if (str(task['query_id']), task['run_id']) != (qid, tid):
            raise ValueError('native trajectory identity differs from the frozen evaluation')
        legacy, visible, has_duplicate_calls = audit(raw)
        counts.update(samples=1, recorded_exact_repeats=len(legacy), visible_exact_repeats=len(visible),
                      duplicate_call_id_trajectories=int(has_duplicate_calls))
        old = row.get('exact_repeat_events')
        if old is not None:
            counts['original_metric_covered'] += 1
            if old != len(legacy):
                raise ValueError(f'frozen repeat count differs from the legacy replay for {tid}')
        if len(legacy) != len(visible):
            differences.append({'sample_id': tid, 'event_ids_without_witness': sorted(legacy - visible.keys())})
        if scored is not None:
            events = read(scored/tid/'events.json')['events']
            labels = {e['event_id'] for e in events if e['label'] == 'R2b'}
            revised = {e['event_id'] for e in events if e['event_id'] in visible}
            counts['measured_r2b'] += len(labels)
            counts['revised_measured_r2b'] += len(revised)
            counts['measured_r2b_changed'] += len(labels ^ revised)
            for event_id in training_scores[tid]:
                if event_id not in labels:
                    raise ValueError('frozen targeted debit lacks a measured R2b receipt')
                counts['targeted_charged_events'] += 1
                counts['targeted_charges_without_visible_witness'] += int(event_id not in visible)
    return dict(counts), differences


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.store/'runs/pilot-182516'
    receipt = read(run/'BASELINE_EVALUATION_RECEIPT.json')
    baseline = args.store/'runs'/receipt['run_name']
    original_p0 = (baseline/'EVAL-P0.json').read_bytes()
    if (hashlib.sha256(original_p0).hexdigest() != receipt['summary_sha256']
            or json.loads(original_p0) != read(run/'EVAL-P0.json')):
        raise ValueError('frozen P0 summary does not match its bound original rollout')
    results = {}
    for arm in ('P0', 'outcome', 'trajectory', 'targeted', 'shuffled', 'uniform'):
        rows = read(run/f'EVAL-{arm}.json')['rows']
        if len(rows) != 128 or len({(row['task_id'], row['sample_id']) for row in rows}) != 128:
            raise ValueError('fixed evaluation is incomplete')
        metrics, changes = audit_folder(rows, (baseline if arm == 'P0' else run)/f'eval-{arm}')
        results[arm] = {'metrics': metrics, 'changed_samples': changes}
        print(arm, json.dumps(metrics), flush=True)

    import torch

    scored = run/'scored'
    charged = defaultdict(list)
    scores = torch.load(scored/'targeted-scores.pt', map_location='cpu', weights_only=True)
    for row in scores['charged']:
        charged[row['traj_id']].append(row['event_id'])
    rows = [dict(task_id=str(row['query_id']), sample_id=row['id'])
            for row in read(scored/'NATIVE_BATCH.json')['trajectories']]
    metrics, changes = audit_folder(rows, run/'train-P0', training_scores=charged, scored=scored)
    if metrics['targeted_charged_events'] != len(scores['charged']):
        raise ValueError('unmatched frozen targeted debit')
    results['train-P0'] = {'metrics': metrics, 'changed_samples': changes}
    print('train-P0', json.dumps(metrics), flush=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump({'source_run': str(run), 'arms': results}, handle, allow_nan=False)


if __name__ == '__main__':
    main()
