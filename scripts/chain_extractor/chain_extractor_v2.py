"""Extract evidence-checked search trajectory chains one round at a time."""
from argparse import ArgumentParser
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha256
import http.client
import json
from pathlib import Path
import re
import time

from chain_extractor import direct_post, encode, identity, jsonl, load, prepare, replace_text, request_body

def obj(value):
    return value if isinstance(value,dict) else {}

def list_field(value,key):
    data=obj(value).get(key)
    return data if isinstance(data,list) else []

def normalized(text):
    return " ".join(text.casefold().split())

def normalize_return(text):
    # Keep visible words and punctuation. Strip Markdown's formatting markers.
    text=re.sub(r"!?\[([^\]]+)\]\([^)]+\)",r"\1",text)
    text=re.sub(r"(?m)^[ \t]*(?:#{1,6}|[*>+-])[ \t]+","",text)
    text=re.sub(r"(?<!\w)_+|_+(?!\w)|[*\x60~]+","",text)
    return normalized(text)

def check_conditions(question, value):
    entries=list_field(value,"conditions")
    target=normalized(question)
    covered=set()
    missing=[]
    ids=[]
    for index,entry in enumerate(entries,1):
        row=obj(entry)
        cid=row.get("id")
        ids.append(cid)
        claim=row.get("text")
        fragment=normalized(claim) if isinstance(claim,str) else ""
        if not fragment or fragment not in target:
            missing.append(index)
        else:
            # Credit one contiguous occurrence per condition. Duplicate fragments
            # cannot inflate the union by matching other repetitions of the text.
            start=target.index(fragment)
            covered.update(range(start,start+len(fragment)))
    size=sum(not ch.isspace() for ch in target)
    coverage=sum(not target[i].isspace() for i in covered)/size if size else 0.0
    reasons=[]
    if len(entries)<2:
        reasons.append("条件数量少于 2")
    if any(not isinstance(cid,str) or not cid for cid in ids) or len(set(ids))!=len(ids):
        reasons.append("条件编号缺失、非法或重复")
    if missing:
        reasons.append("这些序号未匹配到题面连续原文："+", ".join(map(str,missing)))
    if coverage<0.70:
        reasons.append(f"题面覆盖率 {coverage:.1%}，低于 70%")
    return {"valid":not reasons,"reasons":reasons,"coverage":coverage,"count":len(entries),
            "missing_spans":missing,"asked_count":sum(obj(row).get("asked") is True for row in entries)}

def fallback_conditions(question):
    texts=[line.strip() for line in re.split(r"(?<=[。；;])|(?<=[.!?])(?=\s|$)",question) if line.strip()]
    rows=[{"id":f"c{i}","text":text} for i,text in enumerate(texts,1)]
    if rows:
        rows[-1]["asked"]=True
    return {"conditions":rows}

def audit_quote(quote, source, fuzzy=False):
    wanted=normalize_return(quote) if isinstance(quote,str) else ""
    sources=(source,) if isinstance(source,str) else source
    if not wanted or not sources:
        return {"status":"reject","match_fraction":0.0}
    texts=[normalize_return(text) for text in sources]
    if any(wanted in text for text in texts):
        return {"status":"pass","match_fraction":1.0}
    rate=max(SequenceMatcher(None,wanted,text,autojunk=False).find_longest_match().size
             for text in texts)/len(wanted) if fuzzy else 0.0
    return {"status":"flag" if rate>=0.8 else "reject","match_fraction":rate}

def verified_facts(value, ring):
    documents=[(str(hit["docid"]), normalize_return(hit["snippet"]))
               for call in ring["calls"] for hit in call["returned"] if "snippet" in hit]
    kept=[]
    checks=[]
    for index,item in enumerate(list_field(value,"new_facts")):
        item=obj(item)
        quote=item.get("quote")
        fact=item.get("fact")
        q=normalize_return(quote) if isinstance(quote,str) else ""
        docids=list(dict.fromkeys(docid for docid,text in documents if q and q in text))
        usable=bool(docids) and isinstance(fact,str) and bool(fact.strip())
        checks.append({"phase":"A","field":"new_facts","index":index,"quote":quote,
                       "status":"pass" if docids else "reject","matched_docids":docids,"applied":usable})
        if usable:
            kept.append({"fact":fact,"quote":quote,"docid":docids[0]})
    return kept,checks

