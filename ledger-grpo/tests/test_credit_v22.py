"""Synthetic behavioural uptake, route and credit compatibility tests."""
from types import SimpleNamespace

from ledger_grpo.credit import ledger_v135 as L5
from ledger_grpo.credit.config import CreditConfig, PARAMS
from ledger_grpo.credit.events import extract_events, gate_two_pass

C = SimpleNamespace(PARAMS=PARAMS, extract_events=extract_events, gate_two_pass=gate_two_pass)


def check(condition, message):
    assert condition, message


def step(t, targets, evidence=(), excluded=(), chain=None, restriction=""):
    return {"step": t, "query": f"q{t}", "targets": [{"object": o, "conditions": cs, "restriction": restriction} for o, cs in targets],
            "new_docs": 1, "old_docs": 0, "strict": [], "evidence": list(evidence), "verdicts": {}, "earlier_adopted": [],
            "excluded": list(excluded), "answer_chain": chain, "assertions": []}


def ev(key, about, conds, strength="直接"):
    return {"key": key, "doc": "d" + key, "sents": [key], "about": about, "fact": "f", "text": "",
            "conditions": [{"id": c[:-1], "effect": "支持" if c[-1] == "+" else "冲突"} for c in conds], "strength": strength}


CH = lambda a, linked=(): {"answer": a, "linked": [{"object": o, "conditions": cs} for o, cs in linked]}


def labels_of(rec, nt=None):
    return [d["labels"] for d in L5.run(rec, {}, None, None, "", nt or {})["steps"]]


def test_uptake():
    rec = {"query_id": "s", "group": "N", "conditions": ["c1", "c2", "A"], "steps": [
        step(1, [("未知", ["c1"])], [ev("E1@1", "Xavier School", ["c1+"]), ev("E2@1", "Other Place", ["c2+"])]),
        step(2, [("Xavier School", ["c2"])], chain=CH("Xavier School"))]}
    up = L5.uptake(rec, {1: "the Xavier School looks right", 2: ""})
    v = {k: x["verdict"] for k, x in up["steps"][0]["verdicts"].items()}
    check(v == {"E1@1": "采纳", "E2@1": "没理会"}, f"uptake decided by later actions: {v}")
    up2 = L5.uptake(rec, {1: "", 2: "maybe Other Place fits"})
    check(up2["steps"][1]["earlier_adopted"] == ["E2@1"], f"late uptake by mention: {up2['steps'][1]['earlier_adopted']}")
    rec["steps"][0]["verdicts"] = {"E2@1": {"verdict": "采纳"}}
    up3 = L5.uptake(rec, {})
    check(up3["steps"][0]["q3_audit"]["verdicts"] == {"E2@1": {"verdict": "采纳"}}
          and up3["steps"][0]["verdicts"]["E2@1"]["verdict"] == "没理会", "Judge Q3 verdicts are kept only as audit")


def test_missed_by_behaviour():
    p = dict(C.PARAMS)
    mk = lambda later: {"query_id": "s", "group": "N", "conditions": ["c1", "c2", "A"], "steps": [
        step(1, [("未知", ["c1"])], [ev("E1@1", "Quill Hall", ["c1+"])]),
        step(2, [("Quill Hall" if later else "未知", ["c2"] if later else ["c1"])], chain=CH("Quill Hall") if later else None),
        step(3, [("未知", ["A"])])]}
    for later in (False, True):
        res = L5.run(mk(later), {}, None, None, "", {})
        lab = [d["labels"] for d in res["steps"]]
        units, P, R, D = C.extract_events(res["record"]["steps"], res["steps"], ["c1", "c2", "A"],
                                          {"Y": False, "submitted": False}, False, None, None, p)
        o1 = [t for v in R.values() for _, t in v if t.startswith("没用")]
        if later:
            check(not o1, f"picked up at the next step: not an omission {o1}")
        else:
            check("放过线索" in lab[0] and o1, f"returned, answers the asked condition, never acted on: {lab} {o1}")


def test_knowing_error():
    base = lambda t3: {"query_id": "s", "group": "N", "conditions": ["c1", "c2", "A"], "steps": [
        step(1, [("未知", ["c1"])], [ev("E1@1", "Xavier School", ["c1+"])], chain=CH("Xavier School")),
        step(2, [("Xavier School", ["c2"])], [ev("E1@2", "Xavier School", ["c2-"])], chain=CH("Xavier School")),
        step(3, t3, chain=CH("Xavier School")),
        step(4, [("Xavier School", ["A"])], chain=CH("Xavier School"))]}
    # evidence conflict on c2 at step 2; step 3 does not check c2 -> 知错不改 (silent or not)
    L = labels_of(base([("Xavier School", ["A"])]))
    check("知错不改" in L[2] and "知错不改" in L[3], f"conflict returned and ignored by the next actions: {L}")
    # step 3 checks c2 once: exempt; step 4 does not check and still holds -> labelled
    L = labels_of(base([("Xavier School", ["c2"])]))
    check("知错不改" not in L[2] and "知错不改" in L[3], f"one checking step is exempt: {L}")
    L = labels_of(base([("未知", ["c2"])]))
    check("知错不改" not in L[2], f"checking the condition via an unknown target: {L}")
    # changing the candidate ends the issue
    rec = base([("Yale School", ["A"])])
    rec["steps"][2]["answer_chain"] = CH("Yale School")
    rec["steps"][3]["answer_chain"] = CH("Yale School")
    L = labels_of(rec)
    check(all("知错不改" not in x for x in L), f"switching candidate is not knowing-error: {L}")


