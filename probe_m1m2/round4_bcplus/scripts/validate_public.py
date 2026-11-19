"""Check table safety and reconcile counts before publishing."""
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from signals import VARIANTS


ROOT = Path(__file__).resolve().parents[1]
FLAGS = {"S_exact", "S_near", "S_allseen", "O_exact", "O_samecontent", "S_empty", "O_unseen"}
GROUPS = {"0/8", "1–7/8", "8/8", "unknown"}
OUTCOME_TEXT = {
    "termination_reason": {"MODEL_FINAL_STOP", "CONTEXT_LIMIT_STOP", "SAFETY_CEILING_STOP", "GENERATION_LENGTH_STOP",
                           "EMPTY_MODEL_STOP", "OBSERVABILITY_ERROR", "RUNTIME_ERROR", "NO_MODEL_CALL", "missing"},
    "stage_accounting": {"complete", "missing", "unresolved_ValueError", "unresolved_KeyError", "unresolved_return_tokens"},
    "judge_source": {"gpt-oss-120b", "terminal_rule", ""},
    "group_type": GROUPS,
}
CSV_SCALARS = re.compile(r"(?:-?[0-9]+(?:\.[0-9]+)?(?:e[+-][0-9]+)?|True|False)?", re.I)
STAGE_ID = re.compile(r"R[0-9]+(?::T[0-9]+)?")


def read_json(name):
    return json.loads((ROOT / name).read_bytes())


def read_csv(name):
    with (ROOT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def validate():
    split, selection, summary = map(read_json, ("split.json", "selection.json", "signal_summary.json"))
    assert set(split) == {"train", "test"}
    train, test = set(split["train"]), set(split["test"])
    assert len(train) == len(split["train"]) == 664 and len(test) == len(split["test"]) == 166
    assert not train & test and all(re.fullmatch(r"[0-9]+", qid) for qid in train | test)
    assert hashlib.sha256((ROOT / "split.json").read_bytes()).hexdigest() == selection["split_sha256"]
    assert len(selection["training_ids"]) == len(set(selection["training_ids"])) == 50
    assert set(selection["training_ids"]) <= train and selection["test_questions_decoded"] == 0
    outcomes = read_csv("trajectory_outcomes.csv")
    stages = read_csv("stage_signals.csv")
    assert len(outcomes) == len({row["trajectory_id"] for row in outcomes}) == 400
    assert Counter(row["question_id"] for row in outcomes) == dict.fromkeys(selection["training_ids"], 8)
    assert len(stages) == len({(s["trajectory_id"], s["stage_id"]) for s in stages}) == summary["stages"]
    by_trace = defaultdict(list)
    for stage in stages:
        by_trace[stage["trajectory_id"]].append(stage)
        assert STAGE_ID.fullmatch(stage["stage_id"]) and (not stage["strict_match_stage_id"] or
                                                         STAGE_ID.fullmatch(stage["strict_match_stage_id"]))
        assert stage["tool"] in {"search", "open", "unknown", "unparsed", "other"}
        assert stage["group_type"] in GROUPS
        assert all(re.fullmatch(r"[0-9]+", docid) for docid in json.loads(stage["docids"]))
        assert set(json.loads(stage["flags"])) <= FLAGS
        skip = {"trajectory_id", "question_id", "stage_id", "strict_match_stage_id", "tool", "group_type", "docids", "flags"}
        assert all(CSV_SCALARS.fullmatch(value) for key, value in stage.items() if key not in skip)
    assert set(by_trace) <= {row["trajectory_id"] for row in outcomes}
    for row in outcomes:
        qid = row["question_id"]
        assert row["trajectory_id"] == f"{qid}__rep{row['repetition_id']}"
        assert 1 <= int(row["repetition_id"]) <= 8
        assert not row["actor_calls"] or int(row["actor_calls"]) <= 20
        for key, allowed in OUTCOME_TEXT.items():
            assert row[key] in allowed
        assert all(CSV_SCALARS.fullmatch(value) for key, value in row.items()
                   if key not in OUTCOME_TEXT and key != "trajectory_id")
        events = by_trace[row["trajectory_id"]]
        assert all(stage["question_id"] == qid for stage in events)
        if row["stage_accounting"] != "complete":
            continue
        assert len(events) == int(row["tool_calls"])
        assert sum(int(stage["obs_tokens"]) for stage in events) == int(row["return_tokens"])
        assert sum(int(stage["generated_tokens"]) for stage in events) + int(row["unallocated_policy_tokens"]) == int(row["generated_tokens"])
        for mode in ("any", "open"):
            assert sum(int(stage[f"c_new_{mode}"]) for stage in events) == int(row[f"c_new_{mode}"])
    assert sum(row["correct"] == "True" for row in outcomes) == summary["correct"]
    assert sum(row["correct"] != "" for row in outcomes) == summary["resolved_outcomes"]
    for key in ("strict_repeat", "repeat_union"):
        assert sum(stage[key] == "True" for stage in stages) == summary["repetition"][key]["all"]["n"]
    for variant in VARIANTS:
        assigned = [stage for stage in stages if stage[f"A_{variant}"]]
        for stage in assigned:
            assert abs(float(stage[f"A_{variant}"]) - float(stage[f"A_re_{variant}"]) -
                       .3 * float(stage[f"A_st_{variant}"])) < 1e-10
            assert 0 <= int(stage[f"peer_count_{variant}"]) <= 7
        changed = sum(int(stage["generated_tokens"]) for stage in assigned
                      if abs(float(stage[f"A_{variant}"]) - float(stage["A_out"])) > .05)
        assert changed == summary["token_comparison"]["all"]["delta_vs_grpo_gt_005"][variant]["n"]
    assert summary["heldout_used"] == summary["process_judge_requests"] == summary["optimizer_steps"] == 0
    print("validated split, CSV allowlists, Stage and token totals, and all four advantage decompositions")


if __name__ == "__main__":
    validate()
