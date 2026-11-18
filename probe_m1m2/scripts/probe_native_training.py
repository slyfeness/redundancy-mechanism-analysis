"""CPU-only native sequence/mask audit. Never constructs a model or optimizer.

Real 190085 tokens + real preparation functions. Synthetic score tensors only
exercise the preparation interface; they are not labels, rewards or training.
"""
import collections
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time

START = time.monotonic()
B = Path('/file_storage01/home/weiyu/lanyi')
ROOT = B / 'projects/deepsearch-world-pilot/probe_m1m2'
OUT = ROOT / ('native_training-' + os.environ['SLURM_JOB_ID'])
OUT.mkdir(exist_ok=False)
RUN = B / 'projects/deepsearch-world-pilot/pilot-4b-190085'
QUAL = Path('/persist_data/home/weiyu/lanyi/projects/coex-0f50c2e3/qualified-source/ledger-grpo')
BACK = B / 'projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4'
MODEL = B / 'models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a'
sys.path.insert(0, str(QUAL / 'src'))
import torch
from transformers import AutoTokenizer
from ledger_grpo.browsecomp_adapter import native_trajectory
from ledger_grpo.hf_native import native_turn_layout, prepare_native_records

def read(path):
    return json.loads(path.read_bytes())

def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def table(name, rows):
    with (OUT / name).open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

