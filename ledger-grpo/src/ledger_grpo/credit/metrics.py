"""Pure, content-free summaries of v2.1 credits, outcomes and training logs."""
from bisect import bisect_right
from collections import defaultdict
from copy import deepcopy
from math import sqrt

from .utility import best_candidate_progress
from .allocate import _ks_distance


def _get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _quantile(values, q):
    return _weighted_quantile([(v, 1) for v in values], q)


def _weighted_quantile(values, q):
    """Linear order-statistic percentile without expanding generated tokens."""
    ordered = sorted((float(v), int(n)) for v, n in values if n > 0)
    if not ordered:
        return 0.0
    cumulative, total = [], 0
    for _, count in ordered:
        total += count
        cumulative.append(total)
    index = (total - 1) * q
    lo, hi = int(index), min(int(index) + 1, total - 1)
    a = ordered[bisect_right(cumulative, lo)][0]
    b = ordered[bisect_right(cumulative, hi)][0]
    return a + (b - a) * (index - lo)


def _distribution(values):
    mean = _mean(values)
    return dict(count=len(values), mean=mean, std=sqrt(_mean([(x - mean) ** 2 for x in values])),
                min=min(values, default=0.0), max=max(values, default=0.0),
                p05=_quantile(values, .05), p50=_quantile(values, .5), p95=_quantile(values, .95))


def _token_counts(trajectory):
    units = _get(trajectory, "units")
    if units is not None:
        return ({_get(u, "unit_id"): _get(u, "generated_tokens", 0) for u in units},
                sum(_get(u, "returned_tokens", 0) for u in units))
    tokens = _get(trajectory, "tokens", {})
    returned = _get(trajectory, "returned_tokens", {})
    return tokens, sum(returned.values()) if isinstance(returned, dict) else returned


def _group_indices(trajectories, groups):
    if groups is None:
        by_qid = defaultdict(list)
        for index, tr in enumerate(trajectories):
            by_qid[str(_get(tr, "qid", "__batch__"))].append(index)
        return list(by_qid.values())
    by_identity = {id(tr): i for i, tr in enumerate(trajectories)}
    by_key = {(_get(tr, "qid"), _get(tr, "rollout")): i for i, tr in enumerate(trajectories)}
    out = []
    for group in groups:
        members = _get(group, "trajectories", group)
        indices = []
        for member in members:
            if type(member) is int:
                index = member
            else:
                index = by_identity.get(id(member), by_key.get((_get(member, "qid"), _get(member, "rollout"))))
            if index is None or not 0 <= index < len(trajectories):
                raise ValueError("groups must reference trajectories in this metric batch")
            indices.append(index)
        if indices:
            out.append(indices)
    flattened = [i for group in out for i in group]
    if sorted(flattened) != list(range(len(trajectories))):
        raise ValueError("groups must partition the metric batch exactly once")
    return out


def _event_family(tag, source):
    if source == "P":
        if tag.startswith(("有效排除", "采纳反证")):
            return "P3"
        if tag.startswith("取到") and tag.endswith("(未被用)"):
            return "P2"
        if tag.startswith(("采纳", "取到")):
            return "P1"
    else:
        for prefix, family in (("排除正确答案", "E1"), ("无效排除", "E2"), ("无据断言", "E3"), ("错误路线", "E_route"),
                               ("没用", "O1"), ("冲突不改", "O3"), ("有证据不交卷", "O4"), ("浪费", "W")):
            if tag.startswith(prefix):
                return family
    return source + "_other"


