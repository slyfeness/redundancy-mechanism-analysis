"""One fresh Ledger batch -> explicit HF/FSDP PPO epochs; no auto recovery.

Backend modules are imported read-only from LEDGER_HF_BACKEND_SOURCE. A completed
optimizer call, a persisted full checkpoint, and a published inference snapshot
have separate receipts. Snapshot publication does not imply rollout synchronization.
"""
import argparse
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import torch

from ledger_grpo.hf_native import (prepare_native_records, single_step_token_loss, credit_native_token_loss,
                                  native_record_freeze_fingerprint, validate_frozen_native_record)


def write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    pending = path.with_suffix(path.suffix + '.partial')
    with pending.open('x', encoding='utf-8') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    # Hard-link publication is atomic and cannot replace an existing receipt.
    os.link(pending, path)
    pending.unlink()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_step_inputs(native_path, score_path):
    native_path, score_path = Path(native_path), Path(score_path)
    native_digest = file_sha256(native_path)
    score = torch.load(score_path, map_location='cpu', weights_only=True)
    binding = score.get('input_binding') if isinstance(score, dict) else None
    if not isinstance(binding, dict) or binding.get('native_batch_sha256') != native_digest:
        raise ValueError('score input_binding.native_batch_sha256 must match the native batch digest')
    with native_path.open('rb') as handle:
        batch = json.load(handle)
    if binding.get('policy_snapshot_sha256') != batch.get('policy_snapshot_sha256'):
        raise ValueError('score and native batch reference different policy snapshots')
    if 'credit_config' in score:
        from ledger_grpo.credit.training import prepare_credit_native_records
        prepared = prepare_credit_native_records(batch['trajectories'], score['credit_trajectories'],
            config=score['credit_config'], max_generated_tokens=score['max_generated_tokens'],
            training_step=score.get('training_step', 0), sampling_seed=score.get('sampling_seed', 0),
            normalization=score.get('loss_normalization', 'fixed'))
    else:
        prepared = prepare_native_records(batch['trajectories'], score)
    if 'loss_denominator' in score:
        denominator = score['loss_denominator']
        if type(denominator) is not int or denominator <= 0:
            raise ValueError('loss_denominator must be a positive fixed integer')
        if prepared.get('credit_mode') and denominator != prepared['loss_denominator']:
            raise ValueError('credit loss denominator must match the configured fixed normalization')
        prepared['loss_denominator'] = denominator
    if 'training_options' in score:
        options = score['training_options']
        if not isinstance(options, dict) or options.keys() != {'ppo_epsilon', 'learning_rate'}:
            raise ValueError('invalid score training options')
        eps, lr = options['ppo_epsilon'], options['learning_rate']
        if (type(eps) not in (int, float) or not math.isfinite(eps) or not 0 <= eps < 1
                or type(lr) not in (int, float) or not math.isfinite(lr) or lr <= 0):
            raise ValueError('invalid PPO clipping or learning rate')
        prepared['training_options'] = options
        if prepared.get('credit_mode') and (eps != .2 or lr != 1e-6):
            raise ValueError('credit v2.1 requires PPO epsilon 0.2 and learning rate 1e-6')
    if score.get('skip_update') is True:
        prepared['skip_update'] = True
    manifest = {'native_batch_path': str(native_path.resolve()), 'native_batch_sha256': native_digest,
                'score_path': str(score_path.resolve()), 'score_sha256': file_sha256(score_path),
                'score_config': score.get('credit_config', score.get('config')), 'control': score.get('control', 'targeted'),
                'mapping_metrics': prepared['metrics'],
                'loss_denominator': prepared.get('loss_denominator', prepared['global_token_count'])}
    if 'training_options' in prepared:
        manifest['training_options'] = prepared['training_options']
    if 'policy_snapshot_sha256' in binding:
        manifest['policy_snapshot_sha256'] = binding['policy_snapshot_sha256']
    return prepared, manifest


