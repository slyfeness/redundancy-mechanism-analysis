"""Prepare revised event-price batches for the native HF pilot controller."""

from collections import Counter, defaultdict
import concurrent.futures
from dataclasses import asdict
import os
from pathlib import Path
import re
from statistics import fmean

from ledger_grpo.browsecomp_adapter import adapt_trajectory
from ledger_grpo.browsecomp_events import collect_tool_events
from ledger_grpo.evaluation import reasoning_usage, summarize_reasoning_usage
from ledger_grpo.event_price import EventPriceConfig, score_event_prices, scheduled_price_fraction, verify_semantic_calibration
from ledger_grpo.observability import advantage_payload, render_monitor, rollout_payload
from ledger_grpo.pipeline import analyze_trajectory
from ledger_grpo.rules import RuleConfig
from process_preflight import BoundedJudge, read, write


ARMS = ('outcome', 'trajectory', 'targeted', 'shuffled', 'uniform')
_BUDGET = {'CONTEXT_LIMIT_STOP', 'SAFETY_CEILING_STOP', 'GENERATION_LENGTH_STOP'}
_ABANDON = re.compile(r'^\s*(?:I (?:cannot|could not|was unable to) (?:find|determine|identify|answer)\b|'
                      r'\*{0,2}Exact Answer\*{0,2}\s*:\s*(?:unknown|N/A|undetermined)\b)', re.I)


def trajectory_event_metrics(raw, events, coverage):
    received = [r for r in raw['rounds'] if r.get('response_received') is True]
    terminal = raw['metadata']['terminal_status']
    return {'measured_tool_events': len(events), 'recorded_tool_events': len(raw['tool_events']),
            'exact_repeat_events': coverage['observed_exact_repeats'],
            'measured_return_tokens': sum(e['event_cost']['returned_tokens'] for e in events),
            'unmarked_event_cost': sum(sum(e['event_cost'].values()) for e in events if e['label'] is None),
            'budget_exhausted': terminal in _BUDGET,
            **reasoning_usage(raw['rounds']),
            'explicit_abandon': bool(terminal == 'MODEL_FINAL_STOP' and received
                                     and _ABANDON.match(received[-1].get('content') or ''))}


def add_evaluation_event_metrics(folder, summary, tokenizer):
    from ledger_grpo.browsecomp_adapter import native_trajectory
    from ledger_grpo.hf_native import native_turn_layout

    for entry in summary['rows']:
        artifact = folder/'trajectories'/entry['sample_id']
        raw = read(artifact/'trajectory.json')
        try:
            layout = native_turn_layout(native_trajectory(raw, reward=0))
            observed = [r for r in raw['rounds'] if r.get('response_received')
                        and r['token_accounting']['completion_token_ids']]
            turns = [dict(pos, turn_id=record['round_id']) for record,pos in zip(observed,layout['turns'],strict=True)]
        except (KeyError, TypeError, ValueError):
            turns = []
        turn_ids = {t['turn_id'] for t in turns}
        if any(e['round_id'] not in turn_ids for e in raw['tool_events']):
            events, coverage = [], {'observed_exact_repeats': None}
        else:
            events, coverage = collect_tool_events(raw, {'turns': turns}, {'qa': {'parse_ok': False}},
                                                  tokenizer, artifact_root=artifact)
        entry.update(trajectory_event_metrics(raw, events, coverage))
        if coverage['observed_exact_repeats'] is None:
            entry['measured_return_tokens'] = entry['unmarked_event_cost'] = None
    for key in ('budget_exhausted','explicit_abandon','exact_repeat_events','measured_return_tokens',
                'unmarked_event_cost','recorded_tool_events','measured_tool_events','reasoning_tokens','reasoning_rounds'):
        values = [row[key] for row in summary['rows'] if row[key] is not None]
        summary['mean_'+key] = fmean(values) if values else None
    summary['process_metrics'] = 'exact-repeat rule and native event cost; semantic and necessary-gap closure require calibrated independent labels'
    summary['reasoning_usage'] = summarize_reasoning_usage(summary['rows'])


def training_config(settings):
    if type(settings.get('compact_judge_evidence', False)) is not bool:
        raise ValueError('compact_judge_evidence must be a boolean')
    schedule = settings['price_schedule']
    fraction = scheduled_price_fraction(schedule['update'], warmup=schedule['warmup'], ramp=schedule['ramp'])
    options = dict(settings['credit'], price_fraction=fraction)
    if schedule['update'] <= schedule['warmup']:
        options['grounding_weight'] = 0.
    config = EventPriceConfig(**options)
    return config, list(verify_semantic_calibration(config, settings.get('semantic_calibration')))


