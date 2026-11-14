"""Regenerate one BrowseComp event suffix on the existing Actor and retriever."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from ledger_grpo.event_continuation import continue_browsecomp
from ledger_grpo.event_deletion import prepare_event_deletion

from audit_event_deletion_prefixes import token_digest
from audit_shared_tool_coordinates import read, source_rounds


def bind_branch(rollout, audit, sample_id, event_id, tokenizer):
    if Path(sample_id).name != sample_id:
        raise ValueError('expected a direct trajectory ID')
    entries = [row for row in audit['pairs'] if (row['sample_id'], row['event_id']) == (sample_id, event_id)]
    if len(entries) != 1 or audit['protocol'] != 'browsecomp-matched-single-event-prefix-v1':
        raise ValueError('branch must reference a uniquely audited event')
    receipt = entries[0]
    artifact = (rollout / 'trajectories' / sample_id).resolve()
    source = (artifact / 'trajectory.json').read_bytes()
    if hashlib.sha256(source).hexdigest() != receipt['trajectory_sha256']:
        raise ValueError('branch source differs from the audited trajectory')
    raw = json.loads(source)
    for current, following, request, events, _ in source_rounds(raw, artifact):
        if following['round_id'] != receipt['continuation_round']:
            continue
        pair = prepare_event_deletion(current, following, request, events, event_id, tokenizer)
        if any(token_digest(pair[mode]['prompt_token_ids']) != receipt[f'{mode}_prompt_sha256']
               for mode in ('normal', 'delete')):
            raise ValueError('branch prompt IDs differ from the audit')
        target = next(event for event in events if event['event_id'] == event_id)
        return raw, request, pair, target, receipt
    raise ValueError('audited continuation round is missing from the source')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollout', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--sample-id', required=True)
    parser.add_argument('--event-id', required=True)
    parser.add_argument('--condition', choices=('normal', 'delete'), required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--actor-url', required=True)
    parser.add_argument('--actor-dir', type=Path, required=True)
    parser.add_argument('--mcp-port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.rollout = args.rollout.resolve(strict=True)
    args.actor_dir = args.actor_dir.resolve(strict=True)
    args.output = args.output.resolve()
    url = urlsplit(args.actor_url)
    if (url.scheme, url.hostname, url.path, url.query, url.fragment) != ('http', '127.0.0.1', '', '', '') or not url.port:
        parser.error('use the existing same-job Actor on a local port')

    from transformers import AutoTokenizer
    from src.resident_controller import fingerprint
    from src.resident_rollout import ActorAdmin
    from src.rollout import runtime

    runtime(args.output)
    import phase06_runtime as base
    import phase10_actor as phase10

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    audit_bytes = args.audit.read_bytes()
    raw, request, pair, target, receipt = bind_branch(args.rollout, json.loads(audit_bytes), args.sample_id,
                                                       args.event_id, tokenizer)
    metadata = raw['metadata']
    config = read(args.rollout / 'config_manifest.json')
    max_rounds, context = config['max_actor_calls'], config['context']
    max_tokens, headroom = config['max_tokens_per_call'], metadata['headroom_tokens']
    if (metadata['service_max_model_len'], metadata['max_tokens'], request['max_tokens']) != (context, max_tokens, max_tokens):
        raise ValueError('saved continuation and original rollout limits differ')
    sampling = dict(metadata['sampling'], seed=args.seed)
    if any(request[key] != value for key, value in metadata['sampling'].items()):
        raise ValueError('saved request sampling differs from the trajectory freeze')
    runtime_receipt = {'job_id': os.environ['SLURM_JOB_ID'], 'mcp_port': args.mcp_port,
                       'actor_fingerprint': fingerprint(ActorAdmin(args.actor_url, os.environ['OCCAM_ACTOR_ADMIN'])),
                       'request_settings': {key: value for key, value in request.items() if key not in {'seed', 'messages'}},
                       'max_rounds': max_rounds, 'context': context, 'headroom': headroom}
    runtime_sha256 = hashlib.sha256(json.dumps(runtime_receipt, sort_keys=True, allow_nan=False).encode()).hexdigest()
    phase10.R = args.rollout
    args.output.mkdir(mode=0o700, exist_ok=False)
    os.chdir(args.output)

    class Server:
        url, folder = args.actor_url, args.actor_dir

        def metrics(self, name):
            (args.output / f'{name}_metrics.txt').write_bytes(base.http(self.url + '/metrics', timeout=5))

    recorder = phase10.Recorder(args.output, Server(), tokenizer, context, max_tokens, sampling=sampling)
    recorder.current = pair['round_id'] - 1
    identity = {'audit_sha256': hashlib.sha256(audit_bytes).hexdigest(), 'sample_id': args.sample_id,
                'trajectory_sha256': receipt['trajectory_sha256'], 'event_id': args.event_id,
                'condition': args.condition, 'seed': args.seed, 'continuation_round': pair['round_id'],
                'prefix_sha256': receipt[f'{args.condition}_prompt_sha256'], 'runtime_sha256': runtime_sha256}
    recorder.metadata.update(branch=identity)
    recorder.save()
    bot = base.make_native_agent(recorder, [{'mcpServers': {'search-server': {
        'url': f'http://127.0.0.1:{args.mcp_port}/sse'}}}])

    def sample(payload):
        try:
            return recorder.call(payload)
        except base.LengthStop:
            return recorder.rounds[-1]['raw_response']

    def dispatch_tool(name, arguments):
        result = bot._call_tool(name, arguments)
        if name in bot.function_map:
            response = recorder.events[-1].get('raw_mcp_response') or {}
            if response.get('isError') is not False:
                raise ValueError('search service did not return a verified result')
        return result

    result = continue_browsecomp(request, pair[args.condition], seed=args.seed, start_round=pair['round_id'],
                                max_rounds=max_rounds, context=context, headroom=headroom,
                                tokenizer=tokenizer, sample=sample, search=dispatch_tool)
    recorder.metadata['terminal_status'] = result['terminal']
    recorder.save()
    target_args = json.loads(target['exact_arguments'])
    result['exact_target_retries'] = sum(event['tool_name'] == target['tool_name']
                                         and json.loads(event['exact_arguments']) == target_args
                                         for event in recorder.events)
    result['suffix_trajectory_sha256'] = hashlib.sha256((args.output / 'trajectory.json').read_bytes()).hexdigest()
    with (args.output / 'BRANCH_RESULT.json').open('x', encoding='utf-8') as handle:
        json.dump({'identity': identity, **result}, handle, ensure_ascii=False, allow_nan=False)


if __name__ == '__main__':
    main()
