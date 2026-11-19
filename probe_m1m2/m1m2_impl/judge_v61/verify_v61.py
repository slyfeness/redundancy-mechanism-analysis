"""Independently check v6.1 receipts and the exact public/private staged exports."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys

from pipeline import HARD, reconcile, usable_repair
from prepare import digest, read
from run_v61 import CAP, OUTPUTS, repair_targets, source_inputs, sources_for_judge
from sampling import sample_unknown
from judgement import JUDGE_PROMPT, check_verdicts
from bounded import excerpt

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("public_guard", HERE.parent / "check_public.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
guard.ALLOWED = re.compile(
    r"probe_m1m2/m1m2_impl/judge_v61/(?:COUNTS\.txt|pipeline\.py|prepare\.py|run_v61\.py|sampling\.py|test_v61\.py|verify_v61\.py)"
)


def rows(path):
    with path.open(encoding="utf-8") as file:
        yield from map(json.loads, file)


def index(data, key):
    records = {}
    for row in data:
        ident = key(row)
        if ident in records:
            raise ValueError("duplicate receipt identity")
        records[ident] = row
    return records


def replies(path):
    result = {}
    for row in rows(path):
        key = tuple(row["key"]) if isinstance(row["key"], list) else row["key"]
        assert key not in result, "duplicate model request"
        result[key] = None if row["error"] else json.loads(row["raw"]["choices"][0]["message"]["content"])
    return result


def verify(v4, args):
    out = args.out
    inputs, visible, gold, plan, _, prepared = source_inputs(v4, args)
    assert read(out / "plan.json") == plan, "sample differs from v6"
    assert read(out / "runtime_receipt.json") == {**prepared, "hard_call_cap": CAP,
        "judge_prompt_sha256": sha256(JUDGE_PROMPT.encode()).hexdigest()}
    first, repair, retry, judge = (replies(out / file) for file in
                                  ("assertion_raw.jsonl", "repair_raw.jsonl",
                                   "repair_retry_raw.jsonl", "judge_raw.jsonl"))
    assert first.keys() == inputs.keys()
    assert judge.keys() == {("gold", qid) for qid in gold} | {("trajectory", tid) for tid in visible}
    calls = sum(map(len, (first, repair, retry, judge)))
    assert calls <= CAP
    marks, jobs = repair_targets(inputs, first)
    assert repair.keys() == jobs.keys()
    assert retry.keys() == {qid for qid, value in repair.items() if not usable_repair(value)}

    actual = index(rows(out / OUTPUTS[0]), lambda r: r["query_id"])
    assert actual.keys() == inputs.keys()
    audit = defaultdict(list)
    for row in rows(out / OUTPUTS[2]):
        assert row.keys() == {"query_id", "phase", "slot", "reasons", "before", "after"}
        assert row["query_id"] in inputs
        if row["phase"] == "discard":
            assert row["reasons"] and set(row["reasons"]) <= HARD
        audit[row["query_id"]].append(row)
    gold_rows = index(rows(out / OUTPUTS[3]), lambda r: (r["query_id"], r["assertion_id"]))
    trajectories = index(rows(out / OUTPUTS[1]), lambda r: (r["trajectory_id"], r["assertion_id"]))
    seen_gold, seen_trajectory = set(), set()
    records, stats = {}, Counter(model_calls=calls, repair_retry=len(retry))
    for qid, body in inputs.items():
        response = retry.get(qid, repair.get(qid))
        exhausted = qid in repair and not usable_repair(response)
        stats["repair_exhausted"] += exhausted
        record, trail = reconcile(qid, body["question"], first[qid], marks[qid], response, exhausted=exhausted)
        assert all(event in audit[qid] for event in trail)
        for slot, reasons in marks[qid]["claims"].items():
            assert any(row["phase"] == "mark" and row["slot"] == slot and row["reasons"] == reasons
                       and row["before"] == first[qid]["conditions"][slot] for row in audit[qid])
        assert (qid in retry) == any(row["phase"] == "repair_retry" for row in audit[qid])
        dropped = [row for row in audit[qid] if row["phase"] == "discard"]
        if exhausted:
            assert not dropped
        stats["discarded_claims"] += len(dropped)
        conditions = record["conditions"]
        stats["assertions"] += len(conditions)
        decisions = check_verdicts(conditions, gold[qid], judge[("gold", qid)])
        for claim, decision in zip(conditions, decisions, strict=True):
            key = (qid, claim["id"])
            seen_gold.add(key)
            status = decision["status"]
            mark = status not in {"supported", "partial"}
            assert gold_rows[key] == {"query_id": qid, "assertion_id": claim["id"], "status": status,
                                     "reason": decision["reason"], "not_supported_by_gold": mark,
                                     "citations": sources_for_judge(decision, gold[qid], gold=True)}
            if mark:
                claim["flags"] = sorted(set(claim["flags"]) | {"not_supported_by_gold"})
                claim["gold_check_reason"] = decision["reason"]
                stats["not_supported_by_gold"] += 1
        assert actual[qid] == {"question": body["question"], **record}
        records[qid] = record
    assert seen_gold == gold_rows.keys(), "Gold coverage mismatch"

    all_verdicts = []
    for tid, passages in visible.items():
        record = records[plan["trajectory_question"][tid]]
        decisions = check_verdicts(record["conditions"], passages, judge[("trajectory", tid)])
        if not decisions:
            key = (tid, None)
            seen_trajectory.add(key)
            assert trajectories[key] == {"trajectory_id": tid, "assertion_id": None, "status": "unknown",
                "reason": "No assertion passed validation.", "unit_id": None, "citations": []}
        for decision in decisions:
            key = (tid, decision["id"])
            seen_trajectory.add(key)
            row = trajectories[key]
            assert row == {"trajectory_id": tid, "assertion_id": decision["id"], "status": decision["status"],
                           "reason": decision["reason"], "unit_id": decision["unit_id"],
                           "citations": sources_for_judge(decision, passages)}
            stats[row["status"]] += 1
            all_verdicts.append(row)
    assert seen_trajectory == trajectories.keys(), "trajectory coverage mismatch"
    review, eligible = sample_unknown(all_verdicts, plan["trajectory_question"], records, visible, excerpt)
    assert review == list(rows(out / OUTPUTS[4]))
    assert len(review) == min(eligible, 20)
    for sample in review:
        assert len({p["passage_id"] for p in sample["passages"]}) == 2
        assert not re.search(r"\bdifferent\s+entity\b", sample["reason"], re.I)
        assert all(len(p["before"].split()) <= 50 and len(p["after"].split()) <= 50 for p in sample["passages"])
    stats.update(unknown_sampled=len(review), unknown_eligible=eligible, gold_questions=len(gold),
                 trajectories=len(visible), verdict_rows=len(trajectories))
    summary = read(out / "summary.json")
    assert summary["calls"]["total"] == stats["model_calls"]
    assert summary["claims"]["assertions"] == stats["assertions"]
    assert summary["claims"].get("discard", 0) == stats["discarded_claims"]
    assert summary["verdicts"].get("gold_unknown", 0) == stats["not_supported_by_gold"]
    for key in ("supported", "partial", "unknown", "unknown_sampled", "unknown_eligible"):
        assert summary["verdicts"].get(key, 0) == stats[key]
    return inputs, visible, gold, dict(stats)


def privacy(manifest, root, out, inputs, visible, gold):
    grams, literals = defaultdict(set), defaultdict(set)
    for path, source in read(manifest).items():
        text = source["text"]
        assert guard.ALLOWED.fullmatch(path) and not guard.SECRET.search(text)
        assert sha256(text.encode()).hexdigest() == source["sha256"]
        for gram in guard.shingles(guard.words(text), 9):
            grams[gram].add(path)
        for literal in guard.literals(path, text):
            if len(literal) > 1:
                literals[literal].add(path)
    flagged = defaultdict(set)

    def scan(label, value):
        if not isinstance(value, str):
            return
        words = guard.words(value)
        for path in literals.get(tuple(words), ()):
            flagged[path].add(label)
        for gram in guard.shingles(words, 9):
            for path in grams.get(gram, ()):
                flagged[path].add(label)

    for row in inputs.values():
        scan("question", row["question"])
        answers = row["reference_answers"]
        for answer in [answers] if isinstance(answers, str) else answers:
            scan("reference", answer)
    documents = {p["docid"]: p["text"] for pp in gold.values() for p in pp}
    for text in documents.values():
        scan("labelled_source", text)
    for ref in rows(root / "supplement-m1-192125/rollouts_ref.jsonl"):
        if ref["trajectory_id"] not in visible:
            continue
        assert digest(Path(ref["path"])) == ref["sha256"]
        trace = read(Path(ref["path"]))
        for turn in trace["rounds"]:
            scan("actor_text", turn.get("content"))
            scan("actor_text", turn.get("reasoning"))
        for item in trace["tool_events"]:
            scan("tool_return", item["exact_result"])

    def texts(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from texts(item)
        elif isinstance(value, dict):
            assert not {"reference_answers", "evidence_documents", "raw_response"} & value.keys()
            for key, item in value.items():
                if key not in {"flags", "reasons", "phase", "id", "assertion_id", "sentence_id", "passage_id",
                                "trajectory_id", "query_id", "subject", "status", "type", "labels", "docid"}:
                    yield from texts(item)

    code_reasons = {"different entity", "invalid or missing judge verdict", "No assertion passed validation."}
    hashes = {}
    for name in OUTPUTS:
        path = out / name
        assert not guard.SECRET.search(path.read_text(encoding="utf-8"))
        for row in rows(path):
            for value in texts(row):
                if value not in code_reasons:
                    scan(name, value)
                if len(value) >= 300:
                    assert not any(len(doc) >= 300 and doc.strip() in value for doc in documents.values())
        hashes[name] = digest(path)
    return hashes, {path: sorted(kinds) for path, kinds in flagged.items()}


def main():
    parser = ArgumentParser()
    parser.add_argument("mode", choices=("staged", "verify"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--v4-control", type=Path)
    args = parser.parse_args()
    if args.mode == "staged":
        guard.staged(args.manifest)
        return 0
    sys.path.insert(0, str(args.v4_control / "judge_v4"))
    import pilot as v4
    inputs, visible, gold, stats = verify(v4, args)
    hashes, flags = privacy(args.manifest, args.root, args.out, inputs, visible, gold)
    print(json.dumps({"manifest_sha256": digest(args.manifest), "flagged_paths": flags,
                      "private_sha256": hashes, "stats": stats,
                      "judge_prompt_sha256": sha256(JUDGE_PROMPT.encode()).hexdigest()}), flush=True)
    return bool(flags)


if __name__ == "__main__":
    sys.exit(main())
