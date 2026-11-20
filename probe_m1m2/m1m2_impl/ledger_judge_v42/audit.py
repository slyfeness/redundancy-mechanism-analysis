"""Verify the name-only replay, frozen Stage records, and exact upload contents."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from probe_v42 import CAP, evaluate, report
import probe_v4 as v4
from category_events import CLASSES
from flags import name_key
from matcher import alias_key
from prepare_full import read
from publish_check import SECRET, grams, public_stage, words

DIRECTORY = "probe_m1m2/m1m2_impl/ledger_judge_v42/"
PUBLIC = {DIRECTORY + name for name in ("REPORT.md", "probe_v42.py", "category_events.py", "test_replay.py",
                                       "run.sbatch", "audit.py")}
PRIVATE = {"stages": {"trajectory_id", "stage_id", "searches", "input_tokens", "items", "C_new",
                      "judge_raw", "first_invalid", "ledger_after", "labels", "semantic_repeat_distances", "outcome"},
           "events": {"trajectory_id", "event", "stage_id", "var", "type", "wrong_name", "correct_name", "first_stage",
                      "confirmation_stage", "key", "search_window", "attribution_scope"},
           "alias_checks": {"id", "names", "result", "attempts", "provenance"},
           "entity_types": {"question_id", "entities", "attempts"},
           "entity_types_v41": {"question_id", "entities", "generation_receipts", "validation_receipts"},
           "name_types": {"question_id", "name_id", "name", "category", "is_proper_name", "reference_vars",
                          "from_main_name"}}


def decode(raw):
    return [json.loads(line) for line in raw.splitlines()]


def scan_private():
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    assert set(names) - {""} == {f"ledger_judge_v42/{name}.jsonl" for name in PRIVATE}
    hashes = {}
    for name, keys in PRIVATE.items():
        body = subprocess.check_output(["git", "show", f":ledger_judge_v42/{name}.jsonl"])
        if b"\0" in body or SECRET.search(body.decode("utf-8")):
            raise ValueError("private credential scan failed")
        rows = decode(body)
        assert all(row.keys() == keys for row in rows)
        if name == "stages":
            assert len(rows) == v4.EXPECTED and len({(r["trajectory_id"], r["stage_id"]) for r in rows}) == v4.EXPECTED
        elif name in ("entity_types", "entity_types_v41"):
            assert len(rows) == 10
        elif name == "name_types":
            assert len({(row["question_id"], name_key(row["name"])) for row in rows}) == len(rows)
            assert all(row["category"] in (*CLASSES, None) for row in rows)
        hashes[name] = sha256(body).hexdigest()
    print(json.dumps({"private_sha256": hashes, "credential_matches": 0}))


def compare(args):
    selection = v4.scope(args)
    args.replay, args.out, args.url = True, args.work, None
    stages, events, aliases, types, v41_types, names, calls = evaluate(args, selection)
    files = {}
    for name, rebuilt in zip(PRIVATE, (stages, events, aliases, types, v41_types, names), strict=True):
        body = (args.work/"ledger_judge_v42"/f"{name}.jsonl").read_bytes()
        assert decode(body) == rebuilt
        files[name] = sha256(body).hexdigest()
    physical = sum(log.read_text(encoding="utf-8", errors="replace").count("POST /v1/chat/completions")
                   for log in args.work.glob("server-*.log"))
    assert len(list((args.work/"requests").rglob("*.json"))) == sum(calls.values()) == physical <= CAP
    assert {path.name for path in (args.work/"requests").iterdir()} <= {"alias", "type"}
    raw = (args.original/"ledger_judge_v4/stages.jsonl").read_bytes()
    assert read(args.work/"identity.json")["v4_stages_sha256"] == sha256(raw).hexdigest()
    original = {(row["trajectory_id"], row["stage_id"]): row for row in decode(raw)}
    cached = {alias_key(row["names"]["A"], row["names"]["B"]): row for row in
              decode((args.previous_v41/"ledger_judge_v41/alias_checks.jsonl").read_bytes())}
    for row in aliases:
        key = alias_key(row["names"]["A"], row["names"]["B"])
        if key in cached:
            assert row == cached.pop(key)
        else:
            assert row["provenance"] == "v4.2"
    assert not cached
    mapped = {(row["question_id"], name_key(row["name"])): row for row in names}
    assert len(mapped) == len(names)
    for row in stages:
        key = row["trajectory_id"], row["stage_id"]
        old = original[key]
        qid = selection[key[0]]["track"]["question_id"]
        for field in ("judge_raw", "searches", "first_invalid", "C_new", "input_tokens", "outcome"):
            assert row[field] == old[field]
        assert row["labels"]["invalid"] == old["labels"]["invalid"]
        for item, old_item in zip(row["items"] or [], old["items"] or [], strict=True):
            assert (item["main_name"], item["sought_condition"]) == (old_item["main_name"], old_item["sought_condition"])
            if item["main_name"] != "none":
                result = mapped[qid, name_key(item["main_name"])]
                assert result["category"] == item["type"]
                if result["is_proper_name"] == "no":
                    assert item["status"] == "non_proper_name" and item["var"] is None
    check = args.work/"release_check"
    check.mkdir(mode=0o700, exist_ok=True)
    report(check, stages, events, aliases, names, calls)
    assert read(check/"SUMMARY.json") == read(args.work/"SUMMARY.json")
    assert (check/"REPORT.md").read_bytes() == (args.work/"REPORT.md").read_bytes()
    manifest = read(args.manifest)
    assert manifest.keys() == PUBLIC
    protected, public, literals = set(), set(), set()
    for entry in selection.values():
        task = entry["track"]["payload"]
        protected.add(task["question"])
        protected.update(e[k] for e in task["entities"] for k in ("name", "role"))
        protected.update(c["claim"] for c in entry["claims"])
        for frame in task["stages"]:
            protected.update(frame["searches"])
            protected.add(frame["thought_tail"])
    protected.update(row["name"] for row in names)
    for path, row in manifest.items():
        text = row["text"]
        assert sha256(text.encode()).hexdigest() == row["sha256"] and not SECRET.search(text)
        public.update(grams(text))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(text))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    if any(public.intersection(grams(value)) or (len(words(value)) >= 3 and tuple(words(value)) in literals)
           for value in protected):
        raise ValueError("protected task text matched staged publication")
    assert manifest[DIRECTORY+"REPORT.md"]["text"] == (args.work/"REPORT.md").read_text(encoding="utf-8")
    print(json.dumps({"audit": "PASS", "calls": physical, "stage_reextractions": 0,
                      "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(), "private_sha256": files}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("private")
    sub.add_parser("public").add_argument("manifest", type=Path)
    check = sub.add_parser("compare")
    for key in ("manifest", "work", "previous", "fixed", "prep", "original", "previous_v41"):
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
