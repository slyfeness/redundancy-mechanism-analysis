
"""Settle confirmed support and export counts plus the authorized review sample."""

from collections import Counter
import json
from pathlib import Path
from random import Random
from statistics import mean
from tempfile import mkdtemp

from embed import dump
from prepare_full import read
from rules import outcome_label

SEED = 20261119
BASELINE = "judge-v3-5NrGAW/m2-v3-192472"
TERMINAL = ("MODEL_FINAL_STOP", "CONTEXT_LIMIT_STOP", "SAFETY_CEILING_STOP", "EMPTY_MODEL_STOP",
            "GENERATION_LENGTH_STOP")
OUTCOMES = ("correct", "incorrect", "no_submission")
STATUSES = ("supported", "partial", "unknown", "different_entity", "invalid")


def attempts_summary(rows):
    attempts = [r["attempts"] for r in rows]
    before = sum(len(a[0]["invalid_slots"]) for a in attempts)
    after = sum(sum(i in a[-1]["invalid_slots"] for i in a[0]["invalid_slots"]) for a in attempts)
    return {"requests": len(attempts), "calls": sum(map(len, attempts)),
            "retry_requests": sum(len(a) > 1 for a in attempts),
            "invalid_requests_before": sum(bool(a[0]["invalid_slots"] or a[0]["error"]) for a in attempts),
            "invalid_requests_after": sum(bool(set(a[0]["invalid_slots"]) & set(a[-1]["invalid_slots"])
                                               or a[-1]["error"]) for a in attempts),
            "invalid_before": before, "invalid_after": after}


def condition_counts(questions, records, gold_verdicts, cuts):
    over = {row["query_id"] for row in cuts}
    size = {qid: len(record["conditions"]) for qid, record in records.items()}
    gold = {qid: Counter() for qid in questions}
    for row in gold_verdicts:
        gold[row["query_id"]].update(total=1, marked=int(row["not_supported_by_gold"]))
    if any(gold[qid]["total"] != n for qid, n in size.items()):
        raise ValueError("Gold must account for every retained claim exactly once")

    def summarize(qids):
        histogram = Counter(size[qid] for qid in qids)
        return {"questions": len(qids), "under_two": histogram[0] + histogram[1],
                "assertions": sum(size[qid] for qid in qids),
                "gold_marked": sum(gold[qid]["marked"] for qid in qids), "histogram": dict(histogram)}

    counts = {"all": summarize(set(questions)), "overflow": summarize(over),
              "complete_input": summarize(set(questions) - over),
              "by_stage": {phase: len({c["query_id"] for c in cuts if c["phase"] == phase})
                           for phase in ("assertion", "repair", "gold")}}
    return counts


def comparison(driver, root, metrics, result_path):
    baseline = {row["trajectory_id"]: row for row in driver.rows(root / BASELINE / "trajectory_results.jsonl")}
    result = {r["trajectory_id"]: r for r in driver.rows(result_path)}
    if len(result) != 399 or result.keys() != baseline.keys():
        raise ValueError("ledger comparisons must use the same 399 trajectories")
    for tid, row in result.items():
        prior = baseline[tid]
        if any(prior[key] != row[key] for key in ("question_id", "C_new_docid", "submitted", "correct", "terminal_status")):
            raise ValueError("baseline identity, DocID count or outcome mismatch")
    groups = {}
    for tid, row in result.items():
        label = "no_submission" if not row["submitted"] else "correct" if row["correct"] else "incorrect"
        for key in ("all", label, row["terminal_status"]):
            groups.setdefault(key, []).append(baseline[tid]["C_new"])
    for key, values in groups.items():
        if metrics["groups"][key]["n"] != len(values):
            raise ValueError("incorrect denominator in the M2 ledger comparison")
        metrics["groups"][key]["mean_v3"] = mean(values)


def review(args, questions, records, gold_verdicts, trajectory_verdicts, visible,
           track_question, round4, old, sampled_unknown, emit):
    rng = Random(SEED)
    gold = {(row["query_id"], row["assertion_id"]): row for row in gold_verdicts}
    pool = [(qid, claim) for qid, rec in records.items() if qid not in round4 for claim in rec["conditions"]]
    picks = rng.sample(pool, min(30, len(pool)))
    supported = [row for row in trajectory_verdicts if row["status"] == "supported"]
    selected = rng.sample(supported, min(20, len(supported)))
    unknown, eligible = sampled_unknown(trajectory_verdicts, track_question, records, visible, old.excerpt)
    reasons = {qid: set(rec["flags"]) | {"fewer_than_two_after_cleanup"}
               for qid, rec in records.items() if len(rec["conditions"]) < 2}
    for name in ("cleanup.jsonl", "rejected.jsonl"):
        with (args.out / name).open(encoding="utf-8") as events:
            for row in events:
                event = json.loads(row)
                qid = event["query_id"]
                if qid in reasons:
                    if name == "cleanup.jsonl" and event["action"] == "drop":
                        reasons[qid].add(event["reason"])
                    if name == "rejected.jsonl" and event["phase"] in ("discard", "mark_record", "repair_retry"):
                        reasons[qid].update(event["reasons"])
    weak = [{"query_id": qid, "assertion_count": len(records[qid]["conditions"]), "reasons": sorted(why)}
            for qid, why in reasons.items()]

    def enrich(row):
        record = records[row["query_id"]]
        claim = next(c for c in record["conditions"] if c["id"] == row["assertion_id"])
        return {**row, "assertion": claim,
                "subject_name": next(e["name"] for e in record["entities"] if e["var"] == claim["subject"])}

    out = args.out / "m2_v61_full"
    out.mkdir(mode=0o700, exist_ok=True)
    emit(out / "assertion_sample.jsonl", ({"query_id": qid, "question": questions[qid]["question"],
         "entities": records[qid]["entities"], "assertion": claim,
         "gold_check": gold[qid, claim["id"]]} for qid, claim in picks))
    emit(out / "supported_sample.jsonl", (enrich(row) for row in selected))
    emit(out / "unknown_sample.jsonl", (enrich(row) for row in unknown))
    emit(out / "under_two.jsonl", weak)
    return {"new_claims": len(picks), "supported": len(selected), "unknown": len(unknown),
            "unknown_eligible": eligible, "under_two_questions": len(weak)}


