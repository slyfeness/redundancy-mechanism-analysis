"""Fill missing result verdicts on recorded eval trajectories, without regenerating."""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from hf_pilot_controller import paired_comparisons, sha, summarize_evaluation_rows
from ledger_grpo.evaluation import paired_event_diagnostics
from process_preflight import read, write


ARMS = ('outcome', 'trajectory', 'targeted', 'shuffled', 'uniform')


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def bind_arm(run, arm, frozen_tasks, expected_samples):
    """Check IDs, independent verdict order and the original grader's input."""
    folder = run/f'eval-{arm}'
    summary_path = run/f'EVAL-{arm}.json'
    summary = read(summary_path)
    manifest = read(folder/'task_manifest.json')['tasks']
    original = read(folder/'API_JUDGE.json')
    inputs = read(folder/'LOCAL_JUDGE_INPUT.json')
    raw_metrics = read(folder/'TRAJECTORY_METRICS.json')
    samples = [(str(row['query_id']), row['run_id'], row['seed'], row['question_sha256']) for row in manifest]
    if samples != expected_samples:
        raise ValueError(f'{arm} task identities or sampling seeds differ from the frozen baseline')
    work, status_counts = [], Counter()
    for index,(task,verdict,grader,metric,row) in enumerate(zip(manifest,original,inputs,raw_metrics,summary['rows'],strict=True)):
        qid, tid = str(task['query_id']), task['run_id']
        if (row['task_id'],row['sample_id'],str(metric['query_id']),metric['id']) != (qid,tid,qid,tid):
            raise ValueError(f'{arm} recorded evaluation row order differs from the manifest')
        planned = frozen_tasks[qid]
        complete = metric['terminal'] == 'MODEL_FINAL_STOP'
        correct = verdict['correct']
        if correct is not None and type(correct) is not bool:
            raise ValueError('invalid original result verdict')
        reward = (int(correct) if correct is not None else None) if complete else 0
        if (metric['reward'] != reward or row['outcome'] != reward or row['complete'] != complete
                or grader['api_correct'] is not correct or grader['termination'] != metric['terminal']
                or grader['question'] != planned['question'] or grader['gold'] != planned['gold']):
            raise ValueError(f'{arm} original judge inputs and outcomes do not agree with the frozen eval')
        if not complete or correct is not None:
            continue
        # Match the frozen backend's trajectory_row final extraction on disk.
        artifact = read(folder/'trajectories'/tid/'trajectory.json')
        observed = [r for r in artifact['rounds'] if r.get('response_received')]
        final = (observed[-1].get('content') or '') if observed else ''
        if (final != grader['final'] or artifact['metadata']['terminal_status'] != metric['terminal']):
            raise ValueError(f'{arm} saved final text differs from the original judge input')
        statuses = [a['status'] for a in verdict['attempts']]
        status_counts[str(statuses[-1]) if statuses else 'missing'] += 1
        request = {'arm':arm, 'index':index, 'task_id':qid, 'sample_id':tid,
                   'question':planned['question'], 'gold':planned['gold'], 'final':final}
        work.append(dict(request, request_sha256=_hash(request)))
    if summary['resolved_count'] != len(samples)-len(work) or summary['sample_count'] != len(samples):
        raise ValueError(f'{arm} evaluation totals disagree with bound rows')
    return summary, work, {'original_eval_sha256':sha(summary_path), 'missing_normal':len(work),
                           'last_failure_counts':dict(status_counts), 'original_resolved':summary['resolved_count']}


def _balance_available(key):
    import httpx

    with httpx.Client(trust_env=False, follow_redirects=False, timeout=20.) as client:
        response = client.get('https://api.deepseek.com/user/balance',
                              headers={'Authorization':'Bearer '+key})
    if response.status_code != 200:
        raise RuntimeError(f'DeepSeek balance endpoint HTTP status {response.status_code}')
    available = response.json().get('is_available')
    if type(available) is not bool:
        raise RuntimeError('DeepSeek balance endpoint did not return availability')
    return available


