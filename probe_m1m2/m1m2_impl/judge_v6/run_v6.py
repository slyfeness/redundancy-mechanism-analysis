"""Reproducible v6 pilot. All open-ended language model interactions are counted."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import random
import sys

from claims import (REPAIR_PROMPT, event, initial_parts, inspect, prompt_with_examples, reconcile)
from judgement import JUDGE_PROMPT, check_verdicts

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "judge_v5_bounded"))
from bounded import QUESTION_IDS, excerpt

BASELINE = "judge-v5-bounded-192857/results/plan.json"
BASELINE_SHA256 = "a429872bee40fa957d5d8c15b58b8e8a439e01b44740d5f28a67fa2c83f04f5f"
SEED = 20261119
CAP = 120


def load(v4, root):
    path = root / BASELINE
    if sha256(path.read_bytes()).hexdigest() != BASELINE_SHA256:
        raise ValueError("original v5 sample digest mismatch")
    baseline = v4.read(path)
    old_tracks = baseline["old"] + baseline["new"]
    questions, _, outcomes = v4.previous_driver.training(root)
    available = defaultdict(list)
    for tid, row in outcomes.items():
        available[row["question_id"]].append(tid)
    old_questions = {outcomes[tid]["question_id"] for tid in old_tracks}
    if old_questions != set(QUESTION_IDS):
        raise ValueError("unexpected baseline question set")
    rng = random.Random(SEED)
    new_questions = rng.sample(sorted(set(questions) - old_questions), 10)
    new_tracks = [tid for qid in new_questions for tid in rng.sample(sorted(available[qid]), 2)]
    selected = list(QUESTION_IDS) + new_questions
    tids = old_tracks + new_tracks
    if len(set(tids)) != 40 or len(set(selected)) != 20 or len(questions) != 50:
        raise ValueError("unexpected pilot size")

    documents = v4.read(root / "docs-192072/evidence_docs.json")
    inputs = {}
    for qid in selected:
        simplified = questions[qid]
        inputs[qid] = {"query_id": qid, "question": simplified["question"],
                       "reference_answers": simplified["answers"], "evidence_documents": [
                           {"docid": docid, "text": documents[docid]} for docid in simplified["evidence_docs"]]}
    source_stages = v4.previous_driver.stage_rows(root, tids)
    visible = {tid: [passage for block in v4.blocks(source_stages[tid]) for passage in block] for tid in tids}
    plan = {"seed": SEED, "questions": selected, "old_trajectories": old_tracks,
            "new_trajectories": new_tracks, "trajectory_question": {tid: outcomes[tid]["question_id"] for tid in tids},
            "max_model_calls": 2 * len(selected) + len(tids), "heldout_questions_used": 0}
    if plan["max_model_calls"] > CAP:
        raise ValueError("pilot exceeds authorized model calls")
    return inputs, visible, plan


def private_prompt(file):
    data = json.loads(file.read_bytes())
    return prompt_with_examples(data)


def parsed_text(v4, path):
    """Retain the model's content for failed JSON parsing without exporting provider metadata."""
    result = {}
    for row in v4.rows(path):
        try:
            text = row["raw"]["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            continue
        if isinstance(text, str):
            result[row["key"]] = text
    return result


def claims_pass(v4, prompt, inputs, args, calls):
    out = args.out
    first = v4.batch(args.url, prompt, list(inputs.items()), 8192, out / "assertion_raw.jsonl",
                     "assertions", calls, ceiling=CAP)
    marked = {qid: inspect(qid, body["question"], first[qid]) for qid, body in inputs.items()}
    bad_text = parsed_text(v4, out / "assertion_raw.jsonl")
    jobs = []
    with (out / "rejected_v6.jsonl").open("x", encoding="utf-8") as audit:
        for qid, marks in marked.items():
            if not (marks["record"] or marks["claims"]):
                continue
            original = first[qid]
            _, _, conditions = initial_parts(original)
            if marks["record"]:
                v4.emit(audit, event(qid, "mark_record", None, marks["record"],
                                     original if original is not None else bad_text.get(qid)))
            for slot, reasons in marks["claims"].items():
                v4.emit(audit, event(qid, "mark", slot, reasons, conditions[slot]))
            jobs.append((qid, {**inputs[qid], "first_response": original,
                               "marked_slots": [{"slot": slot, "reasons": reasons} for slot, reasons in
                                                marks["claims"].items()],
                               "record_issues": marks["record"],
                               "minimum_needed": max(0, 2 - (len(conditions) - len(marks["claims"])))}))
        repaired = v4.batch(args.url, prompt + REPAIR_PROMPT, jobs, 8192, out / "repair_raw.jsonl",
                            "repair", calls, ceiling=CAP)
        repair_text = parsed_text(v4, out / "repair_raw.jsonl")
        frozen, totals = {}, Counter()
        with (out / "claims_v6.jsonl").open("x", encoding="utf-8") as accepted:
            for qid, body in inputs.items():
                record, events = reconcile(qid, body["question"], first[qid], marked[qid], repaired.get(qid))
                if qid in repaired and not isinstance(repaired[qid], dict):
                    v4.emit(audit, event(qid, "repair_record_unusable", None, ["invalid_repair_json"],
                                         first[qid], repair_text.get(qid)))
                for row in events:
                    v4.emit(audit, row)
                    totals[row["phase"]] += 1
                totals["marked_claims"] += len(marked[qid]["claims"])
                totals["questions_repaired"] += qid in repaired
                totals["assertions"] += len(record["conditions"])
                v4.emit(accepted, {"question": body["question"], **record})
                frozen[qid] = record
    return frozen, totals


def judge_pass(v4, args, frozen, visible, plan, calls):
    def payload(tid):
        record = frozen[plan["trajectory_question"][tid]]
        return {"claims": [{"id": row["id"], "text": row["claim"]} for row in record["conditions"]],
                "entities": [{key: e[key] for key in ("name", "role")} for e in record["entities"]],
                "passages": [{"sentences": [{key: s[key] for key in ("id", "text")} for s in p["sentences"]]}
                             for p in visible[tid]]}

    jobs = [(tid, payload(tid)) for tid in visible]
    raw = v4.batch(args.url, JUDGE_PROMPT, jobs, 6144, args.out / "judge_raw.jsonl",
                   "judge", calls, ceiling=CAP)
    totals = Counter()
    with (args.out / "verdicts_v6.jsonl").open("x", encoding="utf-8") as output:
        for tid, passages in visible.items():
            record = frozen[plan["trajectory_question"][tid]]
            indexed = {passage["id"]: passage for passage in passages}
            decisions = check_verdicts(record["conditions"], passages, raw[tid])
            if not decisions:
                v4.emit(output, {"trajectory_id": tid, "assertion_id": None, "status": "unknown",
                                 "reason": "No assertion passed validation.", "unit_id": None, "citations": []})
            for decision in decisions:
                status = decision["status"]
                citations = [
                    {**excerpt(indexed[pid]["text"], sentence), "passage_id": pid,
                     "unit_id": indexed[pid]["unit_id"]} for pid, sentence in decision["sentences"]]
                totals[status] += 1
                totals["invalid_verdicts"] += not decision["valid"]
                totals["two_passage_supported"] += status == "supported" and decision["passage_count"] == 2
                v4.emit(output, {"trajectory_id": tid, "assertion_id": decision["id"], "status": status,
                                 "reason": decision["reason"], "unit_id": decision["unit_id"],
                                 "citations": citations})
    return totals


def main():
    parser = ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--v4-control", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.v4_control / "judge_v4"))
    import pilot as v4

    examples = BASE / "prompts_private.json"
    prompt = private_prompt(examples)
    inputs, visible, plan = load(v4, args.root)
    print(json.dumps({"questions": len(inputs), "trajectories": len(visible),
                      "maximum_model_calls": plan["max_model_calls"]}), flush=True)
    args.out.mkdir(mode=0o700, exist_ok=False)
    v4.dump(args.out / "plan.json", plan)
    v4.dump(args.out / "private_prompts.json", {
        "first": prompt, "repair": prompt + REPAIR_PROMPT, "judge": JUDGE_PROMPT,
        "source_examples_sha256": sha256(examples.read_bytes()).hexdigest()})
    calls = Counter()
    records, claims = claims_pass(v4, prompt, inputs, args, calls)
    verdicts = judge_pass(v4, args, records, visible, plan, calls)
    summary = {"questions": len(inputs), "trajectories": len(visible), "calls": dict(calls),
               "claims": dict(claims), "verdicts": dict(verdicts)}
    v4.dump(args.out / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
