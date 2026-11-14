"""Replay the frozen training batch with verified native tool-cost receipts."""

import argparse
from collections import Counter
import json
from pathlib import Path

import torch
from transformers import AutoTokenizer

from event_price_pilot import ARMS, training_config
from ledger_grpo.browsecomp_adapter import adapt_trajectory
from ledger_grpo.browsecomp_events import collect_tool_events
from ledger_grpo.event_price import score_event_prices
from ledger_grpo.pipeline import _digest


def read(path):
    return json.loads(path.read_bytes())


def replay_inputs(run, tokenizer, semantic):
    scored, rollout = run/'scored', run/'train-P0'
    questions = {str(row['query_id']): row['question'] for row in read(rollout/'sample_manifest.json')['selected']}
    constraints = read(scored/'CONSTRAINTS.json')
    original, revised, additions = [], [], []
    counts = Counter()
    for native in read(scored/'NATIVE_BATCH.json')['trajectories']:
        tid, qid = native['id'], str(native['query_id'])
        artifact = rollout/'trajectories'/tid
        raw = read(artifact/'trajectory.json')
        trace, current_native = adapt_trajectory(raw, questions[qid], constraints[qid], outcome=int(native['reward']))
        report = read(scored/tid/'report.json')
        if current_native != native or report['trace_digest'] != _digest(trace):
            raise ValueError('replay differs from the original native trajectory or process report')
        prior = read(scored/tid/'events.json')['events']
        events, coverage = collect_tool_events(raw, trace, report, tokenizer, artifact_root=artifact,
                                              enabled_semantic_labels=semantic)
        old = {e['event_id']: e for e in prior}
        new = {e['event_id']: e for e in events}
        required_fields = ('event_tokens', 'label', 'event_cost', 'known_at')
        if not old.keys() <= new.keys() or any(new[k][field] != e[field] for k, e in old.items() for field in required_fields):
            raise ValueError('a previously measured event changed outside the guard accounting update')
        added = [e for e in events if e['event_id'] not in old]
        if sum(e['event_cost']['returned_tokens'] == 0 for e in added) != coverage['terminal_guard_measured_tool_events']:
            raise ValueError('zero returned tokens on added events require an unsent guard receipt')
        counts.update(recorded_tool_events=coverage['recorded_tool_events'], old_measured_events=len(prior),
                      new_measured_events=len(events), visible_exact_repeats=coverage['observed_exact_repeats'])
        additions.extend(dict(sample_id=tid, terminal=native['terminal'], **e) for e in added)
        ground = report['metrics']['grounding_score'] if report['qa']['parse_ok'] else None
        original.append(dict(trace, grounding=ground, events=prior))
        revised.append(dict(trace, grounding=ground, events=events))
    return original, revised, additions, dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    settings = read(args.run/'EVENT_PRICE_SETTINGS.json')
    config, semantic = training_config(settings)
    calibration = settings.get('semantic_calibration')
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    original, revised, additions, counts = replay_inputs(args.run, tokenizer, semantic)
    comparisons = {}
    for arm in ARMS:
        old = score_event_prices(original, config, arm=arm, semantic_calibration=calibration)
        stored = torch.load(args.run/'scored'/f'{arm}-scores.pt', map_location='cpu', weights_only=True)
        for key in ('advantages', 'effective_response_mask'):
            if not torch.equal(old[key], stored[key]):
                raise ValueError(f'{arm} frozen scoring tensor cannot be reproduced')
        if old['charged'] != stored['charged']:
            raise ValueError(f'{arm} frozen debit receipts cannot be reproduced')
        new = score_event_prices(revised, config, arm=arm, semantic_calibration=calibration)
        if not torch.equal(old['effective_response_mask'], new['effective_response_mask']):
            raise ValueError('guard accounting changed the eligible policy mask')
        previous_ids = {(e['traj_id'], e['event_id']) for e in old['charged']}
        comparisons[arm] = {'before': old['metrics'], 'after': new['metrics'],
                            'changed_policy_tokens': int((old['advantages'] != new['advantages']).sum()),
                            'additional_charges': [e for e in new['charged'] if (e['traj_id'], e['event_id']) not in previous_ids]}
    unsent = [e for e in additions if e['event_cost']['returned_tokens'] == 0]
    recovered = [e for e in additions if e['event_cost']['returned_tokens'] > 0]
    report = {'source_run': str(args.run), 'scope': 'saved training batch scoring only', 'coverage': counts,
              'median_event_cost': config.median_event_cost,
              'verified_unsent_events': unsent, 'recovered_native_envelope_events': recovered, 'arms': comparisons}
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, allow_nan=False)
    print(json.dumps({'coverage': counts, 'verified_unsent_events': len(unsent), 'recovered_native_envelope_events': len(recovered),
                      'targeted': comparisons['targeted']}), flush=True)


if __name__ == '__main__':
    main()
