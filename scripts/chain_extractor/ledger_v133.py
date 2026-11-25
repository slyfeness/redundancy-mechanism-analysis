# -*- coding: utf-8 -*-
"""v13.3 (2026-11-25), program-only fixes checked against the 6 hand references (no reference label changes):
- question_text counts as known when checking assertions; returned doc ids are not checked as tokens;
- a badly reasoned exclusion counts toward 放过线索 only if some returned fact supported that object;
- with no answer there is no chain: linked objects are ignored;
- a valid condition-based exclusion counts as progress only for an object that was earlier a named target or the answer.
v13.2: an exclusion of an object that is in the same step's answer chain is dropped (role, not rejection).
v13.2: 重复核实 only when the condition was settled by direct evidence (an inference-only ✔ still needs checking).
v13.1: 放过线索 counts only ignored facts that support a condition (ignoring "X does not fit" is not a missed clue).
v12.3: + gold first seen in raw returns (not only in extracted evidence) counts as 放过正确线索.
v11 bookkeeping, mechanism rules and chain rendering (generic: no question content).

One trajectory record (same schema for hand references and Judge outputs):
{"query_id", "group", "conditions": [ids incl. "A"], "steps": [
  {"step", "targets": [{"object", "conditions": [...], "restriction"}], "plan_match",
   "query", "new_docs", "old_docs", "strict": [...],
   "evidence": [{"key", "doc", "sents": [...], "about", "fact", "conditions": [{"id", "effect"}], "strength"}],
   "verdicts": {key: {"verdict": "采纳|不信|没理会", "reason": ""}},
   "earlier_adopted": [keys], "excluded": [{"object", "reason", "basis", "basis_conditions", "valid"}],
   "answer_chain": {"answer": str|None, "linked": [{"object", "conditions"}]} | None (None = unjudged, keep previous),
   "assertions": [{"claim", "conditions", "tokens": [...]}]}]}
Extra inputs: returns_text {step: "all sentences of all docs returned at that step"}, gold (str|None), t_belief (int|None).
"""
import re

UNKNOWN = "未知"


def clean(name):
    """Drop bracketed notes and a leading 'The' (e.g. 'The Convent X (girls' school)' -> 'Convent X')."""
    s = re.sub(r"[\(（][^\)）]*[\)）]", " ", str(name))
    s = re.sub(r"^\s*the\s+", "", s, flags=re.I)
    return s.strip()


def norm(name):
    if name is None:
        return None
    s = re.sub(r"[\W_]+", "", clean(name).lower())
    return s or None


def tokens(name):
    """Word tokens without single-letter initials (so 'Richard C. Larson' ~ 'Richard Larson')."""
    return [t for t in re.findall(r"[0-9a-z一-鿿]+", clean(name).lower()) if len(t) > 1]


