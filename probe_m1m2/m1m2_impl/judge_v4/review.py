"""Render the v4 numeric report and the bounded private review packet."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from ledger_grpo.ledgercredit.conditions import freeze_digest
from ledger_grpo.ledgercredit.judge_v4 import VERSION, entity_check

from pilot import blocks, detail_rows, inputs, previous_driver, read, rows

SEED = "ledgercredit-v4-review-20261119"
FORCED = {"254", "925", "237", "642", "631"}


def sample(items, key, size):
    return sorted(items, key=lambda r: sha256(f"{SEED}|{key(r)}".encode()).digest())[:size]


def helper(path):
    spec = importlib.util.spec_from_file_location("diagnosis_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_accepted(plan, question, old, new, index, documents):
    if new["version"] != VERSION or new["v3_content_sha256"] != old["content_sha256"]:
        raise ValueError("assertion version mismatch")
    if new["content_sha256"] != freeze_digest({k:v for k,v in new.items() if k!="content_sha256"}):
        raise ValueError("assertion integrity mismatch")
    for row in new["conditions"]:
        if row["question_span"] not in question["question"] or row["entailment"]["verdict"] != "entailed":
            raise ValueError("unsupported question-grounding path")
        proof=row["evidence"][0]
        doc=documents[proof["docid"]]
        parts=[index[key] for key in proof["sentence_ids"]]
        text="\n".join(ref["text"] for ref in parts)
        if (not 1<=len(parts)<=3 or text!=proof["text"] or any(
                ref["docid"]!=proof["docid"] or doc[ref["start"]:ref["end"]]!=ref["text"] for ref in parts)):
            raise ValueError("selected evidence offsets are inconsistent")
        observed=entity_check(row["text"],row["subject"],text,doc,row["entity_check"]["subject_pronoun_exception"])
        if observed!=row["entity_check"] or not observed["passed"]:
            raise ValueError("stored entity check is inconsistent")


def build_packet(diag, questions, original, frozen, audit, docs, decisions, receipts, group):
    text = diag.code_text
    rendered=["# LedgerCredit M2 v4 核验包","",
              "断言样本保留五道指定题，另五道用固定种子抽取。Judge 样本基于可见 Search 片段。","",
              "## 断言与题面条件",""]
    force={qid for qid in questions if str(qid) in FORCED}
    if len(force)!=5:
        raise ValueError("one or more mandatory audit questions are missing")
    chosen=sorted(force,key=str)+sample([q for q in questions if q not in force],str,5)
    for qid in chosen:
        q=questions[qid]
        v4=frozen[qid]
        parents=defaultdict(list)
        for claim in v4["conditions"]:
            parents[claim["parent_id"]].append(claim)
        rendered.extend((f"### query_id {qid}","",f"题面前 30 词 {text(' '.join(q['question'].split()[:30]))}",""))
        def show_evidence(ref):
            literal=ref["text"]
            if literal.strip()==docs[ref["docid"]].strip():
                parts=literal.split()
                literal=" ".join(parts[:min(50,len(parts)-1)])+" …"
            return f"{ref['docid']} / {', '.join(ref['sentence_ids'])} {text(literal)}"
        def show_v4(row):
            rendered.extend((f"  - v4 {row['id']} {text(row['text'])}",
                             f"    - question_span {text(row['question_span'])}",
                             "    - 实体检查通过，蕴含 entailed "+text(row["entailment"]["reason"]),
                             "    - 证据 "+show_evidence(row["evidence"][0])))
        for parent in original[qid]["conditions"]:
            rendered.append(f"- v3 {parent['id']} {text(parent['text'])}")
            for ref in parent["evidence"]:
                rendered.append("  - v3 证据 "+show_evidence(ref))
            if parents[parent["id"]]:
                for row in parents[parent["id"]]:
                    show_v4(row)
            else:
                rendered.append(f"  - 删除原因 {audit[qid]['deleted'][parent['id']]}")
                for row in audit[qid]["rejected"]:
                    if row.get("parent_id")==parent["id"]:
                        if row.get("entity_check"):
                            rendered.append("    - 实体检查 "+text(json.dumps(row["entity_check"],ensure_ascii=False)))
                        if row.get("entailment"):
                            rendered.append("    - 蕴含核查 "+text(json.dumps(row["entailment"],ensure_ascii=False)))
        if parents[None]:
            rendered.append("- 补生成（无 v3 父断言）")
            for row in parents[None]:
                show_v4(row)
        rendered.extend(("","题面条件覆盖",""))
        for row in v4["question_conditions"]:
            rendered.append(f"- {row['id']} / {row['status']} / {text(row['question_span'])} / "
                            f"{', '.join(row['assertion_ids']) or '无'} / {text(row.get('reason'))}")
        rendered.append("")

    pools=defaultdict(list)
    grouped={tid:blocks(stages) for tid,stages in group.items()}
    blockmap={tid:{p["id"]:(block,p) for block,chunk in enumerate(gs,1) for p in chunk}
              for tid,gs in grouped.items()}
    receipt_index={}
    for entry in receipts:
        tid, qid, block=entry["trajectory_id"],entry["question_id"],entry["block"]
        receipt_index[tid,block]={v["id"]:v for v in entry["verdicts"]}
        for row in entry["verdicts"]:
            pid=row["passage_id"]
            if row["status"] in ("supported","partial"):
                n,p=blockmap[tid][pid]
                if n!=block or p["unit_id"]!=row["unit_id"] or any(s not in p["sentences"] for s in row["sentences"]):
                    raise ValueError("judge reference did not resolve to its own visible block")
            if row["status"]=="partial":
                pools["partial"].append((tid,qid,row["id"],block,row,pid))
            if row["status"]=="unknown" and isinstance(row.get("reason"),str) and row["reason"].strip():
                pools["unknown"].append((tid,qid,row["id"],block,row,None))
    for tid, merged in decisions.items():
        qid=merged["question_id"]
        for decision in merged["decisions"]:
            aid=decision["id"]
            entry=merged["audits"][aid]
            row=entry["verdict"]
            if decision["status"]=="supported":
                pid=row["passage_id"]
                n,_=blockmap[tid][pid]
                pools["supported"].append((tid,qid,aid,n,row,pid))
            if entry["comparison"]=="rule_only":
                pid=entry["rule_passage_id"]
                n,_=blockmap[tid][pid]
                pools["rule_only"].append((tid,qid,aid,n,receipt_index[tid,n][aid],pid))
    actual={}
    for category,label,n in (("supported","支持",20),("partial","部分支持",20),
                             ("rule_only","仅规则支持",20),("unknown","未知",10)):
        selected=sample(pools[category],lambda r:f"{category}/{r[0]}/{r[2]}/{r[3]}",n)
        actual[category]={"count":len(selected),"pool":len(pools[category])}
        rendered.extend((f"## {label}（{len(selected)}/{len(pools[category])}）",""))
        for tid,qid,aid,block,row,pid in selected:
            claim=next(c for c in frozen[qid]["conditions"] if c["id"]==aid)
            p=blockmap[tid][pid][1] if pid else None
            unit=row.get("unit_id") or (p["unit_id"] if p else grouped[tid][block-1][0]["unit_id"])
            rendered.extend((f"- trajectory_id {tid} / unit_id {unit} / 断言 {aid} / query_id {qid}",
                             f"  - 题面前 30 词 {text(' '.join(questions[qid]['question'].split()[:30]))}",
                             f"  - 断言 {text(claim['text'])}",
                             f"  - Judge {row['status']} / {text(row.get('reason'))}"))
            if row["sentences"]:
                for sent in row["sentences"]:
                    rendered.append(f"  - 句子 {sent['id']} {text(sent['text'])}")
            if p:
                focus=row["sentences"][0]["text"] if row["sentences"] else claim["evidence"][0]["text"]
                rendered.append(f"  - 相关片段 {pid} {text(diag.excerpt(p['text'],focus))}")
            else:
                rendered.append(f"  - unit_id 是第 {block} 块的起始单元，无引用编号。")
        rendered.append("")
    return "\n".join(rendered).strip()+"\n",actual


def detail_pairs(path, qids, original, frozen, tids, previous):
    old=detail_rows(previous/"pilot",original,tids,"v3")
    new=detail_rows(path,frozen,tids,"v4")
    raw=next(rows(path/"detail_audit.jsonl"))["raw"] or {}
    assessment=defaultdict(lambda:"uncertain")
    try:
        body=json.loads(raw["choices"][0]["message"]["content"])
        for r in body["rows"]:
            if isinstance(r,dict) and isinstance(r.get("id"),str):
                assessment[r["id"]]=r.get("type","uncertain")
    except (KeyError,IndexError,TypeError,ValueError):
        pass
    old_added={key.split("/",1)[1] for key in old if assessment[key]=="added_detail"}
    next_added=set()
    for key in new:
        if assessment[key]!="added_detail":
            continue
        _,tid,block,aid=key.split("/",3)
        desc=next(r for r in frozen[qids[tid]]["conditions"] if r["id"]==aid)
        if desc["parent_id"]:
            next_added.add(f"{tid}/{block}/{desc['parent_id']}")
    return {"v3_added_detail":len(old_added),"v4_added_detail":sum(assessment[k]=="added_detail" for k in new),
            "retained_pairs":len(old_added & next_added),
            "v3_uncertain":sum(assessment[k]=="uncertain" for k in old),
            "v4_uncertain":sum(assessment[k]=="uncertain" for k in new)}


def pct(n,d):
    return f"{n}/{d}（{100*n/d:.1f}%）" if d else f"{n}/{d}（无可比项）"


def report(plan, assertions, pilot, old_pilot, detail, packet, full, old_full, jobs):
    t, old = pilot["tally"], old_pilot
    stats = plan["cutting"]
    cut_summary = []
    for k in ("selected_v3_assertion_sentences","selected_v3_judge_sentences"):
        x=plan[k]
        cut_summary.append(f"{x.get('id_changed',0)}/{x.get('content_changed',0)}/{sum(x.values())}")
    unfilled=assertions.get("generation_lost",0)
    unresolved=assertions.get("unresolved",0)+assertions.get("no_conditions_inventory",0)
    gates=pilot["gate"]
    missing=pct(t.get("unknown_without_reason",0),t.get("raw_unknown",0))
    lines=[
        "# M2 v4 断言与切句验收","",
        f"**[已验证]** v4 使用 50 道训练题和原诊断 10 条轨迹。阶段一调用 "
        f"{pilot['calls']['total']}/150，错误 {pilot['calls'].get('errors',0)}。作业 {jobs}。",
        f"- 切句前→后，证据文档 {stats['documents_old']:,}→{stats['documents_new']:,}，"
        f"可见片段 {stats['snippets_old']:,}→{stats['snippets_new']:,}。v3 已选句按"
        f"编号变化/内容变化/总数计，断言证据 {cut_summary[0]}，Judge 引用 {cut_summary[1]}。",
        f"- 断言 244→{assertions['retained']}。改写 {assertions.get('rewritten',0)}、新增 "
        f"{assertions.get('new',0)}；{assertions['below_three']} 题少于 3 条。删除原因 " +
        "、".join(f"{k} {v}" for k,v in sorted(assertions["deleted_by_reason"].items()))+"。",
    ]
    counts=defaultdict(list)
    for r in assertions["per_question"]:
        counts[r["v3"],r["v4"]].append(str(r["question_id"]))
    lines.append("- 每题断言数（v3→v4） "+" / ".join(f"{a}→{b}〔{','.join(ids)}〕"
                 for (a,b),ids in sorted(counts.items()))+"。")
    lines.extend((
        f"- 条件覆盖 {pct(assertions.get('covered',0),assertions['condition_count'])}。"
        f"无证据 {assertions.get('no_evidence',0)}，模糊 {assertions.get('ambiguous',0)}，"
        f"生成丢失未补 {unfilled}，未确认计入 {unresolved}，修补尝试 {assertions['repair_questions']} 题。","",
        "| 10 条轨迹 | 支持 / 部分 / 未知 | 双支持 / 仅 Judge / 仅规则 | 首次单元一致 |",
        "|---|---:|---:|---:|",
        f"| v3 | {old['supported']} / {old['partial']} / {old['unknown']} | {old['both']} / {old['judge_only']} / {old['rule_only']} | {old['same_first']}/{old['both']} |",
        f"| v4 | {t.get('supported',0)} / {t.get('partial',0)} / {t.get('unknown',0)} | "
        f"{t.get('both',0)} / {t.get('judge_only',0)} / {t.get('rule_only',0)} | {pct(t.get('same_first',0),t.get('both',0))} |",
        "",
        f"**[已验证]** 门槛：实体检查失败 {assertions.get('entity_failures',0)}；编号通过 "
        f"{pct(t.get('valid_refs',0),t.get('attempted_refs',0))}；unknown 缺理由 {missing}。"
        f"实体/编号/理由/覆盖 {' / '.join('通过' if gates[k] else '未通过' for k in ('entity','ids','unknown_reason','coverage'))}。",
        f"**[推断]** 模型复核认为附加细节导致的 partial 从 {detail['v3_added_detail']} 到 "
        f"{detail['v4_added_detail']} 个分块判定，按轨迹、块和 v3 父断言对齐仍有 {detail['retained_pairs']} 个。"
        f"不确定 {detail['v3_uncertain']} / {detail['v4_uncertain']}。","",
    ))
    if full:
        ledger=full["ledger"]; check=ledger["validation"]
        lines.append(f"**[已验证]** 阶段二 {full['trajectories']} 条，空跑 {check['validated_units']} 个单元，"
                     f"输入缺失 {check['dry_run_missing']}。阶段二调用 {full['calls']['total']}，失败 {full['calls'].get('errors',0)}。")
        lines.append("- C_new 分布 "+ "，".join(f"{k}→{v}" for k,v in
                     sorted(ledger["distributions"]["all"].items(),key=lambda r:int(r[0])))+"。")
        lines.append("- 平均 C_new（v4/v3/DocID） "+"，".join(
            f"{label} {r['mean_C_new']:.2f}/{old_full['ledger']['groups'][label]['mean_C_new']:.2f}/{r['mean_DocID']:.2f}"
            for label,r in sorted(ledger["groups"].items()))+"。")
    else:
        if not gates["passed"]:
            lines.append("**[已验证]** 阶段一门槛未全部满足，阶段二未启动。")
        else:
            lines.append("**[已验证]** 阶段二尚无完整全量回执。")
    lines.extend(("","**待确认问题** 题面条件切分、实体别名和语义蕴含待人工复核。规则命中仅用于审计。"
                  f"私有抽样支持/部分/仅规则/未知 {' / '.join(str(packet[k]['count']) for k in ('supported','partial','rule_only','unknown'))}。"))
    return "\n".join(lines)+"\n"


def main():
    parser=ArgumentParser(description=__doc__)
    for key in ("root","previous","work","full","legacy-helper","out"):
        parser.add_argument("--"+key,type=Path)
    parser.add_argument("--jobs",required=True)
    args=parser.parse_args()
    qs,old,outcomes=inputs(args.root,args.previous)
    plan=read(args.work/"inputs"/"plan.json")
    pilot_dir=args.work/"pilot"
    new={r["question_id"]:r for r in rows(pilot_dir/"conditions.jsonl")}
    assertion_stats=read(pilot_dir/"assertions.json")
    if sha256((pilot_dir/"conditions.jsonl").read_bytes()).hexdigest()!=assertion_stats["frozen_sha256"]:
        raise ValueError("v4 freeze file hash mismatch")
    docs=read(args.root/"docs-192072"/"evidence_docs.json")
    for row in rows(args.work/"inputs"/"source_inputs.jsonl"):
        qid=row["qid"]
        verify_accepted(plan,qs[qid],old[qid],new[qid],row["index"],docs)
    audited={r["question_id"]:r for r in rows(pilot_dir/"assertion_audit.jsonl")}
    detail=detail_pairs(pilot_dir,{tid:r["question_id"] for tid,r in outcomes.items()},old,new,
                        set(plan["trajectories"]),args.previous)
    source=args.full or pilot_dir
    merged={r["trajectory_id"]:r for r in rows(source/"merged.jsonl")}
    grouped=previous_driver.stage_rows(args.root,merged)
    raw=list(rows(source/"judge_receipts.jsonl"))
    markdown,picked=build_packet(helper(args.legacy_helper),qs,old,new,audited,docs,merged,raw,grouped)
    full=read(args.full/"full_summary.json") if args.full else None
    previous_full=read(args.previous/"m2-v3-192472"/"full_summary.json")
    pilot_summary=read(pilot_dir/"pilot_summary.json")
    output=report(plan,assertion_stats,pilot_summary,read(args.previous/"pilot"/"pilot_summary.json"),detail,
                  picked,full,previous_full,args.jobs)
    args.out.mkdir(mode=0o700)
    for path,text in (("REVIEW_PACKET_v4.md",markdown),("REPORT.md",output)):
        with (args.out/path).open("x",encoding="utf-8") as file:
            file.write(text)
    summary={"pilot":pilot_summary,"detail_partial_lineage":detail,"full":full,"packet_counts":picked}
    with (args.out/"SUMMARY.json").open("x",encoding="utf-8") as file:
        json.dump(summary,file)
    print(json.dumps(summary),flush=True)


if __name__=="__main__":
    main()
