"""Verify the v6 pilot, both exports, and the exact code staged for publication."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

from claims import CLAIM_FIELDS, ENTITY_FIELDS, RECORD_FIELDS, claim_flags, inspect, reconcile
from judgement import check_verdicts
from run_v6 import CAP, load
from bounded import excerpt

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("public_guard", HERE.parent / "check_public.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
guard.ALLOWED = re.compile(
    r"probe_m1m2/m1m2_impl/judge_v6/(?:claims\.py|judgement\.py|run_v6\.py|verify_v6\.py|test_v6\.py|COUNTS\.txt)"
)
REVIEW_FILES = ("claims_v6.jsonl", "verdicts_v6.jsonl", "rejected_v6.jsonl")
VERDICT_FIELDS = {"trajectory_id", "assertion_id", "status", "reason", "unit_id", "citations"}
AUDIT_FIELDS = {"query_id", "phase", "slot", "reasons", "before", "after"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def rows(path):
    with path.open(encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def get_replies(path):
    replies = {}
    for row in rows(path):
        key = row["key"]
        if key in replies:
            raise ValueError("duplicate request")
        replies[key] = None
        if row["error"] is None:
            replies[key] = json.loads(row["raw"]["choices"][0]["message"]["content"])
    return replies


def indexed(records, key):
    source = list(records)
    result = {row[key]: row for row in source}
    if len(result) != len(source):
        raise ValueError(f"duplicate {key}")
    return result


def review_check(out, inputs, visible, plan):
    assert read(out / "plan.json") == plan, "frozen plan drift"
    initial = get_replies(out / "assertion_raw.jsonl")
    repaired = get_replies(out / "repair_raw.jsonl")
    judged = get_replies(out / "judge_raw.jsonl")
    assert set(initial) == set(inputs) and set(judged) == set(visible)
    assert len(initial) + len(repaired) + len(judged) <= min(CAP, plan["max_model_calls"])
    accepted = indexed(rows(out / REVIEW_FILES[0]), "query_id")
    audit = defaultdict(list)
    for row in rows(out / REVIEW_FILES[2]):
        assert row.keys() == AUDIT_FIELDS and row["query_id"] in inputs
        audit[row["query_id"]].append(row)
    assert accepted.keys() == inputs.keys()
    stats = Counter()
    for qid, body in inputs.items():
        marks = inspect(qid, body["question"], initial[qid])
        assert (qid in repaired) == bool(marks["record"] or marks["claims"])
        record, expected = reconcile(qid, body["question"], initial[qid], marks, repaired.get(qid))
        assert accepted[qid] == {"question": body["question"], **record}
        actual = audit[qid]
        for slot, reasons in marks["claims"].items():
            assert any(row["phase"] == "mark" and row["slot"] == slot and row["reasons"] == reasons
                       and row["before"] == initial[qid]["conditions"][slot] for row in actual)
        if marks["record"]:
            assert any(row["phase"] == "mark_record" and row["reasons"] == marks["record"] for row in actual)
        assert all(row in actual for row in expected)
        # Independent checks on the accepted export and preservation of unmarked rows.
        assert set(record) == RECORD_FIELDS and len(record["conditions"]) <= 10
        entities = indexed(record["entities"], "var")
        assert all(e.keys() == ENTITY_FIELDS for e in entities.values())
        assert len(indexed(record["conditions"], "id")) == len(record["conditions"])
        for condition in record["conditions"]:
            assert condition.keys() == CLAIM_FIELDS
            assert not claim_flags(body["question"], entities, condition)
        if isinstance(initial[qid], dict) and isinstance(initial[qid].get("conditions"), list):
            for slot, condition in enumerate(initial[qid]["conditions"]):
                if slot not in marks["claims"]:
                    assert condition in record["conditions"], "unmarked claim changed"
        stats["claims"] += len(record["conditions"])
        stats["under_two"] += len(record["conditions"]) < 2
        stats["discarded"] += sum(row["phase"] == "discard" for row in actual)

    expected = {}
    for tid, passages in visible.items():
        conditions = accepted[plan["trajectory_question"][tid]]["conditions"]
        decisions = check_verdicts(conditions, passages, judged[tid])
        expected[tid] = {r["id"]: r for r in decisions} if decisions else {None: None}
    seen = set()
    for row in rows(out / REVIEW_FILES[1]):
        assert row.keys() == VERDICT_FIELDS
        tid, cid = row["trajectory_id"], row["assertion_id"]
        assert (tid, cid) not in seen and cid in expected[tid], "duplicate or unexpected verdict"
        seen.add((tid, cid))
        decision = expected[tid][cid]
        if decision is None:
            assert row["status"] == "unknown" and row["unit_id"] is None and not row["citations"]
            continue
        assert (row["status"], row["reason"], row["unit_id"]) == (
            decision["status"], decision["reason"], decision["unit_id"])
        by_passage = {p["id"]: p for p in visible[tid]}
        for citation, (pid, sentence) in zip(row["citations"], decision["sentences"], strict=True):
            passage = by_passage[pid]
            assert citation == {**excerpt(passage["text"], sentence), "passage_id": pid,
                                "unit_id": passage["unit_id"]}
            assert len(citation["before"].split()) <= 50 and len(citation["after"].split()) <= 50
        if row["status"] != "unknown":
            assert 1 <= len(row["citations"]) <= 4
            assert 1 <= len({c["passage_id"] for c in row["citations"]}) <= 2
            assert row["unit_id"] == max(c["unit_id"] for c in row["citations"])
        stats[row["status"]] += 1
        stats["invalid_verdicts"] += not decision["valid"]
        stats["two_passage_supported"] += row["status"] == "supported" and decision["passage_count"] == 2
    assert seen == {(tid, cid) for tid, decisions in expected.items() for cid in decisions}
    stats.update({"model_calls": len(initial) + len(repaired) + len(judged), "assertion_rows": len(accepted),
                  "trajectory_rows": len(visible), "decision_rows": len(seen), "repair_calls": len(repaired)})
    summary = read(out / "summary.json")
    assert summary["calls"]["total"] == stats["model_calls"]
    assert summary["claims"]["assertions"] == stats["claims"]
    assert summary["claims"].get("discard", 0) == stats["discarded"]
    for field in ("supported", "partial", "unknown", "invalid_verdicts", "two_passage_supported"):
        assert summary["verdicts"].get(field, 0) == stats[field]
    return dict(stats)


def privacy(manifest, root, out, inputs, visible):
    grams, literals = defaultdict(set), defaultdict(set)
    for path, source in read(manifest).items():
        body = source["text"]
        assert guard.ALLOWED.fullmatch(path) and not guard.SECRET.search(body)
        assert hashlib.sha256(body.encode()).hexdigest() == source["sha256"]
        for gram in guard.shingles(guard.words(body), 9):
            grams[gram].add(path)
        for value in guard.literals(path, body):
            if len(value) >= 2:
                literals[value].add(path)
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

    private_examples = read(HERE.parent / "prompts_private.json")
    for entry in private_examples.values():
        for example in entry if isinstance(entry, list) else [entry]:
            scan("private_prompt_example", example)
    documents = []
    for body in inputs.values():
        scan("question", body["question"])
        answers = body["reference_answers"]
        for answer in [answers] if isinstance(answers, str) else answers:
            scan("reference", answer)
        for document in body["evidence_documents"]:
            scan("source_document", document["text"])
            documents.append(document["text"])
    for ref in rows(root / "supplement-m1-192125/rollouts_ref.jsonl"):
        if ref["trajectory_id"] not in visible:
            continue
        blob = Path(ref["path"]).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == ref["sha256"]
        trace = json.loads(blob)
        for turn in trace["rounds"]:
            scan("actor_text", turn.get("content"))
            scan("actor_text", turn.get("reasoning"))
        for item in trace["tool_events"]:
            scan("tool_return", item["exact_result"])

    def value_texts(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            assert not {"reference_answers", "evidence_documents", "raw_response"} & value.keys()
            for item in value.values():
                yield from value_texts(item)
        elif isinstance(value, list):
            for item in value:
                yield from value_texts(item)

    fallback = {"invalid or missing judge verdict", "No assertion passed validation.", "different entity"}
    hashes = {}
    for name in REVIEW_FILES:
        path = out / name
        raw = path.read_text(encoding="utf-8")
        assert not guard.SECRET.search(raw)
        for row in rows(path):
            if name == "rejected_v6.jsonl":
                content = [row["before"], row["after"]]
            elif name == "verdicts_v6.jsonl":
                # Sentence IDs and unit coordinates were already independently verified.
                content = [row["reason"], *[citation[key] for citation in row["citations"]
                                            for key in ("text", "before", "after")]]
            else:
                content = row
            for item in value_texts(content):
                if item not in fallback:
                    scan(name, item)
                if len(item) >= 300:
                    assert not any(len(document) >= 300 and document.strip() in item for document in documents)
        hashes[name] = digest(path)
    return hashes, {path: sorted(labels) for path, labels in flagged.items()}


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
    inputs, visible, plan = load(v4, args.root)
    stats = review_check(args.out, inputs, visible, plan)
    hashes, flags = privacy(args.manifest, args.root, args.out, inputs, visible)
    if not flags:
        freeze = {"model": "gpt-oss-120b", "plan_sha256": digest(args.out / "plan.json"),
                  "private_prompts_sha256": digest(args.out / "private_prompts.json"),
                  "sources_sha256": {name: digest(HERE / name)
                                     for name in ("claims.py", "judgement.py", "run_v6.py")},
                  "private_sha256": hashes, "acceptance": stats}
        path = args.out / "FROZEN.json"
        if path.exists():
            assert read(path) == freeze
        else:
            v4.dump(path, freeze)
    print(json.dumps({"manifest_sha256": digest(args.manifest), "flagged_paths": flags,
                      "private_sha256": hashes, "stats": stats, "frozen": not flags}), flush=True)
    return bool(flags)


if __name__ == "__main__":
    sys.exit(main())
