"""Export full submissions for a blinded, offline result diagnostic."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import secrets

from audit_prompt_overlap import bind_prompts
from regrade_pilot import read, sha


ARMS = ("P0", "outcome", "trajectory", "targeted", "shuffled", "uniform")
DEFAULT_ARMS = ("P0", "outcome", "targeted")
PROTOCOL = (
    "Read the entire submission against the supplied reference and question. "
    "Judge whether its endorsed final answer is semantically equivalent to the reference and meets "
    "the requested answer scope. Accept unambiguous equivalent names, phrasing, and numeric formatting. "
    "A reference mentioned only as a rejected alternative does not count. A different answer, "
    "unresolved contradictory answers, or an explicit refusal without an answer is not equivalent. "
    "Use uncertain when equivalence cannot be determined from the available text. "
    "Judge the answer only. Do not infer correctness from arm, run, previous scores, or writing length."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arms", choices=ARMS, nargs="+", default=DEFAULT_ARMS)
    args = parser.parse_args()
    if len(set(args.arms)) != len(args.arms):
        parser.error("select each review arm only once")
    run = args.store / "runs/pilot-182516"
    receipt = read(run / "BASELINE_EVALUATION_RECEIPT.json")
    p0 = args.store / "runs" / receipt["run_name"]
    if sha(p0 / "EVAL-P0.json") != receipt["summary_sha256"] or read(p0 / "EVAL-P0.json") != read(run / "EVAL-P0.json"):
        raise ValueError("P0 evaluation does not match its baseline receipt")
    plan = args.store / "plans/pilot-182406/PRIVATE_PLAN.json"
    tasks = read(plan)["evaluation_rows"]
    frozen = {str(row["query_id"]): row for row in tasks}
    if len(frozen) != len(tasks) or len(tasks) != 16:
        raise ValueError("expected sixteen fixed tasks")
    samples = [(str(row["query_id"]), f"{row['query_id']}__rep{rep+1}", 2026111100+i*8+rep, row["question_sha256"])
               for i, row in enumerate(tasks) for rep in range(8)]
    from src.prepare_training import judge_protocol

    protocol, judge_identity = judge_protocol()
    by_task, bindings = defaultdict(list), {}
    for arm in args.arms:
        source = p0 if arm == "P0" else run
        rows, bindings[arm] = bind_prompts(source, arm, frozen, samples, protocol["create_judge_prompt"])
        originals = read(source / f"eval-{arm}" / "LOCAL_JUDGE_INPUT.json")
        for row, original in zip(rows, originals, strict=True):
            if row["prompt"] is not None:
                by_task[row["task_id"]].append((
                    original["final"],
                    {"arm": arm, "task_id": row["task_id"], "sample_id": row["sample_id"],
                     "archived_verdict": row["outcome"], "prompt_sha256": row["prompt"]},
                ))
    rng = secrets.SystemRandom()
    order = list(by_task)
    rng.shuffle(order)
    groups, identities = [], {}
    for task_id in order:
        rng.shuffle(by_task[task_id])
        question = frozen[task_id]
        cases = []
        for final, binding in by_task[task_id]:
            case = f"case-{len(identities)+1:03d}"
            identities[case] = binding
            cases.append({"id": case, "final": final})
        groups.append({"question": question["question"], "reference": question["gold"], "cases": cases})
    args.output.mkdir(mode=0o700, exist_ok=False)
    with (args.output / "PACKET.json").open("x", encoding="utf-8") as handle:
        json.dump({"protocol": PROTOCOL, "groups": groups}, handle, ensure_ascii=False, allow_nan=False)
    with (args.output / "IDENTITIES.json").open("x", encoding="utf-8") as handle:
        json.dump({"source_run": str(run), "judge_identity": judge_identity, "plan_sha256": sha(plan),
                   "packet_sha256": sha(args.output / "PACKET.json"), "bindings": bindings,
                   "cases": identities}, handle, ensure_ascii=False, allow_nan=False)
    print("blinded_submissions", len(identities), "tasks_with_submissions", len(groups), flush=True)


if __name__ == "__main__":
    main()
