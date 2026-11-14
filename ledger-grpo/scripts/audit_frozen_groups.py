"""CPU-Slurm-only, read-only audit of a saved native rollout; never calls models."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import statistics


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def schema(value, depth=0):
    """Only object field names, shapes and Python type names; no scalar values."""
    if depth >= 6:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: schema(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return {'type': 'list', 'first_item_schema': schema(value[0], depth + 1) if value else None}
    return type(value).__name__


def describe(values):
    if not values:
        return {'count': 0}
    values = sorted(values)
    def percentile(p):
        position = (len(values) - 1) * p
        low = int(position)
        high = min(low + 1, len(values) - 1)
        return values[low] + (values[high] - values[low]) * (position - low)
    return dict(count=len(values), sum=sum(values), min=values[0], max=values[-1],
                mean=statistics.fmean(values), median=statistics.median(values),
                p90=percentile(.90), p95=percentile(.95))


def group_summary(groups):
    result = []
    for task_id, rows in groups.items():
        known = all(type(r['outcome']) in (int, float) and r['outcome'] in (0, 1) for r in rows)
        complete = sum(bool(r['complete']) for r in rows)
        correct = sum(r['outcome'] == 1 for r in rows)
        kind = ('unknown' if not known else 'allwrong' if correct == 0 else
                'allcorrect' if correct == len(rows) else 'mixed')
        exact = len(rows) == 8 and complete == 8
        valid = exact and known and all(r['native_ok'] for r in rows)
        retained = valid and correct > 0
        result.append(dict(task_id=task_id, row_count=len(rows), complete_count=complete,
                           correct_count=correct, outcome_kind=kind, exact8_complete=exact,
                           retained=retained, outcome_signal=retained and kind == 'mixed',
                           potential_process_only_signal=retained and kind == 'allcorrect',
                           drop_reason=None if retained else 'allwrong' if valid else 'incomplete_or_invalid_group'))
    return result


def field_shapes(items):
    """Union of observed field types without copying observations or text."""
    found = defaultdict(set)
    for item in items:
        if isinstance(item, dict):
            for key, value in item.items():
                found[key].add(type(value).__name__)
    return {key: sorted(types) for key, types in sorted(found.items())}


def schema_sample(native, path, source_run):
    rounds, events = native.get('rounds', []), native.get('tool_events', [])
    result = {'trajectory_top_fields': field_shapes([native]),
              'metadata': schema(native.get('metadata', {})),
              'round_fields': field_shapes(rounds), 'tool_event_fields': field_shapes(events)}
    row = next((r for r in rounds if r.get('raw_response')), {})
    result['response_schema'] = schema(row.get('raw_response', {}))
    result['token_accounting_schema'] = schema(row.get('token_accounting', {}))
    result['actor_messages_schema'] = schema(row.get('actor_visible_messages', []))
    tool_response = next((r.get('raw_response', {}) for r in rounds
                          if any(c.get('message', {}).get('tool_calls') for c in (r.get('raw_response') or {}).get('choices', []))), {})
    result['tool_call_response_schema'] = schema(tool_response)
    tool_choices = tool_response.get('choices', [])
    result['tool_calls_schema'] = schema(tool_choices[0].get('message', {}).get('tool_calls', [])) if tool_choices else {}
    result['first_event_schema'] = schema(events[0]) if events else {}
    links = []
    for owner_name, owner in [('round', row), ('event', events[0] if events else {})]:
        for field, value in owner.items():
            if 'path' not in field or not isinstance(value, str):
                continue
            linked = Path(value)
            if not linked.is_absolute():
                linked = path.parent / linked
            linked = linked.resolve()
            info = {'owner': owner_name, 'field': field, 'suffix': linked.suffix,
                    'exists': linked.is_file(), 'inside_source_run': linked.is_relative_to(source_run)}
            if info['exists'] and info['inside_source_run'] and linked.suffix == '.json' and linked.stat().st_size < 20_000_000:
                info['json_schema'] = schema(read(linked))
            links.append(info)
    result['linked_file_schemas'] = links
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--source-code', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--schema-only', type=Path, help='Read one already authorized native file and emit detailed structural keys only')
    args = parser.parse_args()
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('This audit must run under a CPU Slurm job')
    root, source = args.source_run.resolve(), args.source_code.resolve()
    destination = args.output_dir.resolve()
    if not str(destination).startswith('/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot/'):
        raise ValueError('Outputs must remain in the independent ledger-grpo-pilot bulk project')
    destination.mkdir(parents=True, exist_ok=True)
    if args.schema_only is not None:
        native_path = args.schema_only.resolve()
        if not native_path.is_relative_to(root):
            raise ValueError('Schema sample must be inside the authorized source run')
        write(destination / 'NATIVE_SCHEMA_DETAILS.json', schema_sample(read(native_path), native_path, root))
        print(json.dumps({'schema_details_complete': True, 'slurm_job_id': os.environ['SLURM_JOB_ID']}))
        return
    finished = []
    for folder in sorted(root.glob('step-*')):
        receipt = folder / 'STEP_RESULT.json'
        if receipt.is_file():
            value = read(receipt)
            if value.get('train', {}).get('optimizer_step') is True and value.get('policy_synced') is True:
                finished.append((folder, value))
    if not finished:
        raise RuntimeError('No fully updated and policy-synced step exists')
    step_audits = []
    for completed, completed_receipt in finished:
        batches = list(completed.glob('rollout-*/TRAIN_BATCH.json'))
        if len(batches) != 1:
            raise RuntimeError('Ambiguous persisted training batch for a completed step')
        batch_data = batches[0].read_bytes()
        batch_sha = hashlib.sha256(batch_data).hexdigest()
        batch = json.loads(batch_data)
        del batch_data
        step_groups, step_rows = defaultdict(list), []
        for item in batch['trajectories']:
            row = dict(traj_id=item['id'], task_id=str(item['query_id']),
                       complete=item['terminal'] == 'MODEL_FINAL_STOP', outcome=item['reward'],
                       native_ok=bool(item['segments']),
                       generated_tokens=sum(len(s['completion_ids']) for s in item['segments']),
                       max_native_sequence=max((len(s['prompt_ids']) + len(s['completion_ids']) for s in item['segments']), default=0))
            step_rows.append(row)
            step_groups[row['task_id']].append(row)
        group_rows = group_summary(step_groups)
        number = completed_receipt['step']
        step_audits.append({'step': number, 'behavior_policy_step': number - 1,
                           'batch_path': str(batches[0]), 'batch_sha256': batch_sha,
                           'rows': len(step_rows), 'groups': group_rows,
                           'exact8_complete_groups': sum(r['exact8_complete'] for r in group_rows),
                           'retained_groups': sum(r['retained'] for r in group_rows),
                           'mixed_signal_groups': sum(r['outcome_signal'] for r in group_rows),
                           'allcorrect_potential_groups': sum(r['potential_process_only_signal'] for r in group_rows),
                           'outcome_groups_before_filter': dict(Counter(r['outcome_kind'] for r in group_rows)),
                           'first_retained_mixed_group': next((r['task_id'] for r in group_rows if r['outcome_signal']), None),
                           'first_retained_allcorrect_group': next((r['task_id'] for r in group_rows if r['potential_process_only_signal']), None),
                           'generated_tokens': describe([r['generated_tokens'] for r in step_rows]),
                           'max_native_sequence': describe([r['max_native_sequence'] for r in step_rows])})
        del batch
    write(destination / 'STEP_GROUP_AUDIT.json', {
        'steps': step_audits,
        'policy_warning': 'Step 1 samples P0; step 8 samples P7. Saved later-policy rollouts are not on-policy P0 training data.',
        'complete_definition': 'MODEL_FINAL_STOP, binary persisted reward, and nonempty native segments. Per-token accounting is independently checked only for the final complete step.'})
    step, receipt = finished[-1]
    rollouts = [p for p in step.glob('rollout-*') if (p / 'TRAJECTORY_METRICS.json').is_file()]
    if len(rollouts) != 1:
        raise RuntimeError('Expected exactly one completed rollout for the selected step')
    rollout = rollouts[0]
    metrics = read(rollout / 'TRAJECTORY_METRICS.json')
    groups, rows, seen = defaultdict(list), [], set()
    for item in metrics:
        identity = item['id']
        if identity in seen or Path(identity).name != identity or '/' in identity or '\\' in identity:
            raise ValueError('Unsafe or duplicate trajectory identity')
        seen.add(identity)
        path = rollout / 'trajectories' / identity / 'trajectory.json'
        data = path.read_bytes()
        native = json.loads(data)
        observed = [r for r in native['rounds'] if r.get('response_received')]
        lengths, generated, checks = [], 0, []
        for turn in observed:
            tokens = turn.get('token_accounting', {})
            prompt, completion = tokens.get('prompt_token_ids'), tokens.get('completion_token_ids')
            valid_ids = isinstance(prompt, list) and isinstance(completion, list)
            checks.append(valid_ids and tokens.get('exact_prompt_token_ids_equal') is True)
            if valid_ids:
                lengths.append(len(prompt) + len(completion))
                generated += len(completion)
        terminal = native['metadata']['terminal_status']
        native_ok = bool(observed) and all(checks) and terminal == item['terminal'] and generated == item['generated_tokens']
        row = dict(traj_id=identity, task_id=str(item['query_id']), complete=terminal == 'MODEL_FINAL_STOP',
                   outcome=item['reward'], terminal=terminal, native_ok=native_ok,
                   generated_tokens=generated, max_native_sequence=max(lengths, default=0),
                   native_calls=len(observed), tool_calls=len(native['tool_events']),
                   native_sha256=hashlib.sha256(data).hexdigest())
        rows.append(row)
        groups[row['task_id']].append(row)
        if len(rows) == 1:
            write(destination / 'NATIVE_SCHEMA.json', schema_sample(native, path, root))
        del native, data
    summaries = group_summary(groups)
    kept = {r['task_id'] for r in summaries if r['retained']}
    plan = read(root / 'RUN_PLAN.json')
    excluded = [str(qid) for group in plan['training'] for qid in group]
    actors = []
    allowed_flags = {'--model', '--tokenizer', '--served-model-name', '--tensor-parallel-size', '--dtype',
                     '--max-model-len', '--gpu-memory-utilization', '--max-num-seqs', '--max-num-batched-tokens',
                     '--reasoning-parser', '--tool-call-parser', '--generation-config'}
    for launch in sorted(root.glob('step-*/services-*/actor*/launch.json')):
        command = read(launch)['command']
        actors.append({'launch_path': str(launch), 'python': command[0],
                       'flags': {flag: command[i + 1] for i, flag in enumerate(command[:-1]) if flag in allowed_flags},
                       'enable_prefix_caching': '--enable-prefix-caching' in command,
                       'enforce_eager': '--enforce-eager' in command,
                       'sleep_mode': '--enable-sleep-mode' in command,
                       'mtp_requested': '--speculative-config' in command})
    source_receipts = {}
    for name in ('src/stability.py', 'src/stability_train.py', 'src/rollout.py', 'slurm/stability.sbatch'):
        data = (source / name).read_bytes()
        source_receipts[name] = {'path': str(source / name), 'sha256': hashlib.sha256(data).hexdigest()}
    config = {'source_run': str(root), 'source_code': str(source), 'source_status': read(root / 'STATUS.json'),
              'selected_step': receipt['step'], 'sampling_manifest': read(rollout / 'config_manifest.json'),
              'actor_launches': actors, 'source_receipts': source_receipts,
              'tis_cap2_in_executed_source': 'log_cap = math.log(2.)' in (source / 'src/stability.py').read_text(),
              'selected_step_train': receipt['train'], 'actual_colocated_memory': receipt['memory_utilization_colocated'],
              'run_plan_path': str(root / 'RUN_PLAN.json'), 'pool_path': str((source / 'frozen/PRIVATE_POOL.json').resolve()),
              'pool_receipt': read(source / 'frozen/POOL_RECEIPT.json'),
              'sample_manifest_path': str(rollout / 'sample_manifest.json'),
              'legacy_sample_manifest_path': '/file_storage01/home/weiyu/lanyi/projects/新实验/reports/BrowseCompPlus_RANDOM100_T1_N4_DUALACTOR/sample_manifest.json',
              'excluded_old_training_ids': excluded, 'old_training_unique_ids': len(set(excluded)),
              'old_heldout_ids': plan.get('heldout', [])}
    counts = {'trajectories': len(rows), 'groups': len(summaries),
              'complete_trajectories': sum(r['complete'] for r in rows),
              'native_verified_trajectories': sum(r['native_ok'] for r in rows),
              'exact8_complete_groups': sum(r['exact8_complete'] for r in summaries),
              'retained_groups': len(kept), 'retained_rows': sum(r['task_id'] in kept for r in rows),
              'outcome_signal_groups': sum(r['outcome_signal'] for r in summaries),
              'process_only_potential_groups': sum(r['potential_process_only_signal'] for r in summaries),
              'outcome_groups_before_filter': dict(Counter(r['outcome_kind'] for r in summaries)),
              'drop_reasons': dict(Counter(r['drop_reason'] for r in summaries if r['drop_reason']))}
    report = {'slurm_job_id': os.environ['SLURM_JOB_ID'], 'selected_step': receipt['step'], 'counts': counts,
              'lengths_all': {k: describe([r[k] for r in rows]) for k in ('generated_tokens', 'max_native_sequence', 'native_calls', 'tool_calls')},
              'lengths_retained': {k: describe([r[k] for r in rows if r['task_id'] in kept]) for k in ('generated_tokens', 'max_native_sequence')},
              'groups': summaries, 'rows': rows,
              'interpretation': 'Outcome labels are persisted prior judge rewards, not newly verified truth. Complete means MODEL_FINAL_STOP. One incomplete or unknown row drops the whole 8-row group; allwrong then drops. Allcorrect groups may have process signal, not proven here. No model/API/GPU work was run.'}
    write(destination / 'GROUP_AUDIT.json', report)
    write(destination / 'FROZEN_RUNTIME.json', config)
    print(json.dumps({'output_dir': str(destination), 'selected_step': receipt['step'], 'counts': counts}))


if __name__ == '__main__':
    main()
