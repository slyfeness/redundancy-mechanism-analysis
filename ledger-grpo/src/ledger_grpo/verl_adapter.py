"""Explicit, legacy-v0 verl bridge. Importing this module installs nothing.

The tensor adapter is independently usable without verl. Registration only
changes the current process and never edits an installed verl source file.
"""

from dataclasses import fields
from functools import wraps
import importlib
import inspect


ESTIMATOR_NAME = "span_grpo"
VERL_REFERENCE_COMMIT = "81464bb6d35cbb43962be42b0088a591e7020f21"


class NoValidTrainingRows(RuntimeError):
    """The runner must skip this batch and resample before any optimizer step."""


def _get(config, name, default=None):
    if config is None:
        return default
    if hasattr(config, "get"):
        return config.get(name, default)
    return getattr(config, name, default)


def _plain_config(value):
    if hasattr(value, "items"):
        return {key: _plain_config(item) for key, item in value.items()}
    return value


def _bridge_config(config):
    """Separate estimator parameters from adapter-only control routing."""
    from .advantages import AdvantageConfig

    if isinstance(config, AdvantageConfig):
        return config, "targeted", 0
    trainer = _get(config, "trainer")
    if _get(trainer, "use_v1", False):
        raise RuntimeError("verl v1/TransferQueue is not supported by this legacy-v0 bridge")
    actor = _get(_get(config, "actor_rollout_ref"), "actor")
    loss_agg_mode = _get(actor, "loss_agg_mode")
    if loss_agg_mode is not None and loss_agg_mode != "token-mean":
        raise RuntimeError("This bridge requires actor.loss_agg_mode=token-mean for masked invalid rows")
    algorithm = _get(config, "algorithm", config)
    raw = _get(algorithm, "ledger_span", {})
    if isinstance(raw, AdvantageConfig):
        return raw, "targeted", 0
    if raw is None or not hasattr(raw, "items"):
        raise ValueError("config.ledger_span must be a mapping of AdvantageConfig fields")
    options = _plain_config(raw)
    control, seed = options.pop("control", "targeted"), options.pop("seed", 0)
    if not isinstance(control, str) or control not in {"targeted", "uniform", "shuffle", "trajectory"}:
        raise ValueError("control must be targeted, uniform, shuffle, or trajectory")
    if type(seed) is not int or not 0 <= seed <= 2**64 - 1:
        raise ValueError("seed must be a nonnegative 64-bit integer")
    unknown = set(options) - {field.name for field in fields(AdvantageConfig)}
    if unknown:
        raise ValueError(f"Unknown ledger_span configuration fields: {sorted(unknown)}")
    return AdvantageConfig(**options), control, seed


def apply_to_batch(data, config=None):
    """Compute advantages on a DataProto-compatible object, without importing verl.

    ``config`` can be an AdvantageConfig, an algorithm config with ``ledger_span``,
    or a full trainer config with ``algorithm.ledger_span``. Ground truth must be
    supplied independently as outcome_scores; token_level_rewards is not used.
    """
    from .advantages import compute_advantages, apply_control

    settings, control, seed = _bridge_config(config)
    required = ("outcome_scores", "response_mask", "span_redundancy",
                "grounding_scores", "span_deviation")
    missing = [key for key in required if key not in data.batch]
    if missing:
        raise ValueError(f"Missing ledger-grpo batch payload fields: {missing}")
    groups = data.non_tensor_batch.get("uid", data.non_tensor_batch.get("task_id"))
    if groups is None:
        raise ValueError("non_tensor_batch must contain uid or task_id group identifiers")
    if not isinstance(data.meta_info, dict):
        raise ValueError("data.meta_info must be a dictionary")

    # Reapplying the adapter must not replace the original policy-token mask by
    # a previous loss mask containing dropped rows.
    mask = data.batch.get("ledger_response_mask", data.batch["response_mask"])
    result = compute_advantages(
        data.batch["outcome_scores"], groups, mask,
        data.batch["span_redundancy"], data.batch["grounding_scores"],
        data.batch["span_deviation"],
        process_valid=data.batch.get("process_valid"),
        training_valid=data.batch.get("training_valid"), config=settings,
    )
    if not bool(result["valid_rows"].any()):
        raise NoValidTrainingRows("No valid training rows remain; skip this optimizer step and resample")
    effective_mask = mask * result["valid_rows"].to(mask.dtype).unsqueeze(-1)
    adjusted = apply_control(result["advantages"], result["trajectory_advantage"],
                             effective_mask, mode=control, seed=seed)
    data.batch["ledger_response_mask"] = mask.clone()
    data.batch["advantages"] = adjusted
    data.batch["returns"] = adjusted.clone()
    data.batch["response_mask"] = effective_mask
    data.meta_info["ledger_grpo"] = dict(result["metrics"], control=control, control_seed=seed)
    return data


def _span_grpo_estimator(token_level_rewards, response_mask, index=None,
                         config=None, *, payload=None, **kwargs):
    """Registry entry; upstream's generic kwargs omit our required payload."""
    if payload is None:
        raise ValueError(
            "span_grpo requires the full ledger payload: call apply_to_batch or "
            "install register_verl_bridge(); bare upstream estimator dispatch "
            "does not forward outcome_scores or span tensors"
        )
    result = apply_to_batch(payload, config)
    return result.batch["advantages"], result.batch["returns"]


def register_verl_bridge(*, trainer_api="v0"):
    """Install the explicit process-local v0 dispatch bridge, once.

    Unknown upstream call signatures and v1 calls fail closed. The installer
    returns the dispatch function for a startup identity/smoke check.
    """
    if trainer_api != "v0":
        raise RuntimeError("Only verl legacy v0 is supported; v1/TransferQueue is not supported")
    try:
        core = importlib.import_module("verl.trainer.ppo.core_algos")
        trainer = importlib.import_module("verl.trainer.ppo.ray_trainer")
    except ImportError as exc:
        raise RuntimeError(
            "verl and its runtime dependencies must already be installed to register "
            "the bridge; apply_to_batch remains usable without verl"
        ) from exc
    original = getattr(trainer, "compute_advantage", None)
    if getattr(original, "_ledger_grpo_v0_bridge", False):
        return original
    if not callable(original) or not callable(getattr(core, "register_adv_est", None)):
        raise RuntimeError("Incompatible verl: missing legacy compute_advantage or register_adv_est")
    signature = inspect.signature(original)
    required = {"data", "adv_estimator", "gamma", "lam", "num_repeat",
                "norm_adv_by_std_in_grpo", "config"}
    if not required.issubset(signature.parameters):
        raise RuntimeError(f"Incompatible verl compute_advantage signature: {signature}")

    @wraps(original)
    def bridged(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        if bound.arguments["adv_estimator"] != ESTIMATOR_NAME:
            return original(*args, **kwargs)
        # Current v1 delegates through v1.utils and discards extra queue fields.
        # Never let that path appear to work by accident with incomplete data.
        frame = inspect.currentframe()
        try:
            caller = frame.f_back if frame is not None else None
            caller_module = caller.f_globals.get("__name__", "") if caller is not None else ""
            if caller_module.startswith("verl.trainer.ppo.v1"):
                raise RuntimeError("span_grpo v1/TransferQueue calls are unsupported; use legacy v0")
        finally:
            del frame
        return apply_to_batch(bound.arguments["data"], bound.arguments["config"])

    # Registry conflicts must fail before replacing the upstream dispatcher.
    core.register_adv_est(ESTIMATOR_NAME)(_span_grpo_estimator)
    bridged._ledger_grpo_v0_bridge = True
    trainer.compute_advantage = bridged
    return bridged
