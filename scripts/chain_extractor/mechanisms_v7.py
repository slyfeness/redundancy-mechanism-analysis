"""Count v7 mechanisms from stored state, source call coordinates and receipts."""
import re
from statistics import median

from chain_extractor_v7 import candidate_equivalent


STEP_FLAGS = (
    "state_changed", "progress", "zero_new_documents", "strict_repeat", "stagnation",
    "gap_a", "gap_b", "strict_sufficient_at", "practical_sufficient_at",
    "after_strict", "after_strict_unchanged", "after_strict_zero_new",
    "after_practical", "after_practical_unchanged", "after_practical_zero_new",
    "evidence_no_submission_at", "unsupported_claims", "correction", "plan_action_mismatch",
)
CONDITION_FLAGS = ("adoption", "unadopted")
TRAJECTORY_FLAGS = ("zero_calls", "strict_sufficient_at", "practical_sufficient_at", "evidence_no_submission")


def current(row):
    return next((x["name"] for x in row["state"]["candidates"] if x["status"]=="当前"),None)


def candidates_equal(first, second):
    if len(first)!=len(second):
        return False
    match={}
    def visit(i,seen):
        a=first[i]
        for j,b in enumerate(second):
            if j in seen or a["status"]!=b["status"] or not candidate_equivalent(a["name"],b["name"]):
                continue
            seen.add(j)
            if j not in match or visit(match[j],seen):
                match[j]=i
                return True
        return False
    return all(visit(i,set()) for i in range(len(first)))


def state_changed(before, after):
    a,b=before["state"],after["state"]
    return set(a["confirmed"])!=set(b["confirmed"]) or not candidates_equal(a["candidates"],b["candidates"])


def same_checking(value):
    return " ".join(value.casefold().split()) if isinstance(value,str) else ""


def initial_row():
    return {"state":{"candidates":[],"confirmed":[],"open":[]},"checking_object":None}


def answer_forms(lines):
    forms=[]
    for line in lines:
        body=re.sub(r"^\s*(?:\*\*)?(?:final\s+answer|exact\s+answer|answer)\s*:\s*(?:\*\*)?\s*",
                    "",line,flags=re.IGNORECASE).strip()
        if not body:
            continue
        forms.append(body)
        bold=re.findall(r"\*\*(.+?)\*\*",body)
        if len(bold)==1:
            forms.append(bold[0])
    return list(dict.fromkeys(forms))


def derive(states, ordinary, doc_counts, strict, plans, facts, unsupported, answer_lines, terminal):
    assert [row["stage"] for row in states]==list(range(len(states)))
    assert states[0]["type"]=="start" and states[-1]["type"]=="final"
    ordinary=set(ordinary)
    kind=states[-1].get("answer_kind")
    answers=answer_forms(answer_lines) if kind=="作答" else []
    total_calls=len(states)-2
    steps=[]
    first_fact={}
    first_confirm={}
    strict_at=practical_at=no_submission_at=None
    no_submission_name=None
    segments=[]
    segment=[]
    def close_segment():
        if len(segment)>=2:
            segments.append({"start":segment[0],"end":segment[-1],"length":len(segment)})
            for idx in segment:
                steps[idx]["stagnation"]=True
        segment.clear()
    before=initial_row()
    for row in states:
        idx=row["stage"]
        active=current(row)
        pre_current=current(before)
        pre_conf=set(before["state"]["confirmed"])
        confirmations=set(row["state"]["confirmed"])
        changed=state_changed(before,row)
        record={"stage":idx,"type":row["type"],"state_changed":changed,
                "unsupported_claims":unsupported.get(idx,0)}
        steps.append(record)
        if row["type"] in ("start","call"):
            for cid in confirmations & ordinary:
                first_confirm.setdefault(cid,idx)
        if row["type"]=="call":
            evidence=sorted(facts.get(idx,set()) & ordinary)
            for cid in evidence:
                first_fact.setdefault(cid,idx)
            this_excluded=[c["name"] for c in row["state"]["candidates"] if c["status"]=="已排除"]
            prev_excluded=[c["name"] for c in before["state"]["candidates"] if c["status"]=="已排除"]
            new_excluded=[name for name in this_excluded
                          if not any(candidate_equivalent(name,ex) for ex in prev_excluded)]
            checking=same_checking(row.get("checking_object"))
            new_document_count=doc_counts[idx]
            zero=new_document_count==0
            enough=bool(ordinary) and len(confirmations & ordinary)*2>=len(ordinary)
            if strict_at is None and active and ordinary and ordinary<=confirmations:
                strict_at=idx
            if practical_at is None and active and enough and any(candidate_equivalent(active,x) for x in answers):
                practical_at=idx
            if no_submission_at is None and kind=="未交卷" and active and enough:
                no_submission_at=idx
                no_submission_name=active
            record.update(
                progress=bool(active and not candidate_equivalent(active,pre_current) or confirmations-pre_conf or new_excluded),
                progress_new_current=bool(active and not candidate_equivalent(active,pre_current)),
                progress_new_confirmations=sorted(confirmations-pre_conf),
                progress_new_excluded=new_excluded,
                new_document_count=new_document_count,zero_new_documents=zero,
                strict_repeat=bool(strict.get(idx)),strict_repeat_event_ids=strict.get(idx,[]),
                stagnation=False,
                gap_a=bool(not changed and checking and checking==same_checking(before.get("checking_object"))),
                gap_b=not changed and zero,
                strict_sufficient_at=strict_at==idx,practical_sufficient_at=practical_at==idx,
                evidence_no_submission_at=no_submission_at==idx,
                relevant_new_fact_conditions=evidence,
                correction=bool(pre_conf-confirmations or pre_current and any(
                    candidate_equivalent(pre_current,x) for x in this_excluded)),
                retracted_conditions=sorted(pre_conf-confirmations),
                plan_action_mismatch=plans.get(idx)=="不一致",
            )
            for key,at in (("strict",strict_at),("practical",practical_at)):
                after=at is not None and idx>at
                record.update({f"after_{key}":after, f"after_{key}_unchanged":after and not changed,
                               f"after_{key}_zero_new":after and zero})
            if changed:
                close_segment()
            else:
                segment.append(idx)
        before=row
    close_segment()
    adoption={}
    for cid in sorted(ordinary):
        f,g=first_fact.get(cid),first_confirm.get(cid)
        outcome={"id":cid,"first_relevant_fact":f,"first_confirmation":g,
                 "delay":g-f if f is not None and g is not None else None}
        adoption[cid]=outcome
        if f is not None:
            steps[f].setdefault("unadopted" if g is None else "adoption",[]).append(outcome)
    withheld=None
    if no_submission_at is not None:
        withheld={"first_step":no_submission_at,"following_steps":total_calls-no_submission_at,
                  "candidate":no_submission_name,"candidate_kept":all(
                      candidate_equivalent(no_submission_name,current(row)) for row in states[no_submission_at:])}
    trajectory={"answer_kind":kind,"termination_reason":terminal,"zero_calls":total_calls==0,
                "strict_sufficient_at":strict_at,"practical_sufficient_at":practical_at,
                "practical_retrospective":True,"evidence_no_submission":withheld,
                "stagnation_segments":segments,"adoption":adoption}
    return {"steps":steps,"trajectory_events":trajectory}


