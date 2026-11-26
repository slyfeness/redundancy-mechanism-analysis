"""Behavioural uptake and route labels layered on the frozen v13.4 ledger."""
import copy
import re

from . import ledger as L4
from .ledger import UNKNOWN, canon, clean, gold_hit, norm, same, tokens  # noqa: F401  (re-exported)

K_HOLD = 3
K_RESTRICT = 2
ROUTE_LABELS = ("知错不改", "坚持无据候选", "沿限定走")


def mentioned(about, text):
    """Program check: the object a fact is about is named in `text` (full name, or its >=4-letter Latin words)."""
    t = norm(text) or ""
    if not about or not t:
        return False
    a = re.sub(r"[《》]", " ", str(about))
    if norm(a) and norm(a) in t:
        return True
    toks = [w for w in tokens(a) if len(w) >= 4 and not re.search("[一-鿿]", w)]
    hit = [w for w in toks if w in t]
    return bool(toks) and (len(hit) >= 2 or len(hit) == len(toks))


def uptake(record, next_text=None):
    """Return a copy of `record` whose verdicts/earlier_adopted come from behaviour, not from the Judge."""
    rec = copy.deepcopy(record)
    steps = sorted(rec["steps"], key=lambda s: s["step"])
    next_text = next_text or {}
    chain_names, registry, done = [], [], set()
    for i, st in enumerate(steps):
        if "q3_audit" not in st and (st.get("verdicts") or st.get("earlier_adopted")):
            st["q3_audit"] = {"verdicts": st.get("verdicts") or {}, "earlier_adopted": st.get("earlier_adopted") or []}
        ac = st.get("answer_chain")
        if ac is not None:
            chain_names = [n for n in [ac.get("answer")] + [l.get("object") for l in ac.get("linked", [])] if n]
        objs = [tg.get("object") for tg in st.get("targets", [])]
        if i + 1 < len(steps):
            objs += [tg.get("object") for tg in steps[i + 1].get("targets", [])]
        objs = [o for o in objs + chain_names if o and o != UNKNOWN]
        text = next_text.get(st["step"], "")

        def taken(ev):
            if any(same(ev.get("about"), o) for o in objs):
                return "目标或答案链"
            if mentioned(ev.get("about"), text):
                return "下一段提及"
            return None

        verdicts, late = {}, []
        for ev in st.get("evidence", []):
            why = taken(ev)
            verdicts[ev["key"]] = ({"verdict": "采纳", "reason": "程序：" + why} if why
                                   else {"verdict": "没理会", "reason": "程序：之后的动作没有接住"})
        for ev in registry:
            if ev["key"] not in done and taken(ev):
                late.append(ev["key"])
        st["verdicts"], st["earlier_adopted"] = verdicts, late
        done |= {k for k, v in verdicts.items() if v["verdict"] == "采纳"} | set(late)
        registry += st.get("evidence", [])
    rec["steps"] = steps
    return rec


def run(record, returns_text=None, gold=None, t_belief=None, question_text=None, next_text=None,
        k_hold=K_HOLD, k_restrict=K_RESTRICT):
    rec = uptake(record, next_text)
    res = L4.run(rec, returns_text, gold, t_belief, question_text)
    steps = rec["steps"]
    exempt_used = set()                   # issues whose one checking step was already used
    hold_run, restrict_run = 0, 0
    for i, (st, d) in enumerate(zip(steps, res["steps"])):
        t = st["step"]
        labels = d["labels"]
        diag = []
        if "冲突不改" in labels:
            labels.remove("冲突不改")
            diag.append("冲突不改")
        if d["unsupported"]:
            if "无据断言" in labels:
                labels.remove("无据断言")
            diag.append("无据断言")
        progress = "有进展" in labels
        ans = d["chain"].get("answer")
        prev = res["steps"][i - 1] if i else None
        held = bool(prev and ans and prev["chain"].get("answer") and same(prev["chain"]["answer"], ans))
        route = []
        # ---- 知错不改
        issues = set()
        if held:
            issues |= {c for c, v in prev["view"].items() if v[0] == "✘"}
        members = [ans] + [l.get("object") for l in d["chain"].get("linked", [])] if ans else []
        targeted = {c for tg in st.get("targets", [])
                    if (tg.get("object") or UNKNOWN) == UNKNOWN or any(same(tg.get("object"), m) for m in members)
                    for c in (tg.get("conditions") or [])}
        open_now = []
        for c in sorted(issues):
            key = (norm(ans), c)
            checks = c in targeted        # querying the issue for the candidate, a linked object, or "unknown"
            if checks and key not in exempt_used:
                exempt_used.add(key)
                continue
            open_now.append(c)
        if open_now and not progress:
            route.append("知错不改")
        # ---- 坚持无据候选
        if not ans or progress or any(v[0] == "✔" for v in d["view"].values()):
            hold_run = 0
        else:
            hold_run = hold_run + 1 if held else 1
        if hold_run >= k_hold:
            route.append("坚持无据候选")
        # ---- 沿限定走
        restricted = any((x.get("restriction") or "").strip() for x in st.get("targets", []))
        restrict_run = restrict_run + 1 if (restricted and not progress) else 0
        if restrict_run >= k_restrict:
            route.append("沿限定走")
        for x in route:
            if x not in labels:
                labels.append(x)
        d["diagnostic"] = diag
        d["route"] = route
    res["record"] = rec
    return res


def render(record, result, title):
    """Pursuit-line chain: 追 / 拿到 / 候选线 / 条件 / 判定."""
    rec = result.get("record") or record
    lines = [f"# {title}", ""]
    for st, rs in zip(sorted(rec["steps"], key=lambda s: s["step"]), result["steps"]):
        t = st["step"]
        tg = "；".join(f"{x['object']}｜{' '.join(x.get('conditions') or ['（没问）'])}"
                      + (f"（限定：{x['restriction']}）" if (x.get('restriction') or '').strip() else "")
                      for x in st.get("targets", []))
        lines += [f"## #{t}", f"- 追：{tg or '—'}", f"- 查询：{st.get('query', '')}"]
        took = {k for k, v in (st.get("verdicts") or {}).items() if v.get("verdict") == "采纳"}
        for ev in st.get("evidence", []):
            cs = "、".join(f"{c['id']}{'+' if c.get('effect') == '支持' else '−'}" for c in ev.get("conditions", [])) or "无条件"
            lines.append(f"  - 拿到 {ev['key']} [{ev.get('doc')}] {ev.get('fact', '')}（关于 {ev.get('about')}；{cs}；{ev.get('strength')}）"
                         + (" ✓" if ev["key"] in took else ""))
        if st.get("earlier_adopted"):
            lines.append("  - 现在接住：" + "、".join(st["earlier_adopted"]))
        ch = rs["chain"]
        cand = (ch["answer"] or "—") + ("（相连：" + "、".join(f"{l['object']}[{' '.join(l.get('conditions') or [])}]" for l in ch["linked"]) + "）" if ch["linked"] else "")
        drops = [f"放弃 {e['object']}（{e.get('reason', '')}；依据 {e.get('basis')}；{e.get('valid')}）" for e in st.get("excluded", [])]
        lines.append("- 候选线：" + "；".join([cand] + drops))
        lines.append("- 条件：" + " ".join(f"{c} {v[0]}" for c, v in rs["view"].items()))
        lines.append("- 判定：" + ("、".join(rs["labels"] + rs["position"]) or "—")
                     + (f"（诊断：{'、'.join(rs['diagnostic'])}）" if rs.get("diagnostic") else ""))
        lines.append("")
    return "\n".join(lines) + "\n"
