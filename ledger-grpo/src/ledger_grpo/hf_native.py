"""Ledger credit on the stability engine's exact native HF action records.

No model execution, tokenization, distributed initialization, or optimizer is
performed here. Ledger coordinates concatenate the completion axes of maximal
exact native spans; observed-context gaps stay present with mask zero. A call's
turn covers only its original completion, including every thinking token.
"""
from copy import deepcopy
import math

import torch


def native_turn_layout(trajectory):
    """Return response_mask, call-to-turn intervals, and native merged spans.

    This uses the same exact-prefix rule as stability/native_spans.py. Each
    span retains its own original prompt; a nonmatching prefix starts another
    span instead of reconstructing or changing the causal conditioning.
    call_index is zero-based; default turn_id is call_index+1. The caller may
    relabel turn IDs to its original round IDs without changing coordinates.
    """
    if not isinstance(trajectory, dict) or not isinstance(trajectory.get('segments'), list):
        raise ValueError('native trajectory requires a segments list')
    spans, turns = [], []
    for call_index, call in enumerate(trajectory['segments']):
        if not isinstance(call, dict):
            raise ValueError('native call must be an object')
        prompt, actions, probs = (call.get(name) for name in ('prompt_ids', 'completion_ids', 'vllm_logprobs'))
        for tokens in (prompt, actions):
            if not isinstance(tokens, list) or not tokens or any(type(token) is not int or token < 0 for token in tokens):
                raise ValueError('native prompt and completion require nonempty integer token lists')
        if (not isinstance(probs, list) or len(probs) != len(actions)
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in probs)):
            raise ValueError('native probabilities must cover every completion token and be finite')
        prefix = spans[-1]['prompt_ids'] + spans[-1]['completion_ids'] if spans else None
        if prefix is not None and prompt[:len(prefix)] == prefix:
            span = spans[-1]
            offset = len(prompt) - len(span['prompt_ids'])
            span['completion_ids'].extend(prompt[len(prefix):])
            span['completion_ids'].extend(actions)
            span['vllm_logprobs'].extend(probs)
            span['action_offsets'].extend(range(offset, offset + len(actions)))
        else:
            offset = 0
            spans.append({'prompt_ids': list(prompt), 'completion_ids': list(actions),
                          'vllm_logprobs': list(probs), 'action_offsets': list(range(len(actions)))})
        turns.append({'call_index': call_index, 'turn_id': call_index + 1, 'span_index': len(spans) - 1,
                      'token_start': offset, 'token_end': offset + len(actions)})
    mask = []
    for span in spans:
        span['axis_start'] = len(mask)
        part = [0] * len(span['completion_ids'])
        for offset in span['action_offsets']:
            part[offset] = 1
        mask.extend(part)
        span['axis_end'] = len(mask)
    for turn in turns:
        base = spans[turn['span_index']]['axis_start']
        turn['token_start'] += base
        turn['token_end'] += base
    return {'response_mask': mask, 'turns': turns, 'spans': spans}


def _tensor(value, name, shape, device=None):
    if (not isinstance(value, torch.Tensor) or tuple(value.shape) != tuple(shape)
            or (device is not None and value.device != device) or value.is_complex()
            or not bool(torch.isfinite(value).all())):
        raise ValueError(f'{name} must be a finite real tensor with the expected shape and device')
    return value


def _binary(value, name):
    if not bool(((value == 0) | (value == 1)).all()):
        raise ValueError(f'{name} must be binary')
    return value.bool()