def semantic_rule_config(*, check_r2a):
    return RuleConfig(query_similarity_threshold=.65 if check_r2a else 1., r2_local_check=check_r2a)


def schedule_stage(settings, *, runs_root):
    """Use one common outcome warmup before forking independent adaptation arms."""
    from pilot_resume import bind_checkpoint

    training_config(settings)
    schedule = settings['price_schedule']
    index, warmup = schedule['update'], schedule['warmup']
    arms = tuple(settings.get('arms',ARMS))
    if not arms or len(set(arms)) != len(arms) or not set(arms) <= set(ARMS):
        raise ValueError('invalid event-price arm list')
    previous_path = settings.get('resume_from')
    parent = bind_checkpoint(previous_path,runs_root=runs_root) if previous_path else None
    previous = parent['optimizer_step'] if parent else 0
    if index != previous+1:
        raise ValueError('the price schedule must use the next actual optimizer step')
    if parent:
        if settings.get('baseline_evaluation'):
            raise ValueError('a resumed stage must evaluate its own starting policy')
        parent_run = Path(parent['checkpoint']).parents[2]
        prior = read(parent_run/'EVENT_PRICE_SETTINGS.json')
        prior_schedule = prior['price_schedule']
        if (prior_schedule['update'] != previous or any(prior_schedule[k] != schedule[k] for k in ('warmup','ramp'))
                or prior['credit'] != settings['credit'] or prior.get('semantic_calibration') != settings.get('semantic_calibration')):
            raise ValueError('stage settings differ from the frozen price schedule or credit contract')
        if previous <= warmup:
            if parent['control'] != 'outcome':
                raise ValueError('adaptation must fork from the shared outcome warmup')
        elif arms != (parent['control'],):
            raise ValueError('after forking, resume the same experimental arm')
    if index <= warmup:
        arms = ('outcome',)
    return parent, arms


def choose_training_rows(rows, settings):
    reference = settings.get('prior_task_pass_rates')
    if reference is None:
        return rows
    selected = [r for r in rows if .2 <= reference.get(str(r['query_id']), -1) <= .8]
    if not selected:
        raise ValueError('no training task meets the predeclared prior-policy pass band')
    return selected


def verified_baseline(folder, evaluation_rows, seed, expected_summary_sha256):
    from hf_pilot_controller import sha

    prior = read(folder/'RESULT.json')
    passed = {phase['phase'] for phase in prior['phases'] if phase['state'] == 'completed'}
    required = {'initial_fixed_evaluation','initial_evaluation_analysis'}
    if not required <= passed or sha(folder/'EVAL-P0.json') != expected_summary_sha256:
        raise ValueError('saved P0 evaluation lacks the frozen completion and identity receipts')
    rollout = folder/'eval-P0'
    actual = read(rollout/'task_manifest.json')['tasks']
    expected = [{'query_id': row['query_id'], 'repetition_id': rep+1, 'seed': seed+i*8+rep,
                 'run_id': f"{row['query_id']}__rep{rep+1}", 'question_sha256': row['question_sha256']}
                for i,row in enumerate(evaluation_rows) for rep in range(8)]
    expected_config = dict(query_count=len(evaluation_rows),samples_per_query=8,context=65536,
                           max_tokens_per_call=10000,max_actor_calls=20,temperature=1.,top_p=1.,top_k=0)
    if actual != expected or read(rollout/'config_manifest.json') != expected_config:
        raise ValueError('saved P0 evaluation task/seed/sampling manifest differs from this run')
    summary = read(folder/'EVAL-P0.json')
    if (summary != prior['evaluations']['P0'] or
            {(str(row['query_id']),row['run_id']) for row in expected} !=
            {(row['task_id'],row['sample_id']) for row in summary['rows']} or len(summary['rows']) != len(expected)):
        raise ValueError('saved P0 evaluation sample identities differ from its manifest')
    return summary