def test_hold_and_restrict():
    rec = {"query_id": "s", "group": "N", "conditions": ["c1", "A"], "steps": [
        step(t, [("未知", ["c1"])], chain=CH("Zed Corp")) for t in range(1, 6)]}
    L = labels_of(rec)
    check(["坚持无据候选" in x for x in L] == [False, False, True, True, True], f"hold without support k=3: {L}")
    rec["steps"][3]["evidence"] = [ev("E1@4", "Zed Corp", ["c1+"])]
    rec["steps"][3]["targets"] = [{"object": "Zed Corp", "conditions": ["c1"], "restriction": ""}]
    L = labels_of(rec)
    check("坚持无据候选" not in L[3] and "坚持无据候选" not in L[4], f"support resets the run: {L}")
    rec = {"query_id": "s", "group": "N", "conditions": ["c1", "A"], "steps": [
        step(t, [("未知", ["c1"])], restriction=("1990" if t in (1, 2, 3) else "")) for t in range(1, 5)]}
    L = labels_of(rec)
    check(["沿限定走" in x for x in L] == [False, True, True, False], f"restriction route k=2: {L}")


def test_credit_route_and_gate():
    p = dict(C.PARAMS)
    rec = {"query_id": "s", "group": "N", "conditions": ["c1", "A"], "steps": [
        step(t, [("未知", ["c1"])], chain=CH("Zed Corp"), restriction="1990") for t in range(1, 6)]}
    res = L5.run(rec, {}, None, None, "", {})
    recs, der = res["record"]["steps"], res["steps"]
    out = {"Y": False, "submitted": False}
    units, P, R, D = C.extract_events(recs, der, rec["conditions"], out, False, None, None, p)
    route = {u: [m for m, t in R.get(u, []) if t.startswith("错误路线")] for u in units}
    big = p["psi"] * p["eta_p"] * 0.5
    check(route[1] == [] and abs(route[2][0] - big * 0.5) < 1e-12 and abs(route[3][0] - big * 0.25) < 1e-12,
          f"route charge decays in one shared budget: {route}")
    check(all(len(v) <= 1 for v in route.values()), "one route charge per unit")
    check(sum(sum(v) for v in route.values()) <= big + 1e-12, "route budget bounded by psi*eta*w_A")
    check(not any("自加限定(连续)" in t for v in R.values() for _, t in v), "restriction run is a route error, not waste")
    # E3 is diagnostic
    R_a = {1: [(0.1, "浪费:原地打转")], 2: [(0.2, "错误路线:沿限定走"), (0.05, "浪费:重复核实")], 3: [(0.1, "没用E1@1")]}
    R_b = {1: [(0.1, "浪费:原地打转")], 2: [(0.3, "错误路线:坚持无据候选")]}
    g = C.gate_two_pass(R_a, R_b)
    check(g == {1: [(0.1, "浪费:原地打转")], 2: [(0.2, "错误路线:沿限定走")]}, f"two-pass gate by family: {g}")



def test_legacy_preset_rates_q3_and_restores_v211_credit():
    cfg = CreditConfig.from_preset("C_W_v211")
    assert not (cfg.route_errors or cfg.e3_diagnostic or cfg.gate_two_pass)
    assert cfg.use_q3
    rec = {"conditions": ["c1", "A"], "steps": [
        step(1, [("unknown", ["c1"])], [ev("E1@1", "Synthetic Library", ["c1+"])]),
        step(2, [("unknown", ["c1"])]),
    ]}
    rec["steps"][0]["verdicts"] = {"E1@1": {"verdict": "采纳"}}
    from ledger_grpo.credit import ledger
    derived = ledger.run(rec)["steps"]
    _, positive, negative, _ = extract_events(
        rec["steps"], derived, rec["conditions"], {"Y": False, "submitted": False}, False, params=cfg
    )
    assert dict(positive) == {2: [(0.125, "采纳E1@1")], 1: [(0.125, "取到E1@1")]}
    assert not any(tag.startswith(("错误路线", "没用")) for values in negative.values() for _, tag in values)
