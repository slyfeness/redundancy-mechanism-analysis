"""v4 search-chain extraction with separate action/return requests and condition follow-up."""
from argparse import ArgumentParser
from pathlib import Path
import re
import unicodedata

from chain_extractor import load, prepare
from chain_extractor_v2 import list_field, obj
from chain_extractor_v3 import COMMON, MARKS, match_text, numbered, prepare_numbered as prepare_v3
from chain_extractor_v3 import run_case as run_scoped, whole_payload as whole_v3

PHASES = ("S","A1","A2","B","F","W","C")
WORD = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
MARKED = re.compile(r"(?:\*\*|(?<!\w)-|#|(?<!\w)\d+\.|:)\s*$")


def v4_prompts(path):
    return {phase:(path/f"prompt_v4_{phase}.txt").read_text(encoding="utf-8") for phase in PHASES}


def clean(text):
    return unicodedata.normalize("NFKC",text).translate(MARKS)


def lower_words(text):
    return {m[0].casefold() for m in WORD.finditer(text) if m[0].islower()}


def numbers(text):
    return set(NUMBER.findall(match_text(text)))


def check_claim(claim, references, question, corpus):
    normalized_question=match_text(question)
    q_numbers=numbers(question)
    q_lower=lower_words(clean(question))
    numeric=set()
    names={}
    for reference in references:
        text=clean(reference["text"])
        numeric.update(numbers(text)-q_numbers)
        for line in text.splitlines():
            excluded=COMMON|q_lower|lower_words(line)
            run=[]
            previous_end=0
            def keep():
                if run:
                    name=" ".join(run).casefold()
                    if not has_name(normalized_question,name):
                        names[name]=None
                    run.clear()
            for i,m in enumerate(WORD.finditer(line)):
                word=m[0]
                if i==0 or not word[0].isupper() or word.casefold() in excluded or MARKED.search(line[:m.start()]):
                    keep()
                else:
                    if not line[previous_end:m.start()].isspace():
                        keep()
                    run.append(word)
                previous_end=m.end()
            keep()
    evidence=[match_text(text) for text in corpus]
    known_numbers={n for text in evidence for n in NUMBER.findall(text)}
    keywords=[*sorted(numeric),*names]
    missing=[n for n in sorted(numeric) if n not in known_numbers]
    missing.extend(name for name in names if not any(has_name(text,name) for text in evidence))
    return {"claim":claim,"cited_sentences":references,"keywords":keywords,"missing_keywords":missing,
            "status":"无返回依据" if missing else "有依据" if keywords else "无法判断"}


def has_name(text, name):
    return re.search(r"(?<![\w-])"+re.escape(name)+r"(?![\w-])",text) is not None


def prepare_numbered(data, group):
    first,steps,last,answer,terminal=prepare_v3(data,group)
    if group=="W":
        rings=data["rings"]
        prior=rings[-2].get("thinking_after",rings[0]["thinking"])
        if terminal["thinking"]!=prior:
            last=numbered(terminal["thinking"],f"T{len(steps)+1}-")
    return first,steps,last,answer,terminal


def id_range(ids):
    return "无" if not ids else ids[0] if len(ids)==1 else f"{ids[0]}–{ids[-1]}"


def whole_payload(common, first, steps, last, answer, terminal):
    body=whole_v3(common,first,steps,answer,terminal)
    for row,prepared in zip(body["steps"],steps):
        by_doc={}
        for sid,(docid,_) in prepared["document_sentences"].items():
            by_doc.setdefault(docid,[]).append(sid)
        docs="、".join(id_range(ids) for ids in by_doc.values()) or "无"
        before=id_range([s["id"] for s in prepared["before"]])
        after=id_range([s["id"] for s in prepared["after"]])
        heading=f'【第 {row["step"]} 步】（可引用：调用前思考 = {before}；本步新文档 = {docs}；本步之后的思考 = {after}）'
        body["steps"][row["step"]-1]={"heading":heading,**row}
    prior=steps[-1]["after"] if steps else first
    body["terminal"]={"heading":"【正式答案或终止原因】",**body["terminal"]}
    if last!=prior:
        body["terminal"]["last_thinking"]=last
    return body


def step_action(response, i, common, state, step):
    queries=[c["query"] for c in step["calls"]]
    head={**common,"state":state,"queries":queries}
    a1,error1=response("A1",i,{**head,"thinking_before":step["before"]})
    returns=[{k:v for k,v in c.items() if k!="query"} for c in step["calls"]]
    a2,error2=response("A2",i,{**head,"returns":returns})
    values={k:a1.get(k) for k in ("looking_for","plan_match","plan_ids","plan_note")}
    values["new_facts"]=list_field(a2,"new_facts")
    return values,error1 or error2


def missing_checks(output, open_ids):
    supplied={row["id"] for entry in list_field(output,"condition_checks") if
              isinstance((row:=obj(entry)).get("id"),str) and isinstance(row.get("confirmed"),bool)}
    return [key for key in open_ids if key not in supplied]


def follow_up(call, i, payload, b, open_ids, error):
    missing=missing_checks(b,open_ids)
    record={"missing_before":missing,"missing_after":missing.copy(),"requested":False,"error":None}
    if not missing or error:
        return b,record
    answer,problem=call("B_followup",i,{**payload,"missing_condition_ids":missing})
    replacement={}
    for raw in list_field(answer,"condition_checks") if not problem else []:
        row=obj(raw)
        key=row.get("id")
        if key in missing and isinstance(row.get("confirmed"),bool):
            replacement.setdefault(key,row)
    kept=[row for row in list_field(b,"condition_checks") if obj(row).get("id") not in replacement]
    merged={**b,"condition_checks":[*kept,*(replacement[key] for key in missing if key in replacement)]}
    record.update(requested=True,error=problem,missing_after=missing_checks(merged,open_ids))
    return merged,record


class V4Protocol:
    prepare_numbered=staticmethod(prepare_numbered)
    whole_payload=staticmethod(whole_payload)
    step_action=staticmethod(step_action)
    follow_up=staticmethod(follow_up)
    check_claim=staticmethod(check_claim)


def run_case(data,conditions,prompts,cfg,out,group,progress=None):
    return run_scoped(data,conditions,prompts,cfg,out,group,progress,protocol=V4Protocol)


def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument("trajectory",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--group",required=True,choices=("S","W"))
    p.add_argument("--conditions",required=True,type=Path)
    p.add_argument("--terminal",type=Path)
    p.add_argument("--config",type=Path,default=Path(__file__).with_name("config_v4.json"))
    args=p.parse_args()
    cfg=load(args.config)
    data=prepare(load(args.trajectory),load(args.terminal or args.trajectory.with_name("TERMINAL.json")),
                 cfg["thought_truncation"])
    run_case(data,load(args.conditions)["conditions"],v4_prompts(Path(__file__).parent),cfg,args.output,args.group)


if __name__=="__main__":
    main()
