"""Audit identical grader inputs and bounds on the frozen fixed-task accuracy."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from regrade_pilot import ARMS, bind_arm, read, sha


def prompt_overlap(evaluations, *, candidate):
    """Compute task-weighted bounds with explicit assumptions about missing verdicts."""
    indexed, observed, missing = {}, defaultdict(set), Counter()
    for arm, rows in evaluations.items():
        index = {(row["task_id"], row["sample_id"]): row for row in rows}
        if not index or len(index) != len(rows):
            raise ValueError("nonempty evaluations with distinct sample identities are required")
        indexed[arm] = index
        for row in rows:
            outcome, prompt = row["outcome"], row["prompt"]
            key = row["task_id"], prompt
            if outcome is None:
                if not prompt:
                    raise ValueError("ungraded submissions require a bound prompt")
                missing[key] += 1
            elif type(outcome) not in (int, float) or outcome not in (0, 1):
                raise ValueError("expected a binary outcome or missing verdict")
            elif prompt is not None:
                observed[key].add(int(outcome))
    reference = indexed[candidate]
    if any(index.keys() != reference.keys() for index in indexed.values()):
        raise ValueError("evaluations must share fixed task and sample identities")
    tasks = Counter(task for task, _ in reference)
    weights = {task: Fraction(1, len(tasks) * count) for task, count in tasks.items()}
    anchors = {key: next(iter(labels)) for key, labels in observed.items() if len(labels) == 1}
    conflicts = {key for key, labels in observed.items() if len(labels) > 1}

    def bounds(coefficients, known):
        return [float(known + sum(x for x in coefficients if x < 0)),
                float(known + sum(x for x in coefficients if x > 0))]

    arms, comparisons = {}, {}
    for arm, index in indexed.items():
        keys = [(row["task_id"], row["prompt"]) for row in index.values() if row["outcome"] is None]
        arms[arm] = {"missing_verdict_count": len(keys), "distinct_missing_prompts": len(set(keys)),
                     "missing_with_unanimous_observed_prompt": sum(key in anchors for key in keys),
                     "missing_with_conflicting_observed_prompt": sum(key in conflicts for key in keys)}
        if arm == candidate:
            continue
        known, unlinked, coefficients = Fraction(0), [], defaultdict(Fraction)
        for sign, sample_rows in ((1, reference), (-1, index)):
            for (task, _), row in sample_rows.items():
                weight = sign * weights[task]
                if row["outcome"] is None:
                    unlinked.append(weight)
                    coefficients[task, row["prompt"]] += weight
                else:
                    known += weight * int(row["outcome"])
        anchored = known + sum(weight * anchors[key] for key, weight in coefficients.items() if key in anchors)
        comparisons[f"{candidate}_minus_{arm}"] = {
            "unconstrained_delta_bounds": bounds(unlinked, known),
            "tied_missing_prompt_delta_bounds": bounds(coefficients.values(), known),
            "anchored_prompt_delta_bounds": bounds(
                [weight for key, weight in coefficients.items() if key not in anchors], anchored),
        }
    return {"missing_verdict_count": sum(missing.values()), "missing_prompt_count": len(missing),
            "repeated_missing_prompt_count": sum(count > 1 for count in missing.values()),
            "missing_prompt_with_unanimous_observed_count": len(missing.keys() & anchors.keys()),
            "conflicting_observed_prompt_count": len(conflicts), "arms": arms, "comparisons": comparisons}


def bind_prompts(source, arm, frozen, samples, render):
    summary, _, binding = bind_arm(source, arm, frozen, samples)
    folder = source / f"eval-{arm}"
    input_path = folder / "LOCAL_JUDGE_INPUT.json"
    judge_path = folder / "API_JUDGE.json"
    rows, served_models = [], Counter()
    for index, (row, grader, verdict, task) in enumerate(zip(
            summary["rows"], read(input_path), read(judge_path), samples, strict=True)):
        qid, tid, seed, question_sha = task
        digest = None
        if row["complete"]:
            raw = read(folder / "trajectories" / tid / "trajectory.json")
            meta = raw["metadata"]
            native = meta["task"]
            seen = [call for call in raw["rounds"] if call.get("response_received")]
            final = (seen[-1].get("content") or "") if seen else ""
            if (meta["terminal_status"] != "MODEL_FINAL_STOP"
                    or (str(native["query_id"]), native["run_id"], native["seed"],
                        native["question_sha256"]) != task
                    or hashlib.sha256(grader["question"].encode()).hexdigest() != question_sha
                    or final != grader["final"]
                    or read(folder / "api-verdicts" / f"{index:03d}.json") != verdict):
                raise ValueError(f"{arm} recorded request and native submission disagree for {tid}")
            digest = hashlib.sha256(render(grader["question"], final, grader["gold"]).encode()).hexdigest()
            if row["outcome"] is not None:
                if verdict["attempts"][-1]["status"] != 200 or not verdict["served_model"]:
                    raise ValueError("resolved result requires an actual successful service receipt")
                served_models[verdict["served_model"]] += 1
        rows.append({"task_id": qid, "sample_id": tid, "outcome": row["outcome"], "prompt": digest})
    return rows, dict(binding, judge_inputs_sha256=sha(input_path), judge_receipts_sha256=sha(judge_path),
                      served_models=dict(served_models))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = args.store / "runs/pilot-182516"
    receipt = read(run / "BASELINE_EVALUATION_RECEIPT.json")
    p0 = args.store / "runs" / receipt["run_name"]
    if sha(p0 / "EVAL-P0.json") != receipt["summary_sha256"] or read(p0 / "EVAL-P0.json") != read(run / "EVAL-P0.json"):
        raise ValueError("frozen P0 summary does not match the original receipt")
    plan = args.store / "plans/pilot-182406/PRIVATE_PLAN.json"
    tasks = read(plan)["evaluation_rows"]
    frozen = {str(row["query_id"]): row for row in tasks}
    if len(frozen) != len(tasks) or len(tasks) != 16:
        raise ValueError("expected sixteen fixed evaluation tasks")
    samples = [(str(row["query_id"]), f"{row['query_id']}__rep{rep+1}", 2026111100+i*8+rep, row["question_sha256"])
               for i, row in enumerate(tasks) for rep in range(8)]
    from src.prepare_training import judge_protocol
    from src.stability_judge import MODEL

    protocol, identity = judge_protocol()
    evaluations, bindings = {}, {}
    for arm in ("P0", *ARMS):
        evaluations[arm], bindings[arm] = bind_prompts(
            p0 if arm == "P0" else run, arm, frozen, samples, protocol["create_judge_prompt"])
    report = prompt_overlap(evaluations, candidate="targeted")
    report.update(source_run=str(run), plan_sha256=sha(plan), judge_protocol=identity, requested_model=MODEL,
                  bindings=bindings, assumptions={
                      "unconstrained": "Each missing official result can independently be 0 or 1.",
                      "tied_missing_prompt": "Missing outcomes with the same prompt and task share one unknown binary verdict.",
                      "anchored_prompt": "Additionally assume missing outcomes agree with unanimous archived successful "
                                         "receipts on the identical prompt and task. Conflicting receipts never anchor.",
                      "scope": "Fixed-task sensitivity, not sampling intervals or replacement official verdicts.",
                  })
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, allow_nan=False)
    print(json.dumps({key: report[key] for key in ("missing_verdict_count", "missing_prompt_count",
                                                  "repeated_missing_prompt_count", "conflicting_observed_prompt_count",
                                                  "missing_prompt_with_unanimous_observed_count")}), flush=True)


if __name__ == "__main__":
    main()
