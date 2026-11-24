"""Validate scoped chain judgments and derive v10 mechanisms without model calls."""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import re
import unicodedata

KINDS = {"条件", "中间", "自加限定", "没问"}
STATUSES = {"确认", "冲突", "未确认"}
VERDICTS = {"采纳", "否定", "没理会"}
MECHANISMS = ("有进展","重复核实","原地打转","放过线索","放过正确线索","改正","冲突不改",
              "无据断言","自加限定","查没问的","追已排除","计划不符","严格重复","已够还查",
              "信念后核实","有证据不交卷")


def text(x):
    return isinstance(x, str) and bool(x.strip())


def texts(x, allowed, *, nonempty=False):
    return isinstance(x,list) and (bool(x) or not nonempty) and all(text(v) and v in allowed for v in x)


def records(value, name, errors, nonempty=False):
    rows=value.get(name)
    if not isinstance(rows,list) or (nonempty and not rows):
        errors.append(f"{name} 必须是{'非空' if nonempty else ''}数组")
        return []
    if not all(isinstance(row,dict) for row in rows):
        errors.append(f"{name} 中每项都必须是对象")
        return []
    return rows


def action_errors(value, conditions, thought):
    if not isinstance(value,dict):
        return ["输出必须是 JSON 对象"]
    errors=[]
    for i,op in enumerate(records(value,"targets",errors,True),1):
        kind=op.get("kind")
        if not isinstance(kind,str) or kind not in KINDS or not text(op.get("object")):
            errors.append(f"targets[{i}] 需要合法 kind 和非空 object")
        if not texts(op.get("conditions"),conditions,nonempty=kind=="条件"):
            errors.append(f"targets[{i}] 的条件编号非法或缺失")
        if kind!="条件" and not text(op.get("what")):
            errors.append(f"targets[{i}] 非条件类型须给出 what")
        if not texts(op.get("ids"),thought):
            errors.append(f"targets[{i}] 引用不存在的 P 句子")
    if not texts(value.get("plan_ids"),thought):
        errors.append("plan_ids 引用不存在的 P 句子")
    if value.get("plan_match") not in ("一致","不一致","思考没说"):
        errors.append("plan_match 不合法")
    if not text(value.get("looking_for")) or not isinstance(value.get("plan_note"),str):
        errors.append("需要 looking_for 和 plan_note")
    return errors


def fact_errors(value, conditions, documents):
    if not isinstance(value,dict):
        return ["输出必须是 JSON 对象"]
    errors=[]
    for i,row in enumerate(records(value,"facts",errors),1):
        if not texts(row.get("ids"),documents,nonempty=True):
            errors.append(f"facts[{i}] 必须引用本步新文档中存在的句子")
        if not texts(row.get("conditions"),conditions):
            errors.append(f"facts[{i}] 的条件编号不合法")
        if row.get("strength") not in ("直接","推断") or not text(row.get("fact")) or not text(row.get("about")):
            errors.append(f"facts[{i}] 需要合法强度、fact 和 about")
    return errors


def materialize(value, documents, step):
    facts=[]
    for i,item in enumerate(value["facts"],1):
        row={k:item[k] for k in ("fact","ids","about","conditions","strength")}
        row["id"]=f"E{i}@{step}"
        row["quotes"]=[{"id":sid,"docid":documents[sid][0],"text":documents[sid][1]}
                       for sid in dict.fromkeys(row["ids"])]
        facts.append(row)
    return facts


