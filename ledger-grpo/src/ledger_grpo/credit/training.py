"""Credit v2.1 preparation and PPO objective used by the existing HF worker.

Preparation is performed once per rollout batch, before any PPO minibatch or
epoch. The returned detached tensors are the frozen credit targets. No Judge
client is constructed here; the caller explicitly supplies a ledger provider.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path

import torch

from .config import CreditConfig
from .schema import Group, Trajectory, Unit, validate_ledger
from .tokens import write_token_advantages


def fixed_loss_denominator(trajectory_count, max_generated_tokens, *, normalization='fixed', token_count=None):
    if normalization in ('trajectory_mean', 'sequence_mean', 'per_trajectory', 'per_sequence'):
        raise ValueError('per-trajectory averaging is disabled in every credit mode')
    if normalization not in ('fixed', 'batch_token_mean'):
        raise ValueError('normalization must be fixed or explicit debug batch_token_mean')
    if any(type(x) is not int or x <= 0 for x in (trajectory_count, max_generated_tokens)):
        raise ValueError('trajectory count and generated-token limit must be positive integers')
    result = trajectory_count * max_generated_tokens if normalization == 'fixed' else token_count
    if type(result) is not int or result <= 0:
        raise ValueError('loss denominator must be a positive fixed integer')
    return result


def credit_token_loss(current_logprobs, old_logprobs, advantages, action_mask, *, loss_denominator,
                      world_size=1, sampled_logprobs=None, baseline_advantages=None,
                      ledger_selected=True, ledger_sample_q=1., ledger_sample_correction=True,
                      masked_nll_mask=None, process_tau=.05, clip_epsilon=.2):
    """Clipped per-token PPO, optional existing TIS, group correction and NLL.

    Correction combines the two *clipped losses*, not their advantages. TIS is
    computed from the frozen old policy and sampling policy with the unchanged
    cap of two. The existing backend has KL coefficient zero; none is added.
    """
    from ..hf_native import _tensor, _binary
    from .sampling import corrected_loss
    if not isinstance(current_logprobs, torch.Tensor) or current_logprobs.ndim != 1 or not current_logprobs.is_floating_point():
        raise ValueError('current_logprobs must be floating [N]')
    shape, device = current_logprobs.shape, current_logprobs.device
    _tensor(current_logprobs, 'current_logprobs', shape)
    _tensor(old_logprobs, 'old_logprobs', shape, device)
    _tensor(advantages, 'advantages', shape, device)
    mask = _binary(_tensor(action_mask, 'action_mask', shape, device), 'action_mask')
    if type(loss_denominator) is not int or loss_denominator <= 0 or type(world_size) is not int or world_size <= 0:
        raise ValueError('positive integer denominator and world size required')
    if not 0 < ledger_sample_q <= 1 or not 0 < clip_epsilon < 1:
        raise ValueError('invalid sampling probability or PPO clipping')
    old = old_logprobs.detach().to(current_logprobs.dtype)
    difference = torch.zeros_like(old)
    if sampled_logprobs is not None:
        _tensor(sampled_logprobs, 'sampled_logprobs', shape, device)
        difference = old - sampled_logprobs.detach().to(old.dtype)
    importance = difference.clamp(max=math.log(2.)).exp()
    ratio = (current_logprobs - old).exp()
    clipped_ratio = ratio.clamp(1-clip_epsilon, 1+clip_epsilon)
    def numerator(adv):
        adv = adv.detach().to(current_logprobs.dtype)
        return -(torch.minimum(ratio * adv, clipped_ratio * adv) * importance).masked_fill(~mask, 0.).sum()
    full = numerator(advantages)
    local_nll = current_logprobs.sum() * 0.
    if masked_nll_mask is not None:
        nll_mask = _binary(_tensor(masked_nll_mask, 'masked_nll_mask', shape, device), 'masked_nll_mask')
        if bool((nll_mask & ~mask).any()):
            raise ValueError('NLL cannot include prompts, returns, or padding')
        local_nll = -current_logprobs.masked_fill(~nll_mask, 0.).sum()
        full = full + process_tau * local_nll
    if baseline_advantages is not None:
        _tensor(baseline_advantages, 'baseline_advantages', shape, device)
        base = numerator(baseline_advantages)
        total = corrected_loss(base, full, ledger_selected, ledger_sample_q, ledger_sample_correction)
    else:
        if ledger_sample_q != 1:
            raise ValueError('group sampling requires baseline advantages')
        total = full
    count = int(mask.sum())
    return {'loss': total * world_size / loss_denominator, 'loss_numerator': total,
            'auxiliary_loss_numerator': local_nll.detach(),
            'sampling_logprob_difference': difference[mask].detach(),
            'tis_weights': importance[mask].detach(), 'tis_clipped': (difference[mask] > math.log(2.)).detach(),
            'ppo_clip_count': ((ratio.detach() < 1-clip_epsilon) | (ratio.detach() > 1+clip_epsilon))[mask].sum(),
            'diagnostics': {'effective_action_tokens': count, 'loss_denominator': loss_denominator}}


def _config(value):
    if isinstance(value, CreditConfig):
        return value
    value = dict(value or {})
    preset = value.pop('preset', None)
    return CreditConfig.from_preset(preset, **value) if preset else CreditConfig(**value)


def trajectory_from_dict(value):
    if isinstance(value, Trajectory):
        return deepcopy(value)
    value = deepcopy(value)
    value['units'] = [Unit(**u) if isinstance(u, dict) else u for u in value['units']]
    if value.get('confident'):
        value['confident'] = {int(k) if str(k).isdigit() else k: v for k,v in value['confident'].items()}
    return Trajectory(**value)


def _groups(values):
    if isinstance(values, Group):
        return [deepcopy(values)]
    if all(isinstance(value, Group) for value in values):
        return deepcopy(list(values))
    grouped = defaultdict(list)
    for value in values:
        trajectory = trajectory_from_dict(value)
        grouped[trajectory.qid].append(trajectory)
    return [Group(qid, trajectories) for qid, trajectories in grouped.items()]


def _build_ledgers(group, provider, cfg):
    build_for_credit = getattr(provider, 'build_for_credit', None)
    results = build_for_credit(group, config=cfg) if build_for_credit is not None else provider.build(group)
    if len(results) != len(group):
        raise ValueError('provider must return exactly one ledger per trajectory')
    for tr, result in zip(group, results, strict=True):
        tr.records, tr.derived, tr.conds, tr.confident = deepcopy(tuple(result))
        tr.records_b = deepcopy(getattr(result, 'records_b', None))
        tr.derived_b = deepcopy(getattr(result, 'derived_b', None))


@torch.no_grad()
def prepare_credit_native_records(native_trajectories, groups, provider=None, config=None, *,
                                  max_generated_tokens, training_step=0, sampling_seed=0, normalization='fixed'):
    """Provider -> group credit -> exact native HF actions, with no model calls."""
    from ..hf_native import prepare_native_records
    from .group import credit_for_group, ledger_complete
    from .allocate import length_tertiles
    from .metrics import collect_credit_metrics
    from .process_sup import eligible_group, select_masked_nll_units, zero_sum_for_trajectory
    from .sampling import select_group
    cfg, groups = _config(config), _groups(groups)
    all_trajectories = [tr for group in groups for tr in group]
    if not all_trajectories:
        raise ValueError('credit batch must contain at least one trajectory')
    if any(sum(u.generated_tokens for u in tr.units) > max_generated_tokens for tr in all_trajectories):
        raise ValueError('trajectory exceeds the configured generated-token limit')
    width = max(len(tr.response_mask) for tr in all_trajectories)
    length_cutpoints = length_tertiles([u.generated_tokens for tr in all_trajectories for u in tr.units if u.unit_id != 'F'])
    full_rows, base_rows, nll_rows, input_rows, credit_rows, selected_by_id = [], [], [], [], [], {}
    process_units = 0
    for group in groups:
        selected = select_group(group.qid, training_step, cfg.ledger_sample_q, sampling_seed)
        # Baseline uses precisely the same outcome and native tokens.
        baseline_config = CreditConfig.from_preset('A', beta_n=cfg.beta_n, g=cfg.g, eta_p=cfg.eta_p,
                                                  w_max=cfg.w_max)
        baseline = credit_for_group([dict(tr.to_credit_dict(cfg.c_ref), records=[], derived=[])
                                     for tr in group], baseline_config)
        if selected and cfg.requires_ledger and provider is not None:
            _build_ledgers(group, provider, cfg)
        fallback = selected and cfg.requires_ledger and not all(ledger_complete(tr.to_credit_dict()) for tr in group)
        for tr in group:
            if not fallback and tr.records and len(tr.records) == len(tr.derived):
                tr.records, tr.derived, tr.conds = validate_ledger(tr.records, tr.derived, tr.conds)
                if cfg.gate_two_pass and (tr.records_b is not None or tr.derived_b is not None):
                    if tr.records_b is None or tr.derived_b is None or len(tr.records_b) != len(tr.records):
                        raise ValueError('both passes must cover the same ledger units')
                    tr.records_b, tr.derived_b, _ = validate_ledger(tr.records_b, tr.derived_b, tr.conds)
        rows = [tr.to_credit_dict(cfg.c_ref) for tr in group]
        if not cfg.requires_ledger:
            rows = [dict(deepcopy(row), records=[], derived=[], records_b=None, derived_b=None) for row in rows]
        full = credit_for_group(rows, cfg, confident=[tr.confident for tr in group], training_step=training_step,
                                length_cutpoints=length_cutpoints) if selected and not fallback else deepcopy(baseline)
        if fallback:
            for credit in full:
                credit['log'].update(mode='ledger_fallback', ledger_fallback=True)
        chosen = select_masked_nll_units(group, full, cfg) if selected and not fallback else [set() for _ in group]
        if selected and not fallback and cfg.process_sup == 'zero_sum' and eligible_group(group, full):
            for credit in full:
                signals, log = zero_sum_for_trajectory(credit, cfg)
                credit['A'] = {u: value + signals[u] for u,value in credit['A'].items()}
                credit['log']['zero_sum'] = log
        for tr, credit, base, units in zip(group, full, baseline, chosen):
            dense = write_token_advantages(tr, credit['A'])
            base_dense = write_token_advantages(tr, base['A'])
            nll_dense = write_token_advantages(tr, {u.unit_id: float(u.unit_id in units) for u in tr.units})
            padding = (0, width-len(tr.response_mask))
            full_rows.append(torch.nn.functional.pad(dense['advantages'], padding))
            base_rows.append(torch.nn.functional.pad(base_dense['advantages'], padding))
            nll_rows.append(torch.nn.functional.pad(nll_dense['advantages'].bool(), padding))
            input_rows.append({'traj_id': tr.traj_id, 'task_id': tr.qid, 'response_mask': tr.response_mask})
            credit_rows.append(credit)
            selected_by_id[tr.traj_id] = selected
            process_units += len(units)
    score = {'process_inputs': input_rows, 'advantages': torch.stack(full_rows),
             'effective_response_mask': torch.tensor([row['response_mask'] + [0]*(width-len(row['response_mask']))
                                                       for row in input_rows], dtype=torch.bool),
             'valid_rows': torch.ones(len(input_rows), dtype=torch.bool)}
    prepared = prepare_native_records(native_trajectories, score)
    index_by_id = {row['traj_id']: i for i,row in enumerate(input_rows)}
    for record in prepared['records']:
        index = index_by_id[record['trajectory_id']]
        positions = torch.tensor(record['action_offsets'], dtype=torch.long) + record['axis_start']
        record.update(baseline_advantages=base_rows[index][positions].clone(), masked_nll_mask=nll_rows[index][positions].clone(),
                      ledger_selected=selected_by_id[record['trajectory_id']])
    prepared.update(credit_mode=True, credit_config=cfg.to_params(), credits=credit_rows,
                    loss_denominator=fixed_loss_denominator(len(all_trajectories), max_generated_tokens,
                        normalization=normalization, token_count=prepared['global_token_count']),
                    loss_normalization=normalization, training_step=training_step)
    prepared['metrics'].update(unmatched_units=sum(len(tr.to_credit_dict()['unmatched_units']) for tr in all_trajectories),
                               process_selected_units=process_units, process_selected_tokens=sum(int(row.sum()) for row in nll_rows),
                               sampled_groups=sum(select_group(g.qid, training_step, cfg.ledger_sample_q, sampling_seed) for g in groups),
                               group_count=len(groups), judge_calls=0)
    prepared['credit_metrics'] = collect_credit_metrics(all_trajectories, credit_rows, groups=groups,
        modules={'process_selected_units': process_units, 'process_selected_tokens': prepared['metrics']['process_selected_tokens'],
                 'ledger_sample_fraction': prepared['metrics']['sampled_groups'] / len(groups),
                 'ledger_correction_weight': 1 / cfg.ledger_sample_q if cfg.ledger_sample_correction else 1.})
    prepared['metrics'].update(ledger_fallback_groups=prepared['credit_metrics']['groups']['ledger_fallback_count'],
                               ledger_fallback_trajectories=prepared['credit_metrics']['credit']['ledger_fallback_trajectories'],
                               no_receiver=prepared['credit_metrics']['credit']['no_receiver_count'])
    return prepared


def make_credit_score_payload(native_batch_path, trajectories, config=None, *, max_generated_tokens,
                              provider=None, training_step=0, sampling_seed=0, normalization='fixed'):
    """Build the existing --scores payload; torch.save the result for the worker.

    A provider may materialize ledgers here on the program side; the worker then
    needs no provider configuration or Judge credentials. Baseline/skipped groups
    never request ledgers. Native IDs and masks are verified again at load time.
    """
    import json
    cfg, groups = _config(config), _groups(trajectories)
    for group in groups:
        from .sampling import select_group
        if provider is not None and cfg.requires_ledger and select_group(group.qid, training_step, cfg.ledger_sample_q, sampling_seed):
            _build_ledgers(group, provider, cfg)
    raw = Path(native_batch_path).read_bytes()
    batch = json.loads(raw)
    payload = {'input_binding': {'native_batch_sha256': hashlib.sha256(raw).hexdigest(),
                                'policy_snapshot_sha256': batch.get('policy_snapshot_sha256')},
               'credit_config': cfg.to_params(), 'credit_trajectories': [asdict(tr) for group in groups for tr in group],
               'max_generated_tokens': max_generated_tokens, 'training_step': training_step,
               'sampling_seed': sampling_seed, 'loss_normalization': normalization}
    # Validate the complete route before exposing a serializable score payload.
    prepare_credit_native_records(batch['trajectories'], payload['credit_trajectories'], config=cfg,
                                  max_generated_tokens=max_generated_tokens, training_step=training_step,
                                  sampling_seed=sampling_seed, normalization=normalization)
    return payload
