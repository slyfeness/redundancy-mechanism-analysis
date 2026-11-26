# -*- coding: utf-8 -*-
"""Dataset-independent v2.1 reference functions; arithmetic and labels are preserved."""
from .config import PARAMS
from .events import condition_weights, _st, _direct
from .ledger import same

def best_candidate_progress(derived, conds):
    """p per record: best single non-refuted candidate's coverage seen so far (no splicing)."""
    w = condition_weights(conds)
    hist, out, excluded = [], [], set()
    for d in derived:
        for ex in d.get("excluded_now") or []:
            excluded.add(str(ex.get("object")))
        ch = d.get("chain") or {}
        ans = ch.get("answer")
        view = d.get("view") or {}
        cov = sum(w.get(c, 0.0) * (1.0 if _direct(v) else 0.5) for c, v in view.items() if _st(v) == "✔")
        if ans:
            hist.append((ans, cov))
        alive = [cv for a, cv in hist if not any(same(a, e) for e in excluded) or same(a, ans or "")]
        out.append(max(alive) if alive else 0.0)
    return out


def trajectory_reward(records, derived, conds, outcome, waste_cost, params=PARAMS, exec_counts=None):
    """U = Y - beta_n*N + g*J - Y*min(W, w_max). J is the progress area over H execution slots:
    the slots used by record t's executed tool calls show the progress known before it (eta_p*p_{t-1});
    slots after the last execution show 1 for a correct submission, otherwise the last progress."""
    pr = params
    H, T = pr["H"], len(records)
    p = best_candidate_progress(derived, conds)
    phi = [0.0] * (H + 2)
    s, prev = 0, 0.0
    for t in range(1, T + 1):
        k = max(1, int((exec_counts or {}).get(t, 1)))
        for slot in range(s + 1, min(s + k, H) + 1):
            phi[slot] = pr["eta_p"] * prev
        s += k
        prev = p[t - 1] if t - 1 < len(p) else prev
    tail = 1.0 if outcome.get("Y") else pr["eta_p"] * prev
    for slot in range(min(s, H) + 1, H + 1):
        phi[slot] = tail
    if outcome.get("Y") and s >= H:
        phi[H] = 1.0                                     # answer after a full budget: last slot (as v2.1)
    J = sum(phi[1:H + 1]) / H
    Y = 1 if outcome.get("Y") else 0
    N = 0 if outcome.get("submitted") else 1
    Wt = min(waste_cost, pr["w_max"]) if Y else 0.0
    return Y - pr["beta_n"] * N + pr["g"] * J - Y * Wt, dict(J=J, W=Wt, executions=s)


def token_shares(units, tokens):
    tot = sum(max(tokens.get(u, 0), 0) for u in units)
    if tot <= 0:
        return {u: 1.0 / len(units) for u in units}
    return {u: max(tokens.get(u, 0), 0) / tot for u in units}


def loo_advantages(U):
    G = len(U)
    if G < 2:
        return [0.0] * G
    s = sum(U)
    return [u - (s - u) / (G - 1) for u in U]


def utility_reward(records, derived, conds, outcome, waste_cost, params=PARAMS,
                   *, tool_call_count=None, exec_counts=None):
    """Independent utility switch; the full mode calls the reference verbatim."""
    mode = params.get("utility", "progress_waste")
    if mode == "progress_waste":
        return trajectory_reward(records, derived, conds, outcome, waste_cost, params, exec_counts)
    if mode == "progress":
        return trajectory_reward(records, derived, conds, outcome, 0.0, params, exec_counts)
    Y = 1 if outcome.get("Y") else 0
    N = 0 if outcome.get("submitted") else 1
    value = Y - params["beta_n"] * N
    if mode == "outcome_eff":
        T = len(records) if tool_call_count is None else tool_call_count
        value -= Y * params.get("alpha_eff", 0.2) * T / params["H"]
    elif mode != "outcome":
        raise ValueError("Unknown utility mode: " + str(mode))
    return value, dict(J=0.0, W=0.0)
