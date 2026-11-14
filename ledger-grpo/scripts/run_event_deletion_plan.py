"""Run a frozen event intervention schedule on already started Slurm services."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from threading import Lock


def branch_schedule(plan, audit, audit_sha):
    if (plan['protocol'] != 'browsecomp-event-calibration-plan-v1'
            or audit['protocol'] != 'browsecomp-matched-single-event-prefix-v1'
            or plan['audit_sha256'] != audit_sha):
        raise ValueError('intervention plan must match its original prefix audit')
    events = {(e['sample_id'], e['event_id']): e for e in audit['pairs']}
    if len(events) != len(audit['pairs']) or not plan['cases']:
        raise ValueError('prefix audit and experiment cases must be unambiguous')
    schedule, case_ids, used, seeds = [], set(), set(), set()
    for case in plan['cases']:
        case_id, event, blocks = case['case_id'], case['event'], case['blocks']
        key = event['sample_id'], event['event_id']
        if (not re.fullmatch(r'E[0-9]{3,}', case_id) or case_id in case_ids or key in used
                or event != events.get(key) or len(blocks) != 4):
            raise ValueError('case ID, event binding or number of pairs is invalid')
        case_ids.add(case_id)
        used.add(key)
        for block in blocks:
            seed, order = block['seed'], block['order']
            if type(seed) is not int or seed in seeds or sorted(order) != ['delete', 'normal']:
                raise ValueError('each seed must have one normal and one deletion branch')
            seeds.add(seed)
            for condition in order:
                schedule.append({'case_id': case_id, 'sample_id': key[0], 'event_id': key[1],
                                 'trajectory_sha256': event['trajectory_sha256'], 'seed': seed, 'condition': condition,
                                 'continuation_round': event['continuation_round'],
                                 'prefix_sha256': event[f'{condition}_prompt_sha256'],
                                 'relative_path': f'{case_id}/seed-{seed}/{condition}'})
    return schedule


def schedule_lanes(schedule, actor_count):
    if type(actor_count) is not int or actor_count < 1:
        raise ValueError('event schedule requires at least one Actor')
    groups = defaultdict(list)
    for job in schedule:
        groups[job['case_id']].append(job)
    lanes = [[] for _ in range(actor_count)]
    for index, case_jobs in enumerate(groups.values()):
        lanes[index % actor_count].append(case_jobs)
    return lanes


def execute_schedule(schedule, actors, worker, journal):
    lanes = schedule_lanes(schedule, len(actors))
    lock = Lock()
    failures = {}
    completed = 0
    with journal.open('x', encoding='utf-8') as handle:
        def lane(actor, cases):
            nonlocal completed
            for jobs in cases:
                for job in jobs:
                    try:
                        result_sha = worker(job, actor)
                    except Exception as error:
                        with lock:
                            failures[job['case_id']] = {'failed_branch': job, 'error_type': type(error).__name__}
                        break
                    with lock:
                        handle.write(json.dumps(dict(job, branch_result_sha256=result_sha)) + '\n')
                        handle.flush()
                        completed += 1

        with ThreadPoolExecutor(max_workers=len(actors)) as pool:
            futures = [pool.submit(lane, actor, cases) for actor, cases in zip(actors, lanes, strict=True)]
            for future in futures:
                future.result()
    return {'completed_branches': completed, 'failed_cases': failures}


def load_schedule(plan_path, audit_path, rollout=None):
    raw_plan, raw_audit = plan_path.read_bytes(), audit_path.read_bytes()
    plan, audit = json.loads(raw_plan), json.loads(raw_audit)
    plan_sha, audit_sha = (hashlib.sha256(raw).hexdigest() for raw in (raw_plan, raw_audit))
    schedule = branch_schedule(plan, audit, audit_sha)
    if rollout is not None:
        config = (rollout/'config_manifest.json').read_bytes()
        if hashlib.sha256(config).hexdigest() != plan['config_sha256']:
            raise ValueError('rollout configuration differs from the frozen intervention plan')
    return schedule, plan_sha, audit_sha


def run_plan(schedule, plan_sha, audit_sha, *, rollout, audit, model, actors, mcp_port, output):
    runner = Path(__file__).resolve().with_name('run_event_deletion_branch.py')
    base = [sys.executable, str(runner), '--rollout', str(rollout.resolve()), '--audit', str(audit.resolve()),
            '--model', str(model.resolve()), '--mcp-port', str(mcp_port)]
    output.mkdir(mode=0o700, exist_ok=False)
    with (output/'PLAN_RECEIPT.json').open('x', encoding='utf-8') as handle:
        json.dump({'plan_sha256': plan_sha, 'audit_sha256': audit_sha, 'schedule': schedule}, handle, indent=2)

    def worker(job, actor):
        url, actor_dir = actor
        folder = (output/job['relative_path']).resolve()
        folder.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        subprocess.run(base + ['--actor-url', url, '--actor-dir', str(Path(actor_dir).resolve()),
                       '--sample-id', job['sample_id'], '--event-id', job['event_id'],
                       '--condition', job['condition'], '--seed', str(job['seed']), '--output', str(folder)],
                       cwd=folder.parent, check=True)
        raw = (folder/'BRANCH_RESULT.json').read_bytes()
        binding = json.loads(raw)['identity']
        expected = ('sample_id', 'event_id', 'trajectory_sha256', 'seed', 'condition', 'continuation_round', 'prefix_sha256')
        if binding['audit_sha256'] != audit_sha or any(binding[key] != job[key] for key in expected):
            raise ValueError('returned branch does not match the frozen execution schedule')
        return hashlib.sha256(raw).hexdigest()

    summary = execute_schedule(schedule, actors, worker, output/'COMPLETED_BRANCHES.jsonl')
    with (output/'EXECUTION_RESULT.json').open('x', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2)
    if summary['completed_branches'] != len(schedule):
        raise RuntimeError('event execution finished with incomplete cases')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--rollout', type=Path)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--actor-url')
    parser.add_argument('--actor-dir', type=Path)
    parser.add_argument('--mcp-port', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    schedule, plan_sha, audit_sha = load_schedule(args.plan, args.audit, args.rollout if args.execute else None)
    if not args.execute:
        print(json.dumps({'plan_sha256': plan_sha, 'pairs': len(schedule)//2, 'branches': schedule}))
        return

    service = (args.rollout, args.model, args.actor_url, args.actor_dir, args.mcp_port, args.output)
    if None in service:
        parser.error('execute requires rollout, model, actor URL and directory, retriever port and output')
    run_plan(schedule, plan_sha, audit_sha, rollout=args.rollout, audit=args.audit, model=args.model,
             actors=[(args.actor_url, args.actor_dir)], mcp_port=args.mcp_port, output=args.output)


if __name__ == '__main__':
    main()
