"""Frozen v13.4 request rendering and ledger construction, with injectable I/O."""
from pathlib import Path
from copy import deepcopy
from . import ledger, ledger_v135
from .pipeline_checked import checked, checked_q3
from .pipeline_rules import (ground_answer, select_all_new, prior_candidates,
    Q1_CONFIGS, combine_votes, check_document_facts, facts_with_broad,
    tokens_for_claim, validate_q1, validate_q4, validate_q5, usable_dropped)
from .judge import q2_cache_key

WIRE = {"model": "gpt-oss-120b", "temperature": 0, "seed": 2026112004,
        "reasoning_effort": "medium", "max_tokens": 16384, "timeout_seconds": 1800}

def materialize(value, docs, step):
    result = []
    for i, fact in enumerate((value or {}).get("facts", []), 1):
        sources = [docs[x] for x in fact["ids"]]
        docids = list(dict.fromkeys(d["docid"] for d in sources))
        result.append({"key": f"E{i}@{step}", "doc": " / ".join(docids), "sents": fact["ids"],
                       "text": " ".join(d["text"] for d in sources),
                       **{k: fact[k] for k in ("fact", "about", "conditions", "strength")}})
    return result

def prepare_returns(steps):
    seen = {}
    rows, texts = {}, {}
    for step in steps:
        new, old, all_text, citations = [], [], [], {}
        for call in step["returns"]:
            if not call["fed_to_model"]:
                continue
            for doc in call["returned"]:
                docid = str(doc["docid"])
                if "sentences" in doc:
                    sentences = doc["sentences"]
                    if docid not in seen:
                        new.append(doc)
                        for sentence in sentences:
                            citations[sentence["id"]] = {"docid": docid, "text": sentence["text"]}
                    else:
                        old.append(doc["title"])
                    seen[docid] = sentences
                else:
                    old.append(doc["title"])
                    sentences = seen[docid]
                all_text.extend(s["text"] for s in sentences)
        rows[step["step"]] = {"新文档": new, "之前见过": old, "citations": citations}
        texts[step["step"]] = " ".join(all_text)
    return rows, texts

def chain_names(chain):
    return [name for name in [chain["answer"], *(row["object"] for row in chain["linked"])] if name]

def calls_of(row):
    for ballot in row["q1_votes"]["ballots"]:
        yield f"Q1.{ballot['number']}", ballot["call"]
    for phase, call in row["calls"].items():
        if phase in ("Q2", "Q5"):
            yield from ((phase, c) for c in call)
        elif phase != "Q1":
            yield phase, call
    if row.get("q3_audit"):
        yield "Q3", row["q3_audit"]


def next_behaviour(thinking, queries=(), final=None):
    if isinstance(thinking, list):
        thinking = " ".join(str(value.get("text", "")) if isinstance(value, dict) else str(value)
                            for value in thinking)
    return " ".join((str(thinking or ""), " ".join(map(str, queries or ())), str(final or "")))


def extract_document(folder, index, doc, prompt, payload, cfg, ids, send):
    call = checked(folder, f"Q2-{index}", prompt, {**payload, "返回句子": [doc]}, cfg,
                   check_document_facts, send)
    shown = {sentence["id"] for sentence in doc["sentences"]}
    facts, rejected = facts_with_broad(call["parsed"] or {"facts": []}, ids, shown)
    return {**call, "docid": str(doc["docid"])}, facts, rejected

def finish_ledger(record, returns, metadata, *, next_text=None, k_hold=3, k_restrict=2):
    projected = record
    if metadata["gold"]:
        for step in projected["steps"]:
            for ev in step["evidence"]:
                if ev.get("text") and not ledger.norm(ev["text"]):
                    ev["text"] = ""
    if next_text is not None:
        return ledger_v135.run(projected, returns, metadata["gold"], metadata["t_belief"],
                               metadata["question"], next_text, k_hold=k_hold, k_restrict=k_restrict)
    return ledger.run(projected, returns, metadata["gold"], metadata["t_belief"],
                      question_text=metadata["question"])

