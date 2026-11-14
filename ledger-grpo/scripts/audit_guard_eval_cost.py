"""Recompute verified native tool-event costs on the frozen evaluation."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics

from transformers import AutoTokenizer

from ledger_grpo.browsecomp_adapter import _recorded_search_response
from ledger_grpo.browsecomp_events import _call_ranges, _return_counts, _terminal_guard_matches, exact_repeat_witnesses
from ledger_grpo.evaluation import paired_event_diagnostics


def cost_delta(raw, tokenizer, artifact):
    by_round = defaultdict(list)
    for event in raw['tool_events']:
        by_round[event['round_id']].append(event)
    repeats = exact_repeat_witnesses(raw['rounds'], by_round)
    counts = Counter()
    rounds = raw['rounds']
    for i, row in enumerate(rounds):
        events = sorted(by_round[row['round_id']], key=lambda event: event['tool_ordinal'])
        if not events:
            continue
        guard = i+1 == len(rounds) and _terminal_guard_matches(raw, row, events)
        byte_gap = any(not item.get('bytes') for item in row['raw_response']['choices'][0]['logprobs']['content'])
        if not guard and not (byte_gap and i+1 < len(rounds)):
            continue
        spans = _call_ranges(row, events, 0, tokenizer=tokenizer)
        if spans is None:
            continue
        returned = [0]*len(events) if guard else _return_counts(rounds[i+1], events, tokenizer, artifact)
        if returned is None:
            continue
        for event, (start, stop), tokens in zip(events, spans, returned, strict=True):
            if not _recorded_search_response(event):
                continue
            counts['added_events'] += 1
            counts['guard_events' if guard else 'contiguous_byte_events'] += 1
            counts['added_returned_tokens'] += tokens
            if str(event['event_id']) not in repeats:
                counts['added_unmarked_cost'] += stop-start+1+tokens
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.store/'runs/pilot-182516'
    receipt = json.loads((run/'BASELINE_EVALUATION_RECEIPT.json').read_bytes())
    baseline = args.store/'runs'/receipt['run_name']
    if hashlib.sha256((baseline/'EVAL-P0.json').read_bytes()).hexdigest() != receipt['summary_sha256']:
        raise ValueError('baseline raw trajectory identity does not match the frozen receipt')
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    summaries, rows_by_arm = {}, {}
    for arm in ('P0', 'outcome', 'trajectory', 'targeted', 'shuffled', 'uniform'):
        summary_bytes = (run/f'EVAL-{arm}.json').read_bytes()
        rows = json.loads(summary_bytes)['rows']
        folder = (baseline if arm == 'P0' else run)/f'eval-{arm}'/'trajectories'
        if len(rows) != 128 or len({(r['task_id'], r['sample_id']) for r in rows}) != 128:
            raise ValueError('frozen evaluation row identities are incomplete')
        counts = Counter()
        before = [row['unmarked_event_cost'] for row in rows if row['unmarked_event_cost'] is not None]
        returned_before = [row['measured_return_tokens'] for row in rows if row['measured_return_tokens'] is not None]
        for row in rows:
            if row['unmarked_event_cost'] is None or row['measured_tool_events'] == row['recorded_tool_events']:
                continue
            artifact = folder/row['sample_id']
            raw = json.loads((artifact/'trajectory.json').read_bytes())
            task = raw['metadata']['task']
            if (str(task['query_id']), task['run_id']) != (row['task_id'], row['sample_id']):
                raise ValueError('evaluation row does not bind to the native trajectory')
            delta = cost_delta(raw, tokenizer, artifact.resolve())
            if row['measured_tool_events'] + delta['added_events'] > row['recorded_tool_events']:
                raise ValueError('native replay would double-count measured events')
            row['unmarked_event_cost'] += delta['added_unmarked_cost']
            row['measured_return_tokens'] += delta['added_returned_tokens']
            counts.update(delta)
            counts['trajectories_affected'] += int(delta['added_events'] > 0)
        after = [row['unmarked_event_cost'] for row in rows if row['unmarked_event_cost'] is not None]
        returned_after = [row['measured_return_tokens'] for row in rows if row['measured_return_tokens'] is not None]
        rows_by_arm[arm] = rows
        summaries[arm] = dict(counts, original_evaluation_sha256=hashlib.sha256(summary_bytes).hexdigest(),
                              mean_unmarked_before=statistics.fmean(before), mean_unmarked_after=statistics.fmean(after),
                              mean_returned_before=statistics.fmean(returned_before), mean_returned_after=statistics.fmean(returned_after))
        print(arm, json.dumps(summaries[arm]), flush=True)
    paired = {f'targeted_minus_{arm}': {key: value for key, value in
                                     paired_event_diagnostics(rows_by_arm[arm], rows_by_arm['targeted'])['delta'].items()
                                     if key in ('unmarked_event_cost', 'measured_return_tokens')}
              for arm in ('P0', 'outcome', 'trajectory', 'shuffled', 'uniform')}
    result = {'source_run': str(run), 'scope': 'cost accounting replay on fixed existing evaluation trajectories',
              'arms': summaries, 'event_cost_comparisons': paired}
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, allow_nan=False)


if __name__ == '__main__':
    main()