def same(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = set(tokens(a)), set(tokens(b))
    if ta and tb and (ta <= tb or tb <= ta) and min(len(ta), len(tb)) >= 2:
        return True
    short, long_ = sorted((na, nb), key=len)
    return len(short) >= 6 and short in long_


def canon(name, known):
    """Map a name onto an already known object name when equivalent."""
    if name is None or str(name).strip() == UNKNOWN:
        return UNKNOWN
    for k in known:
        if same(k, name):
            return k
    known.append(name)
    return name


def gold_hit(gold, text):
    """Gold named in raw return text: full name, or first+last word for names of 3+ words
    (full name or adjacent first and last words). Golds shorter than 2 words are not
    searched in raw text (numbers and one-word answers would match by accident)."""
    if not gold or not text:
        return False
    words = tokens(gold)
    if len(words) < 2:
        return False
    flat = " " + " ".join(re.findall(r"[0-9a-z一-鿿]+", clean(text).lower())) + " "
    if " " + " ".join(words) + " " in flat:
        return True
    return len(words) >= 3 and " " + words[0] + " " + words[-1] + " " in flat


def run(record, returns_text=None, gold=None, t_belief=None, question_text=None):
    conds = record["conditions"]
    group = record.get("group")
    known, registry, ledger = [], {}, {}
    adopted, ignored, excluded = set(), {}, {}
    chain = {"answer": None, "linked": []}
    seen_keys = {}
    seen_text = question_text or ""  # restating the question is not an unsupported assertion
    out, t_evidence, t_direct = [], None, None
    prev_view = {}
    was_candidate = set()  # objects that were a named target or the answer at an earlier step
    for st in sorted(record["steps"], key=lambda s: s["step"]):
        t = st["step"]
        step_text = (returns_text or {}).get(t, "")
        gold_first_here = gold_hit(gold, step_text) and not gold_hit(gold, seen_text)
        seen_text += " " + step_text
        for ev in st.get("evidence", []):
            ev = dict(ev, about=canon(ev.get("about"), known), step=t)
            registry[ev["key"]] = ev
        targets = []
        for tg in st.get("targets", []):
            obj = canon(tg.get("object"), known)
            for c in (tg.get("conditions") or ["∅"]):
                targets.append((obj, c, bool((tg.get("restriction") or "").strip())))
        before = {k: v["status"] for k, v in ledger.items()}
        settled = {k for k, v in ledger.items() if v["status"] in ("✔", "✘") and v.get("direct")}
        prev_answer = chain.get("answer")
        # adoption events
        newly = []
        for key, v in (st.get("verdicts") or {}).items():
            verdict = v.get("verdict") if isinstance(v, dict) else v
            if verdict == "采纳":
                newly.append(key)
            elif key in registry:
                ignored[key] = (t, verdict)
        corrected = [k for k in st.get("earlier_adopted", []) if k in ignored]
        newly += [k for k in st.get("earlier_adopted", []) if k in registry]
        changed = False
        for key in newly:
            if key in adopted or key not in registry:
                continue
            adopted.add(key)
            ev = registry[key]
            for cc in ev.get("conditions", []):
                slot = (ev["about"], cc["id"])
                status = "✘" if cc.get("effect") == "冲突" else "✔"
                cur = ledger.get(slot)
                if cur is None or (status == "✘" and cur["status"] != "✘"):
                    ledger[slot] = {"status": status, "evidence": [key], "direct": ev.get("strength") == "直接"}
                    changed = True
                elif cur["status"] == status and key not in cur["evidence"]:
                    cur["evidence"].append(key)
                    cur["direct"] = cur["direct"] or ev.get("strength") == "直接"
        # exclusions and chain
        excl_now = []  # only first-time exclusions count; restating an earlier exclusion is not a new event
        excl_role = []  # "X is not the asked kind of thing" while X sits in this step's answer chain: a role, not a rejection
        ac_now = st.get("answer_chain") or {}
        chain_now = [n for n in [ac_now.get("answer")] + [l.get("object") for l in ac_now.get("linked", [])] if n]
        for ex in st.get("excluded", []):
            obj = canon(ex.get("object"), known)
            if any(same(obj, m) or same(ex.get("object"), m) for m in chain_now):
                excl_role.append(obj)
                continue
            if obj in excluded:
                continue
            excluded[obj] = t
            excl_now.append(dict(ex, object=obj))
        readmitted = False
        if st.get("answer_chain") is not None:
            ac = st["answer_chain"]
            new_chain = {"answer": canon(ac.get("answer"), known) if ac.get("answer") else None,
                         "linked": [dict(l, object=canon(l.get("object"), known)) for l in ac.get("linked", [])]}
            if not new_chain["answer"]:
                new_chain["linked"] = []  # no candidate yet: there is no chain for objects to be linked to
            # linked objects carry forward while the answer stays the same (unless excluded now)
            if new_chain["answer"] and new_chain["answer"] == chain.get("answer"):
                have = {l["object"] for l in new_chain["linked"]}
                for l in chain["linked"]:
                    if l["object"] not in have and l["object"] not in {e["object"] for e in excl_now}:
                        new_chain["linked"].append(l)
            old_members = {chain.get("answer")} | {l["object"] for l in chain.get("linked", [])}
            members = [new_chain["answer"]] + [l["object"] for l in new_chain["linked"]]
            back = [m for m in members if m and m not in old_members and m in excluded and excluded[m] < t]
            readmitted = bool(back)
            for m in back:  # re-entering the answer chain lifts the exclusion
                excluded.pop(m, None)
            chain = new_chain
        members = [m for m in [chain["answer"]] + [l["object"] for l in chain["linked"]] if m]
        view = {}
        for c in conds:
            pool = [chain["answer"]] if c == "A" else members
            stats = [ledger[(m, c)] for m in pool if (m, c) in ledger]
            if c == "A" and not stats and chain.get("answer"):
                # the asked item counts as established once the answer itself has adopted supporting evidence
                stats = [v for (m, cc), v in ledger.items() if m == chain["answer"] and v["status"] == "✔"]
            if any(s["status"] == "✘" for s in stats):
                view[c] = ("✘", sorted({e for s in stats if s["status"] == "✘" for e in s["evidence"]}), False)
            elif stats:
                view[c] = ("✔", sorted({e for s in stats for e in s["evidence"]}), any(s["direct"] for s in stats))
            else:
                view[c] = ("○", [], False)
        # mechanisms
        labels = []
        answer_changed = chain.get("answer") != prev_answer
        progress = changed or (answer_changed and bool(newly)) or any(
            e.get("basis") == "条件" and e.get("valid") == "成立" and e["object"] in was_candidate for e in excl_now)
        if progress:
            labels.append("有进展")
        key_labels = []
        for obj, c, restricted in targets:
            tags = set()
            if obj != UNKNOWN and (obj, c) in settled:  # only a directly settled condition makes re-checking redundant
                tags.add("重复核实")
            if c == "∅":
                tags.add("查没问的")
            if (obj, c) in seen_keys and not progress:
                tags.add("原地打转")
            if restricted:
                tags.add("自加限定")
            if obj in excluded and excluded[obj] < t and not readmitted:
                tags.add("追已排除")
            key_labels.append(tags)
            seen_keys.setdefault((obj, c), t)
        for tags in key_labels:
            for x in sorted(tags):
                if x not in labels:
                    labels.append(x)
        missed, missed_gold, unused = [], [], []
        holds_gold = bool(gold) and same(chain.get("answer"), gold)
        for key, (ts, verdict) in ignored.items():
            if ts != t or key in adopted:
                continue
            ev = registry[key]
            ev_conds = {cc["id"] for cc in ev.get("conditions", [])}
            supports = any(cc.get("effect") == "支持" for cc in ev.get("conditions", []))
            if supports and any(ev["about"] == obj or (obj == UNKNOWN and c in ev_conds) for obj, c, _ in targets):
                missed.append(key)  # v13.1: only an ignored supporting fact is a missed clue
            if ev["about"] in members and ev_conds:
                unused.append(key)  # evidence about the held answer chain, not taken up
            if gold and not holds_gold and ev.get("text") and norm(gold) and norm(gold) in norm(ev["text"]):
                missed_gold.append(key)
        def had_clue(o):  # some returned fact supported this object
            return any(same(ev["about"], o) and any(cc.get("effect") == "支持" for cc in ev.get("conditions", []))
                       for ev in registry.values())
        bad_excl = [e for e in excl_now if (e.get("basis") in ("题外", "无依据") or e.get("valid") == "不成立") and had_clue(e["object"])]
        for e in excl_now:
            ev_text = " ".join(registry[k].get("text", "") for k in registry if registry[k]["about"] == e["object"])
            if gold and not holds_gold and (same(e["object"], gold) or (norm(gold) and norm(gold) in (norm(ev_text) or ""))):
                missed_gold.append("排除:" + e["object"])
        if missed or bad_excl:
            labels.append("放过线索")
        if gold_first_here and not holds_gold and not missed_gold:
            missed_gold.append("返回:" + str(gold))
        if missed_gold:
            labels.append("放过正确线索")
        if unused:
            labels.append("漏采证据")
        if corrected or readmitted:
            labels.append("改正")
        if any(v[0] == "✘" for v in prev_view.values()) and not answer_changed and chain.get("answer"):
            labels.append("冲突不改")
        unsupported = []
        for a in st.get("assertions", []):
            docs = {str(ev.get("doc")) for ev in registry.values()}
            toks = [x for x in a.get("tokens", []) if str(x).strip() and str(x).strip() not in docs]
            if not toks or not any(norm(x) and norm(x) in (norm(seen_text) or "") for x in toks):
                unsupported.append(a)
        if unsupported:
            labels.append("无据断言")
        if st.get("plan_match") == "不一致":
            labels.append("计划不符")
        if st.get("strict"):
            labels.append("严格重复")
        if t_evidence is None and conds and all(view[c][0] == "✔" for c in conds):
            t_evidence = t
        if t_direct is None and conds and all(view[c][0] == "✔" and view[c][2] for c in conds):
            t_direct = t
        position = []
        if group == "C" and t_evidence is not None and t > t_evidence:
            position.append("已够还查")
        if group == "C" and t_belief is not None and t > t_belief and (t_evidence is None or t <= t_evidence):
            position.append("信念后核实")
        if group == "N" and t_belief is not None and t > t_belief:
            position.append("有证据不交卷")
        if progress:
            tier = "有进展"
        elif st.get("strict") or (key_labels and all(tags & {"重复核实", "查没问的"} for tags in key_labels)):
            tier = "冗余"
        elif any("自加限定" in tags for tags in key_labels):
            tier = "跑偏"
        else:
            tier = "无进展"
        out.append({"step": t, "targets": targets, "adopted_now": newly, "ignored_now": [k for k, v in ignored.items() if v[0] == t],
                    "excluded_now": excl_now, "excluded_role_only": excl_role, "chain": chain, "view": view, "labels": labels, "position": position,
                    "tier": tier, "missed": missed, "missed_gold": missed_gold, "unused": unused, "unsupported": unsupported})
        prev_view = view
        was_candidate |= {o for o, _, _ in targets if o != UNKNOWN}
        if chain.get("answer"):
            was_candidate.add(chain["answer"])
    return {"steps": out, "t_evidence": t_evidence, "t_evidence_direct": t_direct}


def summary_lines(record, result):
    """前文摘要: one line per finished step, fed to the next calls."""
    lines = []
    for st, rs in zip(sorted(record["steps"], key=lambda s: s["step"]), result["steps"]):
        tg = "；".join(f"{x.get('object')}｜{' '.join(x.get('conditions') or ['没问'])}"
                      + (f"（限定 {x['restriction']}）" if (x.get('restriction') or '').strip() else "")
                      for x in st.get("targets", []))
        ev = "；".join(f"{e['key']} 关于 {e.get('about')}：{e.get('fact', '')}（{e.get('strength')}）" for e in st.get("evidence", []))
        hd = [f"{k} {(v.get('verdict') if isinstance(v, dict) else v)}" for k, v in (st.get("verdicts") or {}).items()]
        hd += [f"{k} 现在采纳" for k in st.get("earlier_adopted", [])]
        hd += [f"排除 {e.get('object')}（{e.get('reason', '')}）" for e in st.get("excluded", [])]
        view = " ".join(f"{c}{v[0]}" for c, v in rs["view"].items())
        lines.append(f"#{st['step']}｜想查 {tg or '—'}｜查询 {st.get('query', '')}｜证据 {ev or '无'}｜处理 {'；'.join(hd) or '无'}"
                     f"｜答案链 {rs['chain']['answer'] or '—'}｜状态 {view}")
    return lines


def render(record, result, title):
    reg = {}
    lines = [f"# {title}", ""]
    for st, rs in zip(sorted(record["steps"], key=lambda s: s["step"]), result["steps"]):
        t = st["step"]
        lines.append(f"## #{t}")
        tg = "；".join(f"{x['object']}｜{' '.join(x.get('conditions') or ['（没问）'])}"
                      + (f"（限定：{x['restriction']}）" if (x.get('restriction') or '').strip() else "")
                      for x in st.get("targets", []))
        lines += [f"- 想查：{tg}" + ("；计划不符" if st.get("plan_match") == "不一致" else ""),
                  f"- 查询：{st.get('query', '')}",
                  f"- 返回：新 {st.get('new_docs', '?')} 旧 {st.get('old_docs', '?')}"]
        for ev in st.get("evidence", []):
            reg[ev["key"]] = ev
            cs = "、".join(f"{c['id']}{'+' if c.get('effect') == '支持' else '−'}" for c in ev.get("conditions", [])) or "无条件"
            lines.append(f"  - {ev['key']} [{ev['doc']}] {ev.get('fact', '')}（关于 {ev.get('about')}；{cs}；{ev.get('strength')}）")
        hd = []
        for k, v in (st.get("verdicts") or {}).items():
            verdict = v.get("verdict") if isinstance(v, dict) else v
            reason = v.get("reason") if isinstance(v, dict) else ""
            hd.append(f"{k} {verdict}" + (f"（{reason}）" if reason else ""))
        hd += [f"{k} 现在采纳" for k in st.get("earlier_adopted", [])]
        hd += [f"排除 {e['object']}（{e.get('reason', '')}；依据 {e.get('basis')}"
               + (f" {' '.join(e.get('basis_conditions') or [])}" if e.get('basis') == '条件' else "")
               + f"；理由{e.get('valid')}）" for e in st.get("excluded", [])]
        lines.append("- 处理：" + ("；".join(hd) if hd else "无"))
        ch = rs["chain"]
        lines.append("- 答案链：" + (ch["answer"] or "—") + ("（相连：" + "、".join(f"{l['object']}[{' '.join(l.get('conditions') or [])}]" for l in ch["linked"]) + "）" if ch["linked"] else ""))
        lines.append("- 状态：" + " ".join(f"{c} {v[0]}" + (f"({','.join(v[1])})" if v[1] else "") for c, v in rs["view"].items()))
        if rs["unsupported"]:
            lines.append("- 无据断言：" + "；".join(a["claim"] for a in rs["unsupported"]))
        lines.append("- 机制：" + ("、".join(rs["labels"] + rs["position"]) or "—") + f"。档位 {rs['tier']}")
        lines.append("")
    return "\n".join(lines) + "\n"
