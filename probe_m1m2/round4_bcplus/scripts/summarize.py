"""Read frozen records and export only numeric values, IDs and controlled enums."""
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from read_stages import outcome_record
from signals import EPS, VARIANTS, is_nonzero, outcomes, stage_advantages


GROUPS = ("0/8", "1–7/8", "8/8")
FLAGS = ("S_exact", "S_near", "S_allseen", "O_exact", "O_samecontent", "S_empty", "O_unseen")
REPETITION = ("strict_repeat", "repeat_union")


def proportion(count, total):
    return count / total if total else None


def distribution(values):
    values = list(values)
    return {"n": len(values), "min": min(values, default=None), "median": median(values) if values else None,
            "max": max(values, default=None), "mean": mean(values) if values else None}


def fraction(count, total):
    return {"n": count, "denominator": total, "fraction": proportion(count, total)}


def num_signals(stages, key, subset=None):
    selected = [stage for stage in stages if subset is None or stage["group_type"] == subset]
    values = [stage[key] for stage in selected]
    return {"distribution": distribution(values), "negative": sum(value < -EPS for value in values),
            "zero": sum(not is_nonzero(value) for value in values), "positive": sum(value > EPS for value in values)}


def repetition_comparison(stages, key, repeated):
    by_trajectory = defaultdict(list)
    for stage in stages:
        by_trajectory[stage["trajectory_id"]].append(stage)
    gaps = []
    repeat_values = []
    for stages_in_trace in by_trajectory.values():
        control = [stage[key] for stage in stages_in_trace if not stage[repeated]]
        repeats = [stage[key] for stage in stages_in_trace if stage[repeated]]
        repeat_values.extend(repeats)
        if control:
            control_mean = mean(control)
            gaps.extend(value - control_mean for value in repeats)
    return {"repeat_advantage": distribution(repeat_values), "repeat_minus_same_trajectory_nonrepeat": distribution(gaps),
            "no_nonrepeat_in_same_trajectory": len(repeat_values) - len(gaps),
            "zero_advantage": fraction(sum(not is_nonzero(value) for value in repeat_values), len(repeat_values))}


def counts_by_group(rows, stages):
    summary = {}
    for group in (*GROUPS, "all"):
        trajectories = [row for row in rows if row["group_type"] == group or group == "all"]
        members = [stage for stage in stages if stage["group_type"] == group or group == "all"]
        token_count = sum(row["generated_tokens"] for row in trajectories if row["A_out"] is not None)
        stage_token_count = sum(stage["generated_tokens"] for stage in members if stage["A_out"] is not None)
        unresolved = sum(row["generated_tokens"] for row in trajectories
                         if row["A_out"] is not None and not row["has_stage_signals"])
        affected = {variant: sum(stage["generated_tokens"] for stage in members
                                 if stage[f"A_{variant}"] is not None and abs(stage[f"A_{variant}"] - stage["A_out"]) > .05)
                    for variant in VARIANTS}
        summary[group] = {"policy_tokens": token_count, "stage_policy_tokens": stage_token_count,
                          "unallocated_policy_tokens": token_count - stage_token_count,
                          "policy_tokens_with_unresolved_stage_signals": unresolved,
                          "delta_vs_grpo_gt_005": {variant: fraction(value, token_count - unresolved)
                                                    for variant, value in affected.items()}}
    return summary


def index_trajectories(tasks, run, evaluation, markers, retries):
    rows = []
    per_question = defaultdict(list)
    for task in tasks:
        tid, qid = task["run_id"], task["query_id"]
        question = evaluation[qid]
        row, stages = outcome_record(task, run / "trajectories" / tid, run / "verdicts" / f"{tid}.json",
                                     markers, set(question["evidence_docs"]), set(question["gold_docs"]),
                                     retries / f"{tid}.json" if retries else None)
        row.update(group_type="unknown", rho_x=None, A_out=None, has_stage_signals=False)
        rows.append(row)
        per_question[qid].append((row, stages))
    assert len(rows) == 400 and len(per_question) == 50 and all(len(group) == 8 for group in per_question.values())
    return rows, per_question