def score_event_training(rollout, questions, output, key, writer, *, arm_writers, settings,
                         policy_snapshot_sha256=None, policy_version='P0'):
    import torch
    from transformers import AutoTokenizer
    from hf_pilot_controller import extract_training_frames, sha

    config, semantic = training_config(settings)
    index = settings['price_schedule']['update']
    warmup = index <= settings['price_schedule']['warmup']
    batch_id = 'p0-training' if index == 1 else f'stage-{index}-training'
    requested = tuple(arm_writers)
    output.mkdir()
    batch_path = rollout/'TRAIN_BATCH.json'
    grouped = defaultdict(list)
    for row in read(batch_path)['trajectories']:
        grouped[str(row['query_id'])].append(row)
    invalid = {qid for qid, rows in grouped.items() if len(rows) != config.group_size
               or any(r['reward'] not in (0., 1.) or not r['segments'] for r in rows)}
    selected = [r for qid, rows in grouped.items() if qid not in invalid for r in rows]
    active = {qid for qid, rows in grouped.items() if qid not in invalid and any(r['reward'] == 1 for r in rows)}
    if warmup:
        active.clear()
    questions = {str(row['query_id']): row['question'] for row in questions}
    tokenizer = AutoTokenizer.from_pretrained(os.environ['LEDGER_BASE_MODEL'], local_files_only=True)
    frame_judge = BoundedJudge(key)
    constraints, active, failures = extract_training_frames(
        {qid: {'question': questions[qid]} for qid in grouped if qid not in invalid}, active, frame_judge)
    write(output/'CONSTRAINTS.json', constraints)
    rule_config = semantic_rule_config(check_r2a='R2a' in semantic)

    def process(row):
        qid, tid = str(row['query_id']), row['id']
        artifact = rollout/'trajectories'/tid
        raw = read(artifact/'trajectory.json')
        trace, native = adapt_trajectory(raw, questions[qid], constraints[qid], outcome=int(row['reward']))
        if any(native[k] != row[k] for k in ('id', 'terminal', 'segments')) or native['query_id'] != qid:
            raise ValueError('adapted native trace differs from the graded rollout')
        judge = (BoundedJudge(key, payment_blocked=frame_judge.payment_blocked,
                              compact_evidence=settings.get('compact_judge_evidence', False))
                 if qid in active and trace['recording_complete'] else None)
        report = analyze_trajectory(trace, judge=judge, rule_config=rule_config)
        events, coverage = collect_tool_events(raw, trace, report, tokenizer, artifact_root=artifact,
                                              enabled_semantic_labels=semantic)
        ground = report['metrics']['grounding_score'] if report['qa']['parse_ok'] else None
        folder = output/tid
        folder.mkdir()
        write(folder/'report.json', report)
        write(folder/'events.json', {'events': events, 'coverage': coverage})
        if judge:
            write(folder/'checks.json', judge.check_audit)
        event_stats = trajectory_event_metrics(raw, events, coverage)
        event_stats.update(judge_input_tokens=judge.usage['prompt_tokens'] if judge else 0,
                           judge_output_tokens=judge.usage['completion_tokens'] if judge else 0)
        writer.emit('rollout.scored', rollout_payload(trace, report, sample_id=tid, split='train', extra_metrics=event_stats),
                    event_id='train-'+tid, batch_id=batch_id, policy_version=policy_version, optimizer_steps_committed=index-1)
        return dict(trace, events=events, grounding=ground), native, coverage

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        processed = list(pool.map(process, selected))
    traces = [t for t,_,_ in processed]
    native_path = output/'NATIVE_BATCH.json'
    native_input = {'trajectories': [n for _,n,_ in processed], 'original_batch_sha256': sha(batch_path)}
    if policy_snapshot_sha256 is not None:
        native_input['policy_snapshot_sha256'] = policy_snapshot_sha256
    write(native_path, native_input)
    coverage = Counter()
    for _,_,item in processed:
        coverage.update(item)
    comparison = {'invalid_input_groups': sorted(invalid), 'frame_failures': failures,
                  'process_annotated_groups': sorted(active), 'event_coverage': dict(coverage),
                  'arm_update_capable': {}, 'equivalent_to': {}, 'arms': {},
                  'config': asdict(config), 'semantic_labels_enabled': semantic}
    previous = {}
    native_hash = sha(native_path)
    for arm in requested:
        if not traces:
            comparison['arm_update_capable'][arm] = False
            continue
        result = score_event_prices(traces, config, arm=arm, semantic_calibration=settings.get('semantic_calibration'))
        binding = {'native_batch_sha256':native_hash}
        if policy_snapshot_sha256 is not None:
            binding['policy_snapshot_sha256'] = policy_snapshot_sha256
        result.update(config=asdict(config), input_binding=binding)
        torch.save(result, output/f'{arm}-scores.pt')
        comparison['arm_update_capable'][arm] = not result['skip_update']
        comparison['arms'][arm] = result['metrics']
        for prior,(advantage,mask) in previous.items():
            if torch.equal(result['advantages'], advantage) and torch.equal(result['effective_response_mask'], mask):
                comparison['equivalent_to'][arm] = prior
                break
        previous[arm] = result['advantages'], result['effective_response_mask']
        arm_writers[arm].emit('advantage.computed', advantage_payload(result, task_ids=[t['task_id'] for t in traces]),
                              event_id=arm+'-advantage', batch_id=batch_id, policy_version=policy_version,
                              optimizer_steps_committed=index-1)
        render_monitor(arm_writers[arm].path, arm_writers[arm].path.parent/'monitor.html')
    write(output/'SCORE_COMPARISON.json', comparison)
    return native_path, comparison
