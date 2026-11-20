"""Replay the sealed v6.1 generation artifacts and Judge only restored claims."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if (HERE.parent / "m2_v61_full").is_dir():
    sys.path.append(str(HERE.parent / "m2_v61_full"))

from context import Budget, Ranking
from embed import dump
from prepare_full import read
from rules import cleanup
from run_full import emit, frozen, gold_plan, judge_gold, loading


def rows(path):
    with path.open(encoding="utf-8") as data:
        yield from (json.loads(line) for line in data)


def cleanup_replayed(qid, question, source, previous):
    conditions = source["conditions"]
    by_id = {row["id"]: row for row in previous["conditions"]}
    old, old_audit = cleanup(qid, source, question["answers"])
    if old != previous:
        raise ValueError("sealed v6.1 cleanup did not reproduce")
    candidates = {row["assertion_id"] for row in old_audit if row["reason"] == "answer_in_subject"}
    preferred = sorted(conditions, key=lambda row: row["id"] not in by_id)
    new, audit = cleanup(qid, {**source, "conditions": preferred}, question["answers"], drop_answer_subject=False)
    actual = {row["id"]: row for row in new["conditions"]}
    if any(actual.get(cid) != row for cid, row in by_id.items()) or actual.keys() - by_id.keys() - candidates:
        raise ValueError("the correction changed an existing claim or restored a non-candidate")
    restored = actual.keys() - by_id.keys()
    remaining = {row["assertion_id"]: row["reason"] for row in audit if row["action"] == "drop"
                 and row["assertion_id"] in candidates}
    if set(remaining) != candidates - restored:
        raise ValueError("a historical subject deletion was not accounted for")
    new["conditions"] = [actual[row["id"]] for row in conditions if row["id"] in actual]
    return new, sorted(restored), remaining, old_audit, audit


def replay(args, old, questions):
    previous = read(args.prior / "records.json")
    previous_cleanup = defaultdict(list)
    for row in rows(args.prior / "cleanup.jsonl"):
        previous_cleanup[row["query_id"]].append(row)
    if questions.keys() != previous.keys():
        raise ValueError("historical claim question coverage changed")
    records, delta, all_audit = {}, {}, []
    candidates, rejected = 0, Counter()
    for qid, question in questions.items():
        original = read(args.prior / "assertions" / f"{qid}.json")["parsed"]
        path = args.prior / "repairs" / f"{qid}.json"
        marked = old.inspect(qid, question["question"], original)
        needed = bool(marked["claims"] or marked["record"])
        if needed != path.exists():
            raise ValueError("missing or unexpected sealed repair receipt")
        repair = read(path)["attempts"][-1]["parsed"] if needed else None
        record, _ = old.reconcile(qid, question["question"], original, marked, repair,
                                  exhausted=needed and not old.usable_repair(repair))
        updated, restored, blocked, historical, audit = cleanup_replayed(qid, question, record, previous[qid])
        if historical != previous_cleanup[qid]:
            raise ValueError("historical deletion receipt changed")
        records[qid] = updated
        if restored:
            new_ids = set(restored)
            delta[qid] = {**updated, "conditions": [c for c in updated["conditions"] if c["id"] in new_ids]}
        candidates += len(restored) + len(blocked)
        rejected.update(blocked.values())
        all_audit.extend(audit)
    if candidates != 1105 or sum(len(r["conditions"]) for r in previous.values()) != 2162 or not delta:
        raise ValueError("sealed restoration population mismatch")
    dump(args.out / "records.json", records)
    dump(args.out / "delta.json", delta)
    emit(args.out / "cleanup.jsonl", all_audit)
    counts = {"train": len(records), "heldout_decoded": 0, "subject_only_recovered": candidates,
              "restored": sum(len(record["conditions"]) for record in delta.values()),
              "still_filtered": dict(rejected), "changed_questions": len(delta),
              "usable_before": sum(len(r["conditions"]) >= 2 for r in previous.values()),
              "usable_after": sum(len(r["conditions"]) >= 2 for r in records.values()), "generation_calls": 0}
    print(json.dumps(counts), flush=True)
    dump(args.out / "restoration_counts.json", counts)


def main():
    parser = ArgumentParser()
    parser.add_argument("phase", choices=("replay", "judge"))
    for name in ("root", "prep", "embedding", "v4", "v6", "v61", "out", "model", "prior"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--url")
    args = parser.parse_args()
    old, pipeline, prepare, v4, first, repair = frozen(args)
    if read(args.out / "fingerprints.json") != read(args.prior / "fingerprints.json"):
        raise ValueError("frozen v6.1 Judge or generation source differs from the previous run")
    questions, docs, receipt = loading(args)
    budget = Budget(args.model)
    if args.phase == "replay":
        replay(args, old, questions)
        delta = read(args.out / "delta.json")
        gold_plan(args, {qid: questions[qid] for qid in delta}, docs, delta, pipeline, prepare, v4, old, budget)
    else:
        v4.previous_driver.check_service(args.url)
        from settle_fix import settle
        delta = read(args.out / "delta.json")
        gold = judge_gold(args, {qid: questions[qid] for qid in delta}, docs, delta, old, pipeline, prepare, v4,
                          budget, Ranking(args.embedding))
        settle(args, questions, receipt, delta, gold, old, pipeline, v4)


if __name__ == "__main__":
    main()
