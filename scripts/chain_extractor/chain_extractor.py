"""Extract a causal chain from a recorded search trajectory with a local Judge."""
from argparse import ArgumentParser
from collections import defaultdict
from hashlib import sha256
import http.client
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

REASONS = {
    "SAFETY_CEILING_STOP": "调用预算用完",
    "TOOL_CALL_LIMIT_STOP": "调用预算用完",
    "CONTEXT_LIMIT_STOP": "上下文写满",
    "GENERATION_LENGTH_STOP": "生成长度上限",
}

def truncate(text, config):
    head,tail=config["head"],config["tail"]
    skipped=len(text)-head-tail
    return text if skipped<=0 else text[:head]+f"[中间省略 {skipped} 字]"+text[len(text)-tail:]

def hits(value):
    if isinstance(value,str):
        value=json.loads(value)
    if isinstance(value,dict):
        value=value.get("results",value.get("result"))
    if isinstance(value,list) and value and all(
            isinstance(item,dict) and item.get("type")=="text" for item in value):
        parsed=[json.loads(item["text"]) for item in value]
        value=parsed[0] if len(parsed)==1 and isinstance(parsed[0],list) else parsed
    if not isinstance(value,list) or any(
        not isinstance(x,dict) or "docid" not in x or not isinstance(x.get("snippet"),str) for x in value):
        raise ValueError("unsupported search result")
    return value

def prepare(trace, terminal, truncation):
    rounds=sorted(trace["rounds"],key=lambda x:x["round_id"])
    by_round=defaultdict(list)
    for e in trace["tool_events"]:
        by_round[e["round_id"]].append(e)
    status=terminal["status"]
    end=REASONS.get(status,"其他" if status!="MODEL_FINAL_STOP" else "正式提交")
    question=next(m["content"] for m in rounds[0]["actor_visible_messages"] if m["role"]=="user")
    full=[r.get("reasoning_content") or "" for r in rounds]
    thought=[truncate(x,truncation) for x in full]
    first=next((i for i,r in enumerate(rounds) if r["round_id"] in by_round),0)
    rings=[{"type":"start","thinking":thought[first]}]
    originals=[{"thought":[full[first]],"returns":[]}]
    seen=defaultdict(dict)
    audits=[]
    for i,r in enumerate(rounds):
        events=sorted(by_round.get(r["round_id"],[]),key=lambda x:x["dispatch_order"])
        if not events:
            continue
        stage=len(rings)
        later=rounds[i+1] if i+1<len(rounds) else {}
        visible_messages=[m for m in later.get("actor_visible_messages",[]) if m["role"] in ("tool","function")]
        if later.get("request_sent") is False:
            visible_messages=[]
        calls=[]
        source_snippets=[]
        current={}
        for event in events:
            args=event["exact_arguments"]
            query=json.loads(args)["query"] if isinstance(args,str) else args["query"]
            raw=event.get("exact_result")
            call_id=event.get("tool_call_id")
            match=next((m for m in visible_messages if call_id and m.get("tool_call_id")==call_id),None)
            if match is None and not call_id:
                match=next((m for m in visible_messages if m.get("content")==raw),None)
            returned=[]
            call={"query":query,"fed_to_model":match is not None,"returned":returned}
            calls.append(call)
            if match is None:
                continue
            raw_visible=match["content"]
            try:
                docs=hits(raw_visible)
            except (ValueError,TypeError,KeyError):
                call["returned_text"]=raw_visible
                source_snippets.append(raw_visible)
                audits.append({"stage":stage,"issue":"unstructured_visible_return"})
                continue
            for doc in docs:
                name=str(doc["docid"])
                text=doc["snippet"]
                title=re.match(r"\A(?:---\r?\n)?title:[ \t]*(.+?)(?:\r?\n|$)",text,re.I)
                entry={"docid":name,"title":title[1] if title else None}
                prior=seen[name]
                same=[n for n,s in prior.items() if s==text]
                if same:
                    entry["previous_seen_rings"]=same
                else:
                    entry["snippet"]=text
                if prior and len(same)!=len(prior):
                    audits.append({"stage":stage,"issue":"changed_snippet","docid":name})
                if name in current and current[name]!=text:
                    audits.append({"stage":stage,"issue":"parallel_changed_snippet","docid":name})
                current[name]=text
                returned.append(entry)
                source_snippets.append(text)
        for key,text in current.items():
            seen[key][stage]=text
        has_next_thought=bool(later) and bool(full[i+1])
        after=thought[i+1] if has_next_thought else (
            f"（无，轨迹在此终止：{end}）" if not later else "（无，下一轮未记录思考）")
        rings.append({"type":"call","stage":stage,"actor_round":r["round_id"],
                      "thinking_before":thought[i],"calls":calls,"thinking_after":after})
        originals.append({"thought":[full[i]]+([full[i+1]] if later else []),"returns":source_snippets})
    submitted=rounds[-1].get("content") if status=="MODEL_FINAL_STOP" else None
    rings.append({"type":"final","thinking":thought[-1],
                  "formal_answer":submitted if submitted else "未交卷",
                  "termination_reason":None if submitted else end,"termination_code":status})
    originals.append({"thought":[full[-1]],"returns":[]})
    return {"question":question,"rings":rings,"quote_sources":originals,"input_audit":audits}