def compute_signals(per_question):
    all_stages = [stage for group in per_question.values() for _, stages in group for stage in stages]
    known_costs = [stage["generated_tokens"] + stage["obs_tokens"] for stage in all_stages
                   if stage["obs_tokens"] is not None]
    cost_median = median(known_costs) if known_costs else None
    assert cost_median is None or cost_median > 0
    group_stats = {}
    for qid, group in per_question.items():
        rows, trajectories = map(list, zip(*group, strict=True))
        assessed = outcomes(rows)
        group_record = {"question_id": qid, "correct": sum(row["correct"] is True for row in rows),
                        "known": sum(type(row["correct"]) is bool for row in rows),
                        "group_type": "unknown", "has_A_out": None, "rho_x": None, "has_stage_signals": False}
        group_stats[qid] = group_record
        has_costs = all(row["stage_accounting"] == "complete" for row in rows)
        if assessed:
            rho, a_out = assessed
            group_type = GROUPS[0] if rho == 0 else GROUPS[2] if rho == 1 else GROUPS[1]
            group_record.update(rho_x=rho, group_type=group_type, has_A_out=any(map(is_nonzero, a_out)),
                                has_stage_signals=has_costs)
            for row, baseline in zip(rows, a_out, strict=True):
                row.update(group_type=group_type, rho_x=rho, A_out=baseline, has_stage_signals=has_costs)
        for row, stages in group:
            for stage in stages:
                cost = None if stage["obs_tokens"] is None else stage["generated_tokens"] + stage["obs_tokens"]
                idle = min(2, cost / cost_median) if stage["strict_repeat"] and cost is not None else (
                    None if stage["strict_repeat"] else 0.0)
                stage.update(idle=idle, stage_cost=cost, A_out=row["A_out"], rho_x=row["rho_x"],
                             group_type=row["group_type"])
                for variant in VARIANTS:
                    for key in ("u", "A_re", "A_st", "A", "peer_count", "u_center"):
                        stage[f"{key}_{variant}"] = None
        if assessed and has_costs:
            for variant in VARIANTS:
                progress = variant.split("_", 1)[0]
                values = stage_advantages(trajectories, a_out, rho, progress, variant.endswith("prime"))
                for stages in trajectories:
                    for stage in stages:
                        stage.update({f"{key}_{variant}": value for key, value in values[stage["event_key"]].items()})
    return all_stages, group_stats, cost_median


def progress_summary(stages, rows, progress):
    key = f"c_new_{progress}"
    measured = [row for row in rows if row[key] is not None]
    numerator = sum(row[key] > 0 for row in measured)
    return {"distribution_per_trajectory": distribution(row[key] for row in measured),
            "trajectories_with_gain": fraction(numerator, len(measured)),
            "stages_with_gain": fraction(sum(stage[key] > 0 for stage in stages), len(stages)),
            "unfed_stages_with_gain": sum(stage[key] > 0 and stage["terminal_unfed"] for stage in stages),
            "gain_units_from_unfed_tool_returns": sum(stage[key] for stage in stages if stage["terminal_unfed"]),
            "by_outcome": {
                "correct": distribution(row[key] for row in measured if row["correct"] is True),
                "all_unsuccessful": distribution(row[key] for row in measured if row["correct"] is False),
                "incorrect_submitted": distribution(row[key] for row in measured
                                                   if row["correct"] is False and row["submitted"]),
                "no_submission": distribution(row[key] for row in measured if row["submitted"] is False),
            }}


