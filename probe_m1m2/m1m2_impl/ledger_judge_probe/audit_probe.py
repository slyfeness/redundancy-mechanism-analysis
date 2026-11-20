"""Check causal input structure, reconstructed outputs and publication boundaries."""

from argparse import ArgumentParser
import ast
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from runner import tally
from checks import validate
from prepare_full import read
from publish_check import SECRET, grams, public_stage, words

DIRECTORY = "probe_m1m2/m1m2_impl/ledger_judge_probe/"
PUBLIC = {DIRECTORY + leaf for leaf in ("REPORT.md", "runner.py", "prepare.py", "checks.py",
                                       "test_checks.py", "run.sbatch", "audit_probe.py")}
PRIVATE = "ledger_judge_probe/stages.jsonl"
FIELDS = {"trajectory_id", "stage_id", "direction", "repeat", "target", "evidence", "searches", "C_new",
          "outcome", "program_strict_repeat", "judge_valid", "F_new", "F_corrected", "correction_stage_id"}


def private():
    paths = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(paths) - {""} != {PRIVATE}:
        raise ValueError("unexpected private staged files")
    data = subprocess.check_output(["git", "show", f":{PRIVATE}"])
    text = data.decode("utf-8")
    if "\0" in text or SECRET.search(text):
        raise ValueError("private credential scan failed")
    rows = [json.loads(line) for line in text.splitlines()]
    if len(rows) != 430 or len({(r["trajectory_id"], r["stage_id"]) for r in rows}) != 430:
        raise ValueError("expected 430 unique private Stage rows")
    for row in rows:
        if set(row) != FIELDS or set(row["evidence"]) != {"quote", "refs", "reason", "prior_search_id"}:
            raise ValueError("unexpected private fields")
        if row["evidence"]["quote"] and len(row["evidence"]["quote"].split()) > 40:
            raise ValueError("private quote exceeds the evidence bound")
    print(json.dumps({"private_rows": len(rows), "sha256": sha256(data).hexdigest(), "credential_matches": 0}))


def verify(work, plan, replies, prior, summary):
    assert plan.keys() == prior.keys() and len(plan) == 40
    staged, groups, counts, agreement = tally(plan, replies)
    assert groups == summary["groups"] and counts == summary["labels"] and agreement == summary["agreement"]
    actual = (work / PRIVATE).read_bytes()
    assert [json.loads(line) for line in actual.splitlines()] == staged
    assert len(staged) == summary["stages"] == 430
    calls = sum(len(v["attempts"]) for v in replies.values())
    assert 40 <= calls <= 80 and calls == summary["calls"]
    assert summary["prep"]["psi"] == summary["prep"]["heldout_decoded"] == 0
    queries = 0
    for tid, item in plan.items():
        payload = item["payload"]
        previous = prior[tid]
        assert payload.keys() == {"question", "entities", "stages"}
        assert (payload["question"], payload["entities"], item["outcome"], item["question_id"]) == (
            previous["problem"], previous["entities"], previous["outcome"], previous["question_id"])
        searches, strict = [], []
        stages = {row["stage_id"]: row for row in payload["stages"]}
        names = {r["var"]: r["name"] for r in payload["entities"]}
        for stage, earlier in zip(payload["stages"], previous["stages"], strict=True):
            sid = stage["stage_id"]
            pre = stage["pre"]
            assert set(stage) == {"stage_id", "pre", "thought_tail", "searches"}
            assert pre.keys() == {"conditions", "searches", "strict_repeats"}
            assert all(row["stage_id"] < sid for entries in pre.values() for row in entries)
            assert [entry["query"] for entry in pre["searches"]] == searches
            assert [entry["stage_id"] for entry in pre["strict_repeats"]] == strict
            assert all(set(hit) == {"title", "docid"} for entry in pre["searches"] for hit in entry["returns"])
            assert item["metrics"][str(sid)]["C_new"] == earlier["C_new"]
            offset = len(searches)
            searches.extend(stage["searches"])
            assert [r["text"] for r in previous["queries"][offset:len(searches)]] == stage["searches"]
            if item["metrics"][str(sid)]["program_strict_repeat"]:
                strict.append(sid)
        queries += len(searches)
        assert len(searches) == len(previous["queries"])
        assert all(validate(row, stages[row["stage_id"]], names) for row in replies[tid]["verdicts"])
    assert queries == 464
    return sha256(actual).hexdigest(), calls


def compare(manifest, work, prior):
    plan, summary = (read(work / name) for name in ("plan.json", "SUMMARY.json"))
    replies = {tid: read(work / "judge" / f"{tid}.json") for tid in plan}
    private_sha, calls = verify(work, plan, replies, read(prior / "plan.json"), summary)
    files = read(manifest)
    if files.keys() != PUBLIC:
        raise ValueError("unexpected public file inventory")
    tokens, literals = set(), set()
    for filename, row in files.items():
        text = row["text"]
        if sha256(text.encode()).hexdigest() != row["sha256"] or SECRET.search(text):
            raise ValueError("public staged file changed")
        tokens.update(grams(text))
        if filename.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(text))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    for item in plan.values():
        payload = item["payload"]
        protected = [payload["question"]]
        protected.extend(entity[k] for entity in payload["entities"] for k in ("name", "role"))
        for step in payload["stages"]:
            protected.extend(step["searches"])
            protected.append(step["thought_tail"])
        for value in protected:
            if tokens.intersection(grams(value)) or (len(words(value)) >= 3 and tuple(words(value)) in literals):
                raise ValueError("protected source text found in public output")
    report = files[DIRECTORY + "REPORT.md"]["text"]
    if report != (work / "REPORT.md").read_text(encoding="utf-8"):
        raise ValueError("public report differs from the verified count report")
    print(json.dumps({"receipt": "PASS", "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
                      "private_sha256": private_sha, "calls": calls, "stages": summary["stages"],
                      "public_files": len(files)}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("public").add_argument("manifest", type=Path)
    sub.add_parser("private")
    both = sub.add_parser("compare")
    for arg in ("manifest", "work", "prior"):
        both.add_argument(arg, type=Path)
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    elif args.mode == "private":
        private()
    else:
        compare(args.manifest, args.work, args.prior)


if __name__ == "__main__":
    main()