def recover_verdicts(output, requests, reuse_sources, judge_identity, key, judge_factory):
    """Keep verified prior results before checking whether more requests can run."""
    sources = [source for source in reuse_sources if (source/'JUDGE_IDENTITY.json').is_file()
               and read(source/'JUDGE_IDENTITY.json') == judge_identity]
    write(output/'JUDGE_IDENTITY.json', judge_identity)
    recovered, todo = {}, []
    for arm, arm_requests in requests.items():
        (output/'receipts'/arm).mkdir(parents=True)
        for req in arm_requests:
            identity = req['request_sha256']
            relative = Path('receipts')/arm/f"{req['index']:03d}.json"
            for source in sources:
                path = source/relative
                if not path.is_file():
                    continue
                old = read(path)
                attempts = old.get('attempts')
                if (old.get('request_sha256') == identity and type(old.get('correct')) is bool
                        and old.get('served_model') and attempts and attempts[-1].get('status') == 200):
                    recovered[identity] = old
                    write(output/relative, old)
                    break
            if identity not in recovered:
                todo.append((req, output/relative))

    if not todo:
        return recovered, 'completed'
    if not _balance_available(key):
        return recovered, 'balance_unavailable'
    judge = judge_factory(key)
    try:
        if judge.identity != judge_identity:
            raise ValueError('live grader protocol differs from the receipt binding')
        for start in range(0, len(todo), 16):
            pending = [(req, path, judge.submit(req['question'], req['final'], req['gold'], path))
                       for req, path in todo[start:start+16]]
            blocked = False
            for req, path, future in pending:
                verdict = dict(future.result(), request_sha256=req['request_sha256'])
                write(path, verdict)
                recovered[req['request_sha256']] = verdict
                blocked |= any(attempt['status'] == 402 for attempt in verdict['attempts'])
            if blocked:
                return recovered, 'balance_exhausted_during_regrade'
        return recovered, 'completed'
    finally:
        judge.close()


def _write_evaluations(output, evaluations, requests, original, recovered):
    final = deepcopy(evaluations)
    for arm, summary in final.items():
        if arm == 'P0':
            continue
        count = 0
        for req in requests[arm]:
            verdict = recovered.get(req['request_sha256'])
            if verdict is not None and type(verdict['correct']) is bool:
                summary['rows'][req['index']]['outcome'] = int(verdict['correct'])
                count += 1
        summary.update(summarize_evaluation_rows(summary['rows']))
        summary['grading_recovery'] = dict(original[arm], recovered=count,
                                            missing_after=original[arm]['missing_normal']-count)
    for arm, summary in final.items():
        write(output/f'EVAL-{arm}.json', summary)
    write(output/'PAIRED_COMPARISONS.json', paired_comparisons(final, training_seed=20261109))
    pairs = [(a,b) for a,b in (('outcome','targeted'),('trajectory','targeted'),
                               ('shuffled','targeted'),('uniform','targeted')) if a in final and b in final]
    write(output/'PAIRED_EVENT_DIAGNOSTICS.json', {f'{b}_minus_{a}':
          paired_event_diagnostics(final[a]['rows'],final[b]['rows']) for a,b in pairs})
    return {a:s['grading_recovery'] for a,s in final.items() if a != 'P0'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arms', choices=ARMS, nargs='+', required=True)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--reuse-from', type=Path, action='append', default=[])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if len(set(args.arms)) != len(args.arms) or (not args.dry_run and args.key_file is None):
        parser.error('unique arms and a key file for live regrading are required')
    run, output = args.run.resolve(strict=True), args.output.resolve()
    if output.is_relative_to(run):
        raise ValueError('regrade output must be separate from frozen run')
    plan = read(args.plan)['evaluation_rows']
    frozen = {str(t['query_id']):t for t in plan}
    if len(frozen) != 16 or len(plan) != 16:
        raise ValueError('expected the frozen sixteen-task evaluation plan')
    samples = [(str(t['query_id']),f"{t['query_id']}__rep{rep+1}",2026111100+i*8+rep,t['question_sha256'])
               for i,t in enumerate(plan) for rep in range(8)]
    baseline = read(run/'EVAL-P0.json')
    if {(r['task_id'],r['sample_id']) for r in baseline['rows']} != {(a,b) for a,b,_,_ in samples}:
        raise ValueError('frozen P0 evaluation identities differ from plan')
    evaluations, requests, original = {'P0':baseline}, {}, {}
    for arm in args.arms:
        evaluations[arm],requests[arm],original[arm] = bind_arm(run,arm,frozen,samples)
    output.mkdir(mode=0o700, exist_ok=False, parents=True)
    write(output/'INPUTS.json', {'source_run':str(run), 'plan_sha256':sha(args.plan),
                               'p0_sha256':sha(run/'EVAL-P0.json'), 'arms':original})
    if args.dry_run:
        write(output/'RESULT.json', {'state':'verified_no_requests','arms':original})
        print(json.dumps({'state':'verified_no_requests','arms':original}),flush=True)
        return
    from src.prepare_training import judge_protocol
    from src.stability_judge import FlashJudge

    key = args.key_file.read_text().strip()
    if not key:
        raise ValueError('result judge key is unavailable')
    _, judge_identity = judge_protocol()
    recovered, status = recover_verdicts(output, requests, args.reuse_from, judge_identity, key, FlashJudge)
    result = _write_evaluations(output,evaluations,requests,original,recovered)
    if status == 'completed' and any(s['missing_after'] for s in result.values()):
        status = 'unresolved_verdicts'
    write(output/'RESULT.json', {'state':status,'arms':result})
    print(json.dumps({'state':status,'arms':result}),flush=True)


if __name__ == '__main__':
    main()