def criteria(s, progress):
    gain = s["progress"][progress]
    correct = gain["by_outcome"]["correct"]["mean"]
    unsuccessful = gain["by_outcome"]["all_unsuccessful"]["mean"]
    measures = {
        "1_outcome_groups": s["outcome_signal"]["total"]["fraction"],
        "2_strict_repeat_in_signal_groups": s["repetition"]["strict_repeat"]["in_A_out_nonzero_groups"]["fraction"],
        "3_trajectory_progress": gain["trajectories_with_gain"]["fraction"],
        "4_comparable_stage": s["variants"][progress + "_u"]["second_path"]["comparable"]["fraction"],
    }
    thresholds = dict(zip(measures, (.3, .5, .5, .6), strict=True))
    result = {key: {"value": value, "threshold": thresholds[key],
                    "pass": value >= thresholds[key] if value is not None else None} for key, value in measures.items()}
    more = correct > unsuccessful if correct is not None and unsuccessful is not None else None
    result["3_trajectory_progress"]["correct_has_more_than_all_unsuccessful"] = more
    if result["3_trajectory_progress"]["pass"] is not False:
        result["3_trajectory_progress"]["pass"] = more
    return result


def summarize(rows, stages, groups, evaluation, cost_median):
    by_group = list(groups.values())
    s = {
        "expected_questions": 50, "expected_trajectories": 400, "reused": 0, "heldout_used": 0,
        "group_records": by_group, "outcome_signal": {}, "repetition": {}, "variants": {},
        "sealed": sum(row["termination_reason"] != "missing" for row in rows),
        "resolved_outcomes": sum(type(row["correct"]) is bool for row in rows),
        "correct": sum(row["correct"] is True for row in rows), "submitted": sum(row["submitted"] is True for row in rows),
        "terminal_statuses": Counter(row["termination_reason"] for row in rows),
        "stage_accounting": Counter(row["stage_accounting"] for row in rows),
        "complete_outcome_groups": sum(group["has_A_out"] is not None for group in by_group),
        "complete_stage_groups": sum(group["has_stage_signals"] for group in by_group),
        "trailing_open_tool_rounds": sum(row["trailing_open_rounds"] for row in rows),
        "stages": len(stages), "unparsed_returns": sum(not stage["return_parsed"] for stage in stages),
        "terminal_returns_not_fed": sum(stage["terminal_unfed"] for stage in stages), "median_stage_cost": cost_median,
        "strict_same_round_only": sum(stage["strict_same_round_only"] for stage in stages),
        "rules": {flag: fraction(sum(flag in stage["flags"] for stage in stages), len(stages)) for flag in FLAGS},
        "tool_counts": Counter(stage["tool"] for stage in stages),
        "annotation_counts": {field: distribution(len(row[field]) for row in evaluation.values())
                              for field in ("evidence_docs", "gold_docs")},
        "group_counts": Counter(group["group_type"] for group in by_group),
        "correct_count_per_complete_group": Counter(group["correct"] for group in by_group if group["known"] == 8),
        "progress": {progress: progress_summary(stages, rows, progress) for progress in ("any", "open")},
        "token_comparison": counts_by_group(rows, stages),
        "new_judge_requests": sum(row["judge_source"] == "gpt-oss-120b" for row in rows),
        "new_judge_failures": sum(row["judge_first_failed"] for row in rows),
        "judge_retries": sum(row["judge_retry"] for row in rows),
        "judge_recovered": sum(row["judge_retry"] and row["correct"] is not None for row in rows),
        "unresolved_judge_results": sum(row["judge_source"] == "gpt-oss-120b" and row["correct"] is None for row in rows),
        "process_judge_requests": 0, "optimizer_steps": 0,
    }
    for group_type in (*GROUPS, "total"):
        group = [r for r in by_group if r["group_type"] == group_type or group_type == "total"]
        s["outcome_signal"][group_type] = fraction(sum(row["has_A_out"] is True for row in group), len(group))
    for repeat in REPETITION:
        marked = [stage for stage in stages if stage[repeat]]
        s["repetition"][repeat] = {
            "all": fraction(len(marked), len(stages)),
            "in_A_out_nonzero_groups": fraction(sum(groups[stage["question_id"]]["has_A_out"] is True
                                                   for stage in marked), len(marked)),
            "in_rho_positive_groups": fraction(sum(bool(stage["rho_x"]) for stage in marked), len(marked)),
            "in_all_wrong_groups": fraction(sum(stage["rho_x"] == 0 for stage in marked), len(marked)),
            "in_unknown_groups": fraction(sum(stage["rho_x"] is None for stage in marked), len(marked)),
        }
    for variant in VARIANTS:
        key = f"A_st_{variant}"
        scored = [stage for stage in stages if stage[key] is not None]
        s["variants"][variant] = {
            "second_path": {
                "comparable": fraction(sum(stage[f"peer_count_{variant}"] > 0 for stage in scored), len(scored)),
                "nonzero": fraction(sum(is_nonzero(stage[key]) for stage in scored), len(scored)),
                "all_wrong": num_signals(scored, key, "0/8"),
            },
            "repeat_signal": {repeat: repetition_comparison(scored, f"A_{variant}", repeat) for repeat in REPETITION},
            "repeat_signal_all_wrong": {
                repeat: repetition_comparison([stage for stage in scored if stage["rho_x"] == 0],
                                              f"A_{variant}", repeat) for repeat in REPETITION},
        }
    s["criteria"] = {progress: criteria(s, progress) for progress in ("any", "open")}
    return s


