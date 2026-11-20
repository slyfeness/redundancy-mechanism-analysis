"""Verify the exact public payload and the two authorized private JSONL exports."""

from argparse import ArgumentParser
import ast
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from probe import after, rows
from flags import mark
from prepare_full import read
from publish_check import SECRET, grams, public_stage, words

PUBLIC_DIR = "probe_m1m2/m1m2_impl/fpremise_probe/"
PUBLIC = {PUBLIC_DIR + leaf for leaf in ("REPORT.md", "probe.py", "flags.py", "test_flags.py",
                                        "run.sbatch", "audit_probe.py")}
PRIVATE = {"timeline.jsonl": {"trajectory_id", "stage_id", "query", "role", "candidate", "match",
                             "F_new", "F_corrected", "C_new", "outcome"},
           "events.jsonl": {"trajectory_id", "role", "candidate", "correct_name", "stage_id",
                            "consecutive_queries", "corrected", "correction_stage_id", "C_new_after_correction"}}


def check_private():
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(names) - {""} != {"fpremise_probe/" + leaf for leaf in PRIVATE}:
        raise ValueError("unexpected private changes")
    hashes, counts = {}, {}
    for leaf, fields in PRIVATE.items():
        raw = subprocess.check_output(["git", "show", f":fpremise_probe/{leaf}"])
        text = raw.decode("utf-8")
        if "\0" in text or SECRET.search(text):
            raise ValueError("private credential scan failed")
        parsed = [json.loads(line) for line in text.splitlines()]
        if any(set(row) != fields for row in parsed):
            raise ValueError("unexpected private review fields")
        hashes[leaf], counts[leaf] = sha256(raw).hexdigest(), len(parsed)
    print(json.dumps({"private": counts, "sha256": hashes, "credential_matches": 0}))


def verify_exports(work, plan, summary):
    timeline = defaultdict(list)
    directory = work / "fpremise_probe"
    for row in rows(directory / "timeline.jsonl"):
        timeline[row["trajectory_id"]].append(row)
    events = defaultdict(list)
    for row in rows(directory / "events.jsonl"):
        events[row["trajectory_id"]].append(row)
    assert timeline.keys() == plan.keys() and events.keys() <= plan.keys()
    tags = Counter()
    for tid, tr in plan.items():
        classified = {q["id"]: q for q in read(work / "judge" / f"{tid}.json")["classifications"]}
        query = {r["id"]: r["text"] for r in tr["queries"]}
        ordered = []
        for actual, stage in zip(timeline[tid], tr["stages"], strict=True):
            sid = stage["stage_id"]
            assert (actual["stage_id"], actual["C_new"], actual["outcome"]) == (sid, stage["C_new"], tr["outcome"])
            candidates = []
            for qid in stage["search_ids"]:
                verdict = classified.get(qid, {"role": None, "candidate": None, "match": "invalid"})
                tags[verdict["match"]] += 1
                candidates.append({"stage_id": sid, "query": query[qid],
                                   **{key: verdict[key] for key in ("role", "candidate", "match")}})
            for key in ("query", "role", "candidate", "match"):
                expected = [item[key] for item in candidates]
                assert actual[key] == (expected if len(expected) > 1 else expected[0] if expected else None)
            ordered.extend(candidates)
        names = {row["var"]: row["name"] for row in tr["entities"]}
        expected = [{"trajectory_id": tid, **event,
                     "C_new_after_correction": after(tr["stages"], event["correction_stage_id"])
                     if event["corrected"] else None} for event in mark(ordered, names)]
        assert events[tid] == expected
        assert {row["stage_id"] for row in timeline[tid] if row["F_new"]} == {r["stage_id"] for r in expected}
        assert {row["stage_id"] for row in timeline[tid] if row["F_corrected"]} == {
            r["correction_stage_id"] for r in expected if r["corrected"]}
    assert sum(map(len, timeline.values())) == summary["stages"]
    assert sum(map(len, events.values())) == summary["events"]
    assert sum(tags.values()) == sum(len(x["queries"]) for x in plan.values())
    return {leaf: sha256((directory / leaf).read_bytes()).hexdigest() for leaf in PRIVATE}


def compare(manifest, work):
    plan, summary = (read(work / name) for name in ("plan.json", "SUMMARY.json"))
    assert len(plan) == 40 and len({row["question_id"] for row in plan.values()}) == 10
    sealed = read(work / "selection_counts.json")
    assert sealed["heldout_decoded"] == sealed["psi"] == 0
    calls = sum(len(read(work / "judge" / f"{tid}.json")["attempts"]) for tid in plan)
    assert 40 <= calls <= 80 and calls == summary["calls"]
    paths = read(manifest)
    if paths.keys() != PUBLIC:
        raise ValueError("unexpected public file inventory")
    matches, literal = set(), set()
    for name, item in paths.items():
        body = item["text"]
        if sha256(body.encode()).hexdigest() != item["sha256"] or SECRET.search(body):
            raise ValueError("public content fails verification")
        matches.update(grams(body))
        if name.endswith(".py"):
            literal.update(tuple(words(tok.value)) for tok in ast.walk(ast.parse(body))
                           if isinstance(tok, ast.Constant) and isinstance(tok.value, str))
    for row in plan.values():
        protected = [row["problem"]] + [q["text"] for q in row["queries"]]
        protected.extend(e[k] for e in row["entities"] for k in ("name", "role"))
        for value in protected:
            if matches.intersection(grams(value)) or (len(words(value)) >= 3 and tuple(words(value)) in literal):
                raise ValueError("protected source text found in public code or report")
    report = paths[PUBLIC_DIR + "REPORT.md"]["text"]
    if report != (work / "REPORT.md").read_text(encoding="utf-8") or len(report.splitlines()) > 15:
        raise ValueError("public report differs from numeric output or exceeds its line allowance")
    print(json.dumps({"receipt": "PASS", "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
                      "calls": calls, "sha256": verify_exports(work, plan, summary),
                      "public_files": len(paths), "report_lines": len(report.splitlines())}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("public").add_argument("manifest", type=Path)
    compare_cmd = sub.add_parser("compare")
    compare_cmd.add_argument("manifest", type=Path)
    compare_cmd.add_argument("work", type=Path)
    sub.add_parser("private")
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    elif args.mode == "private":
        check_private()
    else:
        compare(args.manifest, args.work)


if __name__ == "__main__":
    main()