def collect_credit_metrics(trajectories, credits, *, groups=None, policy=None,
                           modules=None, judge_calls=0, judge_cost=0):
    """Summarize one rollout batch without mutating or exposing content.

    ``groups`` is a partition into index lists or schema Group objects; by
    default qid identifies each group. Role token fractions and zeroed-token
    fractions use all generated tokens. Ratio p95 is token-weighted, excludes
    |A_hat| < 1e-12, and is accompanied by a count of nonzero A at zero base.
    Zero-signal trajectories have effective fraction zero. Evidence accuracy
    uses all trajectories as denominator, not only correct trajectories.

    Policy quantities are supplied by the optimizer; missing values stay None.
    Module quantities are supplied by process/sampling modules. Waste label
    amounts are descriptive overlaps: the W family charges each event once.
    """
    trajectories, credits = list(trajectories), list(credits)
    if len(trajectories) != len(credits):
        raise ValueError("one credit result is required per trajectory")
    if judge_calls < 0 or judge_cost < 0:
        raise ValueError("Judge accounting cannot be negative")
    n = len(trajectories)
    outcomes = [_get(t, "outcome", {}) for t in trajectories]
    tokens_and_returns = [_token_counts(t) for t in trajectories]
    generated = sum(sum(tokens.values()) for tokens, _ in tokens_and_returns)
    returned = sum(count for _, count in tokens_and_returns)
    tool_counts = []
    for tr, (tokens, _) in zip(trajectories, tokens_and_returns):
        units = _get(tr, "units")
        count = (sum(_get(u, "unit_id") != "F" and _get(u, "kind", "tool") == "tool" for u in units)
                 if units is not None else _get(tr, "tool_call_count", sum(u != "F" for u in tokens)))
        tool_counts.append(count)
    progress = []
    for tr in trajectories:
        values = best_candidate_progress(_get(tr, "derived", []), _get(tr, "conds", []))
        progress.append(values[-1] if values else 0.0)
    results = dict(trajectories=n, accuracy=_mean([bool(o.get("Y")) for o in outcomes]),
                   unsubmitted_rate=_mean([not o.get("submitted") for o in outcomes]),
                   evidence_accuracy={str(threshold): _mean([bool(o.get("Y")) and p >= threshold
                       for o, p in zip(outcomes, progress)]) for threshold in (.5, .75, 1.0)},
                   tool_model_calls=sum(tool_counts), mean_tool_model_calls=_mean(tool_counts),
                   generated_tokens=generated, returned_tokens=returned,
                   judge_calls=judge_calls, judge_cost=judge_cost)
    group_indices = _group_indices(trajectories, groups)
    group_flags = defaultdict(list)
    for indices in group_indices:
        correct = [bool(outcomes[i].get("Y")) for i in indices]
        group_flags["all_correct"].append(all(correct))
        group_flags["mixed"].append(any(correct) and not all(correct))
        group_flags["all_wrong"].append(not any(correct))
        group_flags["all_unsubmitted"].append(all(not outcomes[i].get("submitted") for i in indices))
        group_flags["zero_advantage"].append(all(abs(credits[i]["A_hat"]) < 1e-6 for i in indices))
    group_result = {name + "_rate": _mean(group_flags[name]) for name in
                    ("all_correct", "mixed", "all_wrong", "all_unsubmitted", "zero_advantage")}
    group_result["count"] = len(group_indices)
    group_result["ledger_fallback_count"] = sum(any(credits[i].get("log", {}).get("ledger_fallback", False) for i in indices)
                                                for indices in group_indices)
    unit_counts = {r: 0 for r in ("C", "R", "K", "F")}
    token_counts = dict(unit_counts)
    events = {name: dict(count=0, amount=0.0) for name in
              ("P1", "P2", "P3", "E1", "E2", "E3", "E_route", "O1", "O3", "O4", "W", "P_other", "R_other")}
    waste_labels = {}
    route_units, gate_dropped = defaultdict(int), defaultdict(int)
    not_taken_up = 0
    ratios, effective, deviations, dropped_fractions = [], [], [], []
    zeroed = zero_base_nonzero = unmatched = 0
    shuffle = defaultdict(list)
    shuffle_samples = defaultdict(lambda: [[], []])
    for tr, cr, (tokens, _) in zip(trajectories, credits, tokens_and_returns):
        a = cr["A_hat"]
        for u, role in cr["role"].items():
            if u not in tokens:
                continue
            unit_counts[role] += 1
            token_counts[role] += tokens.get(u, 0)
            if abs(a) >= 1e-12:
                ratios.append((abs(cr["A"][u]) / abs(a), tokens.get(u, 0)))
                if cr["A"][u] == 0:
                    zeroed += tokens.get(u, 0)
            elif cr["A"][u] != 0:
                zero_base_nonzero += tokens.get(u, 0)
        absolute = sum(cr["nu"][u] * abs(value) for u, value in cr["A"].items())
        second = sum(cr["nu"][u] * value ** 2 for u, value in cr["A"].items())
        effective.append(absolute ** 2 / second if second else 0.0)
        deviations.append(abs(sum(cr["nu"][u] * value for u, value in cr["A"].items()) - a))
        diagnostics = cr.get("v22", {})
        for label, count in diagnostics.get("route_units", {}).items():
            route_units[label] += count
        for family, count in diagnostics.get("gate_dropped", {}).items():
            gate_dropped[family] += count
        not_taken_up += diagnostics.get("not_taken_up", 0)
        log = cr.get("log", {})
        unmatched += log.get("unmatched_units", len(_get(tr, "unmatched_units", []) or []))
        budget = abs(a) * sum(cr["nu"][u] for u, role in cr["role"].items() if role in ("C", "R"))
        dropped_fractions.append(log.get("dropped", 0.0) / budget if budget else 0.0)
        for name, value in log.get("shuffle_ks", {}).items():
            shuffle[name].append(value)
        for name, (before, after) in log.get("shuffle_samples", {}).items():
            shuffle_samples[name][0].extend(before)
            shuffle_samples[name][1].extend(after)
        for source in ("P", "R"):
            for event_list in cr.get(source, {}).values():
                for amount, tag in event_list:
                    event = events[_event_family(tag, source)]
                    event["count"] += 1
                    event["amount"] += amount
                    if tag.startswith("浪费:"):
                        for label in tag.split(":", 1)[1].split("、"):
                            item = waste_labels.setdefault(label, dict(count=0, amount=0.0))
                            item["count"] += 1
                            item["amount"] += amount
    total_units = sum(unit_counts.values())
    credit_result = dict(role_unit_counts=unit_counts, role_token_counts=token_counts,
        role_unit_fractions={r: count / total_units if total_units else 0.0 for r, count in unit_counts.items()},
        role_token_fractions={r: count / generated if generated else 0.0 for r, count in token_counts.items()},
        events=events, waste_labels=waste_labels, route_units=dict(route_units),
        gate_dropped=dict(gate_dropped), not_taken_up=not_taken_up,
        A_hat_distribution=_distribution([cr["A_hat"] for cr in credits]),
        advantage_ratio_max=max((v for v, count in ratios if count > 0), default=0.0),
        advantage_ratio_p95=_weighted_quantile(ratios, .95),
        nonzero_advantage_with_zero_base_tokens=zero_base_nonzero,
        no_receiver_count=sum(bool(cr.get("log", {}).get("no_receiver")) for cr in credits),
        ledger_fallback_trajectories=sum(bool(cr.get("log", {}).get("ledger_fallback")) for cr in credits),
        infeasible_count=sum(bool(cr.get("log", {}).get("infeasible")) for cr in credits),
        infeasible_rate=_mean([bool(cr.get("log", {}).get("infeasible")) for cr in credits]),
        dropped_mass=sum(cr.get("log", {}).get("dropped", 0.0) for cr in credits),
        dropped_fraction_mean=_mean(dropped_fractions), dropped_fraction_max=max(dropped_fractions, default=0.0),
        zeroed_tokens=zeroed, zeroed_token_fraction=zeroed / generated if generated else 0.0,
        effective_token_fraction_median=_quantile(effective, .5),
        conservation_max_abs=max(deviations, default=0.0), unmatched_units=unmatched)
    policy_result = dict.fromkeys(("entropy", "kl", "clip_fraction", "gradient_norm"))
    policy_result.update(deepcopy(policy or {}))
    module_result = dict(process_selected_units=0, process_selected_tokens=0, auxiliary_loss=0.0,
                         ledger_sample_fraction=1.0, ledger_correction_weight=1.0,
                         shuffle_ks_batch={key: _ks_distance(*values) for key, values in shuffle_samples.items()},
                         shuffle_ks_mean={key: _mean(values) for key, values in shuffle.items()},
                         shuffle_ks_max={key: max(values) for key, values in shuffle.items()})
    module_result.update(deepcopy(modules or {}))
    return dict(result=results, groups=group_result, credit=credit_result,
                policy=policy_result, modules=module_result)