def adoption_errors(value, conditions, fresh, pending, adopted, thought):
    if not isinstance(value,dict):
        return ["输出必须是 JSON 对象"]
    errors=[]
    current={e["id"] for e in fresh}
    seen=[]
    accepted=set(adopted)
    for row in records(value,"evidence",errors):
        eid,status=row.get("id"),row.get("verdict")
        if text(eid):
            seen.append(eid)
        if not text(eid) or eid not in current or not isinstance(status,str) or status not in VERDICTS:
            errors.append("verdict 包含非法的本步证据编号或裁决")
        elif status=="采纳":
            accepted.add(eid)
        if status=="否定":
            basis=row.get("basis")
            if not text(row.get("reason")) or basis not in ("条件","题外","无依据") or row.get("valid") not in ("成立","不成立","看不出"):
                errors.append(f"{eid} 的否定裁决须填写 reason、basis、valid")
            if not texts(row.get("basis_conditions",[]),conditions,nonempty=basis=="条件"):
                errors.append(f"{eid} 的否定依据缺少合法条件编号")
        if not texts(row.get("ids"),thought):
            errors.append(f"{eid} 引用不存在的思考或答案句子")
    if Counter(seen)!=Counter(current):
        errors.append("本步每条证据必须恰好有一条 verdict")
    older=set()
    for row in records(value,"earlier_adopted",errors):
        eid=row.get("id")
        if not text(eid) or eid not in pending or eid in older:
            errors.append("earlier_adopted 限用不重复的此前未采纳证据")
        else:
            older.add(eid)
        if not texts(row.get("ids"),thought):
            errors.append(f"{eid} 引用不存在的思考或答案句子")
    accepted.update(older)
    seen=[]
    for row in records(value,"table",errors):
        cid,status=row.get("condition"),row.get("status")
        if text(cid):
            seen.append(cid)
        if not isinstance(status,str) or status not in STATUSES:
            errors.append(f"{cid} 状态不合法")
        if not texts(row.get("evidence"),accepted,nonempty=status in ("确认","冲突")):
            errors.append(f"{cid} 确认或冲突必须引用已采纳的证据")
    if Counter(seen)!=Counter(conditions):
        errors.append("table 必须恰好覆盖每个条件一次")
    for row in records(value,"assertions",errors):
        if not text(row.get("claim")) or not texts(row.get("conditions"),conditions) or not texts(row.get("ids"),thought):
            errors.append("assertions 需要非空 claim、合法条件编号和思考/答案句子编号")
    return list(dict.fromkeys(errors))


def blank_table(conditions):
    return [{"condition":cid,"status":"未确认","evidence":[]} for cid in conditions]


def adopt_step(reply, fresh, pending, adopted):
    """Carry valid evidence verdicts forward and retain unjudged evidence for later review."""
    acquired=set(adopted)
    deferred=dict(pending)
    by_id={v["id"]:v["verdict"] for v in reply["evidence"]} if reply else {}
    for item in fresh:
        eid=item["id"]
        if by_id.get(eid)=="采纳":
            acquired.add(eid)
        else:
            deferred[eid]=item
    for row in reply["earlier_adopted"] if reply else []:
        acquired.add(row["id"])
        deferred.pop(row["id"])
    return deferred,acquired


def norm(v):
    return " ".join(unicodedata.normalize("NFKC",v or "").casefold().split())


def candidate_same(a,b):
    def key(v):
        return " ".join(re.findall(r"\w+",re.sub(r"\([^)]*\)"," ",norm(v))))
    a,b=key(a),key(b)
    short,long=sorted((a.split(),b.split()),key=len)
    return a==b or bool(short and long and len(short)<len(long) and short[-1]==long[-1] and set(short)<=set(long))


def target_keys(targets):
    return {(norm(t["object"]),t["kind"],cid)
            for t in targets for cid in (t["conditions"] if t["kind"]=="条件" else [""])}


def target_signature(action):
    if action is None:
        return None
    return sorted((norm(t["object"]),t["kind"],tuple(sorted(set(t["conditions"]))),norm(t.get("what")))
                  for t in action["targets"])


def condition_status(rows):
    return {r["condition"]:r["status"] for r in rows}