def report(out, summary):
    def percent(n, d):
        return f"{100 * n / d:.2f}%" if d else "—"

    counts = summary["assertions"]
    total = counts["all"]
    usable = total["questions"] - total["under_two"]
    lines = [
        "# M2 v6.1 全量验收", "",
        f"- 训练题 {total['questions']}｜留出题正文读取 {summary['heldout_decoded']}｜复用轨迹 {summary['trajectories']}",
        f"- 可用题 {usable}/{total['questions']}（{percent(usable, total['questions'])}）｜门槛 80%",
        f"- 断言生成 {summary['generation']['assertion_calls']} 次｜首轮调用错误 {summary['generation']['assertion_errors']} 次"
        f"｜修复（含重试）{summary['generation']['repair_calls']} 次",
        f"- 超限题计数（断言生成/修复/Gold）{' / '.join(str(n) for n in counts['by_stage'].values())}",
        "", "| 每题断言数 | 题数 |", "|---:|---:|",
    ]
    lines.extend(f"| {size} | {n} |" for size, n in sorted(total["histogram"].items()))
    lines += ["", "| 输入 | 题数 | 不足 2 条 | Gold 标记 |", "|---|---:|---:|---:|"]
    for key, label in (("all", "全量"), ("overflow", "超限"), ("complete_input", "完整")):
        row = counts[key]
        lines.append(f"| {label} | {row['questions']} | {row['under_two']} ({percent(row['under_two'], row['questions'])})"
                     f" | {row['gold_marked']}/{row['assertions']} ({percent(row['gold_marked'], row['assertions'])}) |")
    over, full = counts["overflow"], counts["complete_input"]
    if over["assertions"] and full["assertions"]:
        delta = 100 * (over["gold_marked"] / over["assertions"] - full["gold_marked"] / full["assertions"])
        note = "（高出 10 个百分点以上）" if delta > 10 else ""
        lines.extend(["", f"- Gold 标记率差（超限减完整）{delta:+.2f} 个百分点{note}"])
    lines += ["", "| 清理 | 次数 |", "|---|---:|"]
    for key in ("answer_in_subject", "answer_in_claim", "duplicate_claim", "unknown_subject", "entity_variable_replaced"):
        lines.append(f"| {key} | {summary['generation']['cleanup'].get(key, 0)} |")
    lines += ["", "| Judge | 请求 | 含重试调用 | 重试前 invalid 请求 | 重试后 invalid 请求 | 重试前 invalid 断言 | 重试后 invalid 断言 |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for key, label in (("gold", "Gold"), ("trajectory", "轨迹")):
        row = summary["judge"][key]
        request = [f"{row['invalid_requests_' + stage]} ({percent(row['invalid_requests_' + stage], row['requests'])})"
                   for stage in ("before", "after")]
        assertions = [f"{row['invalid_' + stage]} ({percent(row['invalid_' + stage], row['assertions'])})"
                      for stage in ("before", "after")]
        lines.append(f"| {label} | {row['requests']} | {row['calls']} | " + " | ".join(request + assertions) + " |")
    lines += ["", "| Judge | " + " | ".join(STATUSES) + " |", "|---|---:|---:|---:|---:|---:|"]
    for key, label in (("gold", "Gold"), ("trajectory", "轨迹")):
        lines.append(f"| {label} | " + " | ".join(str(summary["judge"][key]["status"].get(s, 0)) for s in STATUSES) + " |")
    lines += ["", "| 轨迹分组 | N | 平均 C_new | 平均 v3 | 平均 DocID |", "|---|---:|---:|---:|---:|"]
    groups = summary["ledger"]["groups"]
    for label in ("all", *OUTCOMES, *TERMINAL, *sorted(groups.keys() - {"all", *OUTCOMES, *TERMINAL})):
        if label in groups:
            row = groups[label]
            lines.append(f"| {label} | {row['n']} | {row['mean_C_new']:.4f} | {row['mean_v3']:.4f} | {row['mean_DocID']:.4f} |")
    lines += ["", "| 轨迹 C_new | 轨迹数 |", "|---:|---:|"]
    lines.extend(f"| {size} | {n} |" for size, n in sorted(summary["ledger"]["distributions"]["all"].items()))
    audit = summary["ledger"]["validation"]
    lines += ["", f"- 空跑验收 {audit['validated_units']} 个 Stage｜缺失 {audit['dry_run_missing']}｜严格重复 {audit['strict_repeat_units']}",
              f"- 私有抽查断言 {summary['review']['new_claims']}｜supported {summary['review']['supported']}｜unknown {summary['review']['unknown']}"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def settle(args, questions, records, receipt, gold, old, pipeline, v4):
    from run_full import emit, journal, judge

    from sampling import sample_unknown

    driver = v4.previous_driver
    pilot_questions, _, outcomes = driver.training(args.root)
    if (set(pilot_questions) != set(receipt["round4_ids"])
            or any(questions[qid] != q for qid, q in pilot_questions.items())):
        raise ValueError("trajectories and full-run training selection disagree")
    grouped = driver.stage_rows(args.root, outcomes)
    track_question = {tid: row["question_id"] for tid, row in outcomes.items()}
    visible = {tid: [passage for block in v4.blocks(stages) for passage in block] for tid, stages in grouped.items()}

    def assess(tid, passages):
        qid = track_question[tid]
        decisions, attempts = judge(args, old, pipeline, driver, records[qid], passages)
        verification = [{"trajectory_id": tid, "query_id": qid, "assertion_id": row["id"],
                         "status": outcome_label(row), "reason": row["reason"], "unit_id": row["unit_id"],
                         "citations": old.sources_for_judge(row, passages)} for row in decisions]
        ledger = [{"id": row["id"], "status": row["status"],
                   "first_supported": row["unit_id"] if row["status"] == "supported" else None,
                   "first_partial": row["unit_id"] if row["status"] == "partial" else None} for row in decisions]
        return {"attempts": attempts, "verdicts": verification, "decisions": ledger,
                "invalid_assertion_ids": [r["id"] for r in decisions if not r["valid"]]}

    trajectories = journal(args.out / "trajectories", visible, assess)
    gold_verdicts = [v for row in gold.values() for v in row["verdicts"]]
    trajectory_verdicts = [v for row in trajectories.values() for v in row["verdicts"]]
    for row in gold_verdicts:
        if row["not_supported_by_gold"]:
            claim = next(c for c in records[row["query_id"]]["conditions"] if c["id"] == row["assertion_id"])
            claim["flags"] = sorted(set(claim["flags"]) | {"not_supported_by_gold"})
            claim["gold_check_reason"] = row["reason"]
    emit(args.out / "claims.jsonl", records.values())
    emit(args.out / "gold_check.jsonl", gold_verdicts)
    emit(args.out / "verdicts.jsonl", trajectory_verdicts)
    emit(args.out / "trajectory_judge_status.jsonl", ({"trajectory_id": tid,
         "invalid_assertion_ids": row["invalid_assertion_ids"]} for tid, row in trajectories.items()))
    cuts = read(args.out / "assertion_cuts.json") + [v["cut"] for v in gold.values() if v["cut"]]
    emit(args.out / "truncation.jsonl", cuts)

    outcome_rows = [outcomes.get(r["trajectory_id"], r) for r in
                    driver.rows(args.root / "supplement-m1-192125/trajectory_results.jsonl")]
    if len(outcome_rows) != 400:
        raise ValueError("expected original eight-slot outcome groups")
    tmp = Path(mkdtemp(prefix="ledger-", dir=args.out))
    ledger = driver.ledger_all(tmp, grouped, trajectories, records, questions, outcomes, outcome_rows)
    comparison(driver, args.root, ledger, tmp / "trajectory_results.jsonl")
    for path in tmp.iterdir():
        path.replace(args.out / path.name)
    tmp.rmdir()
    checked = review(args, questions, records, gold_verdicts, trajectory_verdicts, visible,
                     track_question, set(receipt["round4_ids"]), old, sample_unknown, emit)
    judge_counts = {}
    for key, rows, verdicts in (("gold", gold, gold_verdicts), ("trajectory", trajectories, trajectory_verdicts)):
        judge_counts[key] = {**attempts_summary(rows.values()), "assertions": len(verdicts),
                             "status": dict(Counter(r["status"] for r in verdicts))}
        if judge_counts[key]["invalid_after"] != judge_counts[key]["status"].get("invalid", 0):
            raise ValueError("invalid decisions cannot enter the unknown count")
    summary = {"trajectories": len(trajectories), "heldout_decoded": receipt["heldout_decoded"],
               "assertions": condition_counts(questions, records, gold_verdicts, cuts),
               "generation": read(args.out / "generation_counts.json"), "judge": judge_counts,
               "ledger": ledger, "review": checked}
    report(args.out / "REPORT.md", summary)
    dump(args.out / "SUMMARY.json", summary)
