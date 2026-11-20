"""Check staged v4.7 files against the accepted replay and scan private text."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from replay_v47 import BASE, FILES, build, committed, freeze

sys.path.append(str(BASE / "m2_v61_full"))
from publish_check import SECRET, grams, public_stage, words

PREFIX = "ledger_judge_v47/"
ROOT = "probe_m1m2/m1m2_impl/"
REPORT = f"{ROOT}{PREFIX}REPORT.md"
FREEZE = f"{ROOT}{PREFIX}FREEZE.json"
PUBLIC = {f"{ROOT}{PREFIX}{name}" for name in ("REPORT.md", "replay_v47.py", "test_v47.py", "audit_v47.py")}


def digest(blob):
    return sha256(blob).hexdigest()


def check_private(repo, artifacts, approved):
    git = ["git", "-C", str(repo)]
    paths = subprocess.check_output([*git, "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(paths) - {""} != {f"{PREFIX}{name}.jsonl" for name in FILES}:
        raise ValueError("unexpected private Stage files")
    receipt = {}
    for name, expected in zip(FILES, artifacts, strict=True):
        blob = subprocess.check_output([*git, "show", f":{PREFIX}{name}.jsonl"])
        if b"\0" in blob or SECRET.search(blob.decode("utf-8")):
            raise ValueError("private credential scan failed")
        if [json.loads(line) for line in blob.splitlines()] != expected:
            raise ValueError("private stage data differs from verified replay")
        if approved and name in ("stage_signals", "events"):
            previous = subprocess.check_output([*git, "show", f"HEAD:ledger_judge_v46/{name}.jsonl"])
            if previous != blob:
                raise ValueError("v4.6 event or signal bytes differ")
        receipt[name] = digest(blob)
    return receipt


def check_public(manifest, repo, report, approved):
    index = json.loads(manifest.read_bytes())
    permitted = PUBLIC | ({FREEZE} if approved else set())
    if index.keys() != permitted or index[REPORT]["text"] != report:
        raise ValueError("staged report or freeze status differs from replay")
    if approved:
        provenance = freeze()
        if json.loads(index[FREEZE]["text"]) != provenance:
            raise ValueError("staged freeze metadata differs from gate result")
        for path, expected in provenance["code_sha256"].items():
            full = ROOT + path
            blob = index[full]["text"].encode("utf-8") if full in index else subprocess.check_output(
                ["git", "show", f"HEAD:{full}"])
            if digest(blob) != expected:
                raise ValueError("freeze code hash does not match committed or staged source")

    public_phrases, literals, private_terms = set(), set(), set()
    for path, row in index.items():
        body = row["text"]
        if digest(body.encode("utf-8")) != row["sha256"] or SECRET.search(body):
            raise ValueError("public content or credential scan failed")
        public_phrases.update(grams(body))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(body))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    for row in committed(repo, "ledger_judge_v46/stages.jsonl"):
        private_terms.update(row["searches"])
        private_terms.update(item["main_name"] for item in row["items"] if item["main_name"])
        private_terms.update(rec["raw"] for rec in row["judge_raw"] if isinstance(rec.get("raw"), str))
    for row in committed(repo, "ledger_judge_v45/eligibility_checks.jsonl"):
        private_terms.update((row["name"], row["role"]))
    for row in committed(repo, "ledger_judge_v42/entity_types_v41.jsonl"):
        for entity in row["entities"]:
            private_terms.update((entity["canonical_name"], entity["role"]))
    for term in private_terms:
        tokens = tuple(words(term))
        if public_phrases.intersection(grams(term)) or (len(tokens) >= 3 and tokens in literals):
            raise ValueError("protected search or entity text matched staged publication")


def main():
    parser = ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    public = modes.add_parser("public")
    public.add_argument("manifest", type=Path)
    public.add_argument("--frozen", action="store_true")
    compare = modes.add_parser("compare")
    compare.add_argument("manifest", type=Path)
    compare.add_argument("private_repo", type=Path)
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC | ({FREEZE} if args.frozen else set()))
        return
    artifacts, report, approved = build(args.private_repo)
    receipt = check_private(args.private_repo, artifacts, approved)
    check_public(args.manifest, args.private_repo, report, approved)
    print(json.dumps({"audit": "PASS", "frozen": approved, "judge_calls": 0, "signals": len(artifacts[1]),
                      "manifest_sha256": digest(args.manifest.read_bytes()), "private_sha256": receipt}))


if __name__ == "__main__":
    main()