def skip_reason(prepared):
    if prepared.get('skip_update') or prepared['global_token_count'] == 0:
        return 'score_or_mask_skip_update'
    def has_signal(record):
        mask = record['action_mask'].bool()
        if bool((record['action_advantages'][mask] != 0).any()):
            return True
        if prepared.get('credit_mode'):
            if bool(record['masked_nll_mask'][mask].any()):
                return True
            if prepared['credit_config']['ledger_sample_correction'] and bool((record['baseline_advantages'][mask] != 0).any()):
                return True
        return False
    if not any(has_signal(r) for r in prepared['records']):
        return 'all_effective_advantages_zero'
    return None


def rank_records(prepared, *, rank, world):
    records = prepared['records']
    if not records:
        return []
    selected = list(records[rank::world])
    count = math.ceil(len(records) / world)
    fallback = min(records, key=lambda row: len(row['prompt_ids']) + len(row['completion_ids']))
    while len(selected) < count:
        padding = dict(fallback, action_mask=torch.zeros_like(fallback['action_mask']),
                       action_advantages=torch.zeros_like(fallback['action_advantages']))
        for key in ('baseline_advantages', 'masked_nll_mask'):
            if key in padding:
                padding[key] = torch.zeros_like(padding[key])
        selected.append(padding)
    return selected


class TorchCollective:
    def __init__(self, rank, world, device):
        self.rank, self.world, self.device = rank, world, device
    def barrier(self):
        torch.distributed.barrier()
    def sum(self, value):
        value = torch.as_tensor(value, device=self.device).clone()
        torch.distributed.all_reduce(value, op=torch.distributed.ReduceOp.SUM)
        return value
    def maximum(self, value):
        value = torch.as_tensor(value, device=self.device, dtype=torch.float64).clone()
        torch.distributed.all_reduce(value, op=torch.distributed.ReduceOp.MAX)
        return value


def record_loss(record, prepared, model, collective):
    """Shared optimizer-free native forward and PPO loss for the worker and smoke."""
    device = collective.device
    if prepared.get('credit_mode') and bool(record['action_mask'].any()):
        validate_frozen_native_record(record)
    ids = torch.tensor([record['prompt_ids'] + record['completion_ids']], dtype=torch.long, device=device)
    positions = torch.tensor(record['action_offsets'], dtype=torch.long, device=device) + len(record['prompt_ids'])
    current, entropy = model(ids, positions, observe_entropy=True)
    if bool(collective.maximum(int(not bool(torch.isfinite(current).all() & torch.isfinite(entropy).all())))):
        raise RuntimeError('Nonfinite model logprob or entropy; optimizer not executed')
    sampled = torch.tensor(record['vllm_logprobs'], dtype=current.dtype, device=device)
    advantage = record['action_advantages'].to(device=device, dtype=current.dtype)
    mask = record['action_mask'].to(device=device, dtype=torch.bool)
    if prepared.get('credit_mode'):
        result = credit_native_token_loss(current, sampled, record, prepared, world_size=collective.world)
    else:
        result = single_step_token_loss(current, sampled, advantage, mask,
                                    global_token_count=prepared['global_token_count'], world_size=collective.world,
                                    loss_denominator=prepared.get('loss_denominator'),
                                    epsilon=prepared.get('training_options', {}).get('ppo_epsilon', .2))
    if bool(collective.maximum(int(not bool(torch.isfinite(result['loss']))))):
        raise RuntimeError('Nonfinite loss; optimizer not executed')
    return result, entropy, advantage, mask


