"""Extract v5 search chains with fixed answer type and intermediate-object tracking."""
from argparse import ArgumentParser
from pathlib import Path
import re

from chain_extractor import encode, load, prepare, replace_text
from chain_extractor_v2 import fallback_conditions as split_v4, judge, list_field, normalized, obj
from chain_extractor_v3 import run_case as run_scoped
from chain_extractor_v4 import V4Protocol, check_claim as check_v4, clean

PHASES=("C","S","A1","A2","B","F")


def read_prompts(path):
    return {key:(path/f"prompt_v5_{key}.txt").read_text(encoding="utf-8") for key in PHASES}


def check_conditions(question,value):
    rows=[obj(x) for x in list_field(value,"conditions")]
    reasons=[]
    ids=[x.get("id") for x in rows]
    asked=[i for i,row in enumerate(rows) if row.get("asked") is True]
    if len(asked)!=1:
        reasons.append("必须有且仅有一条标为所问的条件")
    if not 2<=len(rows)-len(asked)<=10:
        reasons.append("除所问之外的条件数量必须在 2 到 10 条之间")
    if any(not isinstance(cid,str) or not cid.strip() for cid in ids) or len(set(ids))!=len(ids):
        reasons.append("条件编号缺失、非法或重复")
    kind=obj(value).get("answer_type")
    if not isinstance(kind,str) or not kind.strip():
        reasons.append("answer_type 不能为空")
    target=normalized(question)
    covered=set()
    missing=[]
    for i,row in enumerate(rows,1):
        claim=row.get("text")
        if not isinstance(claim,str) or not claim.strip():
            missing.append(i)
            continue
        text=normalized(claim)
        parts=[text] if text in target else [p.strip() for p in re.split(r"[,，;；]",text) if p.strip()]
        if not parts or any(p not in target for p in parts):
            missing.append(i)
            continue
        for part in parts:
            start=target.index(part)
            covered.update(range(start,start+len(part)))
    if missing:
        reasons.append("这些条件无法在题面逐段定位："+"、".join(map(str,missing)))
    size=sum(not x.isspace() for x in target)
    coverage=sum(not target[i].isspace() for i in covered)/size if size else 0.0
    if coverage<0.70:
        reasons.append(f"题面覆盖率 {coverage:.1%}，低于 70%")
    return {"valid":not reasons,"reasons":reasons,"coverage":coverage,"missing_spans":missing,
            "count":len(rows),"asked_count":len(asked)}


def fallback_conditions(question,answer_type=None):
    rows=split_v4(question)["conditions"]
    parts=[row["text"] for row in rows[:-1]]
    while len(parts)>10:
        index=min(range(len(parts)-1),key=lambda i:len(parts[i])+len(parts[i+1]))
        parts[index:index+2]=[" ".join(parts[index:index+2])]
    asked=rows[-1]["text"] if rows else question
    conditions=[{"id":f"c{i}","text":value} for i,value in enumerate([*parts,asked],1)]
    conditions[-1]["asked"]=True
    return {"answer_type":answer_type or asked,"conditions":conditions}


def extract_conditions(question,prompt,cfg,folder):
    history=[]
    payload={"question":question}
    answer_type=None
    for attempt in (1,2):
        result,error,raw=judge(folder,f"C{attempt}",prompt,payload,cfg,max_retries=0)
        validation=check_conditions(question,result)
        if error:
            validation["reasons"].insert(0,error)
            validation["valid"]=False
        history.append({"attempt":attempt,"output":result,"validation":validation,"receipt":raw[0]})
        kind=obj(result).get("answer_type")
        if isinstance(kind,str) and kind.strip():
            answer_type=kind.strip()
        if validation["valid"]:
            return {"conditions":result["conditions"],"answer_type":answer_type,"attempts":history,
                    "retried":attempt==2,"sentence_fallback":False,"validation":validation}
        payload={"question":question,"previous_validation_errors":validation["reasons"]}
        if answer_type:
            payload["所问对象类型"]=answer_type
    result=fallback_conditions(question,answer_type)
    return {**result,"attempts":history,"retried":True,"sentence_fallback":True,
            "validation":check_conditions(question,result)}


def numeric_docid(value):
    text=clean(str(value)).strip()
    return str(int(text)) if re.fullmatch(r"\d+",text) else None


class V5Protocol(V4Protocol):
    def __init__(self,answer_type):
        if not isinstance(answer_type,str) or not answer_type.strip():
            raise ValueError("answer_type is required")
        self.answer_type=answer_type
        self.docids=set()
        self.checking_names=set()

    def observe(self,step):
        for call in step["calls"]:
            for doc in call["returned"]:
                code=numeric_docid(doc["docid"])
                if code is not None:
                    self.docids.add(code)

    def check_claim(self,claim,references,question,corpus):
        audit=check_v4(claim,references,question,corpus)
        ignored=[key for key in audit["keywords"] if numeric_docid(key) in self.docids]
        keywords=[key for key in audit["keywords"] if key not in ignored]
        missing=[key for key in audit["missing_keywords"] if key not in ignored]
        return {**audit,"keywords":keywords,"missing_keywords":missing,"ignored_docids":ignored,
                "status":"无返回依据" if missing else "有依据" if keywords else "无法判断"}

    def checking_object(self,b,cite,allowed):
        row=obj(b.get("checking_object"))
        name=row.get("name")
        if isinstance(name,str) and name.strip():
            name=name.strip()
            refs,audit=cite("checking_object",row.get("ids"),allowed,name)
            audit["applied"]=bool(refs)
            self.checking_names.add(normalized(name))
            ids=[r["id"] for r in refs]
        else:
            name=None
            ids=[]
        main=obj(b.get("main_candidate")).get("name")
        conflict=isinstance(main,str) and normalized(main) in self.checking_names
        return {"checking_object":name,"checking_object_ids":ids,
                "checking_object_candidate_conflict":main if conflict else None}

    @staticmethod
    def state_line(state,checking_object):
        candidates="、".join(f'{r["name"]}（{r["status"]}）' for r in state["candidates"]) or "—"
        confirmed="、".join(state["confirmed"]) or "—"
        remaining="、".join(state["open"]) or "—"
        return f'候选：{candidates}｜正在核实：{checking_object or "—"}｜已确认：{confirmed}｜未确认：{remaining}'


def run_case(data,frozen,prompts,cfg,out,progress=None):
    return run_scoped(data,frozen["conditions"],prompts,cfg,out,"S",progress,
                      protocol=V5Protocol(frozen["answer_type"]))


def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument("trajectory",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--conditions",type=Path)
    p.add_argument("--terminal",type=Path)
    p.add_argument("--config",type=Path,default=Path(__file__).with_name("config_v5.json"))
    args=p.parse_args()
    cfg=load(args.config)
    if cfg["reasoning_effort"]!="medium":
        raise ValueError("v5 requires medium reasoning effort")
    data=prepare(load(args.trajectory),load(args.terminal or args.trajectory.with_name("TERMINAL.json")),
                 cfg["thought_truncation"])
    prompts=read_prompts(Path(__file__).parent)
    frozen=load(args.conditions) if args.conditions else extract_conditions(
        data["question"],prompts["C"],cfg,args.output/"condition_checkpoint")
    run_case(data,frozen,prompts,cfg,args.output)
    replace_text(args.output/"CONDITIONS.json",encode(frozen)+"\n")


if __name__=="__main__":
    main()