def checked_items(value,key,source,phase,fuzzy=False):
    checks=[]
    kept=[]
    for i,item in enumerate(list_field(value,key)):
        row=obj(item)
        quote=row.get("quote")
        result=audit_quote(quote,source,fuzzy)
        checks.append({"phase":phase,"field":key,"index":i,"quote":quote,**result})
        if result["status"]!="reject":
            kept.append(row)
    return kept,checks

def checked_text(value,key,quote_key,source,phase,fuzzy=False):
    v=obj(value)
    quote=v.get(quote_key)
    result=audit_quote(quote,source,fuzzy)
    return (v.get(key) if result["status"]!="reject" else None),{
        "phase":phase,"field":quote_key,"quote":quote,**result}

def state_after(state,candidate_ops,condition_ops,ids):
    candidates={x["name"]:x["status"] for x in state["candidates"]}
    for row in candidate_ops:
        name=row.get("name")
        op=row.get("op")
        if not isinstance(name,str) or not name.strip():
            continue
        name=name.strip()
        existing=next((x for x in candidates if normalized(x)==normalized(name)),name)
        if op=="新增":
            candidates.setdefault(existing,"备选")
        elif op=="设为当前":
            for previous,status in candidates.items():
                if previous!=existing and status=="当前":
                    candidates[previous]="备选"
            candidates[existing]="当前"
        elif op=="设为备选":
            candidates[existing]="备选"
        elif op=="排除":
            candidates[existing]="已排除"
    confirmed=set(state["confirmed"])
    for row in condition_ops:
        key=row.get("id")
        if key in ids:
            if row.get("op")=="确认":
                confirmed.add(key)
            elif row.get("op")=="撤回":
                confirmed.discard(key)
    return {"candidates":[{"name":k,"status":v} for k,v in candidates.items()],
            "confirmed":[x for x in ids if x in confirmed],"open":[x for x in ids if x not in confirmed]}

def judge(folder,key,prompt,payload,cfg,post=None,max_retries=3,extended_max_tokens=None):
    body=request_body(prompt,payload,cfg)
    folder.mkdir(parents=True,exist_ok=True)
    send=post or (lambda url,b:direct_post(url,b,cfg["timeout_seconds"]))
    attempts=[]
    i=1
    expanded=False
    while True:
        path=folder/f"{key}.{i}.json"
        if path.is_file():
            row=load(path)
            if row["request"]!=body:
                raise RuntimeError("requested prompt or payload differs from stored attempt")
        else:
            t=time.monotonic()
            started=datetime.now(timezone.utc).isoformat()
            raw=status=parsed=content=reason=finish=tokens=error=None
            try:
                status,raw=send(cfg["url"],body)
                if status==200:
                    envelope=json.loads(raw)
                    tokens=(envelope.get("usage") or {}).get("completion_tokens")
                    choice=envelope["choices"][0]
                    finish=choice.get("finish_reason")
                    message=choice["message"]
                    reason=message.get("reasoning")
                    if reason is None:
                        reason=message.get("reasoning_content")
                    content=message.get("content")
                    if extended_max_tokens is not None and finish=="length":
                        error="output_length_limit"
                    else:
                        parsed=json.loads(content)
                else:
                    error=f"http_{status}"
            except (OSError,http.client.HTTPException) as exc:
                error=f"transport:{type(exc).__name__}"
            except (ValueError,TypeError,KeyError,IndexError,AttributeError):
                error="json_parse_failed"
            row={"attempt":i,"started_utc":started,"elapsed_seconds":round(time.monotonic()-t,6),
                 "http_status":status,"output_tokens":tokens,"finish_reason":finish,"error":error,
                 "request":body,"raw_response":raw,"reasoning_full":reason,
                 "assistant_content":content,"parsed":parsed}
            replace_text(path,encode(row)+"\n")
        attempts.append(row)
        if row["error"]=="output_length_limit" and not expanded:
            body=request_body(prompt,payload,{**cfg,"max_tokens":extended_max_tokens})
            expanded=True
        elif row["error"]!="json_parse_failed" or expanded or i==max_retries+1:
            return row["parsed"],row["error"],attempts
        i+=1

def extract_conditions(question,prompt,cfg,folder):
    history=[]
    payload={"question":question}
    for attempt in (1,2):
        output,error,rows=judge(folder,f"C{attempt}",prompt,payload,cfg,max_retries=0)
        validation=check_conditions(question,output)
        if error:
            validation["reasons"].insert(0,error)
            validation["valid"]=False
        history.append({"attempt":attempt,"output":output,"validation":validation,"receipt":rows[0]})
        if validation["valid"]:
            return {"conditions":output["conditions"],"attempts":history,"retried":attempt==2,
                    "sentence_fallback":False,"validation":validation}
        payload={"question":question,"previous_validation_errors":validation["reasons"]}
    result=fallback_conditions(question)
    return {**result,"attempts":history,"retried":True,"sentence_fallback":True,
            "validation":check_conditions(question,result)}

