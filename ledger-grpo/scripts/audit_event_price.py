"""Check revised credit on the saved, authentic P0 batch without API or GPU."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path

import torch
from transformers import AutoTokenizer

from hf_pilot_train import file_sha256, load_step_inputs
from ledger_grpo.browsecomp_events import collect_tool_events
from ledger_grpo.event_price import EventPriceConfig, calibrate_event_cost, score_event_prices


ARMS = ('outcome', 'trajectory', 'targeted', 'shuffled', 'uniform')


def read(path):
    return json.loads(path.read_bytes())


def write(path, data):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    args = parser.parse_args()
    scored, rollouts = args.run/'scored', args.run/'train-P0'/'trajectories'
    native = scored/'NATIVE_BATCH.json'
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    rows, audit = [], Counter()
    per_task = defaultdict(Counter)
    for original in read(native)['trajectories']:
        tid = original['id']
        source = rollouts/tid
        trace = read(scored/tid/'trace.json')
        report = read(scored/tid/'report.json')
        events, coverage = collect_tool_events(read(source/'trajectory.json'), trace, report, tokenizer,
                                               artifact_root=source)
        audit.update(coverage)
        per_task[trace['task_id']].update(coverage)
        per_task[trace['task_id']]['correct'] += trace['outcome']
        per_task[trace['task_id']]['rows'] += 1
        per_task[trace['task_id']]['budget_failures'] += int(trace['termination_reason'] == 'budget_exhausted')
        per_task[trace['task_id']]['recording_complete'] += int(trace['recording_complete'])
        audit['measured_exact_repeats'] += sum(e['label']=='R2b' for e in events)
        rows.append(dict(trace, events=events, grounding=report['metrics']['grounding_score']))
    config = EventPriceConfig(group_size=8, loss_denominator=128*4096, median_event_cost=calibrate_event_cost(rows),
                              r1_price=0., r2a_price=0.)
    args.output.mkdir(parents=True, exist_ok=False)
    summaries, reference = {}, None
    binding = {'native_batch_sha256': file_sha256(native)}
    for arm in ARMS:
        result = score_event_prices(rows, config, arm=arm)
        result.update(config=asdict(config), input_binding=binding)
        torch.save(result, args.output/f'{arm}-scores.pt')
        mapped, manifest = load_step_inputs(native, args.output/f'{arm}-scores.pt')
        if reference is None:
            reference = result['advantages']
        summaries[arm] = dict(result['metrics'],
                              changed_vs_outcome=int((result['advantages'] != reference).sum()),
                              native_mapping=manifest['mapping_metrics'],
                              loss_denominator=mapped['loss_denominator'])
    write(args.output/'EVENTS.json', [{'traj_id': row['traj_id'], 'events': row['events']} for row in rows])
    write(args.output/'SUMMARY.json', {'source': str(args.run), 'audit': audit, 'per_task': per_task,
                                       'config': asdict(config), 'arms': summaries,
                                       'scope': 'historical P0 engineering replay; no optimizer and no judge API'})
    print(json.dumps({'audit': audit, 'targeted': summaries['targeted']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