@torch.no_grad()
def freeze_native_old_logprobs(prepared, model, collective, *, use_old_as_sampled=False):
    """Cache the initial HF policy once per rollout; never refresh it after an update.

    use_old_as_sampled is an explicit offline-smoke option for records that did
    not save their original sampling probabilities. It cannot validate real TIS.
    """
    if not prepared.get('credit_mode'):
        raise ValueError('old-policy freezing requires a credit batch')
    local = prepared['records'][collective.rank::collective.world]
    if 'old_policy' in prepared:
        for record in local:
            validate_frozen_native_record(record)
        fingerprint = hashlib.sha256(''.join(record['freeze_fingerprint'] for record in local).encode()).hexdigest()
        if fingerprint != prepared['old_policy']['fingerprint']:
            raise ValueError('frozen rollout fingerprint changed')
        return prepared['old_policy']
    for record in rank_records(prepared, rank=collective.rank, world=collective.world):
        ids = torch.tensor([record['prompt_ids'] + record['completion_ids']], dtype=torch.long, device=collective.device)
        positions = torch.tensor(record['action_offsets'], dtype=torch.long, device=collective.device) + len(record['prompt_ids'])
        old, entropy = model(ids, positions, observe_entropy=True)
        if bool(collective.maximum(int(not bool(torch.isfinite(old).all() & torch.isfinite(entropy).all())))):
            raise RuntimeError('nonfinite initial old policy; optimizer not executed')
        if bool(record['action_mask'].any()):
            record['old_logprobs'] = old.detach().cpu().clone()
            if use_old_as_sampled:
                record['vllm_logprobs'] = record['old_logprobs'].tolist()
            record['freeze_fingerprint'] = native_record_freeze_fingerprint(record)
    fingerprint = hashlib.sha256(''.join(record['freeze_fingerprint'] for record in local).encode()).hexdigest()
    prepared['old_policy'] = {'source': 'frozen_initial_forward', 'fingerprint': fingerprint,
                              'rank': collective.rank, 'record_count': len(local),
                              'sampling_probabilities': 'initial_hf_smoke_surrogate' if use_old_as_sampled else 'recorded'}
    return prepared['old_policy']


def run_ppo_updates(prepared, model, optimizer, collective, *, batch_identity, update_index,
                    ppo_epochs=1, on_optimizer_step=None):
    """Run explicit PPO epochs on one immutable rollout with a frozen old policy."""
    if type(ppo_epochs) is not int or ppo_epochs < 1:
        raise ValueError('ppo_epochs must be a positive integer')
    if not prepared.get('credit_mode'):
        if ppo_epochs != 1:
            raise ValueError('multiple PPO epochs require the credit frozen-policy path')
        return run_update(prepared, model, optimizer, collective, batch_identity=batch_identity,
                          update_index=update_index, on_optimizer_step=on_optimizer_step)
    consumed = getattr(optimizer, '_ledger_consumed_batches', set())
    prefix = batch_identity + '#ppo-'
    if batch_identity in consumed or any(value.startswith(prefix) for value in consumed):
        raise ValueError('rollout was already consumed; partial PPO batches are not automatically resumed')
    freeze_native_old_logprobs(prepared, model, collective)
    results = []
    for epoch in range(ppo_epochs):
        result = run_update(prepared, model, optimizer, collective,
                            batch_identity=prefix + str(epoch + 1), update_index=update_index + epoch,
                            on_optimizer_step=on_optimizer_step)
        results.append(result)
        if result['state'] == 'skipped':
            break
    if results[-1]['state'] == 'computed':
        optimizer._ledger_consumed_batches.add(batch_identity)
    return dict(results[-1], optimizer_steps_this_batch=sum(r['optimizer_steps_this_batch'] for r in results),
                persisted_optimizer_steps=update_index - 1,
                ppo_epochs_requested=ppo_epochs, ppo_epoch_losses=[r.get('loss') for r in results],
                old_policy=dict(prepared['old_policy']))


