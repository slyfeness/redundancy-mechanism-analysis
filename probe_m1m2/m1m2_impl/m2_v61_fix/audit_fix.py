"""Apply the existing publication scan to the correction's exact file set."""

from argparse import ArgumentParser
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
if (HERE.parent / "m2_v61_full").is_dir():
    sys.path.append(str(HERE.parent / "m2_v61_full"))

from publish_check import SECRET, compare, public_stage

PARENT = "probe_m1m2/m1m2_impl/"
PUBLIC = {PARENT + "m2_v61_full/" + child for child in ("rules.py", "publish_check.py", "test_subject_fix.py")}
PUBLIC |= {PARENT + "m2_v61_fix/" + child for child in
           ("run_fix.py", "settle_fix.py", "audit_fix.py", "replay.sbatch", "judge.sbatch", "REPORT.md")}
PRIVATE = "m2_v61_fix/restored_assertions_sample.jsonl"


def private():
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode()
    if set(staged.split("\0")) - {""} != {PRIVATE}:
        raise ValueError("unexpected private staged paths")
    body = subprocess.check_output(["git", "show", f":{PRIVATE}"]).decode("utf-8")
    if "\0" in body or SECRET.search(body):
        raise ValueError("private credential scan failed")
    rows = [json.loads(line) for line in body.splitlines()]
    if len(rows) != 15 or len({(row["query_id"], row["assertion"]["id"]) for row in rows}) != 15:
        raise ValueError("expected fifteen different restored assertions")
    for row in rows:
        if row.keys() != {"query_id", "question", "entities", "assertion", "gold_check"}:
            raise ValueError("unexpected private review fields")
        gold = row["gold_check"]
        if (gold["query_id"], gold["assertion_id"]) != (row["query_id"], row["assertion"]["id"]):
            raise ValueError("a private review row contains the wrong Gold result")
        if any(len(ref[key].split()) > 50 for ref in gold["citations"] for key in ("before", "after")):
            raise ValueError("a private citation exceeds its context bound")
    print(json.dumps({"private_staged_rows": len(rows), "credential_matches": 0}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("public").add_argument("manifest", type=Path)
    cluster = sub.add_parser("compare")
    for key in ("manifest", "prep", "root"):
        cluster.add_argument(key, type=Path)
    sub.add_parser("private")
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    elif args.mode == "compare":
        compare(args.manifest, args.prep, args.root, allowed=PUBLIC)
    else:
        private()


if __name__ == "__main__":
    main()
