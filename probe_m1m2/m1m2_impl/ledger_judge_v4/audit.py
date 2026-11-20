"""Audit reproducible causality, request isolation, and staged publication bytes."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from probe_v4 import CAP, EXPECTED, evaluate, report, scope
from prepare_full import read
from publish_check import SECRET, grams, public_stage, words

DIRECTORY = "probe_m1m2/m1m2_impl/ledger_judge_v4/"
PUBLIC = {DIRECTORY + leaf for leaf in ("REPORT.md", "probe_v4.py", "program.py", "test_ledger.py", "run.sbatch", "audit.py")}
PRIVATE = {"stages": {"trajectory_id", "stage_id", "searches", "input_tokens", "items", "C_new",
                     "judge_raw", "first_invalid", "ledger_after", "labels", "semantic_repeat_distances", "outcome"},
           "events": {"trajectory_id", "event", "stage_id", "var", "type", "wrong_name", "correct_name", "first_stage",
                      "confirmation_stage", "key", "search_window"},
           "alias_checks": {"id", "names", "result", "attempts"},
           "entity_types": {"question_id", "entities", "attempts"}}


def decode(raw):
    return [json.loads(line) for line in raw.splitlines()]


def scan_private():
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    assert set(names) - {""} == {f"ledger_judge_v4/{name}.jsonl" for name in PRIVATE}
    hashes = {}
    for name, fields in PRIVATE.items():
        body = subprocess.check_output(["git", "show", f":ledger_judge_v4/{name}.jsonl"])
        if b"\0" in body or SECRET.search(body.decode("utf-8")):
            raise ValueError("private credential scan flagged a staged file")
        rows = decode(body)
        assert all(row.keys() == fields for row in rows)
        if name == "stages":
            assert len(rows) == EXPECTED
            assert len({(row["trajectory_id"], row["stage_id"]) for row in rows}) == EXPECTED
            assert all(row["labels"] == {"invalid": True} for row in rows if row["labels"]["invalid"])
        elif name == "entity_types":
            assert len(rows) == 10 and len({row["question_id"] for row in rows}) == 10
        hashes[name] = sha256(body).hexdigest()
    print(json.dumps({"private_sha256": hashes, "credential_matches": 0}))


def compare(args):
    from transformers import AutoTokenizer
    from probe_v4 import title_cases

    selection = scope(args)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, model_max_length=131072)
    args.replay, args.out, args.url = True, args.work, None
    hashes = {}
    stages, events, aliases, entities, calls = evaluate(args, selection, tokenizer)
    for kind, rebuilt in zip(PRIVATE, (stages, events, aliases, entities), strict=True):
        raw = (args.work / "ledger_judge_v4" / f"{kind}.jsonl").read_bytes()
        assert decode(raw) == rebuilt
        hashes[kind] = sha256(raw).hexdigest()
    physical = sum(log.read_text(encoding="utf-8", errors="replace").count("POST /v1/chat/completions")
                   for log in args.work.glob("server-*.log"))
    assert len(list((args.work/"requests").rglob("*.json"))) == sum(calls.values()) == physical <= CAP
    check = args.work / "release_check"
    check.mkdir(mode=0o700, exist_ok=True)
    report(check, stages, events, aliases, entities, calls)
    assert read(check/"SUMMARY.json") == read(args.work/"SUMMARY.json")
    assert (check/"REPORT.md").read_bytes() == (args.work/"REPORT.md").read_bytes()
    manifest = read(args.manifest)
    assert manifest.keys() == PUBLIC
    protected, known, lines = set(), set(), set()
    for item in selection.values():
        task = item["track"]["payload"]
        protected.add(task["question"])
        protected.update(e[k] for e in task["entities"] for k in ("name", "role"))
        protected.update(c["claim"] for c in item["claims"])
        for step in task["stages"]:
            protected.update(step["searches"])
            protected.add(step["thought_tail"])
    for path, item in manifest.items():
        text = item["text"]
        assert sha256(text.encode()).hexdigest() == item["sha256"] and not SECRET.search(text)
        known.update(grams(text))
        if path.endswith(".py"):
            lines.update(tuple(words(node.value)) for node in ast.walk(ast.parse(text))
                         if isinstance(node, ast.Constant) and isinstance(node.value, str))
    if any(known.intersection(grams(value)) or (len(words(value)) >= 3 and tuple(words(value)) in lines)
           for value in protected):
        raise ValueError("protected task text matched staged publication")
    assert manifest[DIRECTORY+"REPORT.md"]["text"] == (args.work/"REPORT.md").read_text(encoding="utf-8")
    assert len(manifest[DIRECTORY+"REPORT.md"]["text"].splitlines()) <= 25
    assert len(title_cases(selection)) == 10
    print(json.dumps({"audit": "PASS", "calls": physical, "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(),
                      "private_sha256": hashes}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("private")
    sub.add_parser("public").add_argument("manifest", type=Path)
    check = sub.add_parser("compare")
    for name in ("manifest", "work", "previous", "fixed", "prep", "model"):
        check.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.mode == "private":
        scan_private()
    elif args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    else:
        compare(args)


if __name__ == "__main__":
    main()
