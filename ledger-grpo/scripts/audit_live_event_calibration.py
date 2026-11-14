"""Verify live branch receipts and actual recorded model/tool exchanges."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from frozen_event_calibration import read_branches, read_executions, remaining_cases
from run_event_deletion_plan import load_schedule


def read(path):
    return json.loads(path.read_bytes())


def evidence_path(folder, value):
    path = Path(value).resolve(strict=True)
    if not path.is_relative_to(folder):
        raise ValueError('recorded exchange is outside its branch directory')
    return path


def verify_trajectory(trajectory, folder, row, config):
    branch = row['result']
    rounds, events = trajectory['rounds'], trajectory['tool_events']
    by_round = defaultdict(list)
    for event in events:
        by_round[event['round_id']].append(event)
    if (not rounds or len(rounds) != branch['actor_calls'] or len(events) != branch['tool_calls']
            or len({event['tool_call_id'] for event in events}) != len(events)):
        raise ValueError('branch counters do not match recorded exchanges')
    generated = returns_reinjected = 0
    previous = []
    for index, item in enumerate(rounds):
        rid = row['continuation_round'] + index
        if (item['round_id'] != rid or rid > config['max_actor_calls'] or item['request_sent'] is not True
                or item['response_received'] is not True or item['prompt_truncated']):
            raise ValueError('invalid model exchange at the recorded continuation round')
        request = read(evidence_path(folder, item['raw_request_path']))
        response = read(evidence_path(folder, item['raw_response_path']))
        tokens = item['token_accounting']
        prompt = tokens['prompt_token_ids']
        if (request['messages'] != item['actor_visible_messages'] or response != item['raw_response']
                or tokens['exact_prompt_token_ids_equal'] is not True or response['prompt_token_ids'] != prompt
                or response['choices'][0]['token_ids'] != tokens['completion_token_ids']
                or response['usage']['prompt_tokens'] != len(prompt)
                or response['usage']['completion_tokens'] != len(tokens['completion_token_ids'])):
            raise ValueError('saved request, response and native token receipts do not agree')
        if index == 0:
            prompt_sha = hashlib.sha256(json.dumps(prompt, separators=(',', ':')).encode()).hexdigest()
            if prompt_sha != row['prefix_sha256']:
                raise ValueError('first served prompt differs from the frozen branch prefix')
        expected = {'seed': row['seed'], 'max_tokens': config['max_tokens_per_call'],
                    **{name: config[name] for name in ('temperature', 'top_p', 'top_k')}}
        actual = item['sampling_params_actual']['attributes']
        if any(request[key] != val or actual[key] != val for key, val in expected.items()):
            raise ValueError('recorded sampling settings differ from the plan')
        if len(prompt) + expected['max_tokens'] + trajectory['metadata']['headroom_tokens'] > config['context']:
            raise ValueError('a served request exceeded its original context guard')
        if previous:
            observed = request['messages'][-len(previous):]
            if len(observed) != len(previous) or any(message.get('role') != 'tool'
                    or message['tool_call_id'] != event['tool_call_id'] or message['content'] != event['exact_result']
                    for message, event in zip(observed, previous, strict=True)):
                raise ValueError('the preceding tool batch was not faithfully reinjected')
            returns_reinjected += len(previous)
        previous = by_round.pop(rid, [])
        declared = item['tool_calls']
        # The original recorder stops on output-token exhaustion before dispatch.
        if item['finish_reason'] == 'length':
            declared = []
        if [event['tool_call_id'] for event in previous] != [call['id'] for call in declared]:
            raise ValueError('dispatch does not match the native tool call order')
        registered = {tool['function']['name'] for tool in request['tools']}
        for call, event in zip(declared, previous, strict=True):
            name = call['function']['name']
            if event['tool_name'] != name or event['exact_arguments'] != call['function']['arguments']:
                raise ValueError('tool arguments differ from the native response')
            if name not in registered:
                if (event.get('raw_mcp_response_path') is not None
                        or event['exact_result'] != f'Tool {name} does not exists.'):
                    raise ValueError('unregistered tool feedback differs from the original agent')
                continue
            raw_mcp = read(evidence_path(folder, event['raw_mcp_response_path']))
            if raw_mcp != event['raw_mcp_response'] or raw_mcp['isError'] is not False:
                raise ValueError('raw retrieval response does not match its receipt')
        generated += len(tokens['completion_token_ids'])
    if by_round or generated != branch['generated_tokens']:
        raise ValueError('unmatched tool exchanges or generation cost')
    return {'actor_calls': len(rounds), 'tool_calls': len(events), 'generated_tokens': generated,
            'reinjected_tool_results': returns_reinjected, 'exact_target_retries': branch['exact_target_retries']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('run', 'plan', 'audit', 'rollout', 'output'):
        parser.add_argument('--' + option, type=Path, required=True)
    parser.add_argument('--resume-from', type=Path, action='append', default=[])
    args = parser.parse_args()
    schedule, plan_sha, audit_sha = load_schedule(args.plan, args.audit, args.rollout)
    prior = read_executions(args.resume_from, schedule, plan_sha, audit_sha)
    schedule = remaining_cases(schedule, prior)
    config = read(args.rollout/'config_manifest.json')
    preflight = read(args.run/'PREFLIGHT.json')
    if (preflight['plan_sha256'],preflight['audit_sha256'],preflight['branches'],preflight['preflight_only']) != (
            plan_sha, audit_sha, len(schedule), False):
        raise ValueError('live run did not start with the frozen plan and audit')
    folder = (args.run/'branches').resolve(strict=True)
    rows = read_branches(folder, schedule, plan_sha, audit_sha)
    totals, outcomes, cases = defaultdict(Counter), defaultdict(Counter), defaultdict(set)
    pairs = defaultdict(dict)
    for row in rows:
        condition = row['condition']
        source = (folder/row['relative_path']).resolve(strict=True)
        try:
            summary = verify_trajectory(read(source/'trajectory.json'), source, row, config)
        except (KeyError, OSError, ValueError) as error:
            raise ValueError(f'{row["relative_path"]}: {error}') from error
        totals[condition].update(summary)
        outcomes[condition][row['result']['terminal']] += 1
        cases[row['case_id']].add(row['result']['identity']['runtime_sha256'])
        pairs[(row['case_id'], row['seed'])][condition] = dict(summary, terminal=row['result']['terminal'])
    if any(len(identities) != 1 for identities in cases.values()):
        raise ValueError('paired branches within a case did not share one runtime fingerprint')
    paired_rows = [{'case_id': case, 'seed': seed, **conditions}
                   for (case, seed), conditions in pairs.items() if conditions.keys() == {'normal', 'delete'}]
    complete_pairs = len(paired_rows)
    status = read(args.run/'STATUS.json')
    if status['state'] == 'completed':
        result = read(args.run/'RESULT.json')
        if (len(rows) != len(schedule) or complete_pairs * 2 != len(schedule)
                or result['completed_branches'] != len(rows) or result['optimizer_steps_committed'] != 0):
            raise ValueError('controller success does not match the independently verified branches')
    report = {'scope': 'Live continuation and wire receipt audit. Terminal counts have no correctness grading.',
              'source_run': str(args.run), 'plan_sha256': plan_sha, 'audit_sha256': audit_sha,
              'controller_state': status['state'], 'planned_branches': len(schedule), 'verified_branches': len(rows),
              'previously_verified_branches': len(prior),
              'complete_pairs': complete_pairs, 'events_with_verified_branches': len(cases),
              'terminal_counts': outcomes, 'exchange_counts': totals, 'paired_rows': paired_rows,
              'branch_result_sha256': {row['relative_path']: row['branch_result_sha256'] for row in rows}}
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {'branch_result_sha256', 'paired_rows'}}), flush=True)


if __name__ == '__main__':
    main()
