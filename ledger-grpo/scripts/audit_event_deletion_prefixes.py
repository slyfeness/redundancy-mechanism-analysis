"""Validate matched one-event interventions on the frozen training rollout."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer

from audit_shared_tool_coordinates import read, source_rounds
from ledger_grpo.event_deletion import prepare_event_deletion


def token_digest(ids):
    return hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    batch_path = args.run / 'scored/NATIVE_BATCH.json'
    batch = read(batch_path)['trajectories']
    if len(batch) != 32 or len({row['id'] for row in batch}) != 32:
        raise ValueError('expected the frozen 32 training samples')
    totals, rejected, pairs = Counter(), Counter(), []
    for sample in batch:
        artifact = (args.run / 'train-P0/trajectories' / sample['id']).resolve()
        source = (artifact / 'trajectory.json').read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        raw = json.loads(source)
        task = raw['metadata']['task']
        if (task['run_id'], str(task['query_id'])) != (sample['id'], str(sample['query_id'])):
            raise ValueError('native trajectory and frozen sample identities differ')
        totals['trajectories'] += 1
        totals['recorded_events'] += len(raw['tool_events'])
        for current, following, request, events, _ in source_rounds(raw, artifact):
            totals['observed_batches'] += 1
            for event in events:
                totals['observed_events'] += 1
                event_id = event['event_id']
                try:
                    pair = prepare_event_deletion(current, following, request, events, event_id, tokenizer)
                except ValueError as error:
                    rejected[str(error)] += 1
                    continue
                normal, deleted = (pair[name]['prompt_token_ids'] for name in ('normal', 'delete'))
                totals['verified_events'] += 1
                totals['verified_singleton_events'] += int(len(events) == 1)
                pairs.append({'sample_id': sample['id'], 'trajectory_sha256': digest, 'event_id': event_id,
                              'continuation_round': pair['round_id'], 'parallel_calls': len(events),
                              'normal_prompt_tokens': len(normal), 'normal_prompt_sha256': token_digest(normal),
                              'delete_prompt_tokens': len(deleted), 'delete_prompt_sha256': token_digest(deleted)})
    report = {'protocol': 'browsecomp-matched-single-event-prefix-v1',
              'scope': 'Offline input verification. No continuation outcomes were generated.',
              'batch_sha256': hashlib.sha256(batch_path.read_bytes()).hexdigest(),
              'totals': dict(totals), 'rejected': dict(rejected), 'pairs': pairs}
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps({'totals': totals, 'rejected': rejected}), flush=True)


if __name__ == '__main__':
    main()
