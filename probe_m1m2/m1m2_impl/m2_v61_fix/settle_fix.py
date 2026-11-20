"""Merge sealed decisions with the correction and rebuild comparable ledgers."""

from collections import Counter, defaultdict
from pathlib import Path
from random import Random
from statistics import mean
from tempfile import mkdtemp

from embed import dump
from prepare_full import read
from rules import outcome_label
from run_full import emit, judge, journal
from run_fix import rows
from settlement import BASELINE, OUTCOMES, SEED, attempts_summary, comparison


def claim_ids(records):
    return {(qid, claim["id"]) for qid, record in records.items() for claim in record["conditions"]}


def gold_outputs(args, records, gold, delta):
    prior = list(rows(args.prior / "gold_check.jsonl"))
    extra = [row for r in gold.values() for row in r["verdicts"]]
    all_verdicts = prior + extra
    identifiers = {(r["query_id"], r["assertion_id"]) for r in all_verdicts}
    if len(identifiers) != len(all_verdicts) or identifiers != claim_ids(records):
        raise ValueError("complete Gold verdicts do not match the corrected claims")
    by_id = {(r["query_id"], r["assertion_id"]): r for r in extra}
    if set(by_id) != claim_ids(delta):
        raise ValueError("supplemental Gold verdicts do not exactly match restored claims")
    ledger = {(r["query_id"], r["assertion_id"]): r for r in all_verdicts}
    for qid, rec in records.items():
        for claim in rec["conditions"]:
            row = ledger[qid, claim["id"]]
            if row["not_supported_by_gold"]:
                claim["flags"] = sorted(set(claim["flags"]) | {"not_supported_by_gold"})
                claim["gold_check_reason"] = row["reason"]
    emit(args.out / "gold_check.jsonl", all_verdicts)
    emit(args.out / "gold_delta.jsonl", extra)
    emit(args.out / "truncation.jsonl", (row["cut"] for row in gold.values() if row["cut"]))
    return by_id


def trajectory_outputs(args, records, delta, old, pipeline, v4, grouped, outcomes):
    previous = {tid: read(args.prior / "trajectories" / f"{tid}.json") for tid in outcomes}
    visible = {tid: [passage for block in v4.blocks(stages) for passage in block]
               for tid, stages in grouped.items() if outcomes[tid]["question_id"] in delta}

    def assess(tid, passages):
        qid = outcomes[tid]["question_id"]
        checked, attempts = judge(args, old, pipeline, v4.previous_driver, delta[qid], passages)
        decisions = [{"id": r["id"], "status": r["status"],
                      "first_supported": r["unit_id"] if r["status"] == "supported" else None,
                      "first_partial": r["unit_id"] if r["status"] == "partial" else None} for r in checked]
        verdicts = [{"trajectory_id": tid, "query_id": qid, "assertion_id": r["id"], "status": outcome_label(r),
                     "reason": r["reason"], "unit_id": r["unit_id"],
                     "citations": old.sources_for_judge(r, passages)} for r in checked]
        return {"attempts": attempts, "decisions": decisions, "verdicts": verdicts,
                "invalid_assertion_ids": [r["id"] for r in checked if not r["valid"]]}

    supplemental = journal(args.out / "trajectory_delta", visible, assess)
    merged = {}
    for tid, old_row in previous.items():
        extra = supplemental.get(tid, {"decisions": [], "verdicts": [], "invalid_assertion_ids": []})
        qid = outcomes[tid]["question_id"]
        decisions = old_row["decisions"] + extra["decisions"]
        decision_by_id = {row["id"]: row for row in decisions}
        ordered = [c["id"] for c in records[qid]["conditions"]]
        if len(decision_by_id) != len(decisions) or set(decision_by_id) != set(ordered):
            raise ValueError("merged trajectory decisions disagree with claim inventory")
        merged[tid] = {"decisions": [decision_by_id[cid] for cid in ordered],
                       "verdicts": old_row["verdicts"] + extra["verdicts"],
                       "invalid_assertion_ids": old_row["invalid_assertion_ids"] + extra["invalid_assertion_ids"]}
    emit(args.out / "verdicts.jsonl", (row for group in merged.values() for row in group["verdicts"]))
    emit(args.out / "trajectory_judge_status.jsonl", ({"trajectory_id": tid,
         "invalid_assertion_ids": row["invalid_assertion_ids"]} for tid, row in merged.items()))
    return merged, supplemental


def failure_counts(args, records):
    failures = {qid: set(record["flags"]) for qid, record in records.items() if len(record["conditions"]) < 2}
    for event in rows(args.prior / "rejected.jsonl"):
        if event["query_id"] in failures and event["phase"] in ("discard", "mark_record", "repair_retry"):
            failures[event["query_id"]].update(event["reasons"])
    for event in rows(args.out / "cleanup.jsonl"):
        if event["query_id"] in failures and event["action"] == "drop":
            failures[event["query_id"]].add(event["reason"])
    return Counter(reason for labels in failures.values() for reason in (labels or {"fewer_candidate_claims"}))


