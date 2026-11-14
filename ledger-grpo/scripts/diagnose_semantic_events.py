"""Read or independently judge frozen event prefixes before enabling prices."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from event_price_pilot import semantic_rule_config
from ledger_grpo.browsecomp_adapter import adapt_trajectory, extract_constraints
from ledger_grpo.browsecomp_events import exact_repeat_witnesses, semantic_event_predictions
from ledger_grpo.client import JudgeError, LocalJudge
from ledger_grpo.pipeline import analyze_trajectory
from process_preflight import BoundedJudge, read


def through_event(trace, turn_id):
    turns = [turn for turn in trace['turns'] if turn['turn_id'] <= turn_id]
    if not turns or turns[-1]['turn_id'] != turn_id:
        raise ValueError('event does not bind a canonical trajectory turn')
    return dict(trace, turns=turns, response_mask=trace['response_mask'][:turns[-1]['token_end']], outcome=0,
                complete=False, submitted_candidate=None, termination_reason='unknown')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--coordinates', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, help='Run new semantic requests instead of reading archived predictions')
    parser.add_argument('--judge-base-url')
    parser.add_argument('--judge-model')
    args = parser.parse_args()
    if bool(args.judge_base_url) != bool(args.judge_model) or (args.key_file and args.judge_model):
        parser.error('provide a local judge URL and model together, or a DeepSeek key file')
    plan_raw, audit_raw = args.plan.read_bytes(), args.audit.read_bytes()
    plan, audit = json.loads(plan_raw), json.loads(audit_raw)
    coordinates = read(args.coordinates)
    scored, rollout = args.run/'scored', args.run/'train-P0'
    batch_raw = (scored/'NATIVE_BATCH.json').read_bytes()
    if (plan['protocol'] != 'browsecomp-event-calibration-plan-v1'
            or plan['audit_sha256'] != hashlib.sha256(audit_raw).hexdigest()
            or plan['batch_sha256'] != hashlib.sha256(batch_raw).hexdigest()
            or coordinates['batch_sha256'] != plan['batch_sha256']):
        raise ValueError('frozen plan, prefix audit and native training batch do not agree')
    sources = {row['id']: row for row in json.loads(batch_raw)['trajectories']}
    event_audit = {(event['sample_id'], event['event_id']): event for event in audit['pairs']}
    questions = {str(row['query_id']): row['question'] for row in read(rollout/'sample_manifest.json')['selected']}
    archived_frames = read(scored/'CONSTRAINTS.json')
    compact = read(args.run/'EVENT_PRICE_SETTINGS.json').get('compact_judge_evidence', False)
    key = args.key_file.read_text().strip() if args.key_file else None
    if args.key_file and not key:
        raise ValueError('judge credential unavailable')
    local = (LocalJudge(args.judge_base_url, args.judge_model, timeout=60, max_tokens=4096, compact_evidence=True)
             if args.judge_model else None)
    frame_judge = local or (BoundedJudge(key) if key else None)
    frames = {}
    counts, reasons = defaultdict(Counter), Counter()
    cases = []
    for case in plan['cases']:
        event = case['event']
        tid, eid = event['sample_id'], event['event_id']
        if event_audit.get((tid, eid)) != event:
            raise ValueError('plan event does not match its prefix audit')
        original = (rollout/'trajectories'/tid/'trajectory.json').read_bytes()
        if hashlib.sha256(original).hexdigest() != event['trajectory_sha256']:
            raise ValueError('original event trajectory does not match the plan')
        raw = json.loads(original)
        native = sources[tid]
        qid = str(native['query_id'])
        if qid != case['task_id']:
            raise ValueError('frozen event question differs from its native task')
        turn = event['continuation_round'] - 1
        coordinate = coordinates['trajectories'][tid]
        if coordinate['trajectory_sha256'] != event['trajectory_sha256']:
            raise ValueError('native event coordinate receipt differs from the original trajectory')
        by_round = defaultdict(list)
        for item in raw['tool_events']:
            by_round[item['round_id']].append(item)
        repeats = exact_repeat_witnesses(raw['rounds'], by_round)
        measured = [dict(row, turn_id=turn, prior_event_id=repeats.get(row['event_id']))
                    for row in (coordinate['rounds'].get(str(turn)) or [])]
        if frame_judge is not None and qid not in frames:
            try:
                frames[qid] = extract_constraints(questions[qid], frame_judge)
            except (ValueError, JudgeError):
                frames[qid] = None
        trace, observed = adapt_trajectory(raw, questions[qid], frames.get(qid) or archived_frames[qid],
                                           outcome=int(native['reward']))
        if any(observed[field] != native[field] for field in ('id','query_id','terminal','segments')):
            raise ValueError('canonical trace differs from frozen native sample')
        if frame_judge is None:
            report = read(scored/tid/'report.json')
        else:
            judge = None
            if frames[qid]:
                judge = local or BoundedJudge(key, payment_blocked=frame_judge.payment_blocked, compact_evidence=compact)
            trace = through_event(trace, turn)
            report = analyze_trajectory(trace, judge=judge, rule_config=semantic_rule_config(check_r2a=True))
        visible = {'tool_events': [item for item in raw['tool_events'] if item['round_id'] <= turn]}
        candidates = semantic_event_predictions(visible, trace, report, measured)
        match = [row for row in candidates if row['event_id'] == eid and row['turn_id'] == turn]
        if len(match) != 1:
            raise ValueError('event prediction does not uniquely identify the planned tool call')
        for label, prediction in match[0]['predictions'].items():
            counts[label][prediction['prediction']] += 1
            reasons[prediction['reason']] += 1
        cases.append({'case_id': case['case_id'], 'trajectory_sha256': event['trajectory_sha256'],
                      'trace_digest': report['trace_digest'], 'judge': report['judge'], **match[0]})
        if local:
            print(json.dumps({'case_id': case['case_id'], 'judge_requests': local.requests,
                              'predictions': match[0]['predictions']}), flush=True)
    summary = {'mode': 'live_semantic_prefix' if frame_judge else 'archived_process_reports',
               'judge_provider': 'local_vllm' if local else 'deepseek' if key else None,
               'judge_model': getattr(frame_judge, 'model', None),
               'plan_sha256': hashlib.sha256(plan_raw).hexdigest(), 'counts': counts, 'reasons': reasons, 'cases': cases}
    if local:
        summary.update(requests=local.requests, cache_hits=local.cache_hits, usage=local.usage)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'mode': summary['mode'], 'counts': counts, 'reasons': reasons}), flush=True)


if __name__ == '__main__':
    main()