def derive(steps, conditions, belief, submitted, gold_supported, *, correct_submission=False):
    # The fixed condition table includes A, so sufficiency requires A too.
    evidence_point=direct_point=None
    sources={}
    seen_targets=set()
    processed=[]
    for stage in steps:
        t=stage["step"]
        current={e["id"]:e for e in stage["new_evidence"]}
        sources.update(current)
        status=condition_status(stage["table"])
        before=condition_status(stage["before_table"])
        same_answer=candidate_same(stage["candidate_before"],stage["candidate_after"])
        changed=status!=before
        if status and set(status)==set(conditions) and all(v=="确认" for v in status.values()):
            if evidence_point is None:
                evidence_point=t
            if direct_point is None and all(any(sources[e]["strength"]=="直接" for e in r["evidence"])
                                             for r in stage["table"]):
                direct_point=t
        action=stage["action"] or {}
        targets=action.get("targets",[])
        keys=target_keys(targets)
        checked=[z for z in targets if z["kind"]=="条件"]
        repeated=[z for z in checked if same_answer and all(before[c] in ("确认","冲突") for c in z["conditions"])]
        ignored=[]
        valid_rejection=False
        adopted_now=bool(stage["earlier_adopted"])
        for decision in stage["verdicts"]:
            v=decision["verdict"]
            if v=="采纳":
                adopted_now=True
            if v=="否定" and decision.get("basis")=="条件" and decision.get("valid")=="成立":
                valid_rejection=True
            item=current[decision["id"]]
            if item["conditions"] and (v=="没理会" or v=="否定" and (
                decision.get("basis") in ("题外","无依据") or decision.get("valid")=="不成立")):
                ignored.append(item["id"])
        progress=changed or adopted_now and not same_answer or valid_rejection
        strict=bool(stage["strict"])
        extra=any(x["kind"]=="自加限定" for x in targets)
        outside=[x for x in targets if x["kind"]=="没问"]
        final=stage is steps[-1] and submitted
        marks={
            "有进展":progress,
            "重复核实":bool(repeated),
            "原地打转":not changed and bool(keys & seen_targets),
            "放过线索":bool(ignored),
            "放过正确线索":any(gold_supported(current[e]) for e in ignored),
            "改正":bool(stage["earlier_adopted"]),
            "冲突不改":"冲突" in status.values() and (same_answer or final),
            "无据断言":bool(stage["assertions"]),
            "自加限定":extra,
            "查没问的":bool(outside),
            "追已排除":any(candidate_same(z["object"],name) for z in targets for name in stage["excluded_before"]),
            "计划不符":action.get("plan_match")=="不一致",
            "严格重复":strict,
            "已够还查":evidence_point is not None and t>evidence_point,
            "信念后核实":correct_submission and belief is not None and t>belief and (evidence_point is None or t<=evidence_point),
            "有证据不交卷":not submitted and belief is not None and t==belief,
        }
        seen_targets.update(keys)
        if progress:
            tier="有进展"
        elif strict or checked and len(repeated)==len(checked) or targets and len(outside)==len(targets):
            tier="冗余"
        else:
            tier="跑偏" if extra else "无进展"
        processed.append({**stage,"tier":tier,"mechanisms":[k for k,v in marks.items() if v],
                         "ignored_evidence":ignored,"ignored_correct_evidence":[e for e in ignored if gold_supported(current[e])],
                         "table_changed":changed,"supporting_step":evidence_point,
                         "direct_supporting_step":direct_point})
    return {"steps":processed,"belief_point":belief,"evidence_point":evidence_point,"direct_evidence_point":direct_point,
            "unsubmitted_after_belief":not submitted and belief is not None,
            "unsubmitted_after_evidence":not submitted and evidence_point is not None,
            "conflict_at_submission":bool(submitted and steps and "冲突" in condition_status(steps[-1]["table"]).values())}


def align_evidence(left,right):
    candidates=[]
    for a in left:
        x=set(a["ids"])
        for b in right:
            y=set(b["ids"])
            overlap=len(x & y)
            if overlap:
                candidates.append((x==y,Fraction(overlap,len(x|y)),overlap,a["id"],b["id"]))
    used_a,used_b=set(),set()
    pairs=[]
    for _,_,_,a,b in sorted(candidates,key=lambda v:(-v[0],-v[1],-v[2],v[3],v[4])):
        if a not in used_a and b not in used_b:
            used_a.add(a)
            used_b.add(b)
            pairs.append([a,b])
    return pairs


def compare(left,right):
    totals={k:[0,0] for k in ("evidence_verdict","table_cells","table_steps","targets","tiers")}
    mech={key:[0,0] for key in MECHANISMS}
    pairs=[]
    with_labels=0
    def count(key,same,num=1):
        totals[key][0]+=same
        totals[key][1]+=num
    for a,b in zip(left,right,strict=True):
        assert a["step"]==b["step"]
        ids=align_evidence(a["new_evidence"],b["new_evidence"])
        av,bv=({r["id"]:r["verdict"] for r in row["verdicts"]} for row in (a,b))
        for u,v in ids:
            valid=u in av and v in bv
            with_labels+=valid
            count("evidence_verdict",valid and av[u]==bv[v],int(valid))
            pairs.append({"step":a["step"],"a":u,"b":v,"verdict_a":av.get(u),"verdict_b":bv.get(v)})
        x,y=(condition_status(z["table"]) for z in (a,b))
        assert x.keys()==y.keys()
        count("table_cells",sum(x[i]==y[i] for i in x),len(x))
        count("table_steps",x==y)
        ax,bx=(target_signature(z["action"]) for z in (a,b))
        count("targets",ax is not None and ax==bx)
        count("tiers",a["tier"]==b["tier"])
        one,two=set(a["mechanisms"]),set(b["mechanisms"])
        for tag in MECHANISMS:
            mech[tag][0]+=tag in one & two
            mech[tag][1]+=tag in one | two
    return {**totals,"mechanisms":mech,"evidence_pairs":pairs,"matched_evidence":len(pairs),
            "verdict_pairs":with_labels,
            "evidence_totals":[sum(len(s["new_evidence"]) for s in seq) for seq in (left,right)]}