spec = importlib.util.spec_from_file_location('frozen_native_spans', BACK / 'src/native_spans.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
source_files = [QUAL / 'src/ledger_grpo' / name for name in
                ['browsecomp_adapter.py', 'native_capture.py', 'hf_native.py', 'verl_adapter.py', 'verl_plugin.py']]
source_files += [QUAL / 'scripts' / name for name in ['hf_pilot_train.py', 'hf_pilot_controller.py']]
source_files += [BACK / 'src' / name for name in
                 ['native_spans.py', 'prepare_training.py', 'stability_train.py', 'train_smoke.py']]
source_info = []
(OUT / 'source_refs').mkdir()
for path in source_files:
    data = path.read_bytes()
    prefix = 'ledger_' if path.is_relative_to(QUAL) else 'backend_'
    (OUT / 'source_refs' / (prefix + path.name)).write_bytes(data)
    source_info.append({'path': str(path), 'sha256': sha(path), 'lines': len(data.splitlines())})
assert Path(sys.modules['ledger_grpo.hf_native'].__file__).is_relative_to(QUAL)
tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
ids = read(ROOT / 'selection.json')['ids']
input_hashes = {r['trajectory_id']: r['sha256_before'] for r in read(ROOT / 'input_integrity.json')}
native_rows, layouts, provenance, checks, fields, roundtrip, history = [], [], [], [], [], [], []
all_sample_tokens = 0
for i, tid in enumerate(ids):
    path = RUN / 'trajectories' / tid / 'trajectory.json'
    assert sha(path) == input_hashes[tid]
    raw = read(path)
    native = native_trajectory(raw, reward=0)  # dummy value never used for grading
    layout = native_turn_layout(native)
    # Compare with the original backend's actual training record constructor.
    reference = engine.action_records([dict(native, advantage=0)], merge=True)
    for actual, expected in zip(layout['spans'], reference):
        for key in ['prompt_ids', 'completion_ids', 'vllm_logprobs', 'action_offsets']:
            assert actual[key] == expected[key], (tid, key)
    assert len(reference) == len(layout['spans'])
    rounds = [r for r in raw['rounds'] if r.get('response_received') and r['token_accounting']['completion_token_ids']]
    assert len(rounds) == len(native['segments']) == len(layout['turns'])
    total = sum(len(s['completion_ids']) for s in native['segments'])
    assert sum(layout['response_mask']) == total
    stage_ids = [-1 if bit == 0 else None for bit in layout['response_mask']]
    unassigned = collections.Counter()
    template_matches = 0
    roundtrip_matches = 0
    native_provenance = []
    obs_blocks = 0
    for r, segment, turn in zip(rounds, native['segments'], layout['turns']):
        response = r['raw_response']; choice = response['choices'][0]
        assert segment['prompt_ids'] == response['prompt_token_ids']
        assert segment['completion_ids'] == choice['token_ids']
        assert segment['vllm_logprobs'] == [x['logprob'] for x in choice['logprobs']['content']]
        span = layout['spans'][turn['span_index']]
        local_start = turn['token_start'] - span['axis_start']
        # Each action keeps the exact prefix used when sampling, not just the same text.
        assert span['prompt_ids'] + span['completion_ids'][:local_start] == segment['prompt_ids']
        assert span['completion_ids'][local_start:local_start + len(segment['completion_ids'])] == segment['completion_ids']
        assert all(layout['response_mask'][turn['token_start']:turn['token_end']])
        rid = r['round_id']; calls = r.get('tool_calls') or []
        final = not calls and r.get('finish_reason') == 'stop' and bool(r.get('content'))
        labels = [None] * len(segment['completion_ids'])
        if len(calls) == 1 or final:
            labels = [f'R{rid}'] * len(labels)
        elif len(calls) > 1:
            starts = [j for j, x in enumerate(segment['completion_ids']) if x == 248058]
            ends = [j for j, x in enumerate(segment['completion_ids']) if x == 248059]
            assert len(starts) == len(ends) == len(calls)
            for ordinal, (start, end) in enumerate(zip(starts, ends), 1):
                labels[start:end + 1] = [f'R{rid}:T{ordinal}'] * (end + 1 - start)
            unassigned['parallel_shared_thought_or_protocol'] += labels.count(None)
        else:
            unassigned['unfinished_generation'] += len(labels)
        stage_ids[turn['token_start']:turn['token_end']] = labels
        native_provenance.append({'round': rid, **turn, 'native_prompt_exact': True,
                                 'native_completion_exact': True, 'sample_logprobs_exact': True})
        # Actual tool blocks in model-visible prompts must never be action targets.
        prompt = segment['prompt_ids']
        opens = [j for j, x in enumerate(prompt) if x == 248066]
        closes = [j for j, x in enumerate(prompt) if x == 248067]
        assert len(opens) == len(closes)
        for start, end in zip(opens, closes):
            assert start < end
            for pos in range(start, end + 1):
                local = pos - len(span['prompt_ids'])
                if local >= 0:
                    assert layout['response_mask'][span['axis_start'] + local] == 0
            obs_blocks += 1
        if i < 3:
            rd = RUN / 'trajectories' / tid / f'round_{rid:03d}'
            expected = read(rd / 'expected_prompt_token_ids.json')
            assert expected == prompt
            template_matches += 1
            decoded = tokenizer.decode(segment['completion_ids'], skip_special_tokens=False)
            encoded = tokenizer.encode(decoded, add_special_tokens=False)
            equal = encoded == segment['completion_ids']; roundtrip_matches += equal
            roundtrip.append({'trajectory_id': tid, 'round': rid, 'native_tokens': len(segment['completion_ids']),
                              'reencoded_tokens': len(encoded), 'equal': equal,
                              'first_difference': next((j for j, (a, b) in enumerate(zip(encoded, segment['completion_ids'])) if a != b),
                                                       min(len(encoded), len(segment['completion_ids'])) if not equal else None),
                              'used_for_training': False})
    assigned = sum(isinstance(x, str) for x in stage_ids)
    assert assigned + sum(unassigned.values()) == total
    assert sum(x == -1 for x in stage_ids) == len(layout['response_mask']) - total
    checks.append({'trajectory_id': tid, 'question_id': native['query_id'], 'pass': not unassigned,
                   'mask_construction_verified': True, 'native_training_input_verified': True,
                   'verification_scope': 'CPU preparation functions; not an executed 190085 optimizer batch',
                   'failure_items': ';'.join(unassigned), 'native_generated_tokens': total,
                   'diagnostic_mapped_tokens': assigned, 'diagnostic_partition_sum': total,
                   'training_spans': len(reference), 'mask_zero_context_tokens': len(stage_ids) - total,
                   'native_calls': len(rounds), 'exact_prefix_failures': len(reference) - 1,
                   'tool_calls': len(raw['tool_events']), 'tool_returns': len(raw['tool_events']),
                   'has_final': raw['metadata']['terminal_status'] == 'MODEL_FINAL_STOP',
                   'terminal_status': raw['metadata']['terminal_status']})
    fields.append({'trajectory_id': tid, 'rounds': len(rounds), 'prompt_ids': True, 'completion_ids': True,
                   'sampled_logprobs': True, 'sampled_logprobs_count': total,
                   'persisted_response_mask': False, 'persisted_hf_old_logprobs': False,
                   'raw_response': True, 'messages_and_reasoning': True,
                   'tool_block_occurrences_checked_in_prompts': obs_blocks})
    provenance.append({'trajectory_id': tid, 'turns': native_provenance,
                       'unassigned_stage_tokens': dict(unassigned)})
    if i < 3:
        write(f'traj_{i+1}_training_tokens.json', {'trajectory_id': tid,
            'origin': 'actual CPU native_turn_layout output; not historical persisted training tensor',
            'score_tensors': 'synthetic all-valid eligibility only; no reward/gradient/optimizer',
            'spans': layout['spans'], 'response_mask': layout['response_mask'],
            'stage_ids': stage_ids, 'turns': native_provenance,
            'native_generation_decoded': [tokenizer.decode(s['completion_ids'], skip_special_tokens=False) for s in native['segments']]})
        history.append({'trajectory_id': tid, 'template_expected_prompt_ids_equal_serving': template_matches,
                        'calls': len(rounds), 'decode_encode_equal_calls': roundtrip_matches})
    native_rows.append(native); layouts.append(layout)
    all_sample_tokens += total
    assert sha(path) == input_hashes[tid]
    print(json.dumps({'trajectory_id': tid, 'calls': len(rounds), 'spans': len(reference), 'mapped': assigned, 'generated': total}), flush=True)

# Run the exact preparation function on CPU with explicitly synthetic eligibility.
width = max(len(l['response_mask']) for l in layouts)
mask = torch.tensor([l['response_mask'] + [0] * (width - len(l['response_mask'])) for l in layouts], dtype=torch.bool)
score = {'process_inputs': [{'traj_id': n['id'], 'task_id': n['query_id'], 'response_mask': l['response_mask']} for n, l in zip(native_rows, layouts)],
         'advantages': mask.float(), 'effective_response_mask': mask,
         'valid_rows': torch.ones(len(ids), dtype=torch.bool)}
prepared = prepare_native_records(native_rows, score)
assert prepared['global_token_count'] == all_sample_tokens
expected = [s for l in layouts for s in l['spans']]
assert len(prepared['records']) == len(expected)
for record, span in zip(prepared['records'], expected):
    for key in ['prompt_ids', 'completion_ids', 'action_offsets', 'vllm_logprobs']:
        assert record[key] == span[key]
    assert bool(record['action_mask'].all())
    # Same expressions as hf_pilot_train.run_update; no model forward.
    input_ids = torch.tensor([record['prompt_ids'] + record['completion_ids']])
    positions = torch.tensor(record['action_offsets']) + len(record['prompt_ids'])
    assert input_ids[0, positions].tolist() == [record['completion_ids'][j] for j in record['action_offsets']]
score['valid_rows'][0] = False
score['effective_response_mask'] = mask.clone(); score['effective_response_mask'][0] = False
score['advantages'] = score['effective_response_mask'].float()
excluded = prepare_native_records(native_rows, score)
assert excluded['global_token_count'] == all_sample_tokens - sum(layouts[0]['response_mask'])
assert all(r['trajectory_id'] != ids[0] for r in excluded['records'])

table('stage_mapping_check.csv', checks)
write('field_inventory.json', fields)
write('call_training_alignment.json', provenance)
write('roundtrip_diagnostic.json', {'note': 'decode/encode is diagnostic only, never substituted for native training tokens', 'rows': roundtrip, 'samples': history})
write('training_source_audit.json', {'files': source_info, 'loaded_hf_native': sys.modules['ledger_grpo.hf_native'].__file__})
summary = {'job_id': os.environ['SLURM_JOB_ID'], 'source_run': '190085', 'trajectories': len(ids),
    'native_calls': sum(c['native_calls'] for c in checks), 'native_generated_tokens': all_sample_tokens,
    'native_training_input_checks_passed': len(checks), 'mask_checks_passed': len(checks),
    'stage_mapping_complete': sum(c['pass'] for c in checks),
    'stage_mapping_incomplete_ids': [c['trajectory_id'] for c in checks if not c['pass']],
    'training_spans': sum(c['training_spans'] for c in checks),
    'spans_per_trajectory': {'min': min(c['training_spans'] for c in checks), 'median': statistics.median(c['training_spans'] for c in checks), 'max': max(c['training_spans'] for c in checks)},
    'mask_zero_context_tokens': sum(c['mask_zero_context_tokens'] for c in checks),
    'excluded_row_check': True, 'preparation_matches_frozen_backend': True,
    'history_sample_checks': history, 'model_calls': 0, 'optimizer_steps': 0,
    'real_training_on_190085': False, 'persisted_hf_old_logprobs_available': False,
    'source_hashes_unchanged': all(sha(Path(s['path'])) == s['sha256'] for s in source_info),
    'trajectory_hashes_unchanged': True, 'elapsed_seconds': time.monotonic() - START,
    'limitations': ['CPU input construction only; no numeric HF probability recomputation',
                    'synthetic eligibility does not approve real outcomes, groups or training',
                    'parallel shared thought and unfinished Stage ownership remain undecided']}
write('native_training_summary.json', summary)
print(json.dumps(summary), flush=True)
