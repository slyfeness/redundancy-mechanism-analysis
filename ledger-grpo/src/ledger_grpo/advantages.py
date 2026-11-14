"""Conditional component normalization and policy-token span credit.

Implements the uploaded design's equations (lines 238--258), with explicit
edge conventions: sample standard deviations; zero signal for singletons;
whole-group QA fallback; whole-group exclusion for invalid training rows;
and R then D adjustments with one lower-bound budget. Overlap resolution and
phase-specific label selection happen upstream, before these tensors arrive.

Clipping centered z-scores does NOT preserve a zero mean. We intentionally
do not recenter after clipping, nor during batch scaling, to retain the
specified formula. Correct trajectories in all-correct groups can receive
negative relative advantages. beta limits NEW downward D adjustment; it
does not repair an already negative trajectory advantage.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import torch


@dataclass
class AdvantageConfig:
    efficiency_weight: float = 0.15
    grounding_weight: float = 0.1
    eta: float = 1.0
    deviation_weights: dict[str, float] = field(
        default_factory=lambda: {"D1": .1, "D2": .15, "D3": .1, "D4": .15}
    )
    delta_max: float = 0.3
    beta: float = 0.0
    epsilon: float = 1e-6
    batch_scale: bool = True
    phase: str = "v1"
    process_enabled: bool = False
    sign_anchor: bool = True

    def validate(self) -> None:
        for name in ("efficiency_weight", "grounding_weight", "eta", "delta_max", "beta", "epsilon"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.epsilon == 0 or self.eta > 1:
            raise ValueError("epsilon must be positive and eta must be in [0, 1]")
        if not isinstance(self.phase, str) or not self.phase:
            raise ValueError("phase must be a nonempty string")
        for name in ("batch_scale", "process_enabled", "sign_anchor"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if not isinstance(self.deviation_weights, dict) or set(self.deviation_weights) != {"D1", "D2", "D3", "D4"}:
            raise ValueError("deviation_weights must specify D1, D2, D3, and D4")
        for value in self.deviation_weights.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("deviation weights must be finite and nonnegative")


def _tensor(value: torch.Tensor, name: str, shape: tuple[int, ...], device: torch.device) -> None:
    if not isinstance(value, torch.Tensor) or tuple(value.shape) != shape or value.device != device:
        raise ValueError(f"{name} must have shape {shape} on {device}")
    if value.is_complex() or not bool(torch.isfinite(value).all()):
        raise ValueError(f"{name} must be real and finite")


def _binary(value: torch.Tensor, name: str) -> torch.Tensor:
    if not bool(((value == 0) | (value == 1)).all()):
        raise ValueError(f"{name} must be binary")
    return value.bool()


def _std(values: torch.Tensor) -> torch.Tensor:
    return values.std(correction=1) if values.numel() >= 2 else values.new_zeros(())


@torch.no_grad()
def compute_advantages(
    outcomes: torch.Tensor,
    group_ids: Sequence[str],
    response_mask: torch.Tensor,
    redundancy: torch.Tensor,
    grounding: torch.Tensor | None,
    deviations: torch.Tensor,
    *,
    process_valid: torch.Tensor | None = None,
    training_valid: torch.Tensor | None = None,
    config: AdvantageConfig | None = None,
) -> dict[str, Any]:
    """Compute advantages on an entire rollout batch before microbatching.

    Scalars are [B], token fields [B,T]. response_mask selects only native
    policy-generated tokens (never tool/prompt/padding tokens). redundancy is
    max-overlap confidence in [0,1]; deviations already contain lambda*u*c.
    This function must see complete same-task groups and the complete batch
    for its one-scalar batch std; do not call independently on rank shards.

    training_valid=False or an empty policy-token row excludes the whole task
    group. All-wrong groups are also excluded, before deviation application.
    process_valid=False disables all process signals for that task group but
    preserves outcome credit. Callers MUST remove valid_rows=False from the
    policy loss/KL denominator, and skip the update if none remain.

    sign_anchor validates w_e+w_g < min(1/sqrt(G), actual positive outcome
    advantage) for each process-enabled mixed group. Thus default G=8 passes
    and default G=16 fails. This protects mixed-group trajectory signs before
    span offsets, not all-correct groups or beta>0 local changes. grounding=None
    means that the grounding component is unavailable, not a perfect score.
    """
    cfg = config or AdvantageConfig()
    cfg.validate()
    if not isinstance(outcomes, torch.Tensor) or outcomes.ndim != 1:
        raise ValueError("outcomes must be a [B] tensor")
    b = outcomes.shape[0]
    device = outcomes.device
    _tensor(outcomes, "outcomes", (b,), device)
    success = _binary(outcomes, "outcomes")
    if len(group_ids) != b or any(not isinstance(g, str) or not g for g in group_ids):
        raise ValueError("group_ids must contain one nonempty string per trajectory")
    if not isinstance(response_mask, torch.Tensor) or response_mask.ndim != 2 or response_mask.shape[0] != b:
        raise ValueError("response_mask must have shape [B,T]")
    shape = tuple(response_mask.shape)
    _tensor(response_mask, "response_mask", shape, device)
    mask = _binary(response_mask, "response_mask")
    for name, value in (("redundancy", redundancy), ("deviations", deviations)):
        _tensor(value, name, shape, device)
        if bool((value < 0).any()):
            raise ValueError(f"{name} must be nonnegative")
    if bool((redundancy > 1).any()):
        raise ValueError("redundancy must be in [0,1]; resolve overlaps upstream")
    if grounding is not None:
        _tensor(grounding, "grounding", (b,), device)
        if bool(((grounding < 0) | (grounding > 1)).any()):
            raise ValueError("grounding must be in [0,1]")

    flags = []
    for name, value in (("process_valid", process_valid), ("training_valid", training_valid)):
        if value is None:
            flags.append(torch.ones(b, dtype=torch.bool, device=device))
        else:
            _tensor(value, name, (b,), device)
            flags.append(_binary(value, name))
    qa_valid, train_valid = flags
    dtype = torch.float64 if outcomes.dtype == torch.float64 else torch.float32
    y = success.to(dtype)
    red = redundancy.to(dtype)
    dev = deviations.to(dtype)
    counts = mask.sum(-1)
    rho = (red * mask).sum(-1) / counts.clamp_min(1)
    valid_rows = torch.zeros(b, dtype=torch.bool, device=device)
    process_rows = torch.zeros_like(valid_rows)
    acc = torch.zeros(b, dtype=dtype, device=device)
    eff = torch.zeros_like(acc)
    gnd = torch.zeros_like(acc)
    groups: dict[str, list[int]] = defaultdict(list)
    for i, group in enumerate(group_ids):
        groups[group].append(i)
    dropped_wrong: list[str] = []
    dropped_invalid: list[str] = []
    qa_disabled: list[str] = []
    for group, positions in groups.items():
        idx = torch.tensor(positions, dtype=torch.long, device=device)
        if not bool((train_valid[idx] & (counts[idx] > 0)).all()):
            dropped_invalid.append(group)
            continue
        correct = idx[success[idx]]
        if correct.numel() == 0:
            dropped_wrong.append(group)
            continue
        valid_rows[idx] = True
        scores = y[idx]
        acc[idx] = (scores - scores.mean()) / (_std(scores) + cfg.epsilon)
        if not cfg.process_enabled:
            continue
        if not bool(qa_valid[idx].all()):
            qa_disabled.append(group)
            continue
        if cfg.sign_anchor and correct.numel() < idx.numel():
            bound = min(1.0 / math.sqrt(idx.numel()), float(acc[correct].min()))
            if cfg.efficiency_weight + cfg.grounding_weight >= bound:
                raise ValueError(
                    f"sign_anchor requires efficiency_weight + grounding_weight < {bound:.9g} "
                    f"for mixed group {group!r} of size {idx.numel()}"
                )
        process_rows[idx] = True
        if correct.numel() < 2:
            continue
        efficiency_scores = 1 - rho[correct]
        eff[correct] = ((efficiency_scores - efficiency_scores.mean()) / (_std(efficiency_scores) + cfg.epsilon)).clamp(-1, 1)
        if grounding is not None:
            grounding_scores = grounding[correct].to(dtype)
            gnd[correct] = ((grounding_scores - grounding_scores.mean()) / (_std(grounding_scores) + cfg.epsilon)).clamp(-1, 1)

    traj = acc + cfg.efficiency_weight * eff + cfg.grounding_weight * gnd
    raw_mean = float(traj[valid_rows].mean()) if bool(valid_rows.any()) else 0.0
    batch_std = _std(traj[valid_rows])
    # A degenerate batch must not turn tiny constants into enormous advantages.
    scale = float(batch_std) + cfg.epsilon if cfg.batch_scale and float(batch_std) > cfg.epsilon else 1.0
    base = traj / scale
    policy_mask = mask & valid_rows[:, None]
    advantages = base[:, None].expand(shape).clone()
    if cfg.process_enabled:
        eligible = process_rows[:, None] & mask
        apply_r = eligible & success[:, None] & (advantages > 0)
        advantages = torch.where(apply_r, advantages * (1 - cfg.eta * red), advantages)
        # Use the already-masked value for a shared lower-bound budget: overlapping
        # R and D cannot consume base's positive budget twice and cross -beta.
        correct_budget = (advantages + cfg.beta).clamp_min(0)
        delta = torch.where(success[:, None], torch.minimum(dev, correct_budget), dev.clamp_max(cfg.delta_max))
        advantages = advantages - torch.where(eligible, delta, torch.zeros_like(delta))
    advantages = advantages.masked_fill(~policy_mask, 0)
    return {
        "advantages": advantages,
        "returns": advantages.clone(),
        "accuracy_advantage": acc,
        "efficiency_advantage": eff,
        "grounding_advantage": gnd,
        "trajectory_advantage": base,
        "valid_rows": valid_rows,
        "metrics": {
            "phase": cfg.phase,
            "process_enabled": cfg.process_enabled,
            "grounding_available": grounding is not None,
            "batch_std": float(batch_std),
            "batch_scale": scale,
            "trajectory_mean_before_scale": raw_mean,
            "conditional_efficiency_mean": float(eff[valid_rows].mean()) if bool(valid_rows.any()) else 0.0,
            "conditional_grounding_mean": float(gnd[valid_rows].mean()) if bool(valid_rows.any()) else 0.0,
            "redundant_fraction": rho.tolist(),
            "valid_row_count": int(valid_rows.sum()),
            "process_row_count": int(process_rows.sum()),
            "all_wrong_groups": dropped_wrong,
            "invalid_training_groups": dropped_invalid,
            "qa_disabled_groups": qa_disabled,
        },
    }


@torch.no_grad()
def apply_control(
    advantages: torch.Tensor,
    base: torch.Tensor,
    response_mask: torch.Tensor,
    mode: str = "targeted",
    seed: int = 0,
) -> torch.Tensor:
    """Ablate local adjustments, excluding non-policy positions.

    base is [B] trajectory advantage or [B,T] broadcast base. targeted keeps
    the adjustment; uniform spreads its per-row sum across policy tokens;
    shuffle permutes token-level deltas within each row. This shuffle preserves
    their multiset and total, NOT contiguous spans or turn boundaries, and must
    not be reported as the full-span relocation control. trajectory removes
    local adjustment, so only that mode intentionally changes its total.
    Pass an effective response mask with excluded training rows already zeroed.
    """
    if not isinstance(advantages, torch.Tensor) or advantages.ndim != 2 or not advantages.is_floating_point():
        raise ValueError("advantages must be a floating [B,T] tensor")
    shape, device = tuple(advantages.shape), advantages.device
    _tensor(advantages, "advantages", shape, device)
    _tensor(response_mask, "response_mask", shape, device)
    mask = _binary(response_mask, "response_mask")
    if not isinstance(base, torch.Tensor) or tuple(base.shape) not in ((shape[0],), shape):
        raise ValueError("base must have shape [B] or [B,T]")
    _tensor(base, "base", tuple(base.shape), device)
    baseline = base[:, None].expand(shape) if base.ndim == 1 else base
    baseline = baseline.to(advantages.dtype).masked_fill(~mask, 0)
    delta = (advantages - baseline).masked_fill(~mask, 0)
    if mode == "targeted":
        return advantages.masked_fill(~mask, 0).clone()
    if mode == "trajectory":
        return baseline.clone()
    if mode == "uniform":
        return (baseline + delta.sum(-1, keepdim=True) / mask.sum(-1, keepdim=True).clamp_min(1)).masked_fill(~mask, 0)
    if mode != "shuffle":
        raise ValueError("mode must be targeted, uniform, shuffle, or trajectory")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    shuffled = torch.zeros_like(delta)
    for i in range(shape[0]):
        positions = mask[i].nonzero(as_tuple=True)[0]
        permutation = torch.randperm(positions.numel(), generator=generator).to(device)
        shuffled[i, positions] = delta[i, positions[permutation]]
    return baseline + shuffled
