"""v6 stepwise chain extraction with source-clause and final-answer citations."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import re
import unicodedata

from chain_extractor import encode, load, prepare, replace_text
from chain_extractor_v2 import judge, list_field, obj
from chain_extractor_v3 import run_case as run_scoped
from chain_extractor_v5 import V5Protocol

PHASES=("C","S","A1","A2","B","F")
ITEM=re.compile(r"(?<!\S)\d{1,2}[.)](?=\s)")
BOUNDARY=re.compile(r"(?<=[.!?;。！？；])\s+")


def read_prompts(path):
    return {phase:(path/f"prompt_v6_{phase}.txt").read_text(encoding="utf-8") for phase in PHASES}


def split_clauses(question):
    pieces=[]
    for line in question.splitlines():
        starts=[0]
        for match in ITEM.finditer(line):
            prefix=line[:match.start()].rstrip()
            if prefix and prefix.endswith((".",":",";","?","!","；","。","？","！")):
                starts.append(match.start())
        for a,b in zip(starts,[*starts[1:],len(line)]):
            text=line[a:b].strip()
            prefix=ITEM.match(text)
            end=prefix.end() if prefix else 0
            start=0
            for mark in BOUNDARY.finditer(text,end):
                if prefix and mark.start()==end:
                    continue
                pieces.append(text[start:mark.start()].strip())
                start=mark.end()
            pieces.append(text[start:].strip())
    final=[]
    for text in pieces:
        if len(text)>200:
            final.extend(part.strip() for part in re.split(r"(?<=[,，])\s*",text) if part.strip())
        elif text:
            final.append(text)
    return [{"id":f"Q{i}","text":text} for i,text in enumerate(final,1)]


def check_groups(question,clauses,value):
    allowed={row["id"]:row["text"] for row in clauses}
    raw=obj(value)
    groups=[obj(g) for g in list_field(raw,"conditions")]
    ignored=raw.get("ignored")
    reasons=[]
    if not isinstance(ignored,list):
        reasons.append("ignored 必须是数组")
        ignored=[]
    requested=list(ignored)
    ids=[g.get("id") for g in groups]
    asked=sum(g.get("asked") is True for g in groups)
    if asked!=1:
        reasons.append("必须恰有一组所问")
    if not 2<=len(groups)-asked<=10:
        reasons.append("除所问外必须有 2 到 10 组条件")
    if any(not isinstance(i,str) or not i.strip() for i in ids) or len(ids)!=len(set(ids)):
        reasons.append("条件编号缺失或重复")
    for group in groups:
        refs=group.get("clauses")
        if not isinstance(refs,list) or not refs:
            reasons.append("每个条件必须引用至少一个小句")
        else:
            requested.extend(refs)
    if any(not isinstance(r,str) or r not in allowed for r in requested):
        reasons.append("存在未知小句编号")
    counts=Counter(r for r in requested if isinstance(r,str))
    missing=[key for key in allowed if counts[key]==0]
    repeated=[key for key in allowed if counts[key]>1]
    if missing or repeated:
        reasons.append("每个小句须恰好出现一次，遗漏："+ "、".join(missing)+"；重复："+"、".join(repeated))
    ignored_chars=sum(len(allowed[r]) for r in ignored if isinstance(r,str) and r in allowed)
    ratio=ignored_chars/max(1,len(question))
    if ratio>0.30:
        reasons.append(f"忽略字数比例 {ratio:.1%}，超过 30%")
    kind=raw.get("answer_type")
    if not isinstance(kind,str) or not kind.strip():
        reasons.append("answer_type 不能为空")
    return {"valid":not reasons,"reasons":reasons,"missing_clauses":missing,"repeated_clauses":repeated,
            "ignored_ratio":ratio,"ordinary_conditions":len(groups)-asked,"asked_count":asked}


def fallback(clauses,answer_type):
    ordinary=[[row] for row in clauses[:-1]]
    while len(ordinary)>10:
        i=min(range(len(ordinary)-1),key=lambda j:sum(len(row["text"]) for row in ordinary[j]+ordinary[j+1]))
        ordinary[i:i+2]=[ordinary[i]+ordinary[i+1]]
    groups=[{"id":f"c{i}","clauses":[r["id"] for r in rows]} for i,rows in enumerate([*ordinary,clauses[-1:]],1)]
    groups[-1]["asked"]=True
    return {"conditions":groups,"ignored":[],"answer_type":answer_type or clauses[-1]["text"]}


def build_result(question,clauses,value,history,used_fallback,check=check_groups):
    positions={row["id"]:i for i,row in enumerate(clauses)}
    groups=[{**row,"text":" ".join(clauses[i]["text"] for i in sorted(positions[c] for c in row["clauses"]))}
            for row in value["conditions"]]
    return {"question_clauses":clauses,"conditions":groups,"ignored":value["ignored"],
            "answer_type":value["answer_type"].strip(),"attempts":history,"retried":len(history)==2,
            "sentence_fallback":used_fallback,"validation":check(question,clauses,value)}


def extract_conditions(question,prompt,cfg,folder,*,check=check_groups):
    clauses=split_clauses(question)
    if not clauses:
        raise ValueError("question has no clauses")
    history=[]
    payload={"question_clauses":clauses}
    saved_type=None
    for attempt in (1,2):
        result,error,raw=judge(folder,f"C{attempt}",prompt,payload,cfg,max_retries=0)
        validation=check(question,clauses,result)
        if error:
            validation["reasons"].insert(0,error)
            validation["valid"]=False
        history.append({"attempt":attempt,"output":result,"validation":validation,"receipt":raw[0]})
        kind=obj(result).get("answer_type")
        if isinstance(kind,str) and kind.strip():
            saved_type=kind.strip()
        if validation["valid"]:
            return build_result(question,clauses,result,history,False,check)
        payload={"question_clauses":clauses,"previous_validation_errors":validation["reasons"]}
    return build_result(question,clauses,fallback(clauses,saved_type),history,True,check)


def candidate_key(name):
    text=unicodedata.normalize("NFKC",name)
    while True:
        cleaned=re.sub(r"\([^()]*\)","",text)
        if cleaned==text:
            break
        text=cleaned
    without="".join(ch for ch in text if not unicodedata.category(ch).startswith("P"))
    return " ".join(without.casefold().split())


class V6Protocol(V5Protocol):
    def __init__(self,answer_type):
        super().__init__(answer_type)
        self.aliases={}
        self.merges=0

    def merge_candidates(self,initial,operations):
        choices={}
        for row in [*initial["candidates"],*operations]:
            name=row["name"].strip()
            key=candidate_key(name) or name.casefold()
            variants=self.aliases.setdefault(key,set())
            if variants and name not in variants:
                self.merges+=1
            variants.add(name)
            if key not in choices or len(name)>len(choices[key]):
                choices[key]=name
        def representative(row):
            name=row["name"].strip()
            return {**row,"name":choices[candidate_key(name) or name.casefold()]}
        return {**initial,"candidates":[representative(r) for r in initial["candidates"]]},[
            representative(r) for r in operations]

    @staticmethod
    def render_final(end,terminal,cite,allowed,error):
        formal=terminal["formal_answer"]
        reported=end.get("answer_kind")
        refs,audit=cite("answer_ids",end.get("answer_ids"),allowed)
        if formal=="未交卷":
            kind="未交卷"
            refs=[]
        else:
            kind=reported if reported in ("作答","拒答") and not error else None
        audit["applied"]=bool(refs) and kind is not None
        text=" / ".join(f'[{r["id"]}] {r["text"]}' for r in refs)
        if kind=="未交卷":
            rendered=kind
        elif kind:
            rendered=f"{kind} · {text}" if text else f"{kind}（缺少有效答案编号）"
        else:
            rendered="终点类别未确认"+(f" · {text}" if text else "")
        return rendered,{"answer_kind":kind,"reported_answer_kind":reported,"answer_ids":[r["id"] for r in refs]}


def run_case(data,frozen,prompts,cfg,out,progress=None):
    protocol=V6Protocol(frozen["answer_type"])
    result=run_scoped(data,frozen["conditions"],prompts,cfg,out,"S",progress,protocol=protocol)
    return {**result,"candidate_merges":protocol.merges}


def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument("trajectory",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--config",type=Path,default=Path(__file__).with_name("config_v6.json"))
    p.add_argument("--terminal",type=Path)
    p.add_argument("--conditions",type=Path)
    a=p.parse_args()
    cfg=load(a.config)
    if cfg["reasoning_effort"]!="medium":
        raise ValueError("v6 requires medium reasoning effort")
    data=prepare(load(a.trajectory),load(a.terminal or a.trajectory.with_name("TERMINAL.json")),cfg["thought_truncation"])
    prompts=read_prompts(Path(__file__).parent)
    c=load(a.conditions) if a.conditions else extract_conditions(data["question"],prompts["C"],cfg,a.output/"condition_checkpoint")
    run_case(data,c,prompts,cfg,a.output)
    replace_text(a.output/"CONDITIONS.json",encode(c)+"\n")


if __name__=="__main__":
    main()