def display(value):
    return " ".join(value.split()) if isinstance(value,str) and value.strip() else "—"

def render_chain(start,steps,end):
    lines=["# 思维链","", "## 起点","",f"- 理解：{display(start.get('understanding'))}",
           "- 假设："+("、".join(x for x in list_field(start,"hypotheses") if isinstance(x,str)) or "—"),
           f"- 计划：{display(start.get('plan'))}",""]
    for s in steps:
        lines.extend([f"## 第 {s['stage']} 次调用","",f"- 动作：{display(s['action'])}",
                      *[f"  - 查询：{q}" for q in s["queries"]]])
        if s["plan_mismatch"]:
            lines.append(f"  - 与调用前计划不一致：{display(s['plan_mismatch'])}")
        lines.append(f"- 返回：新文档 {s['new_docs']} 篇、旧文档 {s['old_docs']} 篇")
        for f in s["facts"]:
            lines.append(f"  - {display(f['fact'])}（docid `{f['docid']}`）")
        lines.append(f"- 结论：{display(s['conclusion'])}")
        for claim in s["unsupported"]:
            lines.append(f"  - 无返回依据：{display(claim.get('claim'))}")
        if s["state"]==s["before"]:
            lines.append("- 状态：无变化")
        else:
            state=s["state"]
            names="、".join(f"{c['name']}（{c['status']}）" for c in state["candidates"]) or "—"
            lines.extend([f"- 状态：候选 {names}；已确认 {'、'.join(state['confirmed']) or '—'}；"
                          f"还没确认 {'、'.join(state['open']) or '—'}"])
        if s["errors"]:
            message="本步缺少可对应的输出" if "step_missing" in s["errors"] else "本步请求失败"
            lines.append(f"  - {message}，沿用上一步状态。")
        lines.extend([f"- 计划：{display(s['plan'])}",""])
    lines.extend(["## 终点","",f"- 答案：{display(end.get('final_answer'))}",
                  f"- 依据：{display(end.get('basis'))}",f"- 未决：{display(end.get('unresolved'))}"])
    for row in list_field(end,"unsupported"):
        lines.append(f"  - 无返回依据：{display(row.get('claim'))}")
    lines.extend([""," → ".join(display(s["summary"]) for s in steps),""])
    return "\n".join(lines)