def execute(case, metadata, prompts, send, *, cfg=None, q1_early_stop=False, q2_cache=None,
            conditions_version="v13.4", stats=None, use_q3=True, q3_audit=False, k_hold=3, k_restrict=2):
    conditions = case["conditions"]
    ids = {x["id"] for x in conditions}
    tid = case["trajectory_id"]
    records = {"query_id":case["query_id"], "group":case["group"],
               "conditions":[x["id"] for x in conditions], "steps":[]}
    common = {"题目原文":metadata["question"], "条件清单":conditions}
    cfg = {**WIRE, **(cfg or {})}
    stats = stats if stats is not None else {}
    stats.setdefault("q1_early_stops", 0)
    stats.setdefault("q2_cache_hits", 0)
    stats.setdefault("q2_cache_misses", 0)
    rows, known, evidence_registry, adopted, excluded = [], {}, {}, set(), {}
    steps = case["steps"]
    next_text = {}
    returns, returns_text = prepare_returns(steps)
    for i, given in enumerate(steps):
        t = given["step"]
        folder = Path(tid) / f"{t:03}"
        prefix = ledger.run(records, {k:v for k,v in returns_text.items() if k < t},
                            question_text=metadata["question"])
        chain = prefix["steps"][-1]["chain"] if prefix["steps"] else {"answer":None,"linked":[]}
        q1_body = {**common, "已出现过的对象": list(known),
                   "调用前思考": given["before"], "本次查询": given["queries"]}
        def vote(number, settings):
            tag = "Q1" if number == 1 else f"Q1-vote{number}"
            return checked(folder, tag, prompts["Q1"], q1_body, {**cfg, **settings},
                           lambda value: validate_q1(value, ids), send)

        q1_calls = [vote(j, settings) for j, settings in enumerate(Q1_CONFIGS[:2], 1)]
        _, first_two = combine_votes(q1_calls, common["题目原文"], known)
        agreed = first_two["ballots"][0]["yes"] == first_two["ballots"][1]["yes"]
        if q1_early_stop and agreed:
            stats["q1_early_stops"] += 1
        else:
            q1_calls.append(vote(3, Q1_CONFIGS[2]))
        targets, q1_votes = combine_votes(q1_calls, common["题目原文"], known)
        q1 = q1_calls[0]
        selected, selection = select_all_new(returns[t]["新文档"])
        candidates=prior_candidates(records["steps"])
        payload = {**common, "本步目标": targets, "已提到的候选": candidates}
        extracted = []
        for index, doc in enumerate(selected, 1):
            cache_key = q2_cache_key(prompts["Q2"], {**payload, "返回句子": [doc]}, cfg, conditions_version)
            if q2_cache is not None and cache_key in q2_cache:
                value = deepcopy(q2_cache[cache_key])
                stats["q2_cache_hits"] += 1
            else:
                value = extract_document(folder, index, doc, prompts["Q2"], payload, cfg, ids, send)
                stats["q2_cache_misses"] += 1
                if q2_cache is not None:
                    q2_cache[cache_key] = deepcopy(value)
            extracted.append(value)
        q2 = [call for call, _, _ in extracted]
        facts = [fact for _, rows, _ in extracted for fact in rows]
        rejected_facts = [{"docid": call["docid"], **reason}
                          for call, _, rejected in extracted for reason in rejected]
        fresh = materialize({"facts": facts}, returns[t]["citations"], t)
        for ev, source in zip(fresh, facts, strict=True):
            ev["broad"] = source["broad"]
        evidence_registry.update({r["key"]: r for r in fresh})
        fresh_ids = {r["key"] for r in fresh}
        available = {key:value for key,value in evidence_registry.items() if key not in adopted}
        response_material = {**common,"下一轮思考":given["after"] or given["after_marker"]}
        if i+1 < len(steps):
            response_material["下一次查询"] = steps[i+1]["queries"]
        else:
            response_material["正式答案"] = given["final_sentences"]
        next_text[t] = next_behaviour(response_material["下一轮思考"],
                                      response_material.get("下一次查询"), response_material.get("正式答案"))
        q3 = None
        verdicts, earlier, claim_rows = {}, [], []
        if use_q3 or q3_audit:
            q3 = checked_q3(folder, prompts["Q3"],
                            {**response_material,"事实清单":[{"id":k,"about":v["about"],"fact":v["fact"]}
                                                             for k,v in available.items()]},
                            cfg, set(available), send)
            conclusions = q3["parsed"]
            words_to_verdict = {"用了":"采纳","不信":"不信","没提":"没理会"}
            verdicts = {k:{"verdict":words_to_verdict[v],"reason":""}
                        for k,v in conclusions["verdicts"].items() if k in fresh_ids}
            earlier = [k for k,v in conclusions["verdicts"].items() if k not in fresh_ids and v=="用了"]
            adopted.update(k for k,v in conclusions["verdicts"].items() if v=="用了")
            claim_rows = [{"claim":claim,"tokens":tokens_for_claim(claim),"conditions":[]}
                          for claim in conclusions["claims"]]
        q4_prompt = (prompts["Q4"].replace("{上一步答案}", chain["answer"] or "无")
                                  .replace("{所问对象类型}", metadata["answer_type"]))
        q4 = checked(folder, "Q4", q4_prompt, response_material, cfg, lambda x:validate_q4(x,ids), send)
        q4_output=q4["parsed"]
        dropped = usable_dropped(q4_output)
        if not q4["passed"]:
            dropped = next((items for a in reversed(q4["attempts"])
                            if a["receipt"]["finish_reason"]!="length"
                            and (items:=usable_dropped(a["receipt"].get("parsed")))), [])
        input_name = None if not q4["passed"] else q4_output["answer"]
        name_sources = {"thought": [r["text"] for orig in steps[:i+1] for r in orig["before"]+orig["after"]],
                        "query": [x for orig in steps[:i+2] for x in orig["queries"]],
                        "evidence": [ev["text"] for ev in evidence_registry.values()]}
        found_in = ground_answer(input_name,name_sources)
        if not q4["passed"]:
            answer_chain = None
        else:
            answer_chain = {"answer":input_name if found_in else None,"linked":q4_output["linked"]}
        q4["name_check"] = {"proposed":input_name,"matched_source":found_in,
                            "cleared":input_name is not None and found_in is None}
        q5, exclusions = [], []
        for index, drop in enumerate(dropped,1):
            entity = drop["object"]
            excerpts = [{"id":ev["key"],"text":ev["text"],"about":ev["about"]} for ev in evidence_registry.values()
                        if ledger.same(entity, ev["about"])]
            question = {**common,"对象":entity,"理由":drop["reason"],"证据原句":excerpts}
            call = checked(folder, f"Q5-{index}", prompts["Q5"], question, cfg, lambda x:validate_q5(x,ids), send)
            q5.append(call)
            evaluation=call["parsed"] or {"basis":None,"basis_conditions":[],"valid":"看不出"}
            exclusions.append({"object":entity,"reason":drop["reason"],
                               **{k:evaluation[k] for k in ("basis","basis_conditions","valid")}})
        known.update(dict.fromkeys(n for n in [r["object"] for r in targets] + [r["about"] for r in fresh]
                                   + (chain_names(answer_chain) if answer_chain else [])
                                   if n and n != ledger.UNKNOWN))
        excluded.update(dict.fromkeys(r["object"] for r in exclusions))
        record = {"step":t,"query":" | ".join(given["queries"]),"targets":targets,
                  "new_docs":given["new_docs"],"old_docs":given["old_docs"],"strict":given["strict"],
                  "evidence":fresh,"verdicts":verdicts if use_q3 else {},
                  "earlier_adopted":earlier if use_q3 else [],"excluded":exclusions,
                  "answer_chain":answer_chain,"assertions":[r for r in claim_rows if r["tokens"]] if use_q3 else [],
                  "unjudged_evidence":q3["unjudged_evidence"] if use_q3 else []}
        records["steps"].append(record)
        calls = {"Q1": q1, "Q2": q2}
        if use_q3:
            calls["Q3"] = q3
        calls.update(Q4=q4, Q5=q5)
        row = {"step":t,"calls":calls,"record":record,
               "before":{"chain":chain,"excluded":list(dict.fromkeys(
                   e["object"] for rec in records["steps"][:-1] for e in rec["excluded"]))},
               "selection":{"Q1_discarded_restrictions":q1_votes["ballots"][0]["rejected"],"Q2_selected":selection,
                            "Q2_discarded_facts":rejected_facts}}
        if use_q3:
            row["selection"]["Q3_claims_without_tokens"] = [r["claim"] for r in claim_rows if not r["tokens"]]
            row["q3_stray_keys"] = q3["q3_stray_keys"]
        elif q3_audit:
            row["q3_audit"] = q3
        if not use_q3:
            row["next_text"] = next_text[t]
        row["q1_votes"] = q1_votes
        row["unjudged_q2_documents"] = [call["docid"] for call in q2 if not call["passed"]]
        row["prior_candidates_q2"] = candidates
        row["truncation_retry"] = any(call["truncation_retry"] for p, call in calls_of(row)
                                      if use_q3 or p != "Q3")
        row["未判"] = [p for p, call in calls_of(row) if not call["passed"] and (use_q3 or p != "Q3")]
        rows.append(row)
    result = finish_ledger(records, returns_text, metadata, next_text=None if use_q3 else next_text,
                           k_hold=k_hold, k_restrict=k_restrict)
    scored_records = result.get("record", records)["steps"]
    for row, record, derived in zip(rows, scored_records, result["steps"], strict=True):
        row["record"], row["derived"] = record, derived
    return rows