def event_coords(row, name):
    if name in CONDITION_FLAGS:
        return {(s["stage"],x["id"]) for s in row["steps"] for x in s.get(name,[])}
    return {s["stage"] for s in row["steps"] if s.get(name)}


def has_trajectory_event(row, name):
    value=row["trajectory_events"].get(name)
    return bool(value) if name=="zero_calls" else value is not None


def agreed_events(first, second):
    shared={}
    for name in (*STEP_FLAGS,*CONDITION_FLAGS):
        both=event_coords(first,name) & event_coords(second,name)
        if both:
            shared[name]=sorted(both)
    a,b=first["trajectory_events"],second["trajectory_events"]
    whole={name:{"R1":a[name],"R2":b[name]} for name in TRAJECTORY_FLAGS
           if has_trajectory_event(first,name) and has_trajectory_event(second,name)}
    for name in ("answer_kind","termination_reason"):
        if a.get(name) is not None and a.get(name)==b.get(name):
            whole[name]=a[name]
    segment_stages={(x["start"],x["end"]) for x in a["stagnation_segments"]}
    overlap=segment_stages & {(x["start"],x["end"]) for x in b["stagnation_segments"]}
    return {"step_events":shared,"trajectory_events":whole,"exact_stagnation_segments":sorted(overlap)}


def comparison(first, second, first_events, second_events=None):
    a={row["stage"]:row for row in first}
    b={row["stage"]:row for row in second}
    assert a.keys()==b.keys()
    changed_a={row["stage"]:row["state_changed"] for row in first_events["steps"]}
    changed_b=({row["stage"]:row["state_changed"] for row in second_events["steps"]} if second_events else
               {i:row["state_changed"] for i,row in b.items()})
    return [{"stage":i,"type":row["type"],"candidate_same":candidate_equivalent(current(row),current(b[i])),
             "confirmed_same":set(row["state"]["confirmed"])==set(b[i]["state"]["confirmed"]),
             "state_changed_same":changed_a[i]==changed_b[i]} for i,row in a.items()]


def markdown_table(header, rows):
    return ["|"+"|".join(header)+"|","|"+"|".join("---" for _ in header)+"|",
            *("|"+"|".join(map(str,row))+"|" for row in rows)]


