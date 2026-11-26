# -*- coding: utf-8 -*-
"""Dataset-independent v2.1 reference functions; arithmetic and labels are preserved."""
from collections import defaultdict
from .config import PARAMS
from .ledger import canon, same
from .ledger_v135 import ROUTE_LABELS

WASTE_LABELS = {"重复核实", "原地打转", "严格重复", "追已排除"}


def condition_weights(conds):
    rest = [c for c in conds if c != "A"]
    return {c: (0.5 if c == "A" else 0.5 / max(1, len(rest))) for c in conds}


def _st(v):
    return v[0] if isinstance(v, (list, tuple)) else v


def _direct(v):
    return bool(v[2]) if isinstance(v, (list, tuple)) and len(v) > 2 else False


def _qtext(rec):
    q = rec.get("query")
    return " ".join(q) if isinstance(q, list) else str(q or "")


def extract_events(records, derived, conds, outcome, has_final, costs=None, gold=None, params=PARAMS):
    pr = params
    T = len(records)
    units = list(range(1, T + 1)) + (["F"] if has_final else [])
    proc = lambda t: (t + 1) if t < T else ("F" if has_final else T)
    costs = costs or {}
    w = condition_weights(conds)
    wA, wmin = w.get("A", 0.5), min(w.values())
    g_, eta = pr["gamma_o"], pr["eta_p"]
    sig = lambda ev: 1.0 if ev.get("strength") == "直接" else 0.5
    P, R, DIAG = defaultdict(list), defaultdict(list), defaultdict(list)
    known, registry = [], {}
    s_max = defaultdict(float)          # condition completion strength reached so far
    ret_left = {c: pr["rho_r"] * eta * w[c] for c in conds}
    up_left = {c: (1 - pr["rho_r"]) * eta * w[c] for c in conds}
    x_budget, x_count = pr["eps_x"] * eta * wA, 0
    adopted, pursued, excluded_objs = set(), set(), set()
    later_adopt = defaultdict(set)      # key -> records where it was (late) adopted
    for t, rec in enumerate(records, start=1):
        for k in rec.get("earlier_adopted", []):
            later_adopt[k].add(t)
    future_targets = []                 # per record: canonical-free target names of records after t
    for t in range(T):
        names = []
        for rec in records[t + 1:]:
            names += [x.get("object") for x in rec.get("targets", []) if (x.get("object") or "未知") != "未知"]
            names.append(_qtext(rec))
        future_targets.append(names)
    run_conflict = run_ready = run_restrict = route_count = 0

    def give_x(unit, tag):
        nonlocal x_count
        P[unit].append((x_budget * (1 - g_) * g_ ** x_count, tag))
        x_count += 1

    for t, (rec, d) in enumerate(zip(records, derived), start=1):
        up = proc(t)
        for ev in rec.get("evidence", []):
            registry[ev["key"]] = dict(ev, about=canon(ev.get("about"), known), step=t)
        labels = set(d.get("labels") or [])
        pos = set(d.get("position") or [])
        ch = d.get("chain") or {}
        members = [o for o in [ch.get("answer")] + [l.get("object") for l in (ch.get("linked") or [])] if o]
        nxt = records[t] if t < T else None
        nxt_names = ([x.get("object") for x in nxt.get("targets", [])] + [_qtext(nxt)]) if nxt else []
        # ---------- P: adoption -> condition-strength increments (uptake to proc(t), retrieval to origin)
        keys = [k for k, v in (rec.get("verdicts") or {}).items()
                if (v.get("verdict") if isinstance(v, dict) else v) == "采纳"]
        keys += [k for k in rec.get("earlier_adopted", []) if k not in keys]
        for k in keys:
            if k in adopted or k not in registry:
                continue
            adopted.add(k)
            ev = registry[k]
            for cc in ev.get("conditions", []):
                c = cc["id"]
                if c not in w:
                    continue
                if cc.get("effect") == "冲突":          # adopted refutation: shares the exclusion budget
                    give_x(up, f"采纳反证{k}")
                    continue
                inc = max(0.0, sig(ev) - s_max[c])
                if inc <= 0:
                    continue
                s_max[c] += inc
                u_amt = min(up_left[c], (1 - pr["rho_r"]) * eta * w[c] * inc)
                r_amt = min(ret_left[c], pr["rho_r"] * eta * w[c] * inc)
                up_left[c] -= u_amt
                ret_left[c] -= r_amt
                if u_amt > 0:
                    P[up].append((u_amt, f"采纳{k}{'(迟)' if k in rec.get('earlier_adopted', []) else ''}"))
                if r_amt > 0:
                    P[ev["step"]].append((r_amt, f"取到{k}"))
        # ---------- exclusions (E or small P)
        gold_hits = {x[3:] for x in (d.get("missed_gold") or []) if isinstance(x, str) and x.startswith("排除:")}
        e_objs = set()
        for ex in d.get("excluded_now") or []:
            obj = ex.get("object")
            bad = ex.get("basis") in ("题外", "无依据") or ex.get("valid") == "不成立"
            had_clue = any(same(e["about"], obj) and any(c.get("effect") == "支持" for c in e.get("conditions", []))
                           for e in registry.values())
            if pr["privileged"] and gold and same(obj, gold):
                R[up].append((pr["psi"] * eta * wA, f"排除正确答案{obj}"))
                e_objs.add(obj)
            elif bad and had_clue:
                R[up].append((pr["psi"] * eta * wA * pr["eps_x"], f"无效排除{obj}"))
                e_objs.add(obj)
            elif ex.get("basis") == "条件" and ex.get("valid") == "成立" and canon(obj, known) in pursued:
                give_x(up, f"有效排除{obj}")
            if gold and any(same(obj, gh) for gh in gold_hits):
                DIAG[up].append("（诊断）排除了含正确答案线索的对象")
            excluded_objs.add(canon(obj, known))
        # ---------- O1: ignored useful evidence about pursued objects, never used later
        missed = list(d.get("missed") or [])
        gold_keys = {x for x in (d.get("missed_gold") or []) if isinstance(x, str) and x.startswith("E")}
        for k in missed + [k for k in (d.get("unused") or []) if k not in missed]:
            ev = registry.get(k)
            if not ev or ev.get("broad") == "是" or any(same(ev["about"], o) for o in e_objs):
                continue
            if any(tt > t for tt in later_adopt.get(k, ())):
                continue                                   # used later: a late adoption, not an omission
            if any(isinstance(n, str) and n and (same(ev["about"], n) or ev["about"] in n) for n in future_targets[t - 1]):
                continue                                   # the object was taken up later
            sup = [c["id"] for c in ev.get("conditions", []) if c.get("effect") == "支持" and c["id"] in w]
            if not sup:
                continue
            cid = max(sup, key=lambda c: w[c])
            wk = wA if (pr["privileged"] and k in gold_keys) else w[cid]
            budget = (1 - pr["rho_r"]) * eta * wk * sig(ev)
            R[up].append(((1 - g_) * budget, f"没用{k}"))
            r_amt = min(ret_left[cid], pr["rho_r"] * eta * w[cid] * sig(ev))
            if r_amt > 0:                                  # P2: the query that surfaced it still gets retrieval credit
                ret_left[cid] -= r_amt
                P[ev["step"]].append((r_amt, f"取到{k}(未被用)"))
        for x in d.get("missed_gold") or []:
            if isinstance(x, str) and x.startswith("返回:"):
                DIAG[t].append("（诊断）返回原文出现正确答案字符串")
        # ---------- O3: a known conflict on the current answer, not handled
        route = [label for label in ROUTE_LABELS if label in labels] if pr.get("route_errors", True) else []
        if route:
            R[t].append((pr["psi"] * eta * wA * (1 - g_) * g_ ** route_count, "错误路线:" + "、".join(route)))
            route_count += 1
        if "冲突不改" in labels and not pr.get("route_errors", True):
            ans = ch.get("answer")
            verifying = bool(ans) and any(isinstance(n, str) and n and (same(ans, n) or ans in n) for n in nxt_names)
            if not verifying:
                R[up].append(((1 - g_) * g_ ** run_conflict * (1 - pr["rho_r"]) * eta * wA, "冲突不改"))
                run_conflict += 1
        else:
            run_conflict = 0
        # ---------- E3: unsupported assertions that feed a decision
        used_text = " ".join([_qtext(nxt) if nxt else ""] + [str(e.get("reason", "")) for e in d.get("excluded_now") or []]
                             + [str(o) for o in members])
        n_e3 = 0
        for a in d.get("unsupported") or []:
            toks = [str(x) for x in a.get("tokens", []) if str(x).strip()]
            if toks and any(tk in used_text for tk in toks) and n_e3 < 2:
                if pr.get("e3_diagnostic", True):
                    DIAG[up].append("（诊断）无据断言被用于决策")
                else:
                    R[up].append((pr["psi"] * eta * wmin * 0.5, "无据断言(被用于决策)"))
                n_e3 += 1
        # ---------- O4 (ready but keeps searching): general uses all-conditions-supported; belief point is privileged
        ready_general = "已够还查" in pos
        ready_priv = pr["privileged"] and ("有证据不交卷" in pos)
        if (ready_general and not outcome.get("submitted")) or ready_priv:
            R[t].append(((1 - g_) * g_ ** run_ready * (1 - eta), "有证据不交卷"))
            run_ready += 1
        else:
            run_ready = 0
        # ---------- W: one waste charge per unit (query decision -> unit t)
        wl = labels & WASTE_LABELS
        if "已够还查" in pos:
            wl.add("已够还查")
        if pr["privileged"] and "信念后核实" in pos:
            wl.add("信念后核实")
        if "查没问的" in labels:
            wl.add("查没问的")
        restricted = any((x.get("restriction") or "").strip() for x in rec.get("targets", []))
        run_restrict = run_restrict + 1 if (restricted and "有进展" not in labels) else 0
        if run_restrict >= 2 and not pr.get("route_errors", True):
            wl.add("自加限定(连续)")
        if wl:
            R[t].append((pr["lam"] * costs.get(t, 1.0), "浪费:" + "、".join(sorted(wl))))
        pursued |= {canon(x.get("object"), known) for x in rec.get("targets", []) if (x.get("object") or "未知") != "未知"}
        pursued |= {canon(o, known) for o in members}
    # hindsight: a unit whose query surfaced useful evidence is not charged as waste
    for u in units:
        if any(tag.startswith("取到") for _, tag in P.get(u, [])):
            R[u] = [(m, tag) for m, tag in R.get(u, []) if not tag.startswith("浪费")]
    return units, P, R, DIAG


def event_family(tag):
    """The same family on the same unit confirms a negative event."""
    for prefix, family in (("浪费", "W"), ("错误路线", "route"), ("无效排除", "excl"), ("排除正确答案", "excl"),
                           ("没用", "O1"), ("冲突不改", "O3"), ("有证据不交卷", "O4"), ("无据断言", "E3")):
        if tag.startswith(prefix):
            return family
    return tag


def gate_two_pass(R_a, R_b, *, dropped=None):
    kept = {}
    for unit, events in R_a.items():
        confirmed = {event_family(tag) for _, tag in R_b.get(unit, ())}
        for amount, tag in events:
            family = event_family(tag)
            if family in confirmed:
                kept.setdefault(unit, []).append((amount, tag))
            elif dropped is not None:
                dropped[family] += 1
    return kept