def direct_post(url, body, timeout):
    dest=urlsplit(url)
    if (dest.scheme,dest.hostname,dest.path)!=("http","127.0.0.1","/v1") or dest.query or dest.fragment:
        raise ValueError("select an HTTP loopback /v1 endpoint")
    connection=http.client.HTTPConnection("127.0.0.1",dest.port,timeout=timeout)
    try:
        connection.request("POST","/v1/chat/completions",body=json.dumps(body,ensure_ascii=False).encode("utf-8"),
                           headers={"Content-Type":"application/json"})
        with connection.getresponse() as response:
            return response.status,response.read().decode("utf-8",errors="replace")
    finally:
        connection.close()

def encode(value):
    return json.dumps(value,ensure_ascii=False,separators=(",",":"))

def replace_text(path,text):
    tmp=path.with_name(path.name+".part")
    tmp.write_text(text,encoding="utf-8",newline="\n")
    tmp.replace(path)

def load(path):
    return json.loads(path.read_bytes())

def identity(path, run):
    expected=sha256(encode(run).encode("utf-8")).hexdigest()
    if path.exists():
        if path.read_text(encoding="ascii").strip()!=expected:
            raise ValueError("resume cannot change source, prompts or run parameters")
    else:
        replace_text(path,expected+"\n")

def request_body(prompt,payload,cfg):
    return {**{key:cfg[key] for key in ("model","temperature","seed","reasoning_effort","max_tokens")},
            "response_format":{"type":"json_object"},
            "messages":[{"role":"system","content":prompt},{"role":"user","content":encode(payload)}]}

def invoke(body, cfg, receipt_prefix, post):
    attempts=[]
    for index in (1,2):
        path=receipt_prefix.with_name(receipt_prefix.name+f".attempt-{index}.json")
        if path.exists():
            row=load(path)
        else:
            start=time.monotonic()
            status=raw=content=reason=finish=tokens=error=parsed=None
            try:
                status,raw=post(cfg["url"],body)
                if status!=200:
                    error=f"http_{status}"
                else:
                    envelope=json.loads(raw)
                    tokens=(envelope.get("usage") or {}).get("completion_tokens")
                    choice=envelope["choices"][0]
                    message=choice["message"]
                    reason=message.get("reasoning")
                    if reason is None:
                        reason=message.get("reasoning_content")
                    finish=choice.get("finish_reason")
                    content=message.get("content")
                    parsed=json.loads(content)
            except (OSError,http.client.HTTPException) as exc:
                error=f"transport:{type(exc).__name__}"
            except (json.JSONDecodeError,TypeError,KeyError,IndexError,AttributeError):
                error="json_parse_failed"
            row={"attempt":index,"elapsed_seconds":round(time.monotonic()-start,6),
                 "http_status":status,"output_tokens":tokens,"finish_reason":finish,"error":error,
                 "request":body,"raw_response":raw,"reasoning_full":reason,"assistant_content":content,"parsed":parsed}
            replace_text(path,encode(row)+"\n")
        attempts.append(row)
        if row["error"]!="json_parse_failed" or index==2:
            return row["parsed"],row["error"],attempts

def conditions(question,prompt,cfg,folder,post=None):
    folder.mkdir(parents=True,exist_ok=True)
    send=post or (lambda url,body:direct_post(url,body,cfg.get("timeout_seconds",1800)))
    body=request_body(prompt,{"question":question},cfg)
    identity(folder/"identity.sha256",body)
    return invoke(body,cfg,folder/"conditions",send)