def render_mechanisms(runs):
    lines=["# v7 机制计数","","调用环是步级单位。同轮并行调用合成一步；严格重复的原事件编号逐条保存。",
           "凭空认定统计起点、调用环和终点。表中为发生步数，另列条数。采纳按首次相关事实的步号和条件编号对齐，延迟保留负值。",
           "实用充分点是事后口径。两个充分点之后的计数均从下一调用环开始。",
           "两遍在同一坐标出现计为一致。轨迹级存在可以在不同步首次发生。停滞步在两遍均属于停滞段时计一致。",""]
    by_group={g:[r for r in runs if r["group"]==g] for g in ("C","W","N")}
    table=[]
    for name in (*STEP_FLAGS,*CONDITION_FLAGS):
        for group, items in by_group.items():
            count={key:0 for key in ("R1","R2","both","trajectories")}
            for item in items:
                a,b=(event_coords(item[key],name) for key in ("R1","R2"))
                def step_count(coordinates):
                    return len({coord[0] for coord in coordinates}) if name in CONDITION_FLAGS else len(coordinates)
                count["R1"]+=step_count(a)
                count["R2"]+=step_count(b)
                count["both"]+=step_count(a & b)
                count["trajectories"]+=bool(a & b)
            table.append((name,group,*count.values()))
    lines.extend(markdown_table(("步级机制","组","R1","R2","两遍一致","一致轨迹数"),table))
    whole=[]
    for name in TRAJECTORY_FLAGS:
        for group, items in by_group.items():
            vals=[[has_trajectory_event(row[key],name) for key in ("R1","R2")] for row in items]
            whole.append((name,group,sum(a for a,_ in vals),sum(b for _,b in vals),sum(a and b for a,b in vals)))
    for field in ("answer_kind","termination_reason"):
        for group,items in by_group.items():
            values={str(row[run]["trajectory_events"].get(field)) for row in items for run in ("R1","R2")}
            for value in sorted(values):
                vals=[[str(row[key]["trajectory_events"].get(field))==value for key in ("R1","R2")] for row in items]
                whole.append((f"{field}={value}",group,sum(a for a,_ in vals),sum(b for _,b in vals),sum(a and b for a,b in vals)))
    lines+=["","## 轨迹级计数",""]+markdown_table(("机制","组","R1 轨迹","R2 轨迹","一致轨迹数"),whole)
    condition_counts=[]
    for name in CONDITION_FLAGS:
        for group,items in by_group.items():
            sets=[(event_coords(r["R1"],name),event_coords(r["R2"],name)) for r in items]
            condition_counts.append((name,group,sum(len(a) for a,b in sets),sum(len(b) for a,b in sets),
                                     sum(len(a & b) for a,b in sets)))
    lines+=["","## 按条件计的采纳事件",""]+markdown_table(("事件","组","R1","R2","两遍一致"),condition_counts)
    dist=[]
    for group,items in by_group.items():
        for rep in ("R1","R2"):
            values=[r[rep]["trajectory_events"] for r in items]
            delay=[q["delay"] for x in values for q in x["adoption"].values() if q["delay"] is not None]
            durations=[s["length"] for x in values for s in x["stagnation_segments"]]
            claim_count=sum(s["unsupported_claims"] for r in items for s in r[rep]["steps"])
            for name,arr in (("停滞段长度",durations),("采纳延迟",delay)):
                dist.append((name,group,rep,len(arr),min(arr) if arr else "—",median(arr) if arr else "—",
                             max(arr) if arr else "—"))
            dist.append(("无返回依据条数",group,rep,claim_count,"—","—","—"))
    lines+=["","## 分布",""]+markdown_table(("项目","组","遍次","数量","最小","中位数","最大"),dist)
    return "\n".join(lines)+"\n"


def render_agreement(runs):
    lines=["# v7 状态一致记录","","比较同一轨迹同一坐标。调用环单列；起点和终点也逐行保留。",""]
    keys=("candidate_same","confirmed_same","state_changed_same")
    summaries=[]
    details=[]
    for group in ("C","W","N"):
        group_runs=[r for r in runs if r["group"]==group]
        for name in ("R1/R2","R1/REF","R2/REF"):
            extracted=[(r["trajectory_id"],x) for r in group_runs for x in r["comparisons"].get(name,[])]
            for scope in ("调用环","含起终点"):
                rows=[x for _,x in extracted if scope=="含起终点" or x["type"]=="call"]
                n=len(rows)
                summaries.append((group,name,scope,n,*(f"{sum(x[k] for x in rows)}/{n} ({sum(x[k] for x in rows)/n:.1%})"
                                                  if n else "—" for k in keys)))
            for tid,row in extracted:
                details.append((tid,group,name,row["stage"],row["type"],*(int(row[k]) for k in keys)))
    lines+=markdown_table(("组","对照","范围","步数","当前候选","确认集合","状态变化"),summaries)
    lines+=["","## 逐步记录",""]+markdown_table(("轨迹","组","对照","步","类型","候选","确认","变化"),details)
    return "\n".join(lines)+"\n"
