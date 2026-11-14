"""Exercise event continuation using archived wire traffic and frozen tokenizer."""

import argparse
from collections import Counter
import json
from pathlib import Path

from transformers import AutoTokenizer

from ledger_grpo.event_continuation import continue_browsecomp
from run_event_deletion_branch import bind_branch, read


def audit_normal(raw, request, pair, tokenizer, config):
    start = pair['round_id']
    suffix = [row for row in raw['rounds'] if row['round_id'] >= start]
    model = iter(suffix)
    tools = iter(event for event in raw['tool_events'] if event['round_id'] >= start)

    def sample(payload):
        saved = next(model)
        expected = read(Path(saved['raw_request_path']))
        if payload != expected:
            changed = sorted(key for key in set(payload) | set(expected) if payload.get(key) != expected.get(key))
            raise ValueError(f'continuation request differs from archived round {saved["round_id"]} fields {changed}')
        return saved['raw_response']

    def search(name, arguments):
        event = next(tools)
        if name != event['tool_name'] or json.loads(arguments) != json.loads(event['exact_arguments']):
            raise ValueError('continuation search differs from archived dispatch')
        return event['exact_result']

    result = continue_browsecomp(request, pair['normal'], seed=request['seed'], start_round=start,
                                max_rounds=config['max_actor_calls'], context=config['context'],
                                headroom=raw['metadata']['headroom_tokens'], tokenizer=tokenizer,
                                sample=sample, search=search)
    if (result['terminal'] != raw['metadata']['terminal_status'] or next(model, None) is not None
            or next(tools, None) is not None):
        raise ValueError('continuation terminal or archived traffic coverage differs')
    if result['terminal'] == 'MODEL_FINAL_STOP' and result['final'] != suffix[-1]['content']:
        raise ValueError('continuation did not recover the recorded final submission')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollout', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    audit = read(args.audit)
    config = read(args.rollout / 'config_manifest.json')
    first = {}
    for row in audit['pairs']:
        first.setdefault(row['sample_id'], row['event_id'])
    checks = []
    totals = Counter()
    for sample_id, event_id in first.items():
        raw, request, pair, _, _ = bind_branch(args.rollout, audit, sample_id, event_id, tokenizer)
        result = audit_normal(raw, request, pair, tokenizer, config)
        totals.update(trajectories=1, model_requests=result['actor_calls'], search_calls=result['tool_calls'])
        totals[result['terminal']] += 1
        checks.append({'sample_id': sample_id, 'event_id': event_id, 'continuation_round': pair['round_id'],
                       **{key: value for key, value in result.items() if key != 'final'}})
    report = {'scope': 'Offline replay of original control-condition traffic. No new generation or correctness judgments.',
              'totals': dict(totals), 'controls': checks}
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps(totals), flush=True)


if __name__ == '__main__':
    main()
