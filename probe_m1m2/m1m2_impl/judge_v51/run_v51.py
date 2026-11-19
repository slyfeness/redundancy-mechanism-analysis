"""Run the named-claim trial over the exact frozen v5 plan."""

from argparse import ArgumentParser
from functools import partial
import hashlib
import importlib.util
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "judge_v5_bounded"))
from bounded import CALL_LIMIT, QUESTION_IDS
from rules import JUDGE_ENTITY_RULE, PROMPT, judge_payload, validate

BASELINE = "judge-v5-bounded-192857/results/plan.json"
BASELINE_SHA256 = "a429872bee40fa957d5d8c15b58b8e8a439e01b44740d5f28a67fa2c83f04f5f"


def load_frozen(v4, root):
    path = root / BASELINE
    if hashlib.sha256(path.read_bytes()).hexdigest() != BASELINE_SHA256:
        raise ValueError("v5 plan digest mismatch")
    plan = v4.read(path)
    chosen = plan["old"] + plan["new"]
    questions, _, outcomes = v4.previous_driver.training(root)
    if (plan["questions"] != len(QUESTION_IDS) or len(set(chosen)) != 20
            or {outcomes[tid]["question_id"] for tid in chosen} != set(QUESTION_IDS)):
        raise ValueError("v5.1 scope differs from the frozen baseline")
    grouped = v4.previous_driver.stage_rows(root, chosen)
    blocks = sum(len(v4.blocks(grouped[tid])) for tid in chosen)
    if blocks != plan["judge_blocks"] or blocks + 2 * len(QUESTION_IDS) != CALL_LIMIT:
        raise ValueError("v4 block count or call budget changed")
    inputs = root / "judge-v5-brzogs/inputs"
    raw = inputs / "inputs.jsonl"
    if hashlib.sha256(raw.read_bytes()).hexdigest() != v4.read(inputs / "plan.json")["input_sha256"]:
        raise ValueError("frozen input digest mismatch")
    prepared = {row["query_id"]: row for row in v4.rows(raw) if row["query_id"] in QUESTION_IDS}
    if set(prepared) != set(QUESTION_IDS) or any(
            body["question"] != questions[qid]["question"] for qid, body in prepared.items()):
        raise ValueError("frozen question text mismatch")
    return prepared, {tid: grouped[tid] for tid in chosen}, outcomes, plan


def main():
    parser = ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--v4-control", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--url")
    parser.add_argument("--verify-plan", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.v4_control / "judge_v4"))
    import pilot as v4

    if args.verify_plan:
        _, grouped, _, plan = load_frozen(v4, args.root)
        print(f"Frozen plan verified: {plan['questions']} questions, {len(grouped)} trajectories, "
              f"{plan['judge_blocks']} v4 blocks, maximum {plan['max_calls']} model calls")
        return
    if not args.url or not args.out:
        parser.error("--url and --out are required to run inference")
    spec = importlib.util.spec_from_file_location("bounded_trial", BASE / "judge_v5_bounded/run.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    judge = partial(v4.judge_pass, prompt=v4.JUDGE_PROMPT + JUDGE_ENTITY_RULE,
                    make_payload=partial(judge_payload, base_payload=v4.payload))
    runner.run(args, v4, version="v51", prompt=PROMPT, validate_claims=validate,
               input_loader=load_frozen, judge_pass=judge)


if __name__ == "__main__":
    main()