def run_chain(data,conditions,prompts,cfg,out,progress=None,*,whole=None):
    out.mkdir(parents=True,exist_ok=True)
    cache=out/"checkpoint"
    if whole is None:
        cache.mkdir(exist_ok=True)
        identity(cache/"identity.sha256",{"data":data,"conditions":conditions,"prompts":prompts,
                                         "config":{k:v for k,v in cfg.items() if k!="url"}})
    common={"question":data["question"],"conditions":conditions}
    ids=[row["id"] for row in conditions]
    state={"candidates":[],"confirmed":[],"open":ids[:]}
    facts=[]
    logs=[]
    states=[]
    checks=[]
    steps=[]
    def request(phase,stage,payload):
        if whole is not None:
            if phase in ("S","F"):
                return obj(whole["start" if phase=="S" else "final"]),None
            return whole["steps"].get(stage,{}),None if stage in whole["steps"] else "step_missing"
        v,error,a=judge(cache,f"{stage:03d}-{phase}",prompts[phase],payload,cfg)
        for item in a:
            logs.append({"phase":phase,"stage":stage,**item})
        if progress:
            progress(phase,stage,len(a),error)
        return obj(v),error
    start_thought=data["rings"][0]["thinking"]
    start,start_error=request("S",0,{**common,"thinking_before_first_call":start_thought})
    candidates,checks_s=checked_items(start,"candidates",start_thought,"S",True)
    plan,plan_check=checked_text(start,"plan","plan_quote",start_thought,"S",True)
    start={**start,"plan":plan}
    if not start_error:
        state=state_after(state,[{**x,"op":"新增"} for x in candidates],[],ids)
    states.append({"type":"start","stage":0,"state":state,"state_carried_due_to_failure":bool(start_error)})
    checks.extend({"stage":0,**x} for x in [*checks_s,plan_check])
    for ring in data["rings"][1:-1]:
        stage=ring["stage"]
        a,a_error=request("A",stage,{**common,"state":state,"thinking_before":ring["thinking_before"],"calls":ring["calls"]})
        new,checked_a=verified_facts(a,ring)
        after=ring["thinking_after"]
        b,b_error=request("B",stage,{**common,"state":state,"prior_verified_facts":facts,
                                   "new_verified_facts":new,"thinking_after":after})
        source=after if not after.startswith("（无，") else ""
        conclusion,q=checked_text(b,"conclusion","conclusion_quote",source,"B",True)
        candidates,c=checked_items(b,"candidate_ops",source,"B",True)
        conditions_ops,d=checked_items(b,"condition_ops",source,"B",True)
        unsupported,e=checked_items(b,"unsupported",source,"B",True)
        errors=[x for x in (a_error,b_error) if x is not None]
        previous=state
        if not errors:
            state=state_after(state,candidates,conditions_ops,ids)
        calls=[h for call in ring["calls"] for h in call["returned"]]
        new_ids={h["docid"] for h in calls if "snippet" in h}
        old_ids={h["docid"] for h in calls if "snippet" not in h}-new_ids
        steps.append({"stage":stage,"action":a.get("looking_for"),"queries":[call["query"] for call in ring["calls"]],
                      "plan_mismatch":a.get("plan_note") if a.get("plan_match")=="不一致" else None,
                      "new_docs":len(new_ids),"old_docs":len(old_ids),"facts":new,
                      "conclusion":conclusion,"unsupported":unsupported,"state":state,"before":previous,
                      "plan":b.get("plan"),"summary":b.get("step_summary"),"errors":errors})
        states.append({"type":"call","stage":stage,"state":state,"state_carried_due_to_failure":bool(errors)})
        checks.extend({"stage":stage,**x} for x in [*checked_a,q,*c,*d,*e])
        facts.extend({"stage":stage,**f} for f in new)
    terminal=data["rings"][-1]
    stage=len(data["rings"])-1
    end,f_error=request("F",stage,{**common,"state":state,"verified_facts":facts,**{k:v for k,v in terminal.items() if k!="type"}})
    unsupported,checks_f=checked_items(end,"unsupported",
        (terminal["thinking"],terminal["formal_answer"]) if terminal["formal_answer"]!="未交卷"
        else terminal["thinking"],"F",True)
    end={**end,"unsupported":unsupported}
    if terminal["formal_answer"]=="未交卷":
        end.update(final_answer="未交卷",unresolved=terminal["termination_reason"])
    elif f_error:
        end["final_answer"]=terminal["formal_answer"]
    states.append({"type":"final","stage":stage,"state":state,"state_carried_due_to_failure":bool(f_error)})
    checks.extend({"stage":stage,**x} for x in checks_f)
    if whole is None:
        jsonl(out/"RAW.jsonl",logs)
    jsonl(out/"VERIFY.jsonl",checks)
    jsonl(out/"STATE.jsonl",states)
    replace_text(out/"CHAIN.md",render_chain(start,steps,end))
    return {"raw":logs,"quotes":dict(Counter(x["status"] for x in checks)),
            "carried":sum(s["state_carried_due_to_failure"] for s in states),"steps":len(steps),
            "summaries_over_30":sum(len(display(s["summary"]))>30 for s in steps)}

def read_prompts(path):
    return {phase:(path/f"prompt_v2_{phase}.txt").read_text(encoding="utf-8") for phase in "CSABF"}

def prompt_hashes(prompts):
    return {k:sha256(v.encode("utf-8")).hexdigest() for k,v in prompts.items()}

def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument("trajectory",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--terminal",type=Path)
    p.add_argument("--config",type=Path,default=Path(__file__).with_name("config_v2.json"))
    args=p.parse_args()
    config=load(args.config)
    prompts=read_prompts(Path(__file__).parent)
    data=prepare(load(args.trajectory),load(args.terminal or args.trajectory.with_name("TERMINAL.json")),
                 config["thought_truncation"])
    result=extract_conditions(data["question"],prompts["C"],config,args.output/"condition_checkpoint")
    jsonl(args.output/"CONDITIONS.jsonl",[result])
    run_chain(data,result["conditions"],prompts,config,args.output)
    replace_text(args.output/"PROMPT_HASHES.json",encode(prompt_hashes(prompts))+"\n")

if __name__=="__main__":
    main()