@torch.no_grad()
def prepare_native_records(native_trajectories, score_result):
    """Align score_batch output by traj_id, yielding exact native action credit.

    Scoring must already cover complete groups and the whole batch. Valid rows
    retain every native policy token; excluded rows contribute no training
    records or denominator. The caller must skip optimizer/Adam/step counters
    when skip_update is true, and pad rank loops with zero action masks only.

    Identity/mask checks cannot authenticate text contents: the runner must
    additionally bind native-batch, adapter, and score-file digests in its run
    manifest. Never infer causal token history from the report's plain text.
    """
    if not isinstance(native_trajectories, (list, tuple)) or not native_trajectories:
        raise ValueError('native_trajectories must be a nonempty batch')
    if not isinstance(score_result, dict):
        raise ValueError('score_result must be a score_batch dictionary')
    inputs = score_result.get('process_inputs')
    size = len(native_trajectories)
    if not isinstance(inputs, list) or len(inputs) != size:
        raise ValueError('score_result must contain one process_inputs row per native trajectory')
    advantages = score_result.get('advantages')
    if not isinstance(advantages, torch.Tensor) or advantages.ndim != 2 or advantages.shape[0] != size or not advantages.is_floating_point():
        raise ValueError('advantages must be floating [B,T]')
    _tensor(advantages, 'advantages', advantages.shape)
    width, device = advantages.shape[1], advantages.device
    effective = _binary(_tensor(score_result.get('effective_response_mask'), 'effective_response_mask', advantages.shape, device),
                        'effective_response_mask')
    valid = _binary(_tensor(score_result.get('valid_rows'), 'valid_rows', (size,), device), 'valid_rows')
    if bool((advantages[~effective] != 0).any()):
        raise ValueError('tool, padding, or excluded positions contain nonzero advantages')
    by_id = {}
    for index, row in enumerate(inputs):
        if not isinstance(row, dict) or not isinstance(row.get('traj_id'), str) or not row['traj_id'] or row['traj_id'] in by_id:
            raise ValueError('process_inputs requires unique nonempty traj_id values')
        by_id[row['traj_id']] = index
    ids = [row.get('id') if isinstance(row, dict) else None for row in native_trajectories]
    if any(not isinstance(tid, str) or not tid for tid in ids) or len(set(ids)) != size or set(ids) != set(by_id):
        raise ValueError('native trajectory IDs must uniquely match score_result')
    records, trajectory_actions = [], {}
    raw_tokens = 0
    for trajectory in native_trajectories:
        tid = trajectory['id']
        index = by_id[tid]
        row = inputs[index]
        if not isinstance(trajectory.get('query_id'), str) or trajectory['query_id'] != row.get('task_id'):
            raise ValueError('native query_id must equal the scored task_id')
        layout = native_turn_layout(trajectory)
        raw_mask = layout['response_mask']
        supplied = row.get('response_mask')
        if (not isinstance(supplied, list) or any(type(value) not in (int, bool) or value not in (0, 1) for value in supplied)
                or supplied != raw_mask or len(raw_mask) > width):
            raise ValueError('scored response_mask does not match the exact native span layout')
        expected = torch.tensor(raw_mask + [0] * (width - len(raw_mask)), dtype=torch.bool, device=device)
        if not torch.equal(effective[index], expected & valid[index]):
            raise ValueError('effective mask must retain or exclude the entire native trajectory')
        count = sum(raw_mask)
        if bool(valid[index]) and count == 0:
            raise ValueError('an empty native trajectory cannot be valid for training')
        raw_tokens += count
        trajectory_actions[tid] = {'advantages': advantages[index, expected].clone(),
                                   'mask': effective[index, expected].clone(), 'valid': bool(valid[index])}
        if not bool(valid[index]):
            continue
        for span in layout['spans']:
            positions = torch.tensor(span['action_offsets'], dtype=torch.long, device=device) + span['axis_start']
            records.append({**deepcopy(span), 'trajectory_id': tid, 'query_id': trajectory['query_id'],
                            'action_count': count, 'action_advantages': advantages[index, positions].clone(),
                            'action_mask': effective[index, positions].clone()})
    denominator = int(effective.sum())
    if sum(record['action_mask'].sum().item() for record in records) != denominator:
        raise ValueError('native record mapping lost or duplicated effective action tokens')
    return {'records': records, 'trajectory_actions': trajectory_actions,
            'global_token_count': denominator, 'skip_update': denominator == 0,
            'metrics': {'trajectory_count': size, 'valid_trajectory_count': int(valid.sum()),
                        'dropped_trajectory_count': size - int(valid.sum()),
                        'native_action_tokens': raw_tokens, 'effective_action_tokens': denominator,
                        'native_span_count': len(records)}}


