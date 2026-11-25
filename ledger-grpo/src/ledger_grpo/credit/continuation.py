"""Continuation planning only. Real sampling and main-loss merging are deferred."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ContinuationPlan:
    rollout_index: int
    unit_id: object
    responsibility: float
    new_branches: int = 2
    include_original_suffix: bool = True


@dataclass(frozen=True)
class EqualBudgetControl:
    sampling_seed: int
    max_new_tokens: int
    max_tool_calls: int
    control_mode: str = 'new_rollouts'


def choose_branch(group, credits, *, new_branches=2):
    trajectories = list(group.trajectories if hasattr(group, 'trajectories') else group)
    if len(trajectories) != len(credits) or new_branches < 1:
        raise ValueError('invalid continuation group or branch count')
    candidates = []
    for index, (trajectory, credit) in enumerate(zip(trajectories, credits)):
        outcome = trajectory.get('outcome', {}) if isinstance(trajectory, dict) else trajectory.outcome
        adopted = any(tag.startswith('采纳') and size > 0
                      for events in credit['P'].values() for size, tag in events)
        if outcome.get('Y') or not adopted:
            continue
        for unit in credit['role']:
            eo = sum(size for size, tag in credit['R'].get(unit, []) if not tag.startswith('浪费'))
            if eo > 0:
                candidates.append(ContinuationPlan(index, unit, eo, new_branches))
    return max(candidates, key=lambda p: p.responsibility) if candidates else None


def branch_advantages(outcome_rewards):
    values = list(outcome_rewards)
    if len(values) < 2:
        return [0. for _ in values]
    total = sum(values)
    return [value - (total - value) / (len(values) - 1) for value in values]


def sample_continuations(plan, **kwargs):
    # TODO: define prefix restoration and same-policy sampling after the main comparison.
    raise NotImplementedError('continuation sampling and main-loss integration are not authorized yet')
