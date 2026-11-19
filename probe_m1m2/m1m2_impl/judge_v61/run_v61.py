"""Run v6.1 against frozen v6 Judge rules and the same forty trajectories."""

from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

from pipeline import REPAIR_RULE, SUBJECT_RULE, build_payload, inspect, reconcile, usable_repair
from prepare import FROZEN, bind, digest, read
from sampling import sample_unknown

from claims import REPAIR_PROMPT, event, initial_parts
from judgement import JUDGE_PROMPT, check_verdicts
from run_v6 import load, parsed_text
from bounded import excerpt

BASE = Path(__file__).resolve().parent.parent
CAP = 120
OUTPUTS = ("claims_v61.jsonl", "verdicts_v61.jsonl", "rejected_v61.jsonl",
           "gold_check_v61.jsonl", "unknown_sample_v61.jsonl")


def source_inputs(v4, args):
    plan, frozen = bind(args.root, BASE)
    inputs, visible, actual_plan = load(v4, args.root)
    if actual_plan != plan:
        raise ValueError("v6.1 must use the exact frozen v6 selection")
    prior = read(args.root / FROZEN / "private_prompts.json")
    if prior["judge"] != JUDGE_PROMPT:
        raise ValueError("frozen Judge prompt mismatch")
    directory = BASE / "prepared_gold"
    receipt = read(directory / "PREP.json")
    path = directory / "gold_passages.json"
    if (receipt["gold_sha256"] != digest(path) or receipt["plan_sha256"] != frozen["plan_sha256"]
            or receipt["judge_source_sha256"] != frozen["sources_sha256"]["judgement.py"]):
        raise ValueError("prepared Gold payload does not match the frozen run")
    gold = read(path)
    if set(gold) != set(inputs) or len(visible) != 40 or 4 * len(inputs) + len(visible) > CAP:
        raise ValueError("v6.1 sample exceeds the authorized scope")
    return inputs, visible, gold, plan, prior, receipt


def repair_targets(inputs, base):
    marks = {qid: inspect(qid, row["question"], base[qid]) for qid, row in inputs.items()}
    jobs = {}
    for qid, checked in marks.items():
        if checked["claims"] or checked["record"]:
            original = base[qid]
            _, _, conditions = initial_parts(original)
            jobs[qid] = {**inputs[qid], "first_response": original,
                         "marked_slots": [{"slot": slot, "reasons": reasons}
                                          for slot, reasons in checked["claims"].items()],
                         "record_issues": checked["record"],
                         "minimum_needed": max(0, 2 - (len(conditions) - len(checked["claims"])))}
    return marks, jobs


def claim_pass(v4, args, inputs, first_prompt, repair_prompt, calls):
    out = args.out
    first = v4.batch(args.url, first_prompt, list(inputs.items()), 8192, out / "assertion_raw.jsonl",
                     "assertions", calls, ceiling=CAP)
    marks, jobs = repair_targets(inputs, first)
    attempt = v4.batch(args.url, repair_prompt, list(jobs.items()), 8192, out / "repair_raw.jsonl",
                       "repair", calls, ceiling=CAP)
    retry_jobs = [(qid, jobs[qid]) for qid, response in attempt.items() if not usable_repair(response)]
    retry = v4.batch(args.url, repair_prompt, retry_jobs, 8192, out / "repair_retry_raw.jsonl",
                     "repair_retry", calls, ceiling=CAP)
    first_text = parsed_text(v4, out / "assertion_raw.jsonl")
    repair_text = parsed_text(v4, out / "repair_raw.jsonl")
    retry_text = parsed_text(v4, out / "repair_retry_raw.jsonl")
    records, totals = {}, Counter()
    with (out / OUTPUTS[2]).open("x", encoding="utf-8") as audit:
        for qid, body in inputs.items():
            original = first[qid]
            checked = marks[qid]
            _, _, conditions = initial_parts(original)
            if checked["record"]:
                v4.emit(audit, event(qid, "mark_record", None, checked["record"],
                                     original if original is not None else first_text.get(qid)))
            for slot, reasons in checked["claims"].items():
                v4.emit(audit, event(qid, "mark", slot, reasons, conditions[slot]))
            if qid in retry:
                v4.emit(audit, event(qid, "repair_retry", None, ["repair_response_unusable"],
                                     repair_text.get(qid), retry_text.get(qid)))
            response = retry.get(qid, attempt.get(qid))
            exhausted = qid in jobs and not usable_repair(response)
            record, events = reconcile(qid, body["question"], original, checked, response, exhausted=exhausted)
            for row in events:
                v4.emit(audit, row)
                totals[row["phase"]] += 1
            records[qid] = record
            totals.update(marked_claims=len(checked["claims"]), assertions=len(record["conditions"]),
                          repair_exhausted=exhausted)
    return records, totals


