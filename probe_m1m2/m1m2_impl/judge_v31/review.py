"""Assemble the v3/v4/v3.1 comparisons and complete private disposition audit."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from ledger_grpo.ledgercredit.conditions import freeze_digest
from ledger_grpo.ledgercredit.judge_v31 import VERSION, entity_check
from driver import base, read, rows, v4

FORCED = {"254","925","237","642","631"}
STATUS = ("supported","partial","unknown")
SEED = "bcplus-v31-receipt-review-20261119"


def helper(path):
    spec=importlib.util.spec_from_file_location("diagnosis_helpers",path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def sample(items,key,size):
    return sorted(items,key=lambda item:sha256(f"{SEED}|{key(item)}".encode()).digest())[:size]


def state_index(path):
    return {r["trajectory_id"]:r for r in rows(path/"merged.jsonl")}


def pct(n,d):
    return f"{n}/{d}（{100*n/d:.1f}%）" if d else "0/0（无样本）"


def status_cells(row):
    counts=Counter(x["status"] for x in row["decisions"])
    return "/".join(str(counts[k]) for k in STATUS)


def verify(frozen, original, issues, questions, docs):
    for qid,spec in frozen.items():
        v3=original[qid]
        if spec["version"]!=VERSION or spec["v3_content_sha256"]!=v3["content_sha256"] or (
                freeze_digest({k:v for k,v in spec.items() if k!="content_sha256"})!=spec["content_sha256"]):
            raise ValueError("v3.1 source identity mismatch")
        old={r["id"]:r for r in v3["conditions"]}
        decisions={r["parent_id"]:r for r in issues[qid]}
        if decisions.keys()!=old.keys() or len(decisions)!=len(issues[qid]):
            raise ValueError("one disposition per v3 parent is required")
        survivors={r["id"]:r for r in spec["conditions"]}
        for decision in issues[qid]:
            prior=decision["parent_id"]
            if decision["state"]=="delete":
                if decision["claim_id"] is not None:
                    raise ValueError("deleted parent must not reference a release assertion")
                continue
            patch=survivors[decision["claim_id"]]
            if patch["parent_id"]!=prior or (decision["state"]=="keep" and patch["text"]!=old[prior]["text"]):
                raise ValueError("parent assertion was silently changed")
        for claim in spec["conditions"]:
            if claim["parent_id"] not in old.keys() | {"new"}:
                raise ValueError("missing parent")
            if claim["question_span"] is not None and claim["question_span"] not in questions[qid]["question"]:
                raise ValueError("question span lost exact source binding")
            e=claim["evidence"][0]
            doc=docs[e["docid"]]
            if "\n".join(doc[a:b] for a,b in e["offsets"])!=e["text"]:
                raise ValueError("evidence offsets do not reproduce the source")
            new_check=entity_check(claim["text"],e["text"],doc)
            if new_check!=claim["entity_check"] or not new_check["passed"]:
                raise ValueError("retained assertion did not pass entity validation")


def bounded_proof(text,docs,e):
    source=docs[e["docid"]]
    if text.strip()!=source.strip():
        return text
    words=text.split()
    return " ".join(words[:min(50,len(words)-1)])+" …"


def pack(diag,qs,original,frozen,dispositions,docs,old_pilot,v4_pilot,v31_pilot,merged,grouped,receipts):
    text=diag.code_text
    lines=["# LedgerCredit M2 v3.1 私有核验包","",
           "各题的语义核验样本包含指定五题和固定种子抽取的另外五题。","","## 抽样断言",""]
    must=sorted((qid for qid in qs if str(qid) in FORCED),key=str)
    if len(must)!=5:
        raise ValueError("mandatory review questions missing")
    picked=must+sample([qid for qid in qs if qid not in must],str,5)

    for qid in picked:
        q=qs[qid]
        span_prefix=" ".join(q["question"].split()[:30])
        lines.extend((f"### query_id {qid}","",f"题面前 30 词 {text(span_prefix)}",""))
        prior={row["id"]:row for row in original[qid]["conditions"]}
        current={row["id"]:row for row in frozen[qid]["conditions"]}
        for d in dispositions[qid]:
            old=prior[d["parent_id"]]
            lines.append(f"- {old['id']} / {d['state']} / {d['reason']} / v3 {text(old['text'])}")
            if d["claim_id"] in current:
                saved=current[d["claim_id"]]
                lines.extend((f"  - v3.1 {text(saved['text'])}",
                              f"  - 题面跨度 {text(saved.get('question_span'))}",
                              f"  - 实体检查 {text(saved['entity_check']['passed'])}，"
                              f"改写蕴含 {text(saved.get('repair_entailment'))}"))
                for e in saved["evidence"]:
                    lines.append(f"  - {e['docid']} / {', '.join(e['sentence_ids'])} {text(bounded_proof(e['text'],docs,e))}")
        for claim in current.values():
            if claim["parent_id"]=="new":
                lines.append(f"- {claim['id']} / new / {text(claim['text'])}")
                e=claim["evidence"][0]
                lines.append(f"  - {e['docid']} / {', '.join(e['sentence_ids'])} {text(bounded_proof(e['text'],docs,e))}")
        lines.extend(("","题面条件覆盖",""))
        for r in frozen[qid]["question_conditions"]:
            lines.append(f"- {text(r['question_span'])} / {', '.join(r['assertion_ids']) or '无'}")
        lines.append("")

    lines.extend(("## 全量断言去向","",
                  "| query_id | v3 父编号 | 去向 | 原因 | v3.1 编号 |","|---|---|---|---|---|"))
    for qid,items in dispositions.items():
        for it in items:
            lines.append(f"| {qid} | {it['parent_id']} | {it['state']} | {it['reason']} | "
                         f"{it['claim_id'] or '—'} |")
        for claim in frozen[qid]["conditions"]:
            if claim["parent_id"]=="new":
                lines.append(f"| {qid} | new | supplement | empty_question | {claim['id']} |")

    lines.extend(("","## 诊断轨迹逐断言判定","",
                  "v4 只在保留明确父编号时对齐。v4 其余判定以公开报告的总数为准。","",
                  "| trajectory_id | 父编号 | v3 | v4 | v3.1 |",
                  "|---|---|---|---|---|"))
    for tid,row in old_pilot.items():
        qid=row["question_id"]
        old_idx={e["id"]:e["status"] for e in row["decisions"]}
        newer={e["id"]:e["status"] for e in v31_pilot[tid]["decisions"]}
        v4_status={e["id"]:e["status"] for e in v4_pilot[tid]["decisions"]}
        v4_parents=defaultdict(list)
        for e in v4_pilot[tid].get("parent_map",()):
            if e.get("parent_id") is not None:
                v4_parents[e["parent_id"]].append(v4_status.get(e["id"],"—"))
        for parent,decision in old_idx.items():
            lines.append(f"| {tid} | {parent} | {decision} | "
                         f"{', '.join(v4_parents[parent]) or '—'} | {newer.get(parent,'—')} |")
        for aid,decision in newer.items():
            if aid not in old_idx:
                lines.append(f"| {tid} | new | — | — | {decision} |")

    snippets={tid:v4.blocks(values) for tid,values in grouped.items()}
    ref_index={tid:{p["id"]:(i,p) for i,block in enumerate(values,1) for p in block}
               for tid,values in snippets.items()}
    pools=defaultdict(list)
    byblock={}
    for row in receipts:
        tid,qid,block=row["trajectory_id"],row["question_id"],row["block"]
        byblock[tid,block]={v["id"]:v for v in row["verdicts"]}
        for v in row["verdicts"]:
            ref=v["passage_id"]
            if v["status"] in STATUS[:2]:
                n,p=ref_index[tid][ref]
                if n!=block or p["unit_id"]!=v["unit_id"] or any(s not in p["sentences"] for s in v["sentences"]):
                    raise ValueError("Judge sentence ID mismatched the visible block")
            if v["status"]=="partial" or (v["status"]=="unknown" and str(v.get("reason") or "").strip()):
                pools[v["status"]].append((tid,qid,v["id"],block,v,ref))
    for tid,row in merged.items():
        qid=row["question_id"]
        for d in row["decisions"]:
            aid=d["id"]
            info=row["audits"][aid]
            if d["status"]=="supported":
                verdict=info["verdict"]
                pid=verdict["passage_id"]
                block,_=ref_index[tid][pid]
                pools["supported"].append((tid,qid,aid,block,verdict,pid))
            if info["comparison"]=="rule_only":
                pid=info["rule_passage_id"]
                block,_=ref_index[tid][pid]
                pools["rule_only"].append((tid,qid,aid,block,byblock[tid,block][aid],pid))
    info={}
    for kind,limit in (("supported",20),("partial",20),("rule_only",20),("unknown",10)):
        chosen=sample(pools[kind],lambda r:f"{kind}/{r[0]}/{r[2]}/{r[3]}",limit)
        info[kind]={"pool":len(pools[kind]),"included":len(chosen)}
        lines.extend(("",f"## Judge {kind}（{len(chosen)}/{len(pools[kind])}）",""))
        for tid,qid,aid,block,verdict,pid in chosen:
            claim=next(x for x in frozen[qid]["conditions"] if x["id"]==aid)
            snippet=ref_index[tid][pid][1] if pid else None
            unit=verdict.get("unit_id") or (snippet["unit_id"] if snippet else snippets[tid][block-1][0]["unit_id"])
            lines.extend((f"- trajectory_id {tid} / unit_id {unit} / 断言 {aid} / query_id {qid}",
                          f"  - 题面前 30 词 {text(' '.join(qs[qid]['question'].split()[:30]))}",
                          f"  - 断言 {text(claim['text'])}",
                          f"  - Judge {verdict['status']} / {text(verdict.get('reason'))}"))
            for sentence in verdict["sentences"]:
                lines.append(f"  - {sentence['id']} {text(sentence['text'])}")
            if snippet:
                focus=verdict["sentences"][0]["text"] if verdict["sentences"] else claim["evidence"][0]["text"]
                lines.append(f"  - 相关片段 {pid} {text(diag.excerpt(snippet['text'],focus))}")
            else:
                lines.append(f"  - unit_id 为分块 {block} 的起点。")
    return "\n".join(lines).strip()+"\n",info


def report(plan,stats,summary,old_tally,v4_tally,old_pilot,v4_pilot,v31_pilot,full,v3full,samples,jobs):
    t=summary["tally"]
    checks=summary["gate"]
    lines=[
        "# M2 v3.1 定向修正验收","",
        f"**[已验证]** 阶段一新增 {summary['calls']['total']}/200 次调用，失败 {summary['calls'].get('errors',0)}。"
        f"50 道训练题、原 10 条诊断轨迹。Slurm {jobs}。",
        f"- 244 条 v3 断言的证据重新对齐失败 {plan.get('alignment_errors',0)}。"
        f"保留 {stats.get('keep',0)}、改写 {stats.get('rewrite',0)}、删除 {stats.get('delete',0)}、"
        f"标为 new {stats.get('new',0)}。最终 {stats['v31']} 条，父编号缺失 {stats['parent_missing']}。逐条去向见私有核验包。",
        "- 删除原因 " + "、".join(f"{k} {v}" for k,v in sorted(stats['deleted_by_reason'].items())) + "。",
        f"- 题面条件覆盖（只统计）{pct(stats['conditions_covered'],stats['conditions_annotated'])}。"
        f"{stats['missing_question_span']} 条断言无可定位题面跨度。",
        "",
        "| 版本 | supported / partial / unknown | 双支持 / 仅 Judge / 仅规则 | 首次单元一致 |",
        "|---|---:|---:|---:|",
    ]
    for label,x in (("v3",old_tally),("v4",v4_tally),("v3.1",t)):
        lines.append(f"| {label} | {' / '.join(str(x.get(k,0)) for k in STATUS)} | "
                     f"{x.get('both',0)} / {x.get('judge_only',0)} / {x.get('rule_only',0)} | {pct(x.get('same_first',0),x.get('both',0))} |")
    lines.extend((
        "",
        "| 轨迹 ID | v3（S/P/U） | v4（S/P/U） | v3.1（S/P/U） |","|---|---:|---:|---:|",
    ))
    for tid in plan["trajectories"]:
        lines.append(f"| {tid} | {status_cells(old_pilot[tid])} | {status_cells(v4_pilot[tid])} | {status_cells(v31_pilot[tid])} |")
    lines.extend((
        "",
        f"**[已验证]** 门槛结果。实体失败 {stats['failures']}，空题 {stats['zero_questions']}（上限 2），"
        f"编号通过 {pct(t.get('valid_refs',0),t.get('attempted_refs',0))}，"
        f"unknown 缺理由 {pct(t.get('unknown_without_reason',0),t.get('raw_unknown',0))}。"
        f"父编号/实体/空题/编号/理由 {' / '.join('通过' if checks[k] else '未通过' for k in ('parents','entity','zero_questions','sentence_ids','unknown_reason'))}。",
    ))
    if full:
        ledger=full["ledger"]
        groups=ledger["groups"]
        validity=ledger["validation"]
        lines.extend((
            f"**[已验证]** 阶段二完成 {full['trajectories']} 条、{full['calls']['total']} 次调用，"
            f"失败 {full['calls'].get('errors',0)}。空跑 {validity['validated_units']}，缺失 {validity['dry_run_missing']}。",
            "- C_new 分布 " + "，".join(f"{k}→{v}" for k,v in sorted(
                ledger["distributions"]["all"].items(),key=lambda x:int(x[0]))) + "。",
            "- 平均 C_new（v3.1/v3/DocID） " + "，".join(
                f"{k} {x['mean_C_new']:.2f}/{v3full['ledger']['groups'][k]['mean_C_new']:.2f}/{x['mean_DocID']:.2f}"
                for k,x in sorted(groups.items())) + "。",
        ))
    elif not checks["passed"]:
        lines.append("**[已验证]** 阶段二未启动，试跑门槛未全部通过。")
    else:
        lines.append("**[已验证]** 阶段二结果暂缺。")
    lines.extend(("","**待确认问题** [推断] 技术校验通过或编号可重放无法替代原始断言的语义复核。"
                  "保留项沿用 v3 事实，只有实际改写和新补项独立复核蕴含。规则命中只用于审计。"
                  f"私有样本支持/部分/仅规则/未知 {' / '.join(str(samples[k]['included']) for k in ('supported','partial','rule_only','unknown'))}。"))
    return "\n".join(lines)+"\n"


def main():
    ap=ArgumentParser(description=__doc__)
    for key in ("root","previous","v4","work","full","out","legacy-helper"):
        ap.add_argument("--"+key,type=Path)
    ap.add_argument("--jobs",required=True)
    args=ap.parse_args()
    qs,v3,outcomes=v4.inputs(args.root,args.previous)
    docs=read(args.root/"docs-192072"/"evidence_docs.json")
    plan=read(args.work/"inputs"/"plan.json")
    pilot=args.work/"pilot"
    stats=read(pilot/"assertions.json")
    summary=read(pilot/"pilot_summary.json")
    assertion_file=pilot/"conditions.jsonl"
    frozen={r["question_id"]:r for r in rows(assertion_file)}
    if sha256(assertion_file.read_bytes()).hexdigest()!=summary["frozen_sha256"] or frozen.keys()!=v3.keys():
        raise ValueError("v3.1 pilot record identity changed")
    dispositions={r["question_id"]:r["dispositions"] for r in rows(pilot/"dispositions.jsonl")}
    verify(frozen,v3,dispositions,qs,docs)
    old_pilot=state_index(args.previous/"pilot")
    v4_pilot=state_index(args.v4/"pilot")
    v31_pilot=state_index(pilot)
    if old_pilot.keys()!=v4_pilot.keys() or old_pilot.keys()!=v31_pilot.keys() or old_pilot.keys()!=set(plan["trajectories"]):
        raise ValueError("pilot samples must match across all three versions")
    lookup={r["question_id"]:r["conditions"] for r in rows(args.v4/"pilot"/"conditions.jsonl")}
    for r in v4_pilot.values():
        r["parent_map"]=lookup[r["question_id"]]
    source=args.full or pilot
    merged=state_index(source)
    grouped=base.stage_rows(args.root,merged)
    private,examples=pack(helper(args.legacy_helper),qs,v3,frozen,dispositions,docs,old_pilot,v4_pilot,v31_pilot,
                          merged,grouped,list(rows(source/"judge_receipts.jsonl")))
    full=read(args.full/"full_summary.json") if args.full else None
    public=report(plan,stats,summary,read(args.previous/"pilot"/"pilot_summary.json"),
                  read(args.v4/"pilot"/"pilot_summary.json")["tally"],old_pilot,v4_pilot,v31_pilot,
                  full,read(args.previous/"m2-v3-192472"/"full_summary.json"),examples,args.jobs)
    args.out.mkdir(mode=0o700)
    for name,data in (("REPORT.md",public),("REVIEW_PACKET_v31.md",private)):
        with (args.out/name).open("x",encoding="utf-8") as f:
            f.write(data)
    dump(args.out/"SUMMARY.json",{"pilot":summary,"full":full,"review":examples})
    print(json.dumps({"outputs":{"pilot":summary,"full":full,"review":examples}}),flush=True)


if __name__=="__main__":
    from driver import dump
    main()