def usable_groups(args, records, result_path):
    baseline = {row["trajectory_id"]: row for row in rows(args.root / BASELINE / "trajectory_results.jsonl")}
    partitions = defaultdict(list)
    for row in rows(result_path):
        if len(records[row["question_id"]]["conditions"]) < 2:
            continue
        outcome = "no_submission" if not row["submitted"] else "correct" if row["correct"] else "incorrect"
        partitions[outcome].append(row)
    return {name: {"n": len(items), "mean_C_new": mean(r["C_new"] for r in items),
                   "mean_v3": mean(baseline[r["trajectory_id"]]["C_new"] for r in items),
                   "mean_DocID": mean(r["C_new_docid"] for r in items)} for name, items in partitions.items()}


def report(path, summary):
    population = summary["restoration"]
    n, usable = population["train"], population["usable_after"]
    lines = ["# M2 v6.1 主语清理修正", "",
             f"- 训练题 {n}｜留出题正文读取 0｜断言生成调用 0｜账本轨迹 {summary['trajectories']}",
             f"- 可用题 {population['usable_before']}/{n} → {usable}/{n}（{usable / n:.2%}）｜门槛 80%｜不足 2 条 {n - usable}",
             f"- 撤销主语删除 {population['subject_only_recovered']}｜恢复后入账 {population['restored']}",
             f"- 其余规则仍删除 {sum(population['still_filtered'].values())}｜"
             + "｜".join(f"{k} {v}" for k, v in sorted(population["still_filtered"].items())),
             f"- Gold 补判请求 {summary['gold']['requests']}｜轨迹补判 {summary['trajectory']['requests']}｜"
             f"沿用原判轨迹 {summary['trajectories'] - summary['trajectory']['requests']}",
             "", "| 不足 2 条的原因（按题计，可重叠） | 题数 |", "|---|---:|"]
    lines.extend(f"| {reason} | {count} |" for reason, count in sorted(summary["failures"].items()))
    lines.extend(["", "| 轨迹范围 | 结果 | N | 平均 C_new | 平均 v3 | 平均 DocID |", "|---|---|---:|---:|---:|---:|"])
    names = {"correct": "答对", "incorrect": "答错", "no_submission": "未交卷"}
    for label, groups in (("全量", summary["ledger"]["groups"]), ("可用题", summary["usable_groups"])):
        for name in OUTCOMES:
            row = groups.get(name)
            metrics = (f"{row['n']} | {row['mean_C_new']:.4f} | {row['mean_v3']:.4f} | {row['mean_DocID']:.4f}"
                       if row else "0 | — | — | —")
            lines.append(f"| {label} | {names[name]} | {metrics} |")
    audit = summary["ledger"]["validation"]
    lines.extend(["", f"- 空跑 Stage {audit['validated_units']}｜缺失 {audit['dry_run_missing']}｜"
                  f"私有抽查 {summary['review_rows']}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def settle(args, questions, receipt, delta, gold, old, pipeline, v4):
    driver = v4.previous_driver
    pilot, _, outcomes = driver.training(args.root)
    if (set(pilot) != set(receipt["round4_ids"])
            or any(questions[qid] != q for qid, q in pilot.items()) or len(outcomes) != 399):
        raise ValueError("round4 coverage mismatch")
    grouped = driver.stage_rows(args.root, outcomes)
    records = read(args.out / "records.json")
    supplemental_gold = gold_outputs(args, records, gold, delta)
    emit(args.out / "claims.jsonl", records.values())
    merged, supplemental = trajectory_outputs(args, records, delta, old, pipeline, v4, grouped, outcomes)
    outcome_rows = [outcomes.get(row["trajectory_id"], row) for row in
                    rows(args.root / "supplement-m1-192125/trajectory_results.jsonl")]
    tmp = Path(mkdtemp(prefix="ledger-", dir=args.out))
    metrics = driver.ledger_all(tmp, grouped, merged, records, questions, outcomes, outcome_rows)
    comparison(driver, args.root, metrics, tmp / "trajectory_results.jsonl")
    usable = usable_groups(args, records, tmp / "trajectory_results.jsonl")
    for path in tmp.iterdir():
        path.replace(args.out / path.name)
    tmp.rmdir()
    additions = {(qid, c["id"]): c for qid, record in records.items()
                 for c in record["conditions"] if (qid, c["id"]) in supplemental_gold}
    sample = Random(SEED).sample(sorted(additions), 15)
    review_dir = args.out / "m2_v61_fix"
    review_dir.mkdir(mode=0o700, exist_ok=True)
    emit(review_dir / "restored_assertions_sample.jsonl", ({"query_id": qid, "question": questions[qid]["question"],
         "entities": records[qid]["entities"], "assertion": additions[qid, cid],
         "gold_check": supplemental_gold[qid, cid]} for qid, cid in sample))
    summary = {"restoration": read(args.out / "restoration_counts.json"), "trajectories": len(merged),
               "failures": failure_counts(args, records), "usable_groups": usable, "ledger": metrics,
               "gold": attempts_summary(gold.values()), "trajectory": attempts_summary(supplemental.values()),
               "review_rows": len(sample)}
    report(args.out / "REPORT.md", summary)
    dump(args.out / "SUMMARY.json", summary)