def sources_for_judge(decision, passages, *, gold=False):
    indexed = {p["id"]: p for p in passages}
    result = []
    for pid, sentence in decision["sentences"]:
        source = indexed[pid]
        ref = {**excerpt(source["text"], sentence), "passage_id": pid}
        if gold:
            ref.update(docid=source["docid"], labels=source["labels"])
        else:
            ref["unit_id"] = source["unit_id"]
        result.append(ref)
    return result


def judge_pass(v4, args, records, visible, gold, plan, calls):
    jobs = [(("gold", qid), build_payload(records[qid], passages)) for qid, passages in gold.items()]
    jobs.extend((("trajectory", tid), build_payload(records[plan["trajectory_question"][tid]], passages))
                for tid, passages in visible.items())
    raw = v4.batch(args.url, JUDGE_PROMPT, jobs, 6144, args.out / "judge_raw.jsonl",
                   "judge", calls, ceiling=CAP)
    totals = Counter()
    with (args.out / OUTPUTS[3]).open("x", encoding="utf-8") as file:
        for qid, passages in gold.items():
            conditions = records[qid]["conditions"]
            decisions = check_verdicts(conditions, passages, raw[("gold", qid)])
            for claim, decision in zip(conditions, decisions, strict=True):
                status = decision["status"]
                flagged = status not in {"supported", "partial"}
                result = {"query_id": qid, "assertion_id": claim["id"], "status": status,
                          "reason": decision["reason"], "not_supported_by_gold": flagged,
                          "citations": sources_for_judge(decision, passages, gold=True)}
                if flagged:
                    claim["flags"] = sorted(set(claim["flags"]) | {"not_supported_by_gold"})
                    claim["gold_check_reason"] = decision["reason"]
                totals[f"gold_{status}"] += 1
                totals["gold_invalid_verdicts"] += not decision["valid"]
                v4.emit(file, result)
    del jobs
    verdicts = []
    with (args.out / OUTPUTS[1]).open("x", encoding="utf-8") as file:
        for tid, passages in visible.items():
            conditions = records[plan["trajectory_question"][tid]]["conditions"]
            decisions = check_verdicts(conditions, passages, raw[("trajectory", tid)])
            if not decisions:
                v4.emit(file, {"trajectory_id": tid, "assertion_id": None, "status": "unknown",
                               "reason": "No assertion passed validation.", "unit_id": None, "citations": []})
            for decision in decisions:
                status = decision["status"]
                result = {"trajectory_id": tid, "assertion_id": decision["id"], "status": status,
                          "reason": decision["reason"], "unit_id": decision["unit_id"],
                          "citations": sources_for_judge(decision, passages)}
                totals[status] += 1
                totals["invalid_verdicts"] += not decision["valid"]
                totals["two_passage_supported"] += status == "supported" and decision["passage_count"] == 2
                verdicts.append(result)
                v4.emit(file, result)
    samples, eligible = sample_unknown(verdicts, plan["trajectory_question"], records, visible, excerpt)
    with (args.out / OUTPUTS[4]).open("x", encoding="utf-8") as file:
        for row in samples:
            v4.emit(file, row)
    totals.update(unknown_sampled=len(samples), unknown_eligible=eligible,
                  gold_requests=len(gold), trajectory_requests=len(visible))
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

    inputs, visible, gold, plan, prior, receipt = source_inputs(v4, args)
    args.out.mkdir(mode=0o700, exist_ok=False)
    v4.dump(args.out / "plan.json", plan)
    v4.dump(args.out / "runtime_receipt.json", {**receipt, "hard_call_cap": CAP,
            "judge_prompt_sha256": sha256(JUDGE_PROMPT.encode()).hexdigest()})
    calls = Counter()
    first_prompt = prior["first"] + SUBJECT_RULE
    records, claims = claim_pass(v4, args, inputs, first_prompt, first_prompt + REPAIR_PROMPT + REPAIR_RULE, calls)
    verdicts = judge_pass(v4, args, records, visible, gold, plan, calls)
    with (args.out / OUTPUTS[0]).open("x", encoding="utf-8") as file:
        for qid, row in records.items():
            v4.emit(file, {"question": inputs[qid]["question"], **row})
    summary = {"questions": len(inputs), "trajectories": len(visible), "calls": dict(calls),
               "claims": dict(claims), "verdicts": dict(verdicts)}
    v4.dump(args.out / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
