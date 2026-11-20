"""Replay V4.1 without inference and verify both publication payloads."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from probe_v41 import CAP, evaluate, report
import probe_v4 as v4
from prepare_full import read
from publish_check import SECRET, grams, public_stage, words

DIRECTORY = "probe_m1m2/m1m2_impl/ledger_judge_v41/"
PUBLIC = {DIRECTORY + leaf for leaf in ("REPORT.md", "probe_v41.py", "matcher.py", "test_match.py", "run.sbatch", "audit.py")}
PRIVATE = {"stages": {"trajectory_id", "stage_id", "searches", "input_tokens", "items", "C_new",
                       "judge_raw", "first_invalid", "ledger_after", "labels", "semantic_repeat_distances", "outcome"},
           "events": {"trajectory_id", "event", "stage_id", "var", "type", "wrong_name", "correct_name",
                      "first_stage", "confirmation_stage", "key", "search_window", "attribution_scope"},
           "alias_checks": {"id", "names", "result", "attempts", "provenance"},
           "entity_types": {"question_id", "entities", "attempts"},
           "entity_types_v41": {"question_id", "entities", "generation_receipts", "validation_receipts"}}


def decode(raw):
    return [json.loads(line) for line in raw.splitlines()]


def scan_private():
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    assert set(names) - {""} == {f"ledger_judge_v41/{name}.jsonl" for name in PRIVATE}
    hashes = {}
    for name, fields in PRIVATE.items():
        body = subprocess.check_output(["git", "show", f":ledger_judge_v41/{name}.jsonl"])
        if b"\0" in body or SECRET.search(body.decode("utf-8")):
            raise ValueError("private credential scan flagged a staged file")
        rows = decode(body)
        assert all(row.keys() == fields for row in rows)
        if name == "stages":
            assert len(rows) == v4.EXPECTED and len({(r["trajectory_id"], r["stage_id"]) for r in rows}) == v4.EXPECTED
            assert all(row["labels"] == {"invalid": True} for row in rows if row["labels"]["invalid"])
        elif name in ("entity_types", "entity_types_v41"):
            assert len(rows) == 10 and len({row["question_id"] for row in rows}) == 10
        hashes[name] = sha256(body).hexdigest()
    print(json.dumps({"private_sha256": hashes, "credential_matches": 0}))


def compare(args):
    from transformers import AutoTokenizer

    selection = v4.scope(args)
    tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True, model_max_length=131072)
    args.replay, args.out, args.url = True, args.work, None
    stages, events, aliases, old_types, revised, calls = evaluate(args, selection, tok)
    hashes = {}
    for name, rebuilt in zip(PRIVATE, (stages, events, aliases, old_types, revised), strict=True):
        body = (args.work/"ledger_judge_v41"/f"{name}.jsonl").read_bytes()
        assert decode(body) == rebuilt
        hashes[name] = sha256(body).hexdigest()
    access = sum(log.read_text(encoding="utf-8", errors="replace").count("POST /v1/chat/completions")
                 for log in args.work.glob("server-*.log"))
    assert len(list((args.work/"requests").rglob("*.json"))) == sum(calls.values()) == access <= CAP
    qids = {row["question_id"] for row in revised}
    assert all(path.parent.name in qids for path in (args.work/"requests/extract").rglob("*.json"))
    origin = (args.original/"ledger_judge_v4/stages.jsonl").read_bytes()
    baseline = {(row["trajectory_id"], row["stage_id"]): row for row in decode(origin)}
    assert read(args.work/"identity.json")["v4_stages_sha256"] == sha256(origin).hexdigest()
    for row in stages:
        old = baseline[row["trajectory_id"], row["stage_id"]]
        for key in ("judge_raw", "searches", "C_new", "first_invalid", "input_tokens", "outcome"):
            assert row[key] == old[key]
        assert row["labels"]["invalid"] == old["labels"]["invalid"]
        for candidate, original in zip(row["items"] or [], old["items"] or [], strict=True):
            for key in ("main_name", "sought_condition", "type"):
                assert candidate[key] == original[key]
            assert candidate["v4_status"] == original["status"]
    check = args.work/"release_check"
    check.mkdir(mode=0o700, exist_ok=True)
    report(check, stages, events, aliases, revised, calls)
    assert read(check/"SUMMARY.json") == read(args.work/"SUMMARY.json")
    assert (check/"REPORT.md").read_bytes() == (args.work/"REPORT.md").read_bytes()
    manifest = read(args.manifest)
    assert manifest.keys() == PUBLIC
    protected, public, literals = set(), set(), set()
    for item in selection.values():
        task = item["track"]["payload"]
        protected.add(task["question"])
        protected.update(e[k] for e in task["entities"] for k in ("name", "role"))
        protected.update(c["claim"] for c in item["claims"])
        for frame in task["stages"]:
            protected.update(frame["searches"])
            protected.add(frame["thought_tail"])
    for path, item in manifest.items():
        text = item["text"]
        assert sha256(text.encode()).hexdigest() == item["sha256"] and not SECRET.search(text)
        public.update(grams(text))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(text))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    if any(public.intersection(grams(value)) or (len(words(value)) >= 3 and tuple(words(value)) in literals)
           for value in protected):
        raise ValueError("protected task text matched staged publication")
    assert manifest[DIRECTORY+"REPORT.md"]["text"] == (args.work/"REPORT.md").read_text(encoding="utf-8")
    print(json.dumps({"audit": "PASS", "calls": access, "stage_reextractions": 0,
                      "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(), "private_sha256": hashes}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("private")
    sub.add_parser("public").add_argument("manifest", type=Path)
    check = sub.add_parser("compare")
    for key in ("manifest", "work", "previous", "fixed", "prep", "model", "original"):
        check.add_argument(key, type=Path)
    args = parser.parse_args()
    if args.mode == "private":
        scan_private()
    elif args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    else:
        compare(args)


if __name__ == "__main__":
    main()
