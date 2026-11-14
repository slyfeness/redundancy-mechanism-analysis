"""Attach validated reports to native rollout tensors; never infer token offsets.

This module does not import verl or compute advantages. Call it on the complete
rollout batch before ``apply_to_batch``, using the same AdvantageConfig for both.
Container replacement is atomic: failed validation leaves data.batch unchanged.
"""

from collections.abc import Mapping

import torch

from .advantages import AdvantageConfig
from .pipeline import build_process_inputs


def _column(metadata, name, size):
    value = metadata.get(name)
    if value is None or isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f"non_tensor_batch.{name} must contain one ID per row")
    try:
        values = list(value)
    except TypeError as exc:
        raise ValueError(f"non_tensor_batch.{name} must be an ID sequence") from exc
    if len(values) != size or any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"non_tensor_batch.{name} must contain {size} nonempty string IDs")
    return values


def _by_identity(items, name, required_ids):
    if not isinstance(items, (list, tuple)) or len(items) != len(required_ids):
        raise ValueError(f"{name} must contain exactly one record per native batch row")
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("traj_id"), str) or not item["traj_id"]:
            raise ValueError(f"each {name} record requires a nonempty traj_id")
        tid = item["traj_id"]
        if tid in result:
            raise ValueError(f"duplicate {name} traj_id: {tid!r}")
        result[tid] = item
    if set(result) != set(required_ids):
        raise ValueError(f"{name} traj_id set does not match the native batch")
    return result


@torch.no_grad()
def attach_reports(data, traces, reports, *, config=None, enable_artifact_d4=False):
    """Atomically attach six scoring tensors, aligned by trajectory identity.

    ``data`` has a dict or TensorDict ``batch`` and a mapping ``non_tensor_batch``.
    Metadata requires unique ``traj_id`` and ``uid`` or ``task_id`` columns. Every
    supplied group column must equal each trace's task_id. Trace/report order may
    differ from native row order, but their identity sets must match exactly.

    A trace's normalized response_mask must equal the native row after *right*
    zero padding, including tool positions. Overwide traces, left padding and
    missing tool masks are rejected instead of being guessed from a tokenizer.
    ``config`` is an AdvantageConfig or None; configured D4 weights are preserved.
    """
    settings = config if config is not None else AdvantageConfig()
    if not isinstance(settings, AdvantageConfig):
        raise ValueError("config must be an AdvantageConfig or None")
    settings.validate()
    if type(enable_artifact_d4) is not bool:
        raise ValueError("enable_artifact_d4 must be boolean")
    batch = getattr(data, "batch", None)
    metadata = getattr(data, "non_tensor_batch", None)
    if batch is None or not hasattr(batch, "get") or not isinstance(metadata, Mapping):
        raise ValueError("data requires a batch container and non_tensor_batch mapping")
    mask = batch.get("response_mask")
    if not isinstance(mask, torch.Tensor) or mask.ndim != 2 or not all(mask.shape):
        raise ValueError("native response_mask must be a nonempty [B,T] tensor")
    if mask.is_complex() or not bool(torch.isfinite(mask).all()) or not bool(((mask == 0) | (mask == 1)).all()):
        raise ValueError("native response_mask must be real, finite and binary")
    saved_mask = batch.get("ledger_response_mask")
    if saved_mask is not None and (
        not isinstance(saved_mask, torch.Tensor)
        or saved_mask.device != mask.device
        or not torch.equal(saved_mask, mask)
    ):
        raise ValueError("ledger_response_mask differs from the native response_mask; attach before loss masking")
    size, width = mask.shape
    ids = _column(metadata, "traj_id", size)
    if len(set(ids)) != size:
        raise ValueError("duplicate native traj_id values")
    group_keys = [name for name in ("uid", "task_id") if name in metadata]
    if not group_keys:
        raise ValueError("non_tensor_batch must contain uid or task_id group IDs")
    groups = {name: _column(metadata, name, size) for name in group_keys}
    trace_map = _by_identity(traces, "traces", ids)
    report_map = _by_identity(reports, "reports", ids)
    rows = []
    for position, tid in enumerate(ids):
        trace, report = trace_map[tid], report_map[tid]
        task_id = trace.get("task_id")
        if not isinstance(task_id, str) or not task_id or any(column[position] != task_id for column in groups.values()):
            raise ValueError(f"native group ID does not match trace.task_id for {tid!r}")
        if report.get("task_id") != task_id:
            raise ValueError(f"report task_id does not match trace.task_id for {tid!r}")
        row = build_process_inputs(
            trace, report, enable_artifact_d4=enable_artifact_d4,
            d4_weight=settings.deviation_weights["D4"],
        )
        native_length = len(row["response_mask"])
        if native_length > width:
            raise ValueError(f"trace response_mask width exceeds native width for {tid!r}")
        expected = torch.tensor(row["response_mask"] + [0] * (width - native_length), dtype=mask.dtype, device=mask.device)
        if not torch.equal(mask[position], expected):
            raise ValueError(f"trace response_mask does not exactly match native row for {tid!r}")
        rows.append(row)

    def token_tensor(key):
        return torch.tensor([row[key] + [0] * (width - len(row[key])) for row in rows], dtype=torch.float32, device=mask.device)

    payload = {
        "outcome_scores": torch.tensor([row["outcome"] for row in rows], dtype=torch.float32, device=mask.device),
        "span_redundancy": token_tensor("redundancy"),
        "grounding_scores": torch.tensor([row["grounding"] for row in rows], dtype=torch.float32, device=mask.device),
        "span_deviation": token_tensor("deviations"),
        "process_valid": torch.tensor([row["process_valid"] for row in rows], dtype=torch.bool, device=mask.device),
        "training_valid": torch.tensor([row["training_valid"] for row in rows], dtype=torch.bool, device=mask.device),
    }
    # The six payload tensors above plus the existing native response_mask form
    # the seven required scoring fields. Never replace or reconstruct that mask.
    if isinstance(batch, dict):
        staged = dict(batch)
    elif callable(getattr(batch, "clone", None)):
        # TensorDict.clone(recurse=False) copies its container while retaining
        # existing tensor storage; adding new keys cannot mutate original keys.
        staged = batch.clone(recurse=False)
        if staged is batch:
            raise ValueError("batch.clone must return an independent container")
    else:
        raise ValueError("batch must be a dict or TensorDict-compatible container")
    staged.update(payload)
    data.batch = staged
    return data
