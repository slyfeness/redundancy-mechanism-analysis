"""One question group to per-unit advantages; C_W retains reference arithmetic."""
from .config import PARAMS, CreditConfig
from .events import extract_events
from .utility import utility_reward, token_shares, loo_advantages
from .roles import assign_roles
from .allocate import allocate_mode, length_tertiles, shuffle_roles


def ledger_complete(tr):
    """A trajectory's ledger is complete when it has one record (and derived row) per tool-call unit."""
    expected = tr.get("tool_units")
    if expected is None:
        expected = sum(1 for u in tr["tokens"] if u != "F")
    recs, der = tr.get("records") or [], tr.get("derived") or []
    return len(recs) == len(der) == expected and (expected == 0 or bool(tr.get("conds")))


def outcome_only_group(trajs, params=PARAMS):
    """Preset-A credit for a whole group: U = Y - beta_n*N, every unit keeps the LOO advantage."""
    U = [(1 if tr["outcome"].get("Y") else 0) - params["beta_n"] * (0 if tr["outcome"].get("submitted") else 1)
         for tr in trajs]
    out = []
    for tr, u, a in zip(trajs, U, loo_advantages(U)):
        has_final = tr["outcome"].get("submitted") or tr["tokens"].get("F", 0) > 0
        units = [x for x in tr["tokens"] if x != "F"] + (["F"] if has_final else [])
        role = {x: ("F" if x == "F" else "K") for x in units}
        out.append(dict(U=u, info=dict(J=0.0, W=0.0, executions=None), A_hat=a, A={x: a for x in units},
                        role=role, e={x: 0.0 for x in units}, P={}, R={}, diag={},
                        nu=token_shares(units, tr["tokens"]), log=dict(mode="ledger_fallback", ledger_fallback=True)))
    return out


def credit_for_group(trajs, params=PARAMS, *, confident=None, training_step=0,
                     length_cutpoints=None):
    """Return reference dictionaries; accept schema trajectories or mappings.

    ``confident`` is an optional sequence of per-unit confidence mappings.
    Callers processing multiple groups should pass shared batch length tertiles.
    ``unmatched_units`` explicitly protects uncertain alignment as role K.
    """
    params = CreditConfig.from_params(params)
    if hasattr(trajs, "trajectories"):
        trajs = trajs.trajectories
    trajs = [tr.to_credit_dict() if hasattr(tr, "to_credit_dict") else tr for tr in trajs]
    if params.requires_ledger and not all(ledger_complete(tr) for tr in trajs):
        return outcome_only_group(trajs, params)
    if confident is not None and len(confident) != len(trajs):
        raise ValueError("confident must contain one mapping per trajectory")
    if length_cutpoints is None and params.step_credit == "shuffled":
        length_cutpoints = length_tertiles(n for tr in trajs for u, n in tr["tokens"].items() if u != "F")
    pre = []
    for tr in trajs:
        has_final = tr["outcome"].get("submitted") or tr["tokens"].get("F", 0) > 0 or tr.get("has_final", False)
        records, derived, conds = tr["records"], tr["derived"], tr["conds"]
        if records and derived and conds:
            units, P, R, D = extract_events(records, derived, conds, tr["outcome"], has_final,
                                            tr.get("costs"), tr.get("gold"), params)
        else:
            units = list(range(1, len(records) + 1)) + (["F"] if has_final else [])
            P, R, D = {}, {}, {}
        extra = [u for u in tr["tokens"] if u not in units and u != "F"]
        if extra:
            units = [u for u in units if u != "F"] + extra + (["F"] if has_final else [])
        waste = sum(params["lam"] * (tr.get("costs") or {}).get(u, 1.0)
                    for u in units if any(t.startswith("浪费") for _, t in R.get(u, [])))
        U, info = utility_reward(records, derived, conds, tr["outcome"], waste, params,
                                 tool_call_count=tr.get("tool_call_count", sum(u != "F" for u in units)),
                                 exec_counts=tr.get("exec_counts"))
        pre.append((units, P, R, D, U, info))
    A_hat = loo_advantages([x[4] for x in pre])
    out = []
    for index, (tr, (units, P, R, D, U, info), a) in enumerate(zip(trajs, pre, A_hat)):
        nu = token_shares(units, tr["tokens"])
        conf = confident[index] if confident is not None else tr.get("confident")
        role, e = assign_roles(units, P, R, tr["outcome"].get("Y"), conf, params)
        unmatched = set(tr.get("unmatched_units") or [])
        for u in unmatched:
            if u in role and u != "F":
                role[u], e[u] = "K", 0.0
        shuffle_log = {}
        if params.step_credit == "shuffled":
            gated = {u for u in units if params.gate_low_conf and conf is not None and not conf.get(u, True)}
            role, e, shuffle_log = shuffle_roles(units, role, e, tr["tokens"],
                                                 training_step=training_step, qid=tr.get("qid", ""),
                                                 rollout=tr.get("rollout", index), unit_types=tr.get("unit_types"),
                                                 length_cutpoints=length_cutpoints, protected_units=unmatched | gated)
        A, log = allocate_mode(units, nu, a, role, e, params)
        log.update(shuffle_log)
        if unmatched:
            log["unmatched_units"] = sum(u in role and u != "F" for u in unmatched)
        out.append(dict(U=U, info=info, A_hat=a, A=A, role=role, e=e, P=dict(P), R=dict(R), diag=dict(D), nu=nu, log=log))
    return out