def run_update(prepared, model, optimizer, collective, *, batch_identity, update_index,
               on_optimizer_step=None):
    """Retain model/Adam across future fresh batches; never repeat a consumed batch.

    Only one optimizer.step follows the complete globally normalized batch.
    A skipped batch does not advance Adam or the completed update index.
    """
    consumed = getattr(optimizer, '_ledger_consumed_batches', set())
    completed = getattr(optimizer, '_ledger_computed_updates', 0)
    if batch_identity in consumed:
        raise ValueError('This native batch was already consumed; reusing it requires a different algorithm')
    if not isinstance(batch_identity, str) or not batch_identity or update_index != completed + 1:
        raise ValueError('A fresh batch identity and the next computed update index are required')
    reason = skip_reason(prepared)
    if reason:
        return {'state': 'skipped', 'skip_reason': reason, 'computed_optimizer_steps': completed,
                'optimizer_steps_this_batch': 0, 'effective_action_tokens': prepared['global_token_count']}
    if prepared.get('credit_mode'):
        freeze_native_old_logprobs(prepared, model, collective)
    started = time.monotonic()
    device = collective.device
    optimizer.zero_grad(set_to_none=True)
    # numerator, entropy, token count, TIS clipped, abs(q error), TIS sum, +A, -A, zero A
    totals = torch.zeros(11, dtype=torch.float64, device=device)
    error_max = 0.
    for record in rank_records(prepared, rank=collective.rank, world=collective.world):
        result, entropy, advantage, mask = record_loss(record, prepared, model, collective)
        result['loss'].backward()
        with torch.no_grad():
            errors = result['sampling_logprob_difference'].abs().double()
            totals[0] += result['loss_numerator'].detach().double()
            totals[1] += entropy[mask].double().sum()
            totals[2] += mask.sum()
            totals[3] += result['tis_clipped'].sum()
            totals[4] += errors.sum()
            totals[5] += result['tis_weights'].double().sum()
            totals[6] += (advantage[mask] > 0).sum()
            totals[7] += (advantage[mask] < 0).sum()
            totals[8] += (advantage[mask] == 0).sum()
            totals[9] += result.get('auxiliary_loss_numerator', 0.)
            totals[10] += result.get('ppo_clip_count', 0.)
            error_max = max(error_max, float(errors.max()) if errors.numel() else 0.)
        del entropy, advantage, mask, result, errors
    totals = collective.sum(totals)
    count = int(totals[2])
    if count != prepared['global_token_count']:
        raise RuntimeError('Distributed shards lost or duplicated effective tokens; optimizer not executed')
    norm = float(model.clip_grad_norm_(1.))
    if bool(collective.maximum(int(not math.isfinite(norm)))):
        raise RuntimeError('Nonfinite gradient norm; optimizer not executed')
    probes = [(p, p.detach().flatten()[:16].clone()) for p in model.parameters() if p.requires_grad and p.numel()]
    optimizer.step()
    # From this line onward the update happened even if later persistence fails.
    optimizer._ledger_consumed_batches = consumed | {batch_identity}
    optimizer._ledger_computed_updates = update_index
    if on_optimizer_step is not None:
        on_optimizer_step({'state': 'optimizer_returned', 'rank': collective.rank,
                           'optimizer_step': update_index, 'batch_identity': batch_identity,
                           'checkpoint_persisted': False, 'all_ranks_confirmed': False})
    changed = any(not torch.equal(p.detach().flatten()[:16], value) for p, value in probes)
    steps = [int(state['step'].item()) for state in optimizer.state.values() if 'step' in state]
    if not steps or min(steps) != update_index or max(steps) != update_index:
        raise RuntimeError('Optimizer executed but its Adam step counters disagree with the update index')
    receipt = {'state': 'computed', 'computed_optimizer_steps': update_index, 'optimizer_steps_this_batch': 1,
            'persisted_optimizer_steps': update_index - 1, 'snapshot_published': False,
            'loss': float(totals[0]) / prepared.get('loss_denominator', count),
            'loss_denominator': prepared.get('loss_denominator', count),
            'loss_reduction': 'fixed_denominator' if 'loss_denominator' in prepared else 'token_mean',
            'entropy': float(totals[1]) / count,
            'effective_action_tokens': count, 'gradient_norm_before_clip': norm,
            'positive_advantage_tokens': int(totals[6]), 'negative_advantage_tokens': int(totals[7]),
            'zero_advantage_tokens': int(totals[8]), 'tis_cap': 2., 'tis_clip_fraction': float(totals[3]) / count,
            'auxiliary_nll': float(totals[9]) / prepared.get('loss_denominator', count),
            'ppo_clip_fraction': float(totals[10]) / count,
            'tis_weight_mean': float(totals[5]) / count,
            'hf_sample_abs_logprob_error_mean': float(totals[4]) / count,
            'hf_sample_abs_logprob_error_max': float(collective.maximum(error_max)),
            'any_rank_parameter_probe_changed': bool(collective.maximum(int(changed))),
            'parameter_probe_is_full_weight_comparison': False,
            'old_probability': 'frozen_initial_forward' if prepared.get('credit_mode') else 'same_forward_detached',
            'ppo_ratio_is_stability_metric': bool(prepared.get('credit_mode')),
            'kl_coefficient': 0., 'learning_rate': prepared.get('training_options', {}).get('learning_rate', 1e-6),
            'weight_decay': 0.,
            'compute_seconds': time.monotonic() - started}
    if 'credit_metrics' in prepared:
        receipt['credit_metrics'] = deepcopy(prepared['credit_metrics'])
        receipt['credit_metrics']['policy'].update(entropy=receipt['entropy'], kl=None,
            clip_fraction=receipt['ppo_clip_fraction'], gradient_norm=norm)
        receipt['credit_metrics']['modules']['auxiliary_loss'] = receipt['auxiliary_nll']
    return receipt


