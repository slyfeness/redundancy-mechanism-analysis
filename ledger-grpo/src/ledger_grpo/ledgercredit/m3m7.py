"""M3–M7 credit assignment on the frozen v6.1 unit interface."""

from collections import defaultdict
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from statistics import fmean, pstdev


@dataclass(frozen=True)
class Config:
    cost_scale: int = 3146
    strict_repeat_reference: str = "prior_fed_tool_calls"
    idle_gate: str = "strict_repeat"
    n1_enabled: bool = False
    n2_mode: str = "diagnostic"
    d_credit: float = 0.
    minimum_assertions: int = 2
    q: float = 1.
    eta: float = .3
    omega: float = .3
    beta_c: float = .1
    alpha: float = .7
    beta_n: float = .2
    sigma_min: float = .3
    lambda_idle: float = .5
    epsilon: float = .2
    learning_rate: float = 1e-6
    G: int = 8
    kappa: float = 0.

    def __post_init__(self):
        if (self.cost_scale, self.strict_repeat_reference, self.idle_gate, self.n1_enabled,
            self.n2_mode, self.d_credit, self.minimum_assertions, self.q) != (
                3146, "prior_fed_tool_calls", "strict_repeat", False, "diagnostic", 0., 2, 1.):
            raise ValueError("the v1 signal definitions are fixed")
        values = (self.eta, self.omega, self.beta_c, self.alpha, self.beta_n,
                  self.sigma_min, self.lambda_idle, self.epsilon, self.learning_rate, self.kappa)
        if any(not math.isfinite(value) or value < 0 for value in values) or (
                not 0 <= self.eta < .5 or not 0 <= self.epsilon < 1 or self.sigma_min <= 0
                or self.learning_rate <= 0 or type(self.G) is not int or self.G < 2):
            raise ValueError("invalid v1 credit or trainer parameter")

    @classmethod
    def read(cls, path):
        return cls(**json.loads(Path(path).read_bytes()))


def tool_signature(event):
    raw = event["args_raw"]
    args = json.loads(raw) if isinstance(raw, str) else raw
    tool, returned = event["tool"], event["return_text"]
    query = args.get("query") if tool == "search" else json.dumps(args, sort_keys=True, ensure_ascii=False)
    return (tool, query, returned) if isinstance(query, str) and query and returned else None


def exact_repeats(units):
    """Compare each dispatched child with returns visible before the current decision."""
    previous, result = set(), []
    for events in units:
        pairs = [(event, tool_signature(event)) for event in events]
        result.append([index for index, (_, signature) in enumerate(pairs) if signature in previous])
        previous.update(signature for event, signature in pairs if signature is not None and
                        event.get("fed_to_model", event.get("visible_to_actor")) is True)
    return result


def clip(value):
    return min(1., max(-1., value))


def redistribute(aout, utilities, count, eta):
    bounded = [clip(u) for u in utilities]
    denominator = sum(count)
    if not denominator:
        return [aout] * len(count)
    mean = math.fsum(n * u for n, u in zip(count, bounded, strict=True)) / denominator
    return [aout + eta * abs(aout) * (u - mean) for u in bounded]


def state_weight(a, b):
    return (1. - abs(a["z_pre"] - b["z_pre"])) * (1. - abs(a["b_pre"] - b["b_pre"]))


