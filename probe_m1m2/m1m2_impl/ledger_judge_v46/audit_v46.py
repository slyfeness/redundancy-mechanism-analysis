"""Scan the staged v4.6 commit contents and verify exact offline replay."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from replay_v46 import BASE, EVENT_TAGS, FILES, GATE, build, committed, key

sys.path.append(str(BASE / "m2_v61_full"))
from publish_check import SECRET, grams, public_stage, words

PREFIX = "ledger_judge_v46/"
REPORT = f"probe_m1m2/m1m2_impl/{PREFIX}REPORT.md"
PUBLIC = {f"probe_m1m2/m1m2_impl/{PREFIX}{name}"
          for name in ("REPORT.md", "replay_v46.py", "test_v46.py", "audit_v46.py")}


def staged_private(repo):
    git = ["git", "-C", str(repo)]
    paths = subprocess.check_output([*git, "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(paths) - {""} != {f"{PREFIX}{name}.jsonl" for name in FILES}:
        raise ValueError("unexpected private Stage files")
    data = [subprocess.check_output([*git, "show", f":{PREFIX}{name}.jsonl"]) for name in FILES]
    if any(b"\0" in blob or SECRET.search(blob.decode("utf-8")) for blob in data):
        raise ValueError("private credential scan failed")
    return data


def verify_baseline(repo, stages, signals, events, sample):
    before = committed(repo, "ledger_judge_v45/stages.jsonl")
    original_signals = committed(repo, "ledger_judge_v45/stage_signals.jsonl")
    original_sample = committed(repo, "ledger_judge_v45/audit_sample.jsonl")
    event_tags = {(key(row), row["event"]) for row in events}
    for old, new, old_signal, signal in zip(before, stages, original_signals, signals, strict=True):
        if key(old) != key(new) or key(old_signal) != key(signal):
            raise ValueError("v4.5 Stage order changed")
        if old.keys() != new.keys() or any(old[f] != new[f] for f in old.keys() - {"labels", "items"}):
            raise ValueError("protected Stage fields changed")
        if old["labels"].keys() != new["labels"].keys() or any(
                old["labels"][f] != new["labels"][f] for f in old["labels"].keys() - set(EVENT_TAGS)):
            raise ValueError("non-event labels changed")
        for prior, revised in zip(old["items"], new["items"], strict=True):
            if prior["decision_reason"] not in GATE:
                if prior != revised:
                    raise ValueError("rules 1-3 or an unreviewed search changed")
                continue
            residual = {f: value for f, value in prior.items() if f not in (
                "attribution", "decision_reason", "eligibility_check")}
            if revised != residual | {"decision_reason": "wrong_candidate", "attribution": "wrong_candidate"}:
                raise ValueError("unexpected reversal of qualification gate")
        if signal.keys() != old_signal.keys() or any(signal[f] != old_signal[f]
                                                    for f in signal.keys() - {"F_new", "F_corrected"}):
            raise ValueError("M3 credit, token or idle fields changed")
        for tag in ("F_new", "F_corrected"):
            if signal[tag] != int(new["labels"][tag]) or new["labels"][tag] != ((key(new), tag) in event_tags):
                raise ValueError("event and M3 signal differ")

    slots = ("trajectory_id", "stage_id", "query_index", "query", "judge_raw")
    if len(sample) != 70 or any(any(old[f] != new[f] for f in slots)
                                for old, new in zip(original_sample, sample, strict=True)):
        raise ValueError("the review sample was resampled")


def scan(manifest, repo, report):
    index = json.loads(manifest.read_bytes())
    if index.keys() != PUBLIC or index[REPORT]["text"] != report:
        raise ValueError("report or public path allowlist differs from replay")
    private_terms, public_phrases, literals = set(), set(), set()
    for path, row in index.items():
        body = row["text"]
        if sha256(body.encode()).hexdigest() != row["sha256"] or SECRET.search(body):
            raise ValueError("public source fingerprint or credential scan failed")
        public_phrases.update(grams(body))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(body))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    for row in committed(repo, "ledger_judge_v45/stages.jsonl"):
        private_terms.update(row["searches"])
        private_terms.update(item["main_name"] for item in row["items"] if item["main_name"])
        private_terms.update(rec["raw"] for rec in row["judge_raw"] if isinstance(rec.get("raw"), str))
    for row in committed(repo, "ledger_judge_v45/eligibility_checks.jsonl"):
        private_terms.update((row["name"], row["role"]))
    for row in committed(repo, "ledger_judge_v42/entity_types_v41.jsonl"):
        for entity in row["entities"]:
            private_terms.update((entity["role"], entity["canonical_name"]))
    for term in private_terms:
        tokens = tuple(words(term))
        if public_phrases.intersection(grams(term)) or (len(tokens) >= 3 and tokens in literals):
            raise ValueError("protected search or entity text matched staged publication")


def main():
    parser = ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("public").add_argument("manifest", type=Path)
    compare = modes.add_parser("compare")
    compare.add_argument("manifest", type=Path)
    compare.add_argument("private_repo", type=Path)
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
        return

    blobs = staged_private(args.private_repo)
    data = [[json.loads(line) for line in blob.splitlines()] for blob in blobs]
    expected, report = build(args.private_repo)
    if data != list(expected):
        raise ValueError("private staged files differ from the offline replay")
    verify_baseline(args.private_repo, *data)
    scan(args.manifest, args.private_repo, report)
    print(json.dumps({"audit": "PASS", "judge_calls": 0, "signals": len(data[1]), "sample": len(data[3]),
                      "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(),
                      "private_sha256": {name: sha256(blob).hexdigest() for name, blob in zip(FILES, blobs, strict=True)}}))


if __name__ == "__main__":
    main()