def wait_snapshot(receipt, timeout=3600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            payload = json.loads(receipt.read_text(encoding='utf-8'))
            if payload.get('file_sha256') and payload.get('verified_byte_count', 0) > 0:
                return payload
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(.5)
    raise TimeoutError('Updated snapshot was not published with a verified receipt')


def check_snapshot_destination(directory, publication_id):
    if type(publication_id) is not int or publication_id <= 0:
        raise ValueError('publication_id must be a positive integer independent of optimizer_step')
    directory = Path(directory)
    if any(directory.glob(f'step-{publication_id}.*')):
        raise FileExistsError('Snapshot publication ID already has artifacts; never overwrite or auto recover')


def persist_update(model, optimizer, result, backend, collective, output_root, *, update_index,
                   snapshot_directory=None, publication_id=None):
    root = Path(output_root)
    snapshots = Path(snapshot_directory) if snapshot_directory is not None else root / 'policy-snapshots'
    publication_id = update_index if publication_id is None else publication_id
    step = root / f'step-{update_index:04d}'
    if result['state'] != 'computed':
        if collective.rank == 0:
            write_once(step / 'SKIPPED.json', result)
        return result
    result = dict(result, optimizer_step=update_index, publication_id=publication_id,
                  snapshot_directory=str(snapshots.resolve()))
    if collective.rank == 0:
        write_once(step / 'UPDATE_COMPUTED.json', result)
    collective.barrier()
    checkpoint = root / 'checkpoints' / f'step-{update_index:04d}'
    if collective.rank == 0:
        checkpoint.mkdir(parents=True, exist_ok=False)
    collective.barrier()
    started = time.monotonic()
    backend.save_rank(model, optimizer, checkpoint / f'checkpoint-rank{collective.rank}.pt',
                      collective.rank, collective.world, update_index)
    collective.barrier()
    persisted = dict(result, state='checkpoint_persisted', persisted_optimizer_steps=update_index,
                     checkpoint_seconds=time.monotonic() - started)
    if collective.rank == 0:
        files = [checkpoint / f'checkpoint-rank{rank}.pt' for rank in range(collective.world)]
        if not all(path.is_file() and path.stat().st_size > 0 for path in files):
            raise RuntimeError('Optimizer executed but full rank checkpoint set is incomplete')
        write_once(checkpoint / 'COMPLETE.json', {'optimizer_step': update_index,
                   'publication_id': publication_id, 'world_size': collective.world,
                   'contents': ['model', 'optimizer', 'cpu_rng', 'cuda_rng'],
                   'shards': [{'name': path.name, 'bytes': path.stat().st_size} for path in files]})
        write_once(step / 'CHECKPOINT_PERSISTED.json', persisted)
    collective.barrier()
    if collective.rank == 0:
        snapshots.mkdir(parents=True, exist_ok=True)
        check_snapshot_destination(snapshots, publication_id)
    collective.barrier()
    started = time.monotonic()
    backend.export_policy_snapshot(model, backend.model_directory, snapshots, publication_id,
                                   collective.rank, verify_disk=True)
    # Other ranks wait on the CPU, rather than spin in a GPU collective during disk I/O.
    snapshot = wait_snapshot(snapshots / f'step-{publication_id}.json')
    if snapshot.get('snapshot') != f'step-{publication_id}.safetensors':
        raise RuntimeError('Snapshot receipt does not name the requested publication basename')
    collective.barrier()
    complete = dict(persisted, state='snapshot_published', snapshot_published=True,
                    policy_synced=False, snapshot_seconds=time.monotonic() - started,
                    snapshot_receipt=snapshot)
    if collective.rank == 0:
        write_once(step / 'STEP_COMPLETE.json', complete)
    return complete


def load_backend():
    value = os.environ.get('LEDGER_HF_BACKEND_SOURCE')
    if not value:
        raise ValueError('LEDGER_HF_BACKEND_SOURCE must identify the existing read-only v4 source')
    root = Path(value).resolve()
    if not (root / 'src/train_smoke.py').is_file():
        raise ValueError('The backend source must contain src/train_smoke.py')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    modules = [importlib.import_module(name) for name in ('src.train_smoke', 'src.checkpoint', 'src.policy_snapshot')]
    if any(not Path(module.__file__).resolve().is_relative_to(root) for module in modules):
        raise RuntimeError('An already imported src module shadows the explicitly selected backend')
    train, checkpoint, snapshot = modules
    model_path = Path(train.MODEL).resolve()
    override = os.environ.get('LEDGER_MODEL_PATH')
    if override and Path(override).resolve() != model_path:
        raise ValueError('This P0 pilot must use the backend frozen base model path')
    return SimpleNamespace(make_model=train.make_model, save_rank=checkpoint.save_rank, load_rank=checkpoint.load_rank,
                           export_policy_snapshot=snapshot.export_policy_snapshot,
                           model_directory=str(model_path), source_directory=str(root),
                           modules={module.__name__: {'path': module.__file__, 'sha256': file_sha256(module.__file__)} for module in modules})


def restore_stage_optimizer(backend, model, optimizer, parent, *, rank, world):
    previous = parent['optimizer_step']
    backend.load_rank(model,optimizer,Path(parent['checkpoint'])/f'checkpoint-rank{rank}.pt',rank,world,previous)
    steps = [int(state['step'].item()) for state in optimizer.state.values() if 'step' in state]
    if not steps or any(step != previous for step in steps):
        raise ValueError('restored Adam state does not match the checkpoint optimizer step')
    optimizer._ledger_computed_updates = previous
    optimizer._ledger_consumed_batches = set(parent['consumed_batches'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-batch', type=Path, required=True)
    parser.add_argument('--scores', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--snapshot-dir', type=Path, required=True,
                        help='Shared ResidentWeightWorker root; step-N.safetensors is written directly here')
    parser.add_argument('--publication-id', type=int, required=True,
                        help='Unique inference snapshot ID, independent of the optimizer step')
    parser.add_argument('--steps', type=int, default=1)
    parser.add_argument('--ppo-epochs', type=int, default=1,
                        help='Explicit PPO epochs sharing frozen old probabilities and credit on one rollout batch')
    parser.add_argument('--resume-checkpoint', type=Path, help='Explicit prior complete checkpoint inside the pilot run store')
    args = parser.parse_args(argv)
    if args.steps != 1:
        raise ValueError('each worker invocation consumes one fresh batch; configure the next stage with an explicit resume checkpoint')
    if args.ppo_epochs < 1:
        raise ValueError('ppo-epochs must be positive')
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ.get('WORLD_SIZE', '0')) != 4:
        raise RuntimeError('Real worker requires a four-rank torchrun inside an authorized Slurm allocation')
    rank = int(os.environ['LOCAL_RANK'])
    output = args.output_root.resolve()
    snapshots = args.snapshot_dir.resolve()
    parent = None
    if args.resume_checkpoint is not None:
        from pilot_resume import bind_checkpoint
        parent = bind_checkpoint(args.resume_checkpoint, runs_root=Path(os.environ['LEDGER_PILOT_STORE'])/'runs')
    previous = parent['optimizer_step'] if parent else 0
    index = previous+args.ppo_epochs
    step = output/f'step-{index:04d}'
    check_snapshot_destination(snapshots, args.publication_id)
    source_value = os.environ.get('LEDGER_HF_BACKEND_SOURCE')
    if source_value and any(path.is_relative_to(Path(source_value).resolve()) for path in (output, snapshots)):
        raise ValueError('Output must be outside the read-only backend source')
    torch.cuda.set_device(rank)
    torch.distributed.init_process_group('nccl', device_id=torch.device('cuda', rank), timeout=timedelta(minutes=30))
    collective = TorchCollective(rank, 4, torch.device('cuda', rank))
    try:
        if rank == 0:
            step.mkdir(parents=True, exist_ok=False)
        collective.barrier()
        prepared, manifest = load_step_inputs(args.native_batch, args.scores)
        if args.ppo_epochs != 1 and not prepared.get('credit_mode'):
            raise ValueError('multiple PPO epochs require credit v2.1 frozen-policy inputs')
        if parent:
            from pilot_resume import bind_fresh_batch
            bind_fresh_batch(parent,manifest)
            manifest['resume'] = {k:parent[k] for k in ('checkpoint','checkpoint_receipt_sha256','optimizer_step','consumed_batches')}
        if rank == 0:
            manifest.update(optimizer_step=index, publication_id=args.publication_id,
                            snapshot_directory=str(snapshots), ppo_epochs=args.ppo_epochs,
                            first_optimizer_step=previous+1)
            write_once(step/'INPUTS.json', manifest)
        reason = skip_reason(prepared)
        if reason:
            if rank == 0:
                write_once(step/'SKIPPED.json', {'state': 'skipped', 'skip_reason': reason,
                           'computed_optimizer_steps': previous, 'persisted_optimizer_steps': previous})
            collective.barrier()
            return 0
        torch.manual_seed(20261109)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.set_float32_matmul_precision('highest')
        os.environ.setdefault('TRITON_CACHE_DIR', str(output / 'cache/triton'))
        os.environ.setdefault('TORCHINDUCTOR_CACHE_DIR', str(output / 'cache/inductor'))
        backend = load_backend()
        backend_receipt = {'source': backend.source_directory,'model': backend.model_directory,
                           'modules': backend.modules, 'seed': 20261109}
        if parent and parent['backend'] != backend_receipt:
            raise ValueError('resume backend differs from the checkpoint backend')
        if rank == 0:
            write_once(step/'BACKEND.json', backend_receipt)
        model, trainable, kernels, calls = backend.make_model(rank)
        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=prepared.get('training_options', {}).get('learning_rate', 1e-6),
                                      weight_decay=0.)
        if parent:
            restore_stage_optimizer(backend,model,optimizer,parent,rank=rank,world=4)
            write_once(step/f'RESUME-rank{rank}.json', {'rank':rank,'restored_step':previous,
                       'checkpoint_receipt_sha256':parent['checkpoint_receipt_sha256']})
        def optimizer_returned(event):
            if args.ppo_epochs > 1:
                write_once(step/'optimizer-events'/f'step-{event["optimizer_step"]}-rank{rank}.json', event)
            if event['optimizer_step'] == index:
                write_once(step/f'OPTIMIZER_RETURNED-rank{rank}.json', event)
        if prepared.get('credit_mode'):
            freeze = freeze_native_old_logprobs(prepared, model, collective)
            write_once(step/f'OLD_POLICY-rank{rank}.json', freeze)
        result = run_ppo_updates(prepared, model, optimizer, collective,
                            batch_identity=manifest['native_batch_sha256'], update_index=previous+1,
                            ppo_epochs=args.ppo_epochs,
                            on_optimizer_step=optimizer_returned)
        result.update(trainable_parameters=trainable, kernels=kernels, kernel_calls=dict(calls))
        # Gradients are not checkpoint contents. Match the validated stability
        # engine's residency before gathering a full inference snapshot.
        optimizer.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        persist_update(model, optimizer, result, backend, collective, output, update_index=index,
                       snapshot_directory=snapshots, publication_id=args.publication_id)
        collective.barrier()
        return 0
    except BaseException as error:
        if rank == 0:
            write_once(output / 'FAILED.json', {'error_type': type(error).__name__,
                       'optimizer_returned_ranks': [i for i in range(4) if
                           (step/f'OPTIMIZER_RETURNED-rank{i}.json').is_file()
                           or any((step/'optimizer-events').glob(f'*-rank{i}.json'))],
                       'optimizer_step': index, 'publication_id': args.publication_id,
                       'update_computed_receipt_exists': (step/'UPDATE_COMPUTED.json').is_file(),
                       'checkpoint_complete_exists': (output/'checkpoints'/step.name/'COMPLETE.json').is_file(),
                       'snapshot_published_receipt_exists': (step/'STEP_COMPLETE.json').is_file()})
        raise
    finally:
        torch.distributed.destroy_process_group()


if __name__ == '__main__':
    raise SystemExit(main())
