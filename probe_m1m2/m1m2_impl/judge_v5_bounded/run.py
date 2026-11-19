"""Run the twenty-trajectory v5 pilot using the existing v4 sentence Judge."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

from bounded import CALL_LIMIT, PROMPT, QUESTION_IDS, SEED, excerpt, select_tracks, validate


def load_inputs(v4, root):
    questions, _, outcomes = v4.previous_driver.training(root)
    if not set(QUESTION_IDS) <= questions.keys():
        raise ValueError("some requested questions are outside the frozen training sample")
    old = v4.read(root / "judge-v4-YRWP08/inputs/plan.json")["trajectories"]
    previous = root / "judge-v5-brzogs/inputs"
    previous_plan = v4.read(previous / "plan.json")
    excluded = set(old) | set(previous_plan["new"])
    for plan_path in root.glob("judge-diagnosis-*/plan.json"):
        excluded.update(row["trajectory_id"] for row in v4.read(plan_path).get("samples", []))
    candidates = {tid for tid, row in outcomes.items()
                  if row["question_id"] in QUESTION_IDS and tid not in excluded}
    if any(outcomes[tid]["question_id"] not in QUESTION_IDS for tid in old):
        raise ValueError("diagnostic manifest disagrees with the requested questions")
    grouped = v4.previous_driver.stage_rows(root, [*old, *sorted(candidates)])
    block_counts = {tid: len(v4.blocks(stages)) for tid, stages in grouped.items()}
    required = {tid for tid in candidates if outcomes[tid]["question_id"] == "642"}
    new = select_tracks(old, candidates, block_counts, required=required)
    chosen = old + new
    blocks = sum(block_counts[tid] for tid in chosen)
    prior = previous / "inputs.jsonl"
    if sha256(prior.read_bytes()).hexdigest() != previous_plan["input_sha256"]:
        raise ValueError("frozen input digest mismatch")
    prepared = {row["query_id"]: row for row in v4.rows(prior) if row["query_id"] in QUESTION_IDS}
    if set(prepared) != set(QUESTION_IDS) or any(
            body["question"] != questions[qid]["question"] for qid, body in prepared.items()):
        raise ValueError("frozen question text mismatch")
    plan = {"questions": len(prepared), "old": old, "new": new, "seed": SEED,
            "judge_blocks": blocks, "max_calls": 2 * len(prepared) + blocks}
    return prepared, {tid: grouped[tid] for tid in chosen}, outcomes, plan


def export_verdicts(v4, output, grouped, merged, path):
    passages = {tid: {passage["id"]: passage for block in v4.blocks(stages) for passage in block}
                for tid, stages in grouped.items()}
    unknown_reasons = {}
    for record in v4.rows(output / "judge_receipts.jsonl"):
        for row in record["verdicts"]:
            if row["raw_status"] == "unknown" and isinstance(row["reason"], str) and row["reason"].strip():
                unknown_reasons.setdefault((record["trajectory_id"], row["id"]), row["reason"])
    with path.open("x", encoding="utf-8") as file:
        for tid, record in merged.items():
            if not record["decisions"]:
                v4.emit(file, {"trajectory_id": tid, "assertion_id": None, "status": "unknown",
                               "reason": "No assertion passed validation.", "citations": []})
            for decision in record["decisions"]:
                cid = decision["id"]
                picked = record["audits"][cid]["verdict"]
                if picked is None:
                    reason = unknown_reasons.get((tid, cid), "No verified citation was returned.")
                    refs = []
                else:
                    reason = picked["reason"]
                    text = passages[tid][picked["passage_id"]]["text"]
                    refs = [excerpt(text, sentence) for sentence in picked["sentences"]]
                v4.emit(file, {"trajectory_id": tid, "assertion_id": cid, "status": decision["status"],
                               "reason": reason, "citations": refs})


def run(args, v4):
    prepared, grouped, outcomes, plan = load_inputs(v4, args.root)
    if plan["max_calls"] > CALL_LIMIT:
        raise ValueError("run exceeds the authorized call count")
    args.out.mkdir(mode=0o700, exist_ok=False)
    v4.dump(args.out / "plan.json", plan)
    print(json.dumps({key: plan[key] for key in ("questions", "judge_blocks", "max_calls")}), flush=True)
    calls = Counter()
    first = v4.batch(args.url, PROMPT, [(qid, prepared[qid]) for qid in QUESTION_IDS], 8192,
                     args.out / "assertion_first.jsonl", "assertions", calls, ceiling=CALL_LIMIT)
    failures = {qid: validate(qid, prepared[qid]["question"], first[qid]) for qid in QUESTION_IDS}
    requests = [(qid, {**prepared[qid], "validation_errors": errors}) for qid, errors in failures.items() if errors]
    retried = v4.batch(args.url, PROMPT, requests, 8192, args.out / "assertion_retry.jsonl",
                       "retry", calls, ceiling=CALL_LIMIT)
    final = first | retried
    frozen = {}
    unresolved = 0
    with (args.out / "claims_v5.jsonl").open("x", encoding="utf-8") as file:
        for qid in QUESTION_IDS:
            q = prepared[qid]["question"]
            errors = validate(qid, q, final[qid])
            if errors:
                unresolved += 1
                record = {"query_id": qid, "entities": [], "conditions": [], "answer_relation": None,
                          "validation_errors": errors}
            else:
                record = final[qid]
            v4.emit(file, {"question": q, **record})
            frozen[qid] = {"conditions": [{**condition, "text": condition["claim"],
                                           "support_rule": condition["claim"], "evidence": []}
                                          for condition in record["conditions"]]}
    merged, tallies = v4.judge_pass(args, grouped, frozen, outcomes, args.out, calls, ceiling=CALL_LIMIT)
    if set(merged) != grouped.keys() or calls["judge"] != plan["judge_blocks"]:
        raise ValueError("v4 execution does not match the plan")
    export_verdicts(v4, args.out, grouped, merged, args.out / "verdicts_v5.jsonl")
    summary = {"assertions": sum(len(row["conditions"]) for row in frozen.values()),
               "validation_failures_first": len(requests), "validation_failures_final": unresolved,
               "judge_invalid_verdicts": tallies["malformed_verdicts"], "questions": len(prepared),
               "trajectories": len(merged), "calls": dict(calls)}
    summary.update({status: tallies[status] for status in ("supported", "partial", "unknown")})
    v4.dump(args.out / "summary.json", summary)
    print(json.dumps(summary), flush=True)


def main():
    command = ArgumentParser()
    command.add_argument("--root", type=Path, required=True)
    command.add_argument("--v4-control", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--url", required=True)
    args = command.parse_args()
    sys.path.insert(0, str(args.v4_control / "judge_v4"))
    import pilot as v4
    run(args, v4)


if __name__ == "__main__":
    main()