def write_csv(path, rows, fields):
    with path.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, separators=(",", ":")) if isinstance(value, list) else value
                             for key, value in row.items()})


def main(selection, run, tokenizer_path, out, retries=None):
    read = lambda path: json.loads(path.read_bytes())
    tasks = read(selection / "task_manifest.json")["tasks"]
    evaluation = {row["id"]: row for row in read(selection / "evaluation_private.json")}
    split = read(selection / "split.json")
    assert set(evaluation) == {task["query_id"] for task in tasks}
    assert set(evaluation) <= set(split["train"]) and not set(evaluation) & set(split["test"])
    assert len(set(split["train"])) == 664 and len(set(split["test"])) == 166
    added = {item["content"]: item["id"] for item in read(tokenizer_path)["added_tokens"]}
    markers = {key: added[key] for key in ("<tool_call>", "</tool_call>", "<tool_response>", "</tool_response>")}
    rows, per_question = index_trajectories(tasks, run, evaluation, markers, retries)
    stages, groups, cost_median = compute_signals(per_question)
    summary = summarize(rows, stages, groups, evaluation, cost_median)
    summary["analysis_job"] = int(os.environ["SLURM_JOB_ID"])
    summary["source_gpu_job"] = int(run.name.split("-")[-1])
    summary["judge_retry_job"] = int(retries.parent.name.split("-")[-1]) if retries else None
    out.mkdir(mode=0o700, exist_ok=False)
    write_csv(out / "trajectory_outcomes.csv", rows, list(rows[0]))
    fields = ["trajectory_id", "question_id", "stage_id", "round", "tool", "docids", "flags", "return_parsed",
              "repeat_union", "strict_repeat", "strict_match_stage_id", "strict_same_round_only",
              "observation_visible", "terminal_unfed", "generated_tokens", "obs_tokens", "stage_cost",
              "b_before", "z_before_any", "z_before_open", "c_new_any", "c_new_open", "idle", "group_type", "rho_x", "A_out"]
    fields.extend(f"{key}_{variant}" for variant in VARIANTS for key in ("u", "A_re", "A_st", "A", "peer_count", "u_center"))
    write_csv(out / "stage_signals.csv", stages, fields)
    (out / "signal_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                              encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("sealed", "resolved_outcomes", "stages", "stage_accounting",
                                                   "group_counts", "criteria")}), flush=True)


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
