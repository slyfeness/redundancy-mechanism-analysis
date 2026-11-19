"""Render a public numeric report and a restricted M2 v3 review packet."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from ledger_grpo.ledgercredit.__main__ import rows
from ledger_grpo.ledgercredit.judge_v3 import VERSION, blocks, normalize_for_match, quote_match

from run import emit, read, stage_rows, training

SEED = "ledgercredit-m2-v3-review-20261119"


def load_legacy(path):
    spec = importlib.util.spec_from_file_location("legacy_diagnosis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy_recheck(diag, plan, receipts):
    by_id = {s["trajectory_id"]: s for s in plan["samples"]}
    lookup = {(r["tid"], r["variant"], r["block"]): r for r in receipts}
    counts = {v: Counter() for v in ("V1", "V2", "V3")}
    v3_states = defaultdict(dict)
    def tally(tag, refs, quotes):
        index = {r["citation_id"]: r["passages"] for r in refs}
        for row in quotes:
            baseline = row["codes"] == ["A8"] if tag == "V1" else row["normalized_pass"]
            citation_id = row["citation_id"]
            cited = index.get(citation_id, []) if type(citation_id) is int else []
            quote = row["quote"]
            valid = "A7" not in row["codes"] and any(quote_match(quote, text) for text in cited)
            counts[tag].update(total=1, old=baseline, new=valid,
                               rescued=valid and not baseline, lost=baseline and not valid)
            if valid and not baseline:
                literal = any(normalize_for_match(quote) in normalize_for_match(text) for text in cited)
                counts[tag]["format_only" if literal else "ordered_ellipsis"] += 1

    for tid, sample in by_id.items():
        tally("V1", sample["legacy"], sample["quote_rows"])
    for job in plan["jobs"]:
        tid, variant = job["tid"], job["variant"]
        sample = by_id[tid]
        receipt = lookup[(tid, variant, job["block"])]
        refs = diag.grouped_refs(job, sample["snippets"])
        checks, quotes = diag.compare_receipt(sample["claims"], refs, receipt,
                                               normalized=True, expected_claims=True)
        tally(variant, refs, quotes)
        if variant == "V3":
            for check in checks:
                cid, status = check["id"], check["status"]
                previous = v3_states[tid].get(cid, "unknown")
                ranks = ("unknown", "partial", "supported")
                v3_states[tid][cid] = max(previous, status, key=ranks.index)
    return {k: dict(v) for k, v in counts.items()}, Counter(
        status for trajectory in v3_states.values() for status in trajectory.values())


def seeded(items, key, count):
    return sorted(items, key=lambda item: sha256(f"{SEED}|{key(item)}".encode()).digest())[:count]


def validate_frozen(work, pilot, original, documents, frozen):
    for item in rows(work / "inputs" / "assertion_inputs.jsonl"):
        qid = item["qid"]
        parent_ids = {p["id"] for p in original[qid]["conditions"]}
        for row in frozen[qid]["conditions"]:
            if (row["parent_id"] not in parent_ids or row["atomic_check"] != "atomic" or
                    row["coverage_check"] != "complete" or len(row["evidence"]) != 1):
                raise ValueError("retained assertion lacks its verified source identity")
            evidence = row["evidence"][0]
            resolved = [item["sentence_index"][key] for key in evidence["sentence_ids"]]
            source = documents[evidence["docid"]]
            if (not 1 <= len(resolved) <= 3 or
                    any(r["docid"] != evidence["docid"] or source[r["start"]:r["end"]] != r["text"]
                        for r in resolved) or evidence["text"] != "\n".join(r["text"] for r in resolved)):
                raise ValueError("a frozen sentence failed an independent source-offset check")
    if sha256((pilot / "conditions.jsonl").read_bytes()).hexdigest() != read(
            pilot / "assertions.json")["frozen_sha256"]:
        raise ValueError("the v3 freeze changed after extraction")


def packet(diag, questions, original, documents, frozen, assert_receipts, grouped, merged, receipts):
    lines = ["# LedgerCredit M2 v3 核验包", "",
             "证据取自程序按编号定位的原文。断言与判定样本使用相同的固定种子。", "",
             "## 断言拆分", ""]
    stats_by_qid = {r["question_id"]: r["parents"] for r in assert_receipts}
    for qid in seeded(list(questions), str, 10):
        question = " ".join(questions[qid]["question"].split()[:30])
        lines.extend((f"### query_id {qid}", "", f"题面前 30 词 {diag.code_text(question)}", ""))
        children = defaultdict(list)
        for r in frozen[qid]["conditions"]:
            children[r["parent_id"]].append(r)
        pstats = {r["id"]: r for r in stats_by_qid[qid]}
        for parent in original[qid]["conditions"]:
            cid = parent["id"]
            lines.append(f"- {cid} / {pstats[cid]['atomic_check']} / "
                         f"{diag.code_text(parent['text'])}")
            for evidence in parent["evidence"]:
                lines.append(f"  - v2 证据 {evidence['docid']} {diag.code_text(evidence['quote'])}")
            for child in children[cid]:
                lines.append(f"  - {child['id']} / {child['atomic_check']} / "
                             f"{child['coverage_check']} / {diag.code_text(child['text'])}")
                for e in child["evidence"]:
                    text = e["text"]
                    if text.strip() == documents[e["docid"]].strip():
                        # Preserve a bounded excerpt if the source is itself a single quoted sentence.
                        words = text.split()
                        text = " ".join(words[:min(50, len(words) - 1)]) + " …"
                    lines.append(f"    - {e['docid']} / {', '.join(e['sentence_ids'])} {diag.code_text(text)}")
            if not children[cid]:
                lines.append("  - 无保留子断言")
        lines.append("")

    by_block = {tid: blocks(stages) for tid, stages in grouped.items()}
    source = {tid: {p["id"]: p for block in parts for p in block} for tid, parts in by_block.items()}
    block_index = {tid: {p["id"]: i for i, group in enumerate(parts, 1) for p in group}
                   for tid, parts in by_block.items()}
    for receipt in receipts:
        tid, block = receipt["trajectory_id"], receipt["block"]
        for verdict in receipt["verdicts"]:
            if verdict["status"] != "unknown":
                pid = verdict["passage_id"]
                passage = source[tid][pid]
                if (block_index[tid][pid] != block or passage["unit_id"] != verdict["unit_id"] or
                        any(s not in passage["sentences"] for s in verdict["sentences"])):
                    raise ValueError("judge citation failed independent source check")
    receipt_index = {(r["trajectory_id"], r["block"]): {v["id"]: v for v in r["verdicts"]}
                     for r in receipts}
    candidates = defaultdict(list)
    for tid, r in merged.items():
        for decision in r["decisions"]:
            cid, status = decision["id"], decision["status"]
            check = r["audits"][cid]
            if status == "supported":
                candidates[status].append((tid, cid, check["verdict"], check))
            if check["comparison"] == "rule_only":
                # Prefer the response to the block containing the matched rule passage.
                n = block_index[tid][check["rule_passage_id"]]
                judged = receipt_index.get((tid, n), {}).get(cid)
                candidates["rule_only"].append((tid, cid, judged or check["verdict"], check))
    # Partial examples are accepted block-level verdicts, including early partials later resolved.
    for r in receipts:
        for verdict in r["verdicts"]:
            if verdict["status"] == "partial":
                candidates["partial"].append((r["trajectory_id"], verdict["id"], verdict, {}))
    picked_counts = {}
    for kind, heading in (("supported", "支持"), ("rule_only", "仅规则支持"), ("partial", "部分支持")):
        picked = seeded(candidates[kind], lambda r: f"{kind}|{r[0]}|{r[1]}|"
                        f"{(r[2] or {}).get('passage_id')}", 20)
        picked_counts[kind] = {"pool": len(candidates[kind]), "picked": len(picked)}
        lines.extend((f"## {heading}（{len(picked)}/{len(candidates[kind])}）", ""))
        if kind == "partial":
            lines.extend(("抽取已通过编号校验的分块 partial。其后仍可能建立支持。", ""))
        for tid, cid, verdict, audit in picked:
            verdict = verdict or {}
            qid = merged[tid]["question_id"]
            claim = next(c for c in frozen[qid]["conditions"] if c["id"] == cid)
            judge_passage = verdict.get("passage_id")
            display_passage = judge_passage or audit.get("rule_passage_id")
            unit = verdict.get("unit_id") or audit.get("rule_unit")
            question = " ".join(questions[qid]["question"].split()[:30])
            lines.extend((f"- trajectory_id {tid} / unit_id {unit} / 断言 {cid} / query_id {qid}",
                          f"  - 题面前 30 词 {diag.code_text(question)}",
                          f"  - 断言 {diag.code_text(claim['text'])}",
                          f"  - Judge 状态 {verdict.get('status', 'unknown')}，理由 "
                          f"{diag.code_text(verdict.get('reason'))}"))
            focus = next(iter(claim["evidence"]))["text"]
            if verdict.get("sentences"):
                for row in verdict["sentences"]:
                    lines.append(f"  - 句子 {row['id']} {diag.code_text(row['text'])}")
                focus = verdict["sentences"][0]["text"]
            if display_passage:
                actual = source[tid][display_passage]
                lines.append(f"  - 片段 {display_passage} / unit {actual['unit_id']} "
                             f"{diag.code_text(diag.excerpt(actual['text'], focus))}")
            rule_passage = audit.get("rule_passage_id")
            if kind == "rule_only" and rule_passage and rule_passage != display_passage:
                actual = source[tid][rule_passage]
                lines.append(f"  - 规则片段 {rule_passage} / unit {actual['unit_id']} "
                             f"{diag.code_text(diag.excerpt(actual['text'], claim['evidence'][0]['text']))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", picked_counts


def ratio(n, d):
    return f"{n}/{d}（{100*n/d:.1f}%）" if d else f"{n}/{d}（无分母）"


def public_summary(asserts, pilot, old, legacy, full, picked, ids):
    fmt = pilot["gate"]
    new = [pilot.get(s, 0) for s in ("supported", "partial", "unknown")]
    r = pilot.get("rule_only", 0)
    both = pilot.get("both", 0)
    checks = pilot["valid_refs"], pilot["attempted_refs"]
    lines = [
        "# M2 v3 断言与句子编号验收", "",
        f"**[已验证]** {VERSION} 在 50 道训练题上完成。第一阶段共 "
        f"{asserts['calls'] + pilot['calls']} 次本地调用，断言 {asserts['calls']}、"
        f"句子 Judge {pilot['calls']}。请求错误分别为 {asserts.get('errors', 0)}、{pilot.get('errors', 0)}。",
        "",
        f"- 断言从 210 条变为 {asserts['conditions']} 条。{asserts['split_parents']} 条父断言被标为复合，"
        f"提出 {asserts['split_proposed']} 条子断言，保留 {asserts['split_retained']} 条。"
        f"{asserts['parents_without_child']} 条父断言无保留子项，{asserts['below_three']} 题少于 3 条。"
        f"{asserts['restricted']} 题受源文档输入预算限制。",
        "- 作废 " + str(asserts["rejected"]) + " 项。"
        + "，".join(f"{k} {v}" for k, v in sorted(asserts["rejected_by_reason"].items())) + "。",
    ]
    changes = defaultdict(list)
    for q in asserts["per_question"]:
        changes[q["v2"], q["v3"]].append(str(q["question_id"]))
    lines.append("- 每题变化（v2→v3） " + " / ".join(f"{a}→{b}〔{','.join(values)}〕"
                       for (a, b), values in sorted(changes.items())) + "。")
    lines.extend((
        "",
        f"**[已验证]** 第一阶段使用同 10 条轨迹。编号通过 {ratio(*checks)}。"
        f"旧 V3 → v3 的支持/部分/未知为 "
        f"{'/'.join(str(old.get(k,0)) for k in ('supported','partial','unknown'))} → "
        f"{'/'.join(map(str,new))}。断言池随版本变化。",
        "",
        "| 审计对照 | 两者支持 | 仅 Judge | 仅规则 | 首次单元一致 |",
        "|---|---:|---:|---:|---:|",
        "| 旧 V3 | 13 | 4 | 14 | 11/13 |",
        f"| v3 | {both} | {pilot.get('judge_only',0)} | {r} | {ratio(pilot.get('same_first',0), both)} |",
        "",
        f"**[已验证]** 门槛为编号 ≥95% 和仅规则 ≤10 对。结果分别为 "
        f"{'通过' if fmt['format_passed'] else '未通过'}、{'通过' if fmt['rule_only_passed'] else '未通过'}。"
        f"仅规则占规则命中的比例为 14/27 → {ratio(r, r+both)}。",
        "",
        "| 旧摘录 | 原通过率 | 新规范化 | 救回（字符归一 / 有序省略） |",
        "|---|---:|---:|---:|",
    ))
    for version, values in legacy.items():
        lines.append(f"| {version} | {ratio(values['old'], values['total'])} | "
                     f"{ratio(values['new'], values['total'])} | "
                     f"{values.get('format_only',0)} / {values.get('ordered_ellipsis',0)} |")
    lines.append("")
    if full:
        groups = full["ledger"]["groups"]
        validate = full["ledger"]["validation"]
        dist = full["ledger"]["distributions"]["all"]
        lines.extend((
            f"**[已验证]** 第二阶段 {full['trajectories']} 条、{full['calls']} 次 Judge 调用，"
            f"{full.get('errors',0)} 次请求错误。空跑 {validate['validated_units']} 个单元，缺失 {validate['dry_run_missing']}。",
            f"- 全量沿用试跑编号口径通过 {ratio(full['valid_refs'], full['attempted_refs'])}，包括对异常 unknown 的检查。",
            "- C_new 分布 " + "，".join(f"{k}→{v}" for k,v in sorted(dist.items(), key=lambda x:int(x[0]))) + "。",
            "- 平均 C_new/DocID " + "，".join(f"{k} {v['mean_C_new']:.2f}/{v['mean_DocID']:.2f}"
                                              for k,v in sorted(groups.items())) + "。",
        ))
    else:
        why = "门槛未全部通过" if not fmt["passed"] else "全量回执不可用"
        lines.append(f"**[已验证]** 第二阶段无可用结果。{why}。")
    lines.extend((
        "",
        f"**待确认问题** [推断] 编号和规范化验证的是取证位置。原子性、覆盖充分性及真实支持仍需逐例核验。"
        f"私有核验包抽取支持/仅规则/部分分别 "
        f"{'/'.join(str(picked[k]['picked']) for k in ('supported','rule_only','partial'))} 条。"
        f"分块 Judge 以单个可见片段为支持单位，规则仅用于审计。Slurm {ids}。",
    ))
    return "\n".join(lines) + "\n"


def main():
    parser = ArgumentParser(description=__doc__)
    for key in ("root", "work", "legacy", "legacy-run", "legacy-script", "full", "out"):
        parser.add_argument(f"--{key}", type=Path)
    parser.add_argument("--jobs", required=True)
    args = parser.parse_args()
    diag = load_legacy(args.legacy_script)
    pilot_dir = args.work / "pilot"
    source_dir = args.full or pilot_dir
    qs, old, _ = training(args.root)
    old_hash = sha256((args.root / "m2-192109" / "conditions.jsonl").read_bytes()).hexdigest()
    if old_hash != read(args.work / "inputs" / "plan.json")["old_conditions_sha256"]:
        raise ValueError("the source v2 assertion file changed")
    docs = read(args.root / "docs-192072" / "evidence_docs.json")
    frozen = {r["question_id"]: r for r in rows(pilot_dir / "conditions.jsonl")}
    validate_frozen(args.work, pilot_dir, old, docs, frozen)
    sample = read(args.legacy / "plan.json")
    receipts = list(rows(args.legacy_run / "requests.jsonl"))
    old_quotes, old_status = legacy_recheck(diag, sample, receipts)
    official = read(args.legacy / "DIAGNOSIS.json")["versions"]
    if any(v["total"] != official[k]["quote_total"] or v["old"] != official[k]["quote_pass"]
           for k, v in old_quotes.items()):
        raise ValueError("legacy comparison denominator drift")
    merged = {r["trajectory_id"]: r for r in rows(source_dir / "merged.jsonl")}
    grouped = stage_rows(args.root, merged)
    packet_md, picked = packet(diag, qs, old, docs, frozen, list(rows(pilot_dir / "assertion_receipts.jsonl")),
                               grouped, merged, list(rows(source_dir / "judge_receipts.jsonl")))
    pilot = read(pilot_dir / "pilot_summary.json")
    assert_summary = read(pilot_dir / "assertions.json")
    full = read(args.full / "full_summary.json") if args.full else None
    report = public_summary(assert_summary, pilot, old_status, old_quotes, full, picked, args.jobs)
    args.out.mkdir(mode=0o700, exist_ok=False)
    for name, text in (("REPORT.md", report), ("REVIEW_PACKET_v3.md", packet_md)):
        with (args.out / name).open("x", encoding="utf-8") as file:
            file.write(text)
    summary = {"old_quotes": old_quotes, "old_v3_status": dict(old_status), "pilot": pilot,
               "review_counts": picked, "full": full, "heldout_read": 0}
    with (args.out / "SUMMARY.json").open("x", encoding="utf-8") as file:
        emit(file, summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
