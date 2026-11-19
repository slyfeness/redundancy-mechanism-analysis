"""Versioned M2-v4 Slurm stages over the frozen training pilot."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from ledger_grpo.ledgercredit.evidence_judge import fed_events
from ledger_grpo.ledgercredit.judge_v3 import (
    STATUSES, audit_rule_first, check_verdicts, merge_verdicts, payload,
    sentence_spans as old_spans, unique_index,
)
from ledger_grpo.ledgercredit.judge_v4 import JUDGE_PROMPT, JUDGE_VERSION, VERSION, compact, entity_check, gate, sentences
from ledger_grpo.ledgercredit.stages import observed_texts

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "judge_v3"))
import run as previous_driver
from assertions_v4 import (DRAFT, VERIFY, DETAIL_AUDIT, approve, candidates_from, consume_conditions,
                           coverage, freeze, list_rows, verify_payload)

BUDGET = 150
WORKERS = 8
EXPECTED = 50
TERM = re.compile(r"[^\W_]{3,}")
emit, dump, read, rows = (previous_driver.emit, previous_driver.dump, previous_driver.read, previous_driver.rows)


def inputs(root, previous):
    questions, v2, outcomes = previous_driver.training(root)
    v3 = previous_driver.read_v3(previous / "pilot", v2)
    if len(v3) != EXPECTED or sum(len(q["conditions"]) for q in v3.values()) != 244:
        raise ValueError("expected the 244 published v3 assertions")
    return questions, v3, outcomes


def blocks(stages):
    by_unit = defaultdict(list)
    index = 0
    for event, unit, returns in fed_events(stages):
        for text in observed_texts(returns):
            index += 1
            pid = f"c{index}"
            by_unit[unit].append({"id": pid, "unit_id": unit, "return_index": event, "text": text,
                                  "match_text": compact(text), "sentences": sentences(text, pid)})
    order = sorted(by_unit)
    return [[r for unit in order[i:i+5] for r in by_unit[unit]] for i in range(0, len(order), 5)]


def split_change(old, new):
    aligned = next((n for n in new if (n["start"], n["end"]) == (old["start"], old["end"])), None)
    if aligned is None:
        return "content_changed"
    return "id_changed" if old["id"] != aligned["id"] else "same"


def make_input(q, original, documents, tokenize):
    index = {}
    for number, docid in enumerate(q["evidence_docs"], 1):
        for ref in sentences(documents[docid], f"d{number}"):
            index[ref["id"]] = {**ref, "docid": docid}
    lookup = list(index)
    context = [q["question"]] + [c["text"] for c in original["conditions"]]
    targets = [set(TERM.findall(t.casefold())) for t in context]

    def size(chosen):
        return tokenize(json.dumps([{"id": key, "text": index[key]["text"]} for key in chosen], ensure_ascii=False))

    selected = lookup
    if size(selected) > 95_000:
        positions = {k: i for i, k in enumerate(lookup)}
        def rank(key):
            terms = set(TERM.findall(index[key]["text"].casefold()))
            return max((len(t & terms) for t in targets), default=0), -positions[key]
        ranked = sorted(lookup, key=rank, reverse=True)
        a, b = 0, len(ranked)
        while a + 1 < b:
            middle = (a + b) // 2
            if size(ranked[:middle]) <= 95_000:
                a = middle
            else:
                b = middle
        selected = sorted(ranked[:a], key=positions.get)
    return {"qid": q["id"], "question": q["question"], "index": {key: index[key] for key in selected},
            "restricted": len(selected) < len(lookup), "sentence_count": len(lookup)}


def prepare(args):
    from transformers import AutoTokenizer
    questions, original, outcomes = inputs(args.root, args.previous)
    original_sample = read(args.previous / "inputs" / "plan.json")["tids"]
    if len(set(original_sample)) != 10 or any(t not in outcomes for t in original_sample):
        raise ValueError("pilot sample differs from the frozen v3 plan")
    grouped = previous_driver.stage_rows(args.root, outcomes)
    total, sampled = Counter(), Counter()
    old_evidence = {item["qid"]: item["sentence_index"] for item in
                    rows(args.previous / "inputs" / "assertion_inputs.jsonl")}
    old_judge = defaultdict(list)
    for item in rows(args.previous / "m2-v3-192472" / "judge_receipts.jsonl"):
        old_judge[item["trajectory_id"]].extend(v for v in item["verdicts"] if v["status"] != "unknown")
    for tid, stages in grouped.items():
        indexed = [s for chunk in blocks(stages) for s in chunk]
        by_id = {s["id"]: s for s in indexed}
        total["snippets_old"] += sum(len(old_spans(x["text"])) for x in indexed)
        total["snippets_new"] += sum(len(x["sentences"]) for x in indexed)
        changes = {(v["passage_id"], s["id"]): s for v in old_judge[tid] for s in v["sentences"]}
        for (pid, sid), sentence in changes.items():
            sampled[split_change(sentence, by_id[pid]["sentences"])] += 1
    docs = read(args.root / "docs-192072" / "evidence_docs.json")
    scope = {did for q in questions.values() for did in q["evidence_docs"]}
    total.update(documents_old=sum(len(old_spans(docs[d])) for d in scope),
                 documents_new=sum(len(sentences(docs[d], "d")) for d in scope))
    v3_selected = Counter()
    for qid, q in questions.items():
        fresh = {d: sentences(docs[d], f"d{i}") for i, d in enumerate(q["evidence_docs"], 1)}
        choices = {(e["docid"], sid) for c in original[qid]["conditions"] for e in c["evidence"]
                   for sid in e["sentence_ids"]}
        for docid, sid in choices:
            v3_selected[split_change(old_evidence[qid][sid], fresh[docid])] += 1
    nblocks = sum(len(blocks(grouped[t])) for t in original_sample)
    if 2 * len(questions) + nblocks + 1 > BUDGET:
        raise ValueError("essential calls exceed first-stage budget")
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True, model_max_length=1_000_000)
    args.out.mkdir(mode=0o700)
    with (args.out / "source_inputs.jsonl").open("x", encoding="utf-8") as file:
        for qid, q in questions.items():
            emit(file, make_input(q, original[qid], docs, lambda t: len(tokenizer.encode(t, add_special_tokens=False))))
    summary = {"trajectories": original_sample, "pilot_blocks": nblocks, "static_calls": 101+nblocks,
               "cutting": dict(total), "selected_v3_assertion_sentences": dict(v3_selected),
               "selected_v3_judge_sentences": dict(sampled),
               "model_revision": "config-sha256:" + sha256((args.model_path / "config.json").read_bytes()).hexdigest(),
               "v3_file_sha256": sha256((args.previous / "pilot" / "conditions.jsonl").read_bytes()).hexdigest(),
               "prompt_sha256": {k: sha256(v.encode()).hexdigest() for k, v in
                                  (("draft", DRAFT), ("verify", VERIFY), ("judge", JUDGE_PROMPT))},
               "heldout_read": 0}
    dump(args.out / "plan.json", summary)
    print(json.dumps(summary), flush=True)


def batch(url, prompt, work, max_tokens, output, tag, counter, *, ceiling=None):
    if ceiling is not None and counter["total"] + len(work) > ceiling:
        raise ValueError("stage-one call limit exceeded")
    counter.update(total=len(work), **{tag: len(work)})
    def request(item):
        key, body = item
        parsed, raw, error = previous_driver.call(url, prompt, body, max_tokens)
        return key, parsed, raw, error
    result = {}
    with output.open("x", encoding="utf-8") as file, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for count, (key, parsed, raw, error) in enumerate(pool.map(request, work), 1):
            result[key] = parsed if not error else None
            counter["errors"] += bool(error)
            emit(file, {"key": key, "raw": raw, "error": error})
            if count % 10 == 0 or count == len(work):
                print(json.dumps({"phase": tag, "done": count, "total": len(work), "errors": counter["errors"]}), flush=True)
    return result


def source_messages(source):
    return [{"id": key, "text": val["text"]} for key, val in source["index"].items()]


def draft_body(source, original, missing=()):
    return {"question": source["question"], "v3_assertions": [
        {"id": a["id"], "text": a["text"]} for a in original["conditions"]],
        "source_sentences": source_messages(source), "repair_conditions": list(missing),
        "source_inventory_restricted": source["restricted"]}


def assertion_pass(args, data, original, plan, counter):
    docs = read(args.root / "docs-192072" / "evidence_docs.json")
    stage = args.out
    drafts = batch(args.url, DRAFT, [(qid, draft_body(s,original[qid])) for qid,s in data.items()],
                   8192, stage/"draft_receipts.jsonl", "draft", counter, ceiling=BUDGET)
    inventories, candidates, rejected = {}, {}, {}
    for qid, source in data.items():
        raw = drafts[qid]
        inventories[qid] = consume_conditions(source["question"], list_rows(raw, "conditions"))
        parents = {a["id"] for a in original[qid]["conditions"]}
        candidates[qid], rejected[qid] = candidates_from(raw, inventories[qid], source["index"], parents, docs)
    def body(qid, options):
        source=data[qid]
        return verify_payload(source["question"], inventories[qid], options, source_messages(source), source["restricted"])
    reviews = batch(args.url, VERIFY, [(qid, body(qid, candidates[qid])) for qid in data],
                    8192, stage/"entailment_receipts.jsonl", "entailment", counter, ceiling=BUDGET)
    accepted, covers = {}, {}
    for qid, source in data.items():
        accepted[qid], failure = approve(reviews[qid], candidates[qid], inventories[qid])
        rejected[qid].extend(failure)
        covers[qid] = coverage(source["question"], inventories[qid], reviews[qid], accepted[qid], source["restricted"])
    repair = [(qid, [r for r in covers[qid].values() if r["status"] in ("generation_lost", "unresolved")])
              for qid in data if not covers[qid] or any(
                  r["status"] in ("generation_lost","unresolved") for r in covers[qid].values())]
    repair.sort(key=lambda item: (-sum(r["status"] == "generation_lost" for r in item[1]),
                                 -len(item[1]), str(item[0])))
    repair = repair[:(BUDGET-counter["total"]-plan["pilot_blocks"]-1)//2]
    if repair:
        proposed = batch(args.url, DRAFT, [(qid,draft_body(data[qid],original[qid],missing)) for qid,missing in repair],
                         8192, stage/"repair_draft_receipts.jsonl", "repair_draft", counter, ceiling=BUDGET)
        new_options = {}
        for qid, _ in repair:
            source=data[qid]
            extra = consume_conditions(source["question"], list_rows(proposed[qid], "conditions"))
            inventories[qid] = {**extra, **covers[qid]}
            parents = {a["id"] for a in original[qid]["conditions"]}
            new_options[qid], failure = candidates_from(proposed[qid], inventories[qid],
                                                       source["index"], parents, docs, prefix="r")
            rejected[qid].extend(failure)
        audits = batch(args.url, VERIFY, [(qid, body(qid,new_options[qid])) for qid,_ in repair],
                       8192, stage/"repair_entailment_receipts.jsonl", "repair_entailment", counter, ceiling=BUDGET)
        for qid, _ in repair:
            source=data[qid]
            children, failure = approve(audits[qid], new_options[qid], inventories[qid], previously=accepted[qid])
            rejected[qid].extend(failure)
            accepted[qid].extend(children)
            latest = coverage(source["question"], inventories[qid], audits[qid], accepted[qid], source["restricted"])
            # A known generation loss is closed only by a checked assertion.
            prior_losses = {r["question_span"] for r in covers[qid].values() if r["status"] == "generation_lost"}
            for row in latest.values():
                if row["question_span"] in prior_losses and not row["assertion_ids"]:
                    row["status"] = "generation_lost"
            covers[qid] = latest

    releases, stats, declines, per_question = {}, Counter(), Counter(), []
    with (stage/"conditions.jsonl").open("x",encoding="utf-8") as file, (
            stage/"assertion_audit.jsonl").open("x",encoding="utf-8") as audit:
        for qid in data:
            before = {r["id"]:r for r in original[qid]["conditions"]}
            after = accepted[qid]
            parents = {r["parent_id"] for r in after if r["parent_id"] is not None}
            reasons = defaultdict(list)
            for item in rejected[qid]:
                if isinstance(item.get("parent_id"),str):
                    reasons[item["parent_id"]].append(item["reason"])
            declined = {parent: (reasons[parent][0] if reasons[parent] else "no_question_span")
                        for parent in before if parent not in parents}
            declines.update(declined.values())
            stats.update(retained=len(after), below_three=len(after)<3,
                         rewritten=sum(r["parent_id"] is not None and
                            compact(r["text"]) != compact(before[r["parent_id"]]["text"]) for r in after),
                         new=sum(r["parent_id"] is None for r in after),
                         entity_failures=sum(not r["entity_check"]["passed"] for r in after),
                         no_conditions_inventory=not covers[qid])
            stats.update(r["status"] for r in covers[qid].values())
            per_question.append({"question_id":qid,"v3":len(before),"v4":len(after),
                                 "covered":sum(r["status"]=="covered" for r in covers[qid].values()),
                                 "conditions":len(covers[qid])})
            releases[qid] = freeze(qid,original[qid],after,covers[qid])
            emit(file,releases[qid])
            emit(audit,{"question_id":qid,"deleted":declined,"rejected":rejected[qid]})
    summary = dict(stats, deleted_by_reason=dict(declines), per_question=per_question,
                   restriction_questions=sum(x["restricted"] for x in data.values()),repair_questions=len(repair),
                   condition_count=sum(len(r) for r in covers.values()),
                   frozen_sha256=sha256((stage/"conditions.jsonl").read_bytes()).hexdigest())
    dump(stage/"assertions.json",summary)
    print(json.dumps({"assertion_summary":{k:v for k,v in summary.items() if k!="per_question"}}),flush=True)
    return releases, summary


def judge_pass(args, grouped, frozen, outcomes, folder, counter, *, ceiling=None,
               prompt=JUDGE_PROMPT, make_payload=None):
    if make_payload is None:
        make_payload = lambda question, block: payload(question["conditions"], block)
    chunks={tid:blocks(stages) for tid,stages in grouped.items()}
    jobs=[((tid,i),make_payload(frozen[outcomes[tid]["question_id"]],b))
          for tid,groups in chunks.items() for i,b in enumerate(groups)]
    raw=batch(args.url,prompt,jobs,6144,folder/"judge_raw.jsonl","judge",counter,ceiling=ceiling)
    merged, counts={},Counter()
    with (folder/"judge_receipts.jsonl").open("x",encoding="utf-8") as receipts, (
            folder/"merged.jsonl").open("x",encoding="utf-8") as result:
        for tid, groups in chunks.items():
            qid=outcomes[tid]["question_id"]
            claims=frozen[qid]["conditions"]
            evaluated=[]
            for index,block in enumerate(groups):
                response=raw[tid,index]
                parsed=unique_index(list_rows(response,"verdicts"),"id")
                checked, audit=check_verdicts(claims,block,response)
                counts.update(audit)
                for r in checked:
                    original=parsed.get(r["id"],{})
                    if original.get("status")=="unknown":
                        why=original.get("reason")
                        counts.update(raw_unknown=1,unknown_without_reason=not(isinstance(why,str) and why.strip()))
                evaluated.append(checked)
                emit(receipts,{"trajectory_id":tid,"question_id":qid,"block":index+1,"verdicts":checked})
            decisions,picks=merge_verdicts(claims,evaluated)
            audits={}
            for assertion, decision in zip(claims,decisions,strict=True):
                key=assertion["id"]
                # V4 rule comparison uses the same normalization for frozen strings and seen passages.
                rule = rule_first(assertion, groups)
                ru = rule["unit_id"] if rule else None
                ju = decision["first_supported"]
                relation=("both" if ru is not None and ju is not None else "rule_only" if ru is not None
                          else "judge_only" if ju is not None else "neither")
                counts.update({decision["status"]:1,relation:1})
                counts["same_first"] += relation=="both" and ru==ju
                audits[key]={"comparison":relation,"rule_unit":ru,"rule_passage_id":rule["id"] if rule else None,
                             "verdict":picks.get(key)}
            merged[tid]={"question_id":qid,"decisions":decisions,"audits":audits}
            emit(result,{"trajectory_id":tid,**merged[tid]})
    return merged,counts


def rule_first(assertion, groups):
    from ledger_grpo.ledgercredit.judge_v3 import ordered_match
    needles = [[compact(line) for line in e["text"].splitlines()] for e in assertion["evidence"]]
    return next((b for group in groups for b in group if any(
        ordered_match(terms,b["match_text"]) for terms in needles)),None)


def detail_rows(folder, original, tids, version):
    result={}
    for record in rows(folder/"judge_receipts.jsonl"):
        tid=record["trajectory_id"]
        if tid not in tids:
            continue
        texts={a["id"]:a["text"] for a in original[record["question_id"]]["conditions"]}
        for row in record["verdicts"]:
            if row["status"]=="partial":
                key=f"{version}/{tid}/{record['block']}/{row['id']}"
                result[key]={"id":key,"assertion":texts[row["id"]],"reason":row["reason"],
                             "evidence":[s["text"] for s in row["sentences"]]}
    return result


def pilot(args):
    questions,original,outcomes=inputs(args.root,args.previous)
    previous_driver.check_service(args.url)
    plan=read(args.inputs/"plan.json")
    if sha256((args.previous/"pilot"/"conditions.jsonl").read_bytes()).hexdigest()!=plan["v3_file_sha256"]:
        raise ValueError("frozen v3 hash changed")
    args.out.mkdir(mode=0o700)
    source={r["qid"]:r for r in rows(args.inputs/"source_inputs.jsonl")}
    if source.keys()!=questions.keys():
        raise ValueError("frozen training question inventory mismatch")
    counter=Counter()
    frozen,stats=assertion_pass(args,source,original,plan,counter)
    selected=set(plan["trajectories"])
    grouped=previous_driver.stage_rows(args.root,selected)
    if sum(len(blocks(v)) for v in grouped.values()) != plan["pilot_blocks"]:
        raise ValueError("pilot block plan changed")
    _, tally=judge_pass(args,grouped,frozen,outcomes,args.out,counter,ceiling=BUDGET-1)
    detail=detail_rows(args.previous/"pilot",original,selected,"v3") | detail_rows(args.out,frozen,selected,"v4")
    assessment=batch(args.url,DETAIL_AUDIT,[("detail",{"rows":list(detail.values())})],3072,
                     args.out/"detail_audit.jsonl","detail_audit",counter,ceiling=BUDGET)["detail"]
    annotations=unique_index(list_rows(assessment,"rows"),"id")
    detail_summary={v:dict(Counter(annotations.get(key,{}).get("type","uncertain")
                                  for key in detail if key.startswith(v+"/"))) for v in ("v3","v4")}
    validity=gate(stats.get("entity_failures",0),tally["valid_refs"],tally["attempted_refs"],
                  tally["unknown_without_reason"],tally["raw_unknown"],stats.get("covered",0),
                  stats["condition_count"],stats.get("generation_lost",0),
                  stats.get("unresolved",0)+stats.get("no_conditions_inventory",0))
    summary={"tally":dict(tally),"calls":dict(counter),"gate":validity,"detail_partial":detail_summary,
             "trajectories":len(grouped),"assertion_sha256":stats["frozen_sha256"]}
    dump(args.out/"pilot_summary.json",summary)
    print(json.dumps(summary),flush=True)


def full(args):
    from ledger_grpo.ledgercredit.conditions import freeze_digest
    questions,original,outcomes=inputs(args.root,args.previous)
    result=read(args.pilot/"pilot_summary.json")
    if not result["gate"]["passed"] or sha256((args.pilot/"conditions.jsonl").read_bytes()).hexdigest()!=result["assertion_sha256"]:
        raise ValueError("pilot gate or frozen assertion identity failed")
    frozen={r["question_id"]:r for r in rows(args.pilot/"conditions.jsonl")}
    if frozen.keys()!=original.keys() or any(
        r["version"]!=VERSION or r["v3_content_sha256"]!=original[q]["content_sha256"] or
        r["content_sha256"]!=freeze_digest({k:v for k,v in r.items() if k!="content_sha256"}) for q,r in frozen.items()):
        raise ValueError("frozen v4 assertion records changed")
    previous_driver.check_service(args.url)
    args.out.mkdir(mode=0o700)
    counter=Counter()
    grouped=previous_driver.stage_rows(args.root,outcomes)
    judged,tally=judge_pass(args,grouped,frozen,outcomes,args.out,counter)
    f=args.root/"supplement-m1-192125"/"trajectory_results.jsonl"
    outcome_rows=[outcomes.get(r["trajectory_id"],r) for r in rows(f)]
    ledger=previous_driver.ledger_all(args.out,grouped,judged,frozen,questions,outcomes,outcome_rows)
    summary={"calls":dict(counter),"tally":dict(tally),"ledger":ledger,"trajectories":len(grouped)}
    dump(args.out/"full_summary.json",summary)
    print(json.dumps(summary),flush=True)


def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("prepare","pilot","full"))
    for key in ("root","previous","out","model-path","inputs","pilot"):
        parser.add_argument("--"+key,type=Path)
    parser.add_argument("--url")
    args=parser.parse_args()
    {"prepare":prepare,"pilot":pilot,"full":full}[args.stage](args)


if __name__=="__main__":
    main()
