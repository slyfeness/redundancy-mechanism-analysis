"""Verify the frozen replay and scan the exact public and private release contents."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from probe_v43 import report, rows

FULL = Path(__file__).resolve().parent.parent / "m2_v61_full"
if FULL.is_dir():
    sys.path.append(str(FULL))
from publish_check import SECRET, grams, public_stage, words

PUBLIC_DIR = "probe_m1m2/m1m2_impl/ledger_judge_v43"
PUBLIC = {f"{PUBLIC_DIR}/{name}" for name in ("probe_v43.py", "audit.py", "test_probe_v43.py", "REPORT.md")}
PRIVATE = "ledger_judge_v43/stages.jsonl"


def verify_frozen(before, after):
    if len(before) != len(after) or len(after) != 430:
        raise ValueError("unexpected Stage count")
    for old, new in zip(before, after, strict=True):
        allowed = {"new_docids", "seen_docids"}
        if new.keys() != old.keys() | allowed:
            raise ValueError("unexpected Stage fields")
        if new["labels"].keys() != old["labels"].keys() | {"semantic_repeat", "stale_return"}:
            raise ValueError("unexpected Stage labels")
        editable = allowed | {"labels", "semantic_repeat_distances"}
        if any(new[key] != old[key] for key in old.keys() - editable):
            raise ValueError("frozen Stage fields changed")
        if any(new["labels"][key] != value for key, value in old["labels"].items() if key != "semantic_repeat"):
            raise ValueError("frozen labels changed")
        if any(type(new[key]) is not int or new[key] < 0 for key in allowed):
            raise ValueError("invalid document count")


def scan_private():
    paths = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(paths) - {""} != {PRIVATE}:
        raise ValueError("unexpected private staged paths")
    stage_blob = subprocess.check_output(["git", "show", f":{PRIVATE}"])
    frozen = subprocess.check_output(["git", "show", "HEAD:ledger_judge_v42/stages.jsonl"])
    alias_blob = subprocess.check_output(["git", "show", "HEAD:ledger_judge_v42/alias_checks.jsonl"])
    text = stage_blob.decode("utf-8")
    if "\0" in text or SECRET.search(text):
        raise ValueError("unexpected private content or credential pattern")
    verify_frozen(list(map(json.loads, frozen.decode("utf-8").splitlines())),
                  list(map(json.loads, text.splitlines())))
    print(json.dumps({"stages_sha256": sha256(stage_blob).hexdigest(), "frozen_sha256": sha256(frozen).hexdigest(),
                      "alias_sha256": sha256(alias_blob).hexdigest(), "credential_matches": 0}))


def verify_m2(after, ledger):
    expected = {(row["trajectory_id"], row["stage_id"]): row for row in after}
    received = set()
    open_only_stale = 0
    for record in rows(ledger):
        key = record["trajectory_id"], record["unit_id"]
        if key not in expected:
            continue
        if key in received:
            raise ValueError("duplicate M2 Stage")
        received.add(key)
        row = expected[key]
        prior, current = set(record["L_pre"]["evidence"]), set(record["L_post"]["evidence"])
        # Accumulated M2 evidence independently checks novelty. Its event index
        # retains both repeat hits and multiple appearances of the same ID.
        returned = set()
        for attempt in record["E_t"]["attempts"]:
            if attempt["status"] == "ok" and attempt["fed_to_model"]:
                returned.update(str(hit["docid"]) for hit in attempt["returned_docids"])
                if attempt["opened_docid"] is not None:
                    returned.add(str(attempt["opened_docid"]))
        if (prior | returned != current or len(current - prior) != row["new_docids"]
                or len(prior & returned) != row["seen_docids"] or row["C_new"] != record["C_new"]):
            raise ValueError("visible documents or condition credit differ from frozen M2")
        all_seen = row["seen_docids"] and not row["new_docids"] and not row["C_new"]
        if all_seen and not row["searches"] and not row["labels"].get("strict_repeat"):
            open_only_stale += 1
    if received != expected.keys():
        raise ValueError("missing M2 Stage")
    return open_only_stale


def compare(args):
    before = list(rows(args.frozen / "stages.jsonl"))
    after = list(rows(args.work / "stages.jsonl"))
    verify_frozen(before, after)
    open_only_stale = verify_m2(after, args.ledger)
    manifest = json.loads(args.manifest.read_bytes())
    if manifest.keys() != PUBLIC or manifest[f"{PUBLIC_DIR}/REPORT.md"]["text"] != report(before, after):
        raise ValueError("staged report differs from replay")
    public, literals = set(), set()
    for path, record in manifest.items():
        body = record["text"]
        if sha256(body.encode()).hexdigest() != record["sha256"] or SECRET.search(body):
            raise ValueError("public release fingerprint or credential scan failed")
        public.update(grams(body))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(body))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))

    def check(text):
        tokens = tuple(words(text))
        if public.intersection(grams(text)) or (len(tokens) >= 3 and tokens in literals):
            raise ValueError("protected text matched staged public release")

    sample = {row["trajectory_id"] for row in after}
    plan = json.loads(args.plan.read_bytes())
    if set(plan) != sample:
        raise ValueError("frozen sample differs from private plan")
    for track in plan.values():
        payload = track["payload"]
        check(payload["question"])
        for entity in payload["entities"]:
            check(entity["name"])
            check(entity["role"])
        for stage in payload["stages"]:
            check(stage["thought_tail"])
            for query in stage["searches"]:
                check(query)
    for row in rows(args.m1_stages):
        if row["trajectory_id"] in sample:
            for event in row["tool_events"]:
                check(event["return_text"])
    print(json.dumps({
        "audit": "PASS", "m2_stages": len(after), "open_only_all_seen_no_credit": open_only_stale,
        "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(),
        "stages_sha256": sha256((args.work / "stages.jsonl").read_bytes()).hexdigest(),
        "frozen_sha256": sha256((args.frozen / "stages.jsonl").read_bytes()).hexdigest(),
        "alias_sha256": sha256((args.frozen / "alias_checks.jsonl").read_bytes()).hexdigest(),
    }))


def main():
    parser = ArgumentParser()
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("public").add_argument("manifest", type=Path)
    commands.add_parser("private")
    verification = commands.add_parser("compare")
    for field in ("manifest", "work", "frozen", "m1_stages", "ledger", "plan"):
        verification.add_argument(field, type=Path)
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    elif args.mode == "private":
        scan_private()
    else:
        compare(args)


if __name__ == "__main__":
    main()
