# -*- coding: utf-8 -*-
"""Dataset-independent v2.1 reference functions; arithmetic and labels are preserved."""
from .config import PARAMS

import bisect
import hashlib
import json
import random
from collections import defaultdict

def allocate(units, nu, A_hat, role, e, params=PARAMS):
    """One capped water-filling allocation. Returns A, log."""
    A = {u: A_hat for u in units}
    log = dict(mode="none", infeasible=False, moved=0.0, dropped=0.0, receivers=0)
    if abs(A_hat) < 1e-12:
        return A, log
    S = [u for u in units if role[u] in ("C", "R")]
    recv = [u for u in S if role[u] == ("C" if A_hat > 0 else "R") and e[u] > 0]
    give = [u for u in S if u not in recv]
    if not recv or not give:
        log["mode"] = "no_receiver" if not recv else "nothing_to_move"
        return A, log
    B = abs(A_hat) * sum(nu[u] for u in S)
    amax = params["kappa"] * abs(A_hat)
    capacity = sum(nu[u] * amax for u in recv)
    sign = 1.0 if A_hat > 0 else -1.0
    log["receivers"] = len(recv)
    if B > capacity + 1e-12:
        log["infeasible"] = True
        mode = params["infeasible"]
        if mode == "abstain":
            log["mode"] = "abstain"
            return A, log
        for u in recv:
            A[u] = sign * amax
        left = B - capacity
        if mode == "partial":                                # give-ups keep part of their credit, conservation holds
            gt = sum(nu[u] for u in give)
            for u in give:
                A[u] = sign * left / gt
            log["mode"] = "partial"
        else:                                                # drop
            for u in give:
                A[u] = 0.0
            log["dropped"] = left
            log["mode"] = "drop"
        log["moved"] = capacity
        return A, log
    # water-filling: b_u = min(nu_u*amax, theta*e_u), sum b_u = B
    order = sorted(recv, key=lambda u: nu[u] * amax / e[u])
    rem_B, rem_w = B, sum(e[u] for u in recv)
    b = {}
    for i, u in enumerate(order):
        theta = rem_B / rem_w
        if theta * e[u] > nu[u] * amax:
            b[u] = nu[u] * amax
            rem_B -= b[u]
            rem_w -= e[u]
        else:
            for v in order[i:]:
                b[v] = theta * e[v]
            break
    for u in recv:
        A[u] = sign * b[u] / nu[u] if nu[u] > 0 else 0.0
    for u in give:
        A[u] = 0.0
    log["mode"], log["moved"] = "transfer", B
    return A, log


def allocate_mode(units, nu, A_hat, role, e, params=PARAMS, *, step_credit=None):
    """Dispatch independent allocation controls without altering the reference."""
    mode = step_credit or params.get("step_credit", "transfer")
    if mode == "draco":
        raise NotImplementedError("DRACO allocation awaits a separately specified rule")
    if mode in ("transfer", "shuffled"):
        return allocate(units, nu, A_hat, role, e, params)
    if mode == "transfer_uniform":
        weights = {u: (1.0 if role[u] in ("C", "R") and e[u] > 0 else e[u]) for u in units}
        return allocate(units, nu, A_hat, role, weights, params)
    A = {u: A_hat for u in units}
    log = dict(mode="none", infeasible=False, moved=0.0, dropped=0.0, receivers=0)
    if mode == "none" or abs(A_hat) < 1e-12:
        return A, log
    if mode != "clear_only":
        raise ValueError("Unknown step_credit mode: " + str(mode))
    S = [u for u in units if role[u] in ("C", "R")]
    recv = [u for u in S if role[u] == ("C" if A_hat > 0 else "R") and e[u] > 0]
    give = [u for u in S if u not in recv]
    if not recv or not give:
        log["mode"] = "no_receiver" if not recv else "nothing_to_move"
        return A, log
    for u in give:
        A[u] = 0.0
    log.update(mode="clear_only", receivers=len(recv),
               dropped=abs(A_hat) * sum(nu[u] for u in give))
    return A, log


def length_tertiles(lengths):
    """Linear empirical 1/3 and 2/3 quantiles shared across a rollout batch."""
    values = sorted(lengths)
    if not values:
        return (0.0, 0.0)
    def quantile(q):
        index = (len(values) - 1) * q
        lo = int(index)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)
    return quantile(1 / 3), quantile(2 / 3)


def _ks_distance(first, second):
    if not first and not second:
        return 0.0
    if not first or not second:
        return 1.0
    a, b = sorted(first), sorted(second)
    return max(abs(bisect.bisect_right(a, x) / len(a) - bisect.bisect_right(b, x) / len(b))
               for x in set(a + b))


def shuffle_roles(units, role, e, tokens, *, training_step=0, qid="", rollout=0,
                  unit_types=None, length_cutpoints=None, protected_units=()):
    """Shuffle (role, event weight) pairs within one trajectory, protecting F.

    Singleton strata first merge position bins, then length bins, then types.
    A merge absorbs all sibling strata, so every unit is permuted exactly once.
    Normal K units participate; explicit alignment/confidence gates remain K.
    """
    nonfinal = [u for u in units if u != "F"]
    protected = set(protected_units)
    movable = [u for u in nonfinal if u not in protected]
    cuts = length_cutpoints if length_cutpoints is not None else length_tertiles(tokens.get(u, 0) for u in nonfinal)
    unit_types = unit_types or {}
    position = {u: i / max(1, len(nonfinal) - 1) for i, u in enumerate(nonfinal)}
    keys = {u: (str(unit_types.get(u, "tool")), bisect.bisect_right(cuts, tokens.get(u, 0)),
                min(2, int(position[u] * 3))) for u in movable}
    initial = defaultdict(list)
    for u in movable:
        initial[keys[u]].append(u)
    groups = list(initial.values())
    levels = {u: 0 for u in movable}
    for depth in (2, 1, 0):
        targets = {keys[group[0]][:depth] for group in groups if len(group) == 1}
        if not targets:
            break
        kept, merged = [], defaultdict(list)
        for group in groups:
            prefix = keys[group[0]][:depth]
            if prefix in targets:
                merged[prefix].extend(group)
            else:
                kept.append(group)
        for group in merged.values():
            for u in group:
                levels[u] = 3 - depth
        groups = kept + list(merged.values())
    seed_text = json.dumps([training_step, str(qid), rollout], ensure_ascii=False, separators=(",", ":"))
    seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:16], "big")
    rng = random.Random(seed)
    shuffled_role, shuffled_e = dict(role), dict(e)
    for group in groups:
        pairs = [(role[u], e[u]) for u in group]
        rng.shuffle(pairs)
        for u, (r, weight) in zip(group, pairs):
            shuffled_role[u], shuffled_e[u] = r, weight
    ks = {}
    for r in ("C", "R"):
        before = [u for u in nonfinal if role[u] == r]
        after = [u for u in nonfinal if shuffled_role[u] == r]
        ks[r + "_length"] = _ks_distance([tokens.get(u, 0) for u in before], [tokens.get(u, 0) for u in after])
        ks[r + "_position"] = _ks_distance([position[u] for u in before], [position[u] for u in after])
    return shuffled_role, shuffled_e, dict(shuffle_ks=ks, shuffle_seed=seed,
                                          shuffle_strata=groups, shuffle_relaxation=levels,
                                          length_cutpoints=tuple(cuts))
