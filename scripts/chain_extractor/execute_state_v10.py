"""Execute a sequential A1/A2/B2 state chain over frozen, numbered inputs."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from hashlib import sha256
from pathlib import Path
import http.client
import json
import os
import sys
from time import monotonic
from urllib.parse import urlsplit

from chain_state_v10 import action_errors, adopt_step, adoption_errors, blank_table, fact_errors, materialize


PROMPTS={
 "A1":"bf90978bec1beafae2642848b1aa51e0062040b0c78df57d67f5b62360503bca",
 "A2":"81e153334e4c551a30f447486f575bbf6479e818d55bfa0c5837d3b2eafc3362",
 "B2":"b4d691fb3794ae2a38bf56b14dc416fcf04776c8257936d3410b95715cb103ef",
}
WIRE={"model":"gpt-oss-120b","temperature":0,"seed":2026112004,"reasoning_effort":"medium",
      "max_tokens":16384,"timeout_seconds":1800}
CONDITIONS_SHA="9d3273f4c2e09f34b087395fdc0bdda3541c9183aecd609146782a8286fd096d"


def load(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def atomic(path, serialized):
    path.parent.mkdir(parents=True,exist_ok=True)
    part=path.with_suffix(path.suffix+".part")
    part.write_text(serialized,encoding="utf-8",newline="\n")
    part.replace(path)


def compact(obj):
    return json.dumps(obj,ensure_ascii=False,separators=(",",":"))


def step_inputs(conditions,table,step):
    common={"条件清单":conditions,"当前状态":{"答案":step["candidate_before"],"条件表":table},"本次查询":step["queries"]}
    return {**common,"调用前思考":step["before"]},{**common,"本次返回":step["returns"]}


def checked(folder,phase,prompt,body,cfg,validate,send):
    attempts=[]
    errors=[]
    for n in range(1,4):
        payload={**body,"上一次校验错误":errors} if errors else body
        key=f"{phase}.try{n}"
        parsed,error,raw=send(folder,key,prompt,payload,cfg,max_retries=0)
        errors=[error] if error else validate(parsed)
        attempts.append({"attempt":n,"file":key+".1.json","errors":errors,
                         "finish_reason":raw[0]["finish_reason"],"error":raw[0]["error"]})
        if not errors:
            return {"passed":True,"parsed":parsed,"attempts":attempts}
    return {"passed":False,"parsed":None,"attempts":attempts}


def run_case(work,case,variant,url,prompts,send):
    tid=case["trajectory_id"]
    folder=work/"RAW"/tid/variant
    conditions=case["conditions"]
    ids=[row["id"] for row in conditions]
    table=blank_table(ids)
    pending,adopted={},set()
    out=[]
    begin=monotonic()
    for step in case["steps"]:
        t=step["step"]
        active=folder/f"{t:03}"
        a1_args,a2_args=step_inputs(conditions,table,step)
        config={**WIRE,"url":url}
        a1=checked(active,"A1",prompts["A1"],a1_args,config,
                   lambda x:action_errors(x,ids,{r["id"] for r in step["before"]}),send)
        a2=checked(active,"A2",prompts["A2"],a2_args,config,
                   lambda x:fact_errors(x,ids,step["document_sentences"]),send)
        fresh=materialize(a2["parsed"],step["document_sentences"],t) if a2["passed"] else []
        after=step["after"]
        finals=step["final_sentences"]
        known={r["id"] for r in after+finals}
        b2_args={"条件清单":conditions,"模型此刻的答案":step["candidate_after"],"v7本步候选线":step["v7_B"],
                 "上一步条件表":table,"本步证据":fresh,"此前还没采纳的证据":list(pending.values()),
                 "下一轮思考":step["after_marker"] or after}
        if finals:
            b2_args["正式答案"]=finals
        b2=checked(active,"B2",prompts["B2"],b2_args,config,
                   lambda x:adoption_errors(x,ids,fresh,pending,adopted,known),send)
        value=b2["parsed"]
        pending,adopted=adopt_step(value,fresh,pending,adopted)
        old=table
        carried=not all(r["passed"] for r in (a1,a2,b2))
        if not carried:
            by_id={r["condition"]:r for r in value["table"]}
            table=[by_id[c] for c in ids]
        out.append({k:step[k] for k in ("step","queries","new_docs","old_docs","candidate_before","candidate_after",
                                       "excluded_before","excluded_after","strict","v7_B","final_sentences")} | {
           "before_table":old,"table":table,"state_carried":carried,
           "action":a1["parsed"],"new_evidence":fresh,
           "verdicts":value["evidence"] if value else [],
           "earlier_adopted":value["earlier_adopted"] if value else [],
           "assertions":value["assertions"] if value else [],
           "pending_ids":list(pending),"adopted_ids":sorted(adopted),
           "calls":{"A1":a1,"A2":a2,"B2":b2}})
        atomic(work/"INFERENCE"/tid/(variant+".jsonl"),"".join(compact(s)+"\n" for s in out))
    return {"trajectory":tid,"run":variant,"steps":len(out),"seconds":round(monotonic()-begin,2),
            "attempts":sum(len(x["attempts"]) for r in out for x in r["calls"].values()),
            "unjudged":sum(not x["passed"] for r in out for x in r["calls"].values())}


def endpoints(work):
    receipt=load(work/"SERVICE_RECEIPT.json")
    assert receipt["job"]==os.environ["SLURM_JOB_ID"]=="198830"
    assert (receipt["tp"],receipt["replicas"],receipt["eager"],receipt["prefix_cache"])==(1,4,False,True)
    for url in receipt["endpoints"]:
        dest=urlsplit(url)
        assert (dest.scheme,dest.hostname,dest.path)==("http","127.0.0.1","/v1")
        conn=http.client.HTTPConnection("127.0.0.1",dest.port,timeout=8)
        try:
            conn.request("GET","/v1/models")
            r=conn.getresponse()
            assert r.status==200 and any(x["id"]==WIRE["model"] for x in json.loads(r.read())["data"])
        finally:
            conn.close()
    return receipt["endpoints"]


def main(work,control):
    sys.path.insert(0,str(control))
    from chain_extractor_v2 import judge
    settings={}
    for label,hash_ in PROMPTS.items():
        path=control/f"prompt_v10_{label}.txt"
        assert digest(path)==hash_
        settings[label]=path.read_text(encoding="utf-8")
    fixed=load(work/"INPUT_MANIFEST.json")
    assert fixed["conditions_sha256"]==CONDITIONS_SHA
    assert fixed["stages"]==sum(v["steps"] for v in fixed["source"].values())
    urls=endpoints(work)
    queued=[0]*len(urls)
    jobs=[]
    for tid,row in sorted(fixed["source"].items(),key=lambda e:(-e[1]["steps"],e[0])):
        path=work/"prepared"/(tid+".json")
        assert digest(path)==row["prepared_sha256"]
        case=load(path)
        assert len(case["steps"])==row["steps"] and case["conditions_sha256"]==CONDITIONS_SHA
        r=min(range(len(urls)),key=queued.__getitem__)
        queued[r]+=row["steps"]
        jobs.extend((case,run,urls[r]) for run in ("a","b"))
    begin=monotonic()
    result=[]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        running=[pool.submit(run_case,work,*args,settings,judge) for args in jobs]
        for future in as_completed(running):
            report=future.result()
            result.append(report)
            print(compact(report),flush=True)
    receipt={"job_id":os.environ["SLURM_JOB_ID"],"step_id":os.environ["SLURM_STEP_ID"],
             "seconds":monotonic()-begin,"runs":sorted(result,key=lambda x:(x["trajectory"],x["run"])),
             "prompts":PROMPTS,"wire":WIRE,"requests":sum(x["attempts"] for x in result)}
    atomic(work/"EXECUTION_RECEIPT.json",compact(receipt)+"\n")
    print(compact({k:v for k,v in receipt.items() if k!="runs"}),flush=True)


if __name__=="__main__":
    main(*(Path(s) for s in sys.argv[1:]))