def single_step_token_loss(current_logprobs, sampled_logprobs, advantages, action_mask,
                           *, global_token_count, world_size, loss_denominator=None, epsilon=.2):
    """One-batch/one-step PPO objective with the existing detached TIS cap 2.

    The old HF policy is this same forward detached. This is valid only while
    the full batch accumulates gradients before ONE optimizer.step(), with
    dropout disabled and a frozen incoming policy. Multiple epochs/steps need
    separately frozen old probabilities and are outside this interface.

    FSDP averages rank gradients, so loss = numerator * world/global_tokens.
    All real and padded records use the same global denominator; masked dummy
    forwards may synchronize ranks but cannot enter that count or diagnostics.
    PPO ratio is identically one here and is NOT a policy stability metric.
    Returned diagnostics instead compare HF pre-update and actual sampled q.
    """
    if not isinstance(current_logprobs, torch.Tensor) or current_logprobs.ndim != 1 or not current_logprobs.is_floating_point():
        raise ValueError('current_logprobs must be floating [N]')
    shape, device = current_logprobs.shape, current_logprobs.device
    _tensor(current_logprobs, 'current_logprobs', shape)
    _tensor(sampled_logprobs, 'sampled_logprobs', shape, device)
    _tensor(advantages, 'advantages', shape, device)
    mask = _binary(_tensor(action_mask, 'action_mask', shape, device), 'action_mask')
    if type(global_token_count) is not int or global_token_count <= 0 or int(mask.sum()) > global_token_count:
        raise ValueError('global_token_count must be positive and cover every local effective token')
    if type(world_size) is not int or world_size <= 0:
        raise ValueError('world_size must be a positive integer')
    denominator = global_token_count if loss_denominator is None else loss_denominator
    if type(denominator) is not int or denominator <= 0:
        raise ValueError('loss_denominator must be a positive integer')
    if type(epsilon) not in (int, float) or not math.isfinite(epsilon) or not 0 <= epsilon < 1:
        raise ValueError('epsilon must be in [0,1)')
    old = current_logprobs.detach()
    difference = old - sampled_logprobs.detach().to(current_logprobs.dtype)
    if not bool(torch.isfinite(difference).all()):
        raise ValueError('HF/sample logprob differences must be finite')
    importance = difference.clamp(max=math.log(2.)).exp()
    clipped = difference > math.log(2.)
    advantage = advantages.detach().to(current_logprobs.dtype)
    ratio = (current_logprobs - old).exp()
    objective = torch.minimum(ratio * advantage, ratio.clamp(1 - epsilon, 1 + epsilon) * advantage) * importance
    numerator = -objective.masked_fill(~mask, 0).sum()
    count = int(mask.sum())
    observed = difference[mask]
    diagnostic = {'effective_action_tokens': count,
                  'old_logprob_source': 'same_forward_detached', 'ppo_ratio_is_stability_metric': False,
                  'sampled_logprob_abs_error_mean': float(observed.abs().double().mean()) if count else None,
                  'sampled_logprob_abs_error_max': float(observed.abs().max()) if count else None,
                  'sampled_logprob_difference_mean': float(observed.double().mean()) if count else None,
                  'tis_cap_fraction': float(clipped[mask].double().mean()) if count else None,
                  'tis_weight_mean': float(importance[mask].double().mean()) if count else None}
    return {'loss': numerator * world_size / denominator, 'loss_numerator': numerator,
            'global_token_count': global_token_count, 'world_scale': world_size / denominator,
            'diagnostics': diagnostic, 'sampling_logprob_difference': observed.detach(),
            'tis_weights': importance[mask].detach(), 'tis_clipped': clipped[mask].detach()}
