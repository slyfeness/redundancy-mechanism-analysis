"""Produce the numeric v5 report and bounded private audit packet."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import importlib.util
import re

from ledger_grpo.ledgercredit.judge_v5 import redact_answers, tokens

from driver import base, dump, read, rows, v4

SEED = "ledgercredit-v5-review-20261119"
STATUS = ("supported", "partial", "unknown")
FORCED = {"254", "925", "642"}


def load_helper(path):
    spec = importlib.util.spec_from_file_location("diagnosis_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(values, key, count):
    return sorted(values, key=lambda x: sha256(f"{SEED}|{key(x)}".encode()).digest())[:count]


def index(folder):
    return {row["trajectory_id"]: row for row in rows(folder / "merged.jsonl")}


def counts(records, tids):
    return dict(Counter(r["status"] for tid in tids for r in records[tid]["decisions"]))


def fmt(counts_by_status):
    return " / ".join(str(counts_by_status.get(s, 0)) for s in STATUS)


def fraction(n, d):
    return f"{n}/{d}（{n/d:.1%}）" if d else "0/0"


def quote(text, maximum=80):
    words = list(re.finditer(r"\S+", text))
    return text if len(words) <= maximum else text[:words[maximum-1].end()] + " …"


def packet(helper, qs, claims, new, grouped, merged, receipts, partial_categories):
    selected = sorted(FORCED) + sample(set(qs) - FORCED, str, 7)
    if len(selected) != 10 or not FORCED <= qs.keys():
        raise ValueError("expected ten audit questions including all mandatory IDs")

    def field(qid, value, limit=None):
        if not value:
            return helper.code_text(None)
        answers = qs[qid]["answers"]
        answers = [answers] if isinstance(answers, str) else answers
        value = redact_answers(value, answers)
        return helper.code_text(quote(value, limit) if limit else value)

    lines = ["# LedgerCredit M2 v5 私有核验包", "",
             "答案实体已遮蔽。同一占位符表示该题被遮蔽的参考答案。"
             "题面前缀与模型选中的 question_span 分别列出。", "", "## 断言"]
    for qid in selected:
        spec = claims[qid]
        lines.extend(("", f"### {qid}", f"- 题面前 30 词 {field(qid, qs[qid]['question'], 30)}"))
        lines.append("- 实体对应表")
        for e in spec["entities"]:
            lines.append(f"  - {field(qid, e['var'])} / {field(qid, e['name'])} / {field(qid, e['role'])}")
        lines.append("- 原文跨度与断言")
        for c in spec["conditions"]:
            lines.append(f"  - {c['id']} / {field(qid, c['question_span'])} / {field(qid, c['claim'])}")
        if spec["validation_failures"]:
            lines.append("- 验证失败 " + ", ".join(spec["validation_failures"]))

    chunks = {tid: v4.blocks(grouped[tid]) for tid in new}
    by_passage = {tid: {p["id"]: p for chunk in groups for p in chunk} for tid, groups in chunks.items()}
    unknowns = {}
    for record in receipts:
        tid = record["trajectory_id"]
        if tid not in chunks:
            continue
        for r in record["verdicts"]:
            if r["status"] == "unknown" and r["raw_status"] == "unknown" and r.get("reason"):
                unknowns.setdefault((tid, r["id"]), (record["block"], r))

    pools = defaultdict(list)
    for tid in new:
        qid = merged[tid]["question_id"]
        for c in merged[tid]["decisions"]:
            cid = c["id"]
            status = c["status"]
            v = merged[tid]["audits"][cid]["verdict"]
            if v:
                passage = by_passage[tid][v["passage_id"]]
                pools[status].append((tid, qid, cid, v, passage))
            elif (tid, cid) in unknowns:
                num, u = unknowns[tid, cid]
                claim = next(r["claim"] for r in claims[qid]["conditions"] if r["id"] == cid)
                keys = {t[0] for t in tokens(claim)}
                p = max(chunks[tid][num-1], default=None,
                        key=lambda p: len(keys & {t[0] for t in tokens(p["text"])}))
                pools[status].append((tid, qid, cid, {**u, "block": num}, p))

    lines.extend(("", "## 新抽轨迹的判定样本"))
    counts = {}
    for status, limit in (("supported", 15), ("partial", 15), ("unknown", 10)):
        picked = sample(pools[status], lambda row: f"{row[0]}|{row[2]}", limit)
        counts[status] = {"available": len(pools[status]), "reviewed": len(picked)}
        lines.extend(("", f"### {status}（{len(picked)}/{len(pools[status])}）"))
        for tid, qid, cid, verdict, passage in picked:
            c = next(r for r in claims[qid]["conditions"] if r["id"] == cid)
            unit = verdict["unit_id"] if verdict["unit_id"] is not None else passage["unit_id"] if passage else None
            lines.extend((f"- {tid} / unit_id {unit} / 断言 {cid}",
                          f"  - 题面前 30 词 {field(qid, qs[qid]['question'], 30)}",
                          f"  - 断言 {field(qid, c['claim'])}",
                          f"  - 理由 {field(qid, verdict.get('reason'), 50)}"))
            if status == "partial":
                lines.append(f"  - 归类 {partial_categories.get(f'{tid}:{cid}', 'other')}")
            if verdict["sentences"]:
                for sentence in verdict["sentences"]:
                    lines.append(f"  - {sentence['id']} {field(qid, sentence['text'], 80)}")
            else:
                lines.append("  - 无引用句。以下片段来自本次判定的分块，供核对。")
            if passage:
                focus = verdict["sentences"][0]["text"] if verdict["sentences"] else c["claim"]
                lines.append(f"  - 片段 {passage['id']} {field(qid, helper.excerpt(passage['text'], focus))}")
    return "\n".join(lines) + "\n", counts


def report(plan, pilot, compared, full, reference, reviews, jobs):
    stats, judge = pilot["assertions"], pilot["judge"]
    spread = stats["coverage"]
    slurm = f"Slurm {jobs}。"
    build = ", ".join(f"{k}→{v}" for k, v in stats["count_distribution"].items())
    lines = [
        "# LedgerCredit M2 v5 试验", "",
        f"**[已验证]** 50 题、20 条训练轨迹。{slurm}第 1–2 步 {pilot['calls']['total']}/200 次调用"
        f"（初次 {pilot['calls']['assertion_first']}、重生成 {pilot['calls'].get('assertion_retry',0)}、"
        f"Judge {pilot['calls'].get('judge',0)}、归类 {pilot['calls'].get('partial_audit',0)}），"
        f"请求失败 {pilot['calls'].get('errors',0)}。",
        f"- 证据输入 {50-len(plan['excerpted_question_ids'])} 题为全文，"
        f"{len(plan['excerpted_question_ids'])} 题按文档取片段（{', '.join(plan['excerpted_question_ids']) or '无'}）。",
        f"- 每题断言数→题数 {build}，共 {stats['total_assertions']} 条。校验失败 {stats['failed']}，"
        f"空题 {stats['empty']}。失败 ID {', '.join(stats['failure_ids']) or '无'}。",
        "- 覆盖率（最小 / 中位 / 平均 / 最高）"
        f" {spread['min']:.1%} / {spread['median']:.1%} / {spread['mean']:.1%} / {spread['max']:.1%}，"
        f"{spread['at_least_70pct']}/50 达到 70%。失败题按零计入。",
        f"- 编号通过 {fraction(judge.get('valid_refs',0), judge.get('attempted_refs',0))}，"
        f"unknown 缺理由 {fraction(judge.get('unknown_without_reason',0), judge.get('raw_unknown',0))}。"
        f"门槛 {'全部通过' if pilot['gate']['passed'] else '未通过 ' + ', '.join(k for k,v in pilot['gate'].items() if not v and k!='passed')}。",
        "", "| 诊断样本 | v3 支持 / 部分 / 未知 | v4 | v5 |", "|---|---:|---:|---:|",
    ]
    for label, row in compared.items():
        lines.append(f"| {label} | {fmt(row['v3'])} | {fmt(row['v4']) if 'v4' in row else '—'} | {fmt(row['v5'])} |")
    p = pilot["partials"]
    counts = p["counts"]
    lines.extend(("", f"**[推断]** v5 的 partial 中，证据只支持一部分 {counts.get('partial_evidence',0)}，"
                  f"断言不准确 {counts.get('inaccurate_claim',0)}，其他 {counts.get('other',0)}"
                  f"（含归类缺失 {p['unclassified']}）。分类由独立本地调用给出。"))
    if full:
        g = full["ledger"]["groups"]
        ref = reference["ledger"]["groups"]
        check = full["ledger"]["validation"]
        outcomes = ["correct", "incorrect", "no_submission"]
        lines.extend(("", f"**[已验证]** 第 3 步完成 {full['trajectories']} 条，{full['calls']['total']} 次调用、"
                      f"失败 {full['calls'].get('errors',0)}。空跑覆盖 {check['validated_units']} 单元，"
                      f"缺失 {check['dry_run_missing']}。",
                      "- 每轨迹 C_new→轨迹数 " + "、".join(f"{k}→{v}" for k,v in
                          sorted(full["ledger"]["distributions"]["all"].items(), key=lambda x:int(x[0]))) + "。",
                      "- 平均 C_new（v5 / v3 / DocID） " + "；".join(
                          f"{k} {g[k]['mean_C_new']:.2f}/{ref[k]['mean_C_new']:.2f}/{g[k]['mean_DocID']:.2f}"
                          for k in outcomes if k in g) + "。",
                      "- 各终止方式（n / 平均 C_new） " + "；".join(
                          f"{k} {g[k]['n']}/{g[k]['mean_C_new']:.2f}" for k in sorted(g)
                          if k not in {"all", *outcomes}) + "。"))
    else:
        lines.extend(("", "**[已验证]** 第 3 步未运行，" + (
            "当前报告仅含小样本。" if pilot["gate"]["passed"] else "小样本门槛未全部通过。")))
    lines.extend(("", "v3 对原 10 条取旧诊断结果，对新 10 条取旧全量结果。各版断言总数有差异。",
                  f"私有核验抽样（支持 / 部分 / 未知） "
                  f"{' / '.join(str(reviews[k]['reviewed']) for k in STATUS)}。"))
    return "\n".join(lines) + "\n"


def main():
    p = ArgumentParser(description=__doc__)
    for key in ("root", "previous", "v4", "work", "full", "helper", "out"):
        p.add_argument("--" + key, type=Path)
    p.add_argument("--jobs", required=True)
    a = p.parse_args()
    qs, _, outcomes = base.training(a.root)
    plan = read(a.work / "inputs" / "plan.json")
    folder = a.work / "pilot"
    pilot = read(folder / "pilot_summary.json")
    assertions = folder / "conditions.jsonl"
    if sha256(assertions.read_bytes()).hexdigest() != pilot["assertions"]["sha256"]:
        raise ValueError("v5 frozen assertions hash mismatch")
    claims = {r["question_id"]:r for r in rows(assertions)}
    old, new = plan["old"], plan["new"]
    v5_records = index(folder)
    if v5_records.keys() != set(old + new) or claims.keys() != qs.keys():
        raise ValueError("pilot sample identity mismatch")
    baseline = a.previous / "m2-v3-192472"
    compared = {
        "原 10 条": {"v3": counts(index(a.previous/"pilot"), old), "v4": counts(index(a.v4/"pilot"), old),
                   "v5": counts(v5_records, old)},
        "新 10 条": {"v3": counts(index(baseline), new), "v5": counts(v5_records, new)},
    }
    compared["合计 20 条"] = {ver: dict(Counter(compared["原 10 条"][ver]) + Counter(compared["新 10 条"][ver]))
                               for ver in ("v3", "v5")}
    grouped = base.stage_rows(a.root, new)
    packet_md, reviews = packet(load_helper(a.helper), qs, claims, new, grouped, v5_records,
                                rows(folder/"judge_receipts.jsonl"), read(folder/"partial_cases.json"))
    full = read(a.full/"full_summary.json") if a.full else None
    md = report(plan, pilot, compared, full, read(baseline/"full_summary.json"), reviews, a.jobs)
    a.out.mkdir(mode=0o700)
    for name, value in (("REPORT.md", md), ("REVIEW_PACKET_v5.md", packet_md)):
        with (a.out/name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
    dump(a.out/"SUMMARY.json", {"pilot":pilot, "full":full, "comparison":compared, "review":reviews,
                               "sample_ids":{"old":old, "new":new}})
    print("reports_complete", flush=True)


if __name__ == "__main__":
    main()