def assign(signals, config):
    """Compute scored units and the leave-one-out trajectory-level receipts."""
    groups = defaultdict(lambda: defaultdict(list))
    for row in signals:
        groups[row["query_id"]][row["trajectory_id"]].append(row)
    values, tracks = {}, {}
    for qid, group in groups.items():
        if len(group) > config.G:
            raise ValueError("observed group exceeds its configured size")
        won = {tid: rows[0]["R"] for tid, rows in group.items()}
        rho = sum(won.values()) / len(group)
        for tid, rows in group.items():
            if tid in tracks or any(row["R"] != won[tid] or row["submitted"] != rows[0]["submitted"] for row in rows):
                raise ValueError("trajectory outcome changed across units")
            for row in rows:
                stage = row["unit_type"] == "stage"
                cost = (row["n_gen"] + row["n_ret"]) / config.cost_scale
                idle = config.q * cost * row["I_N"] if stage else 0.
                utility = row["C_new"] - config.lambda_idle * rho * idle if stage else 0.
                if stage and rho == 0:
                    utility -= config.kappa * row["I_N"]
                key = tid, row["unit_id"]
                if key in values:
                    raise ValueError("duplicate M1/M2 unit")
                values[key] = {**row, "c": cost, "idle": idle, "u": utility}
            totals = [values[tid, u["unit_id"]] for u in rows]
            tracks[tid] = {"trajectory_id": tid, "query_id": qid, "rho": rho,
                           "C": math.fsum(r["c"] for r in totals), "W": math.fsum(r["idle"] for r in totals)}
        rewards = {}
        for tid, rows in group.items():
            entry = tracks[tid]
            ref = min((tracks[other]["C"] for other in group if other != tid and won[other]), default=None)
            per = config.beta_c * ref / (ref + config.alpha * entry["W"]) if ref is not None and ref > 0 else 0.
            reward = won[tid] * (1. + per) - config.beta_n * (not rows[0]["submitted"])
            entry.update(B=ref, reward=reward)
            rewards[tid] = reward
        mean, denominator = fmean(rewards.values()), max(pstdev(rewards.values()), config.sigma_min)

        peer_rows = {tid: [r for r in rows if r["unit_type"] == "stage"]
                     for tid, rows in group.items()}
        for tid, units in group.items():
            aout = (rewards[tid] - mean) / denominator
            tracks[tid]["A_out"] = aout
            rows = [values[tid, r["unit_id"]] for r in units]
            allocated = redistribute(aout, [r["u"] for r in rows], [r["n_gen"] for r in rows], config.eta)
            for row, are in zip(rows, allocated, strict=True):
                peers = []
                if row["unit_type"] == "stage":
                    for other, candidates in peer_rows.items():
                        if other == tid or not candidates:
                            continue
                        weight, step = max((state_weight(row, item), -item["unit_id"]) for item in candidates)
                        if weight > 0:
                            peers.append((other, -step, weight))
                baseline = (math.fsum(weight * values[other, sid]["u"] for other, sid, weight in peers)
                            / math.fsum(w for _, _, w in peers)) if peers else None
                ast = clip(row["u"] - baseline) if baseline is not None else 0.
                row.update(A_out=aout, A_re=are, A_st=ast, A=are + config.omega * ast,
                           peers=[(other, sid) for other, sid, _ in peers])
    return [values[r["trajectory_id"], r["unit_id"]] for r in signals], tracks


def map_scores(trajectories, values, config, *, input_binding=None):
    """Produce the exact hf_pilot_train score schema on the native loss axis."""
    import torch
    from ..hf_native import native_turn_layout

    by_tid = defaultdict(list)
    for row in values:
        by_tid[row["trajectory_id"]].append(row)
    ids = [row["id"] for row in trajectories]
    if len(set(ids)) != len(ids) or set(ids) != by_tid.keys():
        raise ValueError("native batch and scored trajectories differ")
    masks = {tid: native_turn_layout(trace)["response_mask"] for tid, trace in zip(ids, trajectories, strict=True)}
    width = max(map(len, masks.values()), default=0)
    advantages = torch.zeros((len(ids), width), dtype=torch.float32)
    effective = torch.zeros((len(ids), width), dtype=torch.bool)
    inputs = []
    for index, trace in enumerate(trajectories):
        tid, qid = trace["id"], trace["query_id"]
        source_mask = masks[tid]
        for row in by_tid[tid]:
            start, end = row["gen_start"], row["gen_end"]
            if (row["query_id"] != qid or not 0 <= start <= end <= len(source_mask)
                    or end - start != row["n_gen"] or not math.isfinite(row["A"])):
                raise ValueError("invalid M7 coordinates or credit")
            if bool(effective[index, start:end].any()):
                raise ValueError("M7 unit intervals overlap")
            effective[index, start:end] = True
            advantages[index, start:end] = row["A"]
        if effective[index, :len(source_mask)].tolist() != [bool(bit) for bit in source_mask]:
            raise ValueError("M7 intervals do not equal native generated-token positions")
        inputs.append({"traj_id": tid, "task_id": qid, "response_mask": source_mask})
    config_record = asdict(config)
    output = {"advantages": advantages, "effective_response_mask": effective,
              "valid_rows": torch.ones(len(ids), dtype=torch.bool), "process_inputs": inputs,
              "training_options": {"ppo_epsilon": config.epsilon, "learning_rate": config.learning_rate},
              "config": config_record, "control": "ledger_v1"}
    if input_binding is not None:
        output["input_binding"] = input_binding
    return output
