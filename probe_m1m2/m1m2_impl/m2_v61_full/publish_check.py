
"""Check the staged publication against the authorized file and data boundaries."""

from argparse import ArgumentParser
from collections import defaultdict
from hashlib import sha256
import ast
import json
from pathlib import Path
import re
import subprocess

from prepare_full import read

PREFIX = "probe_m1m2/m1m2_impl/m2_v61_full/"
PUBLIC = {"context.py", "embed.py", "embedding.sbatch", "full.sbatch", "local_env.sh", "prepare_full.py",
          "rules.py", "run_full.py", "settlement.py", "test_full.py", "publish_check.py", "REPORT.md"}
PRIVATE = {"assertion_sample.jsonl": 30, "supported_sample.jsonl": 20, "unknown_sample.jsonl": 20,
           "under_two.jsonl": None}
SECRET = re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----|"
                    r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{18,}|gh[pousr]_[A-Za-z0-9_]{24,}|github_pat_[A-Za-z0-9_]{24,}"
                    r"|hf_[A-Za-z0-9]{24,}|AKIA[A-Z0-9]{16}|"
                    r"(?:api_key|credential|password|access_token)\s*[:=]\s*['\"][A-Za-z0-9_/-]{20,}['\"]")


def words(value):
    return re.findall(r"[^\W_]+", value.casefold())


def grams(value, width=10):
    tokens = words(value)
    return zip(*(tokens[i:] for i in range(width)))


def public_stage(output):
    index = {}
    for name in subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0"):
        if not name:
            continue
        if name not in {PREFIX + child for child in PUBLIC}:
            raise ValueError("unexpected public staged path")
        body = subprocess.check_output(["git", "show", f":{name}"]).decode("utf-8")
        if len(body) > 100_000 or "\0" in body or SECRET.search(body):
            raise ValueError("unexpected public content or credential pattern")
        index[name] = {"text": body, "sha256": sha256(body.encode()).hexdigest()}
    if set(index) != {PREFIX + child for child in PUBLIC}:
        raise ValueError("incomplete staged public deliverables")
    output.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"public_staged_files": len(index), "credential_matches": 0}))


def compare(manifest, prep, root):
    staged = read(manifest)
    index, literals, findings = defaultdict(set), defaultdict(set), defaultdict(set)
    for name, record in staged.items():
        if name not in {PREFIX + child for child in PUBLIC}:
            raise ValueError("unexpected path in presubmit manifest")
        text = record["text"]
        if sha256(text.encode()).hexdigest() != record["sha256"] or SECRET.search(text):
            raise ValueError("staged public manifest mismatch")
        for gram in grams(text):
            index[gram].add(name)
        if name.endswith(".py"):
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    literals[tuple(words(node.value))].add(name)

    def scan(label, value):
        if isinstance(value, str):
            for gram in grams(value):
                for name in index.get(gram, ()):
                    findings[name].add(label)

    questions = read(prep / "questions.json")
    for question in questions.values():
        scan("question", question["question"])
        for answer in question["answers"]:
            scan("answer", answer)
            key = tuple(words(answer))
            if len(key) >= 2:
                for name in literals.get(key, ()):
                    findings[name].add("answer_literal")
    for document in read(prep / "documents.json").values():
        scan("labelled_document", document)
    ids = {row["trajectory_id"] for row in json_lines(root / "supplement-m2-192129/trajectory_results.jsonl")}
    scanned = set()
    for reference in json_lines(root / "supplement-m1-192125/rollouts_ref.jsonl"):
        tid = reference["trajectory_id"]
        if tid not in ids:
            continue
        seal = Path(reference["path"]).read_bytes()
        if sha256(seal).hexdigest() != reference["sha256"]:
            raise ValueError("source trace changed")
        trace = json.loads(seal)
        for event in trace["tool_events"]:
            scan("tool_return", event["exact_result"])
        for actor in trace["rounds"]:
            scan("actor_answer_or_reasoning", actor.get("content"))
            scan("actor_answer_or_reasoning", actor.get("reasoning"))
        scanned.add(tid)
    if len(ids) != 399 or scanned != ids:
        raise ValueError("unexpected trace coverage in public privacy scan")
    for row in json_lines(root / "supplement-m1-192125/stages.jsonl"):
        if row["trajectory_id"] in ids:
            for event in row["tool_events"]:
                scan("stage_return", event["return_text"])
    print(json.dumps({"files": len(staged), "train": len(questions), "heldout_decoded": 0,
                      "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
                      "findings": {name: sorted(labels) for name, labels in findings.items()}}))
    if findings:
        raise ValueError("public privacy scan found matches")


def json_lines(path):
    with path.open(encoding="utf-8") as stream:
        yield from (json.loads(line) for line in stream)


def private_stage(directory, expected_under_two):
    keys = {
        "assertion_sample.jsonl": {"query_id", "question", "entities", "assertion", "gold_check"},
        "supported_sample.jsonl": {"trajectory_id", "query_id", "assertion_id", "status", "reason",
                                   "unit_id", "citations", "assertion", "subject_name"},
        "unknown_sample.jsonl": {"trajectory_id", "query_id", "assertion_id", "claim", "reason",
                                 "passages", "assertion", "subject_name"},
        "under_two.jsonl": {"query_id", "assertion_count", "reasons"},
    }
    actual = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(actual) - {""} != {f"{directory}/{name}" for name in PRIVATE}:
        raise ValueError("unexpected private staged paths")
    counts = {}
    for name, count in PRIVATE.items():
        text = subprocess.check_output(["git", "show", f":{directory}/{name}"]).decode()
        if "\0" in text or SECRET.search(text):
            raise ValueError("private credential scan failed")
        rows = [json.loads(line) for line in text.splitlines()]
        if len(rows) != (count if count is not None else expected_under_two):
            raise ValueError("private sample count mismatch")
        for row in rows:
            if row.keys() != keys[name]:
                raise ValueError("unexpected private review fields")
            refs = row.get("citations") or row.get("passages") or row.get("gold_check", {}).get("citations", [])
            if name == "unknown_sample.jsonl" and len(refs) != 2:
                raise ValueError("unknown review row must contain two source excerpts")
            if any(len(ref[key].split()) > 50 for ref in refs for key in ("before", "after")):
                raise ValueError("private citation exceeds its context bound")
        counts[name] = len(rows)
    print(json.dumps({"private_staged_rows": counts, "credential_matches": 0}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("public").add_argument("manifest", type=Path)
    cluster = sub.add_parser("compare")
    for key in ("manifest", "prep", "root"):
        cluster.add_argument(key, type=Path)
    private = sub.add_parser("private")
    private.add_argument("directory")
    private.add_argument("under_two", type=int)
    args = parser.parse_args()
    if args.mode == "public":
        public_stage(args.manifest)
    elif args.mode == "compare":
        compare(args.manifest, args.prep, args.root)
    else:
        private_stage(args.directory, args.under_two)


if __name__ == "__main__":
    main()