def audits(output,ring,sources,condition_ids):
    obj=output if isinstance(output,dict) else {}
    quote=obj.get("quote")
    present=isinstance(quote,str) and bool(quote.strip())
    thought=present and any(quote in x for x in sources["thought"])
    returned=present and any(quote in x for x in sources["returns"])
    answer=present and ring["type"]=="final" and ring["formal_answer"]!="未交卷" and quote in ring["formal_answer"]
    state=obj.get("state")
    state=state if isinstance(state,dict) else {}
    lists={}
    for k in ("confirmed","open"):
        values=state.get(k)
        if not isinstance(values,list):
            values=[]
        values=[item.get("id") if isinstance(item,dict) else item for item in values]
        lists[k]=[{"id":v,"exists":isinstance(v,str) and v in condition_ids} for v in values]
    return {"quote_present":present,"quote_source":"出自本环思考" if thought else
            "出自本环返回" if returned else "都找不到","in_thinking":thought,"in_return":returned,
            "in_formal_answer":answer,"condition_ids":lists}

def execute(data,condition_set,prompt,cfg,folder,post=None,on_ring=None):
    folder.mkdir(parents=True,exist_ok=True)
    send=post or (lambda url,body:direct_post(url,body,cfg.get("timeout_seconds",1800)))
    identity(folder/"identity.sha256",{"data":data,"conditions":condition_set,"prompt":prompt,
                                     "config":{k:v for k,v in cfg.items() if k!="url"}})
    ids={x["id"] for x in (condition_set.get("conditions",[]) if isinstance(condition_set,dict) and
                          isinstance(condition_set.get("conditions"),list) else [])
         if isinstance(x,dict) and isinstance(x.get("id"),str)}
    chain=[]
    collected=[]
    state=None
    for i,(ring,sources) in enumerate(zip(data["rings"],data["quote_sources"])):
        payload={"question":data["question"],"numbered_conditions":condition_set,
                 "prior_chain":chain,"ring":ring}
        path=folder/f"{i:04d}"
        row_path=path.with_suffix(".json")
        if row_path.exists():
            row=load(row_path)
        else:
            result,error,attempts=invoke(request_body(prompt,payload,cfg),cfg,path,send)
            if error is not None:
                result={"type":ring["type"],"extraction_failed":True,"state":state}
            row={"index":i,"type":ring["type"],"stage":ring.get("stage"),"output":result,"error":error,
                 "audit":audits(result,ring,sources,ids),"attempts":attempts}
            replace_text(row_path,encode(row)+"\n")
            if on_ring:
                on_ring(row)
        output=row["output"]
        if isinstance(output,dict) and "state" in output:
            state=output["state"]
        chain.append(output)
        collected.append(row)
    return collected

def jsonl(path,values):
    replace_text(path,"".join(encode(x)+"\n" for x in values))

def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("trajectory",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--terminal",type=Path)
    parser.add_argument("--config",type=Path,default=Path(__file__).with_name("config.json"))
    parser.add_argument("--conditions",type=Path)
    parser.add_argument("--run",default="T0")
    args=parser.parse_args()
    cfg=load(args.config)
    src=Path(__file__).parent
    prompt=(src/"extract.txt").read_text(encoding="utf-8")
    split=(src/"conditions.txt").read_text(encoding="utf-8")
    data=prepare(load(args.trajectory),load(args.terminal or args.trajectory.with_name("TERMINAL.json")),
                 cfg["thought_truncation"])
    args.output.mkdir(parents=True,exist_ok=True)
    cond_path=args.output/"CONDITIONS.json"
    cond,attempts=None,[]
    if args.conditions:
        cond=load(args.conditions)
    else:
        cond,error,attempts=conditions(data["question"],split,{**cfg,**cfg["condition_run"]},args.output/"checkpoint"/"conditions")
        if error:
            jsonl(args.output/"RAW_JUDGE.jsonl",attempts)
            raise RuntimeError(error)
    replace_text(cond_path,encode(cond)+"\n")
    run_cfg={**cfg,**cfg["runs"][args.run]}
    rows=execute(data,cond,prompt,run_cfg,args.output/"checkpoint"/args.run)
    jsonl(args.output/f"CHAIN_{args.run}.jsonl",(r["output"] for r in rows))
    jsonl(args.output/"INPUTS.jsonl",data["rings"])
    jsonl(args.output/"RAW_JUDGE.jsonl",attempts+[a for r in rows for a in r["attempts"]])
    jsonl(args.output/"AUDIT.jsonl",(r["audit"] for r in rows))
    replace_text(args.output/"PROMPT_HASHES.json",encode({k:sha256(v.encode()).hexdigest() for k,v in
                 (("conditions",split),("extract",prompt))})+"\n")

if __name__=="__main__":
    main()
