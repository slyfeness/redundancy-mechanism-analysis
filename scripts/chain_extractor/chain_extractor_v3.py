"""Extract search chains with scoped sentence IDs and closed state questions."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import re
import unicodedata

from chain_extractor import encode, identity, jsonl, load, prepare, replace_text
from chain_extractor_v2 import display, extract_conditions, judge, list_field, obj, state_after
from chain_extractor_whole import check_steps

PHASES = "CSABFW"
MARKS = str.maketrans({**dict.fromkeys("‐‑‒–—―−­", "-"),
                       **dict.fromkeys("‘’‚‛", "'"), **dict.fromkeys("“”„‟", '"')})
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\s?\d{3})*(?:\.\d+)?(?:st|nd|rd|th)?(?:\s*%)?(?!\w|\.\d)", re.I)
NAME = re.compile(r"(?<![\w-])[A-Z][A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*")
COMMON = set("""I The This That These Those Here There However Therefore So But And Let It He She They We What Which
Who When Where How Why If Then Next First Second Third Now Also Both One Two Some Many Not No Yes A An In Of
On At By To From For Is Are Was Were Will Would Can Could May Might Must Need Perhaps Maybe Probably
Based Since After Before With Given Search Check Look Try Find Use Current Final Answer Title""".casefold().split())


def numbered(text, prefix):
    if text.startswith("（无，"):
        return []
    sentences = []
    for line in text.splitlines():
        for part in re.split(r"(?<=[.!?。！？])(?=\s)", line):
            fragments = re.split(r"(?<=[;；])", part) if len(part) > 400 else [part]
            sentences.extend(fragment for fragment in fragments if fragment.strip())
    return [{"id": f"{prefix}{i}", "text": value} for i, value in enumerate(sentences, 1)]


def checked_ids(ids, allowed):
    supplied = ids if isinstance(ids, list) else ([] if ids is None else [ids])
    valid = list(dict.fromkeys(x for x in supplied if isinstance(x, str) and x in allowed))
    invalid = [x for x in supplied if not isinstance(x, str) or x not in allowed]
    return ([{"id": x, "text": allowed[x]} for x in valid],
            {"requested_ids": supplied, "valid_ids": valid, "invalid_ids": invalid,
             "status": "partial" if valid and invalid else "valid" if valid else "invalid" if invalid else "none"})


def match_text(text):
    text = unicodedata.normalize("NFKC", text).translate(MARKS).casefold()
    text = re.sub(r"(?<=\d),\s?(?=\d{3}(?:\D|$))", "", text)
    return " ".join(re.sub(r"(?<=\d)\s+%", "%", text).split())


def claim_keywords(texts, question):
    question_names = set(re.findall(r"[a-z][a-z0-9]*(?:[-'][a-z0-9]+)*", match_text(question)))
    keys = {}
    for original in texts:
        text = unicodedata.normalize("NFKC", original).translate(MARKS)
        for m in NUMBER.finditer(text):
            keys[match_text(m[0])] = None
        for m in NAME.finditer(text):
            word = match_text(m[0])
            if word not in COMMON and word not in question_names:
                keys[word] = None
    return list(keys)


def check_claim(claim, references, question, corpus):
    words = claim_keywords([row["text"] for row in references], question)
    missing = []
    normalized_corpus = [match_text(text) for text in corpus] if words else []
    for word in words:
        boundary = (r"(?<![\w.])", r"(?!\w|\.\d)") if NUMBER.fullmatch(word) else (r"(?<![\w-])", r"(?![\w-])")
        expression = re.compile(boundary[0] + re.escape(word) + boundary[1])
        if not any(expression.search(text) for text in normalized_corpus):
            missing.append(word)
    return {"claim": claim, "cited_sentences": references, "keywords": words, "missing_keywords": missing,
            "status": "无返回依据" if missing else "有依据" if words else "无法判断"}


def read_prompts(path):
    return {phase: (path / f"prompt_v3_{phase}.txt").read_text(encoding="utf-8") for phase in PHASES}


def scope(sentences):
    return {row["id"]: row["text"] for row in sentences}


def prepare_numbered(data, group):
    rings = data["rings"]
    first = numbered(rings[0]["thinking"], "S")
    prior = first
    steps = []
    for ring in rings[1:-1]:
        i = ring["stage"]
        before = numbered(ring["thinking_before"], "P") if group == "S" else prior
        after = numbered(ring["thinking_after"], "N" if group == "S" else f"T{i}-")
        marker = ring["thinking_after"] if ring["thinking_after"].startswith("（无，") else None
        returns = []
        docs = {}
        snippets = []
        for call in ring["calls"]:
            hits = []
            for doc in call["returned"]:
                row = {k: v for k, v in doc.items() if k != "snippet"}
                if "snippet" in doc:
                    row["sentences"] = numbered(doc["snippet"], f'{doc["docid"]}-')
                    snippets.append(doc["snippet"])
                    for sentence in row["sentences"]:
                        old = docs.setdefault(sentence["id"], (str(doc["docid"]), sentence["text"]))
                        if old != (str(doc["docid"]), sentence["text"]):
                            raise ValueError("different sentences share a document ID inside a step")
                hits.append(row)
            if call.get("returned_text"):
                snippets.append(call["returned_text"])
            returns.append({**call, "returned": hits})
        steps.append({"step": i, "before": before, "after": after, "marker": marker,
                      "calls": returns, "document_sentences": docs, "snippets": snippets})
        prior = after
    terminal = rings[-1]
    thought = numbered(terminal["thinking"], "F") if group == "S" else prior
    answer = [] if terminal["formal_answer"] == "未交卷" else numbered(terminal["formal_answer"], "Z")
    return first, steps, thought, answer, terminal


def whole_payload(common, first, steps, answer, terminal):
    return {**common, "start_thinking": first,
            "steps": [{"step": row["step"], "queries": [c["query"] for c in row["calls"]],
                       "returns": [{k:v for k,v in c.items() if k!="query"} for c in row["calls"]],
                       "thinking_after": row["marker"] or row["after"]} for row in steps],
            "terminal": {"answer": answer, "submission_status": "未交卷" if terminal["formal_answer"] == "未交卷" else "已交卷",
                         "termination_reason": terminal["termination_reason"]}}


def state_view(state, conditions):
    by_id = {row["id"]: row["text"] for row in conditions}
    return {"candidates": state["candidates"],
            **{field: [{"id": i, "text": by_id[i]} for i in state[field]] for field in ("confirmed", "open")}}


def cites_for(audits, phase, step):
    def add(field, ids, allowed, key=None):
        refs, result = checked_ids(ids, allowed)
        row = {"phase": phase, "step": step, "field": field, "key": key, **result, "applied": False}
        audits.append(row)
        return refs, row
    return add


def apply_state(answer, initial, ids, cite, allowed, phase, *, block_main=False, merge=None):
    candidates = []
    conditions = []
    groups = (("candidates", "新增"), ("main_candidate", "设为当前")) if phase == "S" else (
        ("main_candidate", "设为当前"), ("excluded", "排除"), ("other_candidates", "新增"))
    names = {match_text(row["name"]) for row in initial["candidates"]}
    for field, op in groups:
        rows = [answer[field]] if field == "main_candidate" and isinstance(answer.get(field), dict) else list_field(answer, field)
        for raw in rows:
            row = obj(raw)
            name = row.get("name")
            refs, audit = cite(field, row.get("ids"), allowed, name)
            eligible = bool(refs) and isinstance(name, str) and bool(name.strip())
            if field=="main_candidate" and block_main:
                audit["blocked_by_checking_object"]=True
                continue
            if eligible and (merge or op != "新增" or match_text(name) not in names):
                candidates.append({"name": name, "op": op})
                names.add(match_text(name))
                audit["applied"] = True
    if phase == "B":
        for field, op, eligible_ids in (("condition_checks","确认",initial["open"]),
                                       ("retracted","撤回",initial["confirmed"])):
            for raw in list_field(answer, field):
                row = obj(raw)
                key = row.get("id")
                refs, audit = cite(field, row.get("ids"), allowed, key)
                audit["change_requested"] = field == "retracted" or row.get("confirmed") is True
                if refs and key in eligible_ids and audit["change_requested"]:
                    conditions.append({"op": op, "id": key})
                    audit["applied"] = True
    if merge:
        initial,candidates=merge(initial,candidates)
    return state_after(initial, candidates, conditions, ids)


def claim_rows(answer, cite, allowed, question, corpus, phase, step, auditor=check_claim):
    values = []
    for raw in list_field(answer, "claims"):
        row = obj(raw)
        claim = row.get("claim")
        refs, audit = cite("claims", row.get("ids"), allowed, claim)
        audit["applied"] = bool(refs)
        values.append({"phase":phase,"step":step, **auditor(claim, refs, question, corpus)})
    return values


def show_refs(values):
    return " / ".join(f'[{row["id"]}] {display(row["text"][:200])}' for row in values)


def citations_line(text, values):
    return display(text) + (f"（{show_refs(values)}）" if values else "（无有效引用编号）")


def state_line(state):
    candidates = "、".join(f'{x["name"]}（{x["status"]}）' for x in state["candidates"]) or "—"
    return f'候选 {candidates}；已确认 {"、".join(state["confirmed"]) or "—"}；未确认 {"、".join(state["open"]) or "—"}'


def unsupported_lines(rows):
    return [f'  - 无返回依据：{display(r["claim"])}。未找到 {"、".join(r["missing_keywords"])}'
            for r in rows if r["status"] == "无返回依据"]


def run_case(data, conditions, prompts, cfg, out, group, progress=None, *, protocol=None):
    if cfg["reasoning_effort"] != "medium":
        raise ValueError("v3 requires medium reasoning effort")
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "checkpoint"
    cache.mkdir(exist_ok=True)
    answer_type=getattr(protocol,"answer_type",None)
    fingerprint={"input":data,"conditions":conditions,"group":group,"prompts":prompts,
                 "config":{k:v for k,v in cfg.items() if k!="url"}}
    if answer_type is not None:
        fingerprint["answer_type"]=answer_type
    identity(cache / "identity.sha256", fingerprint)
    merge=getattr(protocol,"merge_candidates",None)
    finish=getattr(protocol,"render_final",None)
    prepare_case=protocol.prepare_numbered if protocol else prepare_numbered
    check_claims=protocol.check_claim if protocol else check_claim
    first, steps, last, answer, terminal = prepare_case(data, group)
    common = {"question": data["question"], "conditions": conditions}
    if answer_type is not None:
        common["所问对象类型"]=answer_type
    ids = [row["id"] for row in conditions]
    state = {"candidates": [], "confirmed": [], "open": ids}
    raw, states, cites, claims, facts, corpus, summaries = [], [], [], [], [], [], []
    check = None
    failed = False
    model = {}
    by_step = {}

    def call(phase, stage, payload):
        extended = cfg["whole_max_tokens"] if phase == "W" else None
        followup=phase=="B_followup"
        result, error, attempts = judge(cache, f"{stage}-{phase}", prompts["B" if followup else phase], payload, cfg,
                                        max_retries=0 if followup else 3, extended_max_tokens=extended)
        raw.extend({"phase":phase,"stage":stage,**r} for r in attempts)
        if progress:
            progress(phase, stage, len(attempts), error)
        return result, error

    def response(phase, stage, payload):
        if group == "S":
            result,error=call(phase,stage,payload)
            return obj(result),error
        if phase in ("S","F"):
            return obj(model.get("start" if phase=="S" else "final")),None
        return by_step.get(stage,{}),None if stage in by_step else "step_missing"

    if group == "W":
        payload=protocol.whole_payload(common,first,steps,last,answer,terminal) if protocol else (
            whole_payload(common,first,steps,answer,terminal))
        result,error=call("W",None,payload)
        model=obj(result)
        by_step,check=check_steps(result,[row["step"] for row in steps])
        failed=bool(error)
        check.update(request_error=error,length_retry=any(r["request"]["max_tokens"]==cfg["whole_max_tokens"] for r in raw))
        replace_text(out/"STEP_CHECK.json",encode(check)+"\n")

    def save_state(kind,step,error):
        states.append({"type":kind,"stage":step,"state":state,"state_carried_due_to_failure":bool(error)})

    if failed:
        text=["# 思维链","","整条提取失败，详见 RAW.jsonl。"]
    else:
        start,error=response("S",0,{**common,"start_thinking":first})
        cite=cites_for(cites,"S",0)
        planrefs,_=cite("plan_ids",start.get("plan_ids"),scope(first))
        if not error:
            state=apply_state(start,state,ids,cite,scope(first),"S",merge=merge)
        save_state("start",0,error)
        text=["# 思维链","","## 起点","",f'- 理解：{display(start.get("understanding"))}',
              "- 假设："+("、".join(display(x) for x in list_field(start,"hypotheses")) or "—"),
              f'- 计划：{citations_line(start.get("plan"),planrefs)}',f'- 状态：{state_line(state)}',""]
        for step in steps:
            i=step["step"]
            before=state
            view=state_view(state,conditions)
            if protocol:
                a,a_error=protocol.step_action(response,i,common,view,step)
            else:
                a,a_error=response("A",i,{**common,"state":view,"thinking_before":step["before"],"calls":step["calls"]})
            cite_plan=cites_for(cites,"A1" if protocol else "A",i)
            cite_a=cites_for(cites,"A2" if protocol else "A",i)
            doc_sentences=step["document_sentences"]
            doc_scope={sid:item[1] for sid,item in doc_sentences.items()}
            planrefs,_=cite_plan("plan_ids",a.get("plan_ids"),scope(step["before"]))
            new=[]
            for item in list_field(a,"new_facts"):
                item=obj(item)
                fact=item.get("fact")
                ref,row=cite_a("new_facts",item.get("ids"),doc_scope,fact)
                if ref and isinstance(fact,str) and fact.strip():
                    row["applied"]=True
                    docids=list(dict.fromkeys(doc_sentences[r["id"]][0] for r in ref))
                    new.append((fact,docids,ref))
            facts.extend({"step":i,"fact":fact} for fact,_,_ in new)
            corpus.extend(step["snippets"])
            if answer_type is not None:
                protocol.observe(step)
            b_payload={**common,"state":view,"verified_facts":facts,
                       "thinking_after":step["marker"] or step["after"]}
            b,b_error=response("B",i,b_payload)
            followup=None
            if protocol and group=="S":
                b,followup=protocol.follow_up(call,i,b_payload,b,before["open"],b_error)
            cite_b=cites_for(cites,"B",i)
            following=scope(step["after"])
            resultrefs,_=cite_b("conclusion_ids",b.get("conclusion_ids"),following)
            rows=claim_rows(b,cite_b,following,data["question"],corpus,"B",i,check_claims)
            claims.extend(rows)
            checking=(protocol.checking_object(b,cite_b,following) if answer_type is not None else {})
            conflict=bool(checking.get("checking_object_candidate_conflict"))
            if not (a_error or b_error):
                state=apply_state(b,state,ids,cite_b,following,"B",block_main=conflict,merge=merge)
            save_state("call",i,a_error or b_error)
            states[-1].update(checking)
            if followup is not None:
                states[-1]["condition_followup"]=followup
                if finish:
                    states[-1]["unjudged_conditions"]=[{"id":key,"status":"未判断"} for key in followup["missing_after"]]
            dnew={d["docid"] for c in step["calls"] for d in c["returned"] if "sentences" in d}
            dold={d["docid"] for c in step["calls"] for d in c["returned"] if "sentences" not in d}-dnew
            text.extend([f"## 第 {i} 次调用","",f'- 动作：{display(a.get("looking_for"))}',
                         *(f'  - 查询：{c["query"]}' for c in step["calls"])])
            if protocol:
                text.append(f'  - 计划一致性：{citations_line(a.get("plan_match"),planrefs)}')
            if a.get("plan_match")=="不一致":
                text.append(f'  - 与计划不一致：{citations_line(a.get("plan_note"),planrefs)}')
            text.append(f"- 返回：新文档 {len(dnew)} 篇、旧文档 {len(dold)} 篇")
            text.extend(f'  - {display(fact)}（docid {"、".join(docids)}；{show_refs(ref)}）' for fact,docids,ref in new)
            shown_state=(protocol.state_line(state,checking.get("checking_object")) if answer_type is not None
                         else state_line(state) if state!=before else "无变化")
            text.extend([f'- 结论：{citations_line(b.get("conclusion"),resultrefs)}',*unsupported_lines(rows),
                         "- 状态："+shown_state])
            if states[-1].get("unjudged_conditions"):
                text.append("  - 未判断："+"、".join(row["id"] for row in states[-1]["unjudged_conditions"]))
            if a_error or b_error:
                text.append("  - 本步沿用上一步的状态，详见回执。")
            text.extend([f'- 计划：{display(b.get("plan"))}',""])
            summaries.append(display(b.get("step_summary")))
        i=len(steps)+1
        end,error=response("F",i,{**common,"state":state_view(state,conditions),"verified_facts":facts,
                                 "last_thinking":last,"answer":answer,
                                 "submission_status":"未交卷" if terminal["formal_answer"]=="未交卷" else "已交卷",
                                 "termination_reason":terminal["termination_reason"]})
        final_scope={**scope(last),**scope(answer)}
        cite=cites_for(cites,"F",i)
        basis,_=cite("basis_ids",end.get("basis_ids"),final_scope)
        unresolved,_=cite("unresolved_ids",end.get("unresolved_ids"),final_scope)
        rows=claim_rows(end,cite,final_scope,data["question"],corpus,"F",i,check_claims)
        claims.extend(rows)
        save_state("final",i,error)
        formal=terminal["formal_answer"]
        final_text=formal if formal=="未交卷" or error else end.get("final_answer")
        if finish:
            final_text,final_fields=finish(end,terminal,cite,scope(answer),error)
            states[-1].update(final_fields)
        text.extend(["## 终点","",f"- 答案：{display(final_text)}",
                     f'- 依据：{citations_line(end.get("basis"),basis)}',
                     f'- 未决：{citations_line(end.get("unresolved"),unresolved)}'])
        if terminal["termination_reason"]:
            text.append(f'- 终止原因：{terminal["termination_reason"]}')
        text.extend([*unsupported_lines(rows),""," → ".join(summaries)])
    replace_text(out/"CHAIN.md","\n".join(text)+"\n")
    for name,rows in (("STATE",states),("CITES",cites),("CLAIMS",claims),("RAW",raw)):
        jsonl(out/f"{name}.jsonl",rows)
    count_candidates={"candidates","main_candidate","other_candidates","excluded"}
    count_conditions={"condition_checks","retracted"}
    result={"raw":raw,"steps":len(steps),"whole_failed":failed,"step_check":check,
            "carried":sum(row["state_carried_due_to_failure"] for row in states),
            "bad_ids":sum(len(row["invalid_ids"]) for row in cites),
            "candidate_checks_unapplied":sum(row["field"] in count_candidates and not row["applied"] for row in cites),
            "condition_checks_unapplied":sum(row["field"] in count_conditions and row.get("change_requested") and not row["applied"] for row in cites),
            "claims":dict(Counter(row["status"] for row in claims))}
    if protocol:
        followups=[row["condition_followup"] for row in states if "condition_followup" in row]
        errors=Counter()
        for row in cites:
            errors[row["field"]]+=len(row["invalid_ids"])
        result.update(condition_followups=sum(r["requested"] for r in followups),
                      missing_before=sum(len(r["missing_before"]) for r in followups),
                      missing_after=sum(len(r["missing_after"]) for r in followups),
                      bad_ids_by_field={field:n for field,n in errors.items() if n})
    if answer_type is not None:
        result.update(candidate_conflicts=sum(bool(row.get("checking_object_candidate_conflict")) for row in states),
                      final_candidates=len(state["candidates"]))
    if finish:
        result.update(answer_kind=states[-1]["answer_kind"],
                      unjudged=sum(len(row.get("unjudged_conditions",[])) for row in states))
    return result


def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument("trajectory",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--group",required=True,choices=("S","W"))
    p.add_argument("--config",type=Path,default=Path(__file__).with_name("config_v3.json"))
    p.add_argument("--terminal",type=Path)
    p.add_argument("--conditions",type=Path)
    args=p.parse_args()
    cfg=load(args.config)
    if cfg["reasoning_effort"]!="medium":
        raise ValueError("v3 requires medium reasoning effort")
    data=prepare(load(args.trajectory),load(args.terminal or args.trajectory.with_name("TERMINAL.json")),
                 cfg["thought_truncation"])
    prompts=read_prompts(Path(__file__).parent)
    row=load(args.conditions) if args.conditions else extract_conditions(
        data["question"],prompts["C"],cfg,args.output/"condition_checkpoint")
    run_case(data,row["conditions"],prompts,cfg,args.output,args.group)
    replace_text(args.output/"CONDITIONS.json",encode(row)+"\n")


if __name__=="__main__":
    main()
