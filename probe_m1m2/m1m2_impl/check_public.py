"""Check the public commit without copying private benchmark material off cluster."""

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ALLOWED = re.compile(
    r"ledger-grpo/src/ledger_grpo/ledgercredit/[a-z_]+\.py|"
    r"ledger-grpo/tests/test_ledgercredit\.py|"
    r"probe_m1m2/m1m2_impl/(?:REPORT\.md|check\.sbatch|judge\.sbatch|check_public\.py)"
)
SECRET = re.compile(
    r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:sk-[A-Za-z0-9_-]{18,}|gh[pousr]_[A-Za-z0-9]{24,}|"
    r"github_pat_[A-Za-z0-9_]{24,}|hf_[A-Za-z0-9]{24,}|AKIA[A-Z0-9]{16})|"
    r"(?:key|secret|token)\s*=\s*['\"][A-Za-z0-9_/-]{20,}['\"]"
)
SIZE_LIMIT = 100_000


def staged(output):
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode()
    names = [name for name in names.split("\0") if name]
    if not names:
        raise ValueError("no staged files")
    files = {}
    for path in names:
        if not ALLOWED.fullmatch(path):
            raise ValueError(f"unexpected staged path: {path}")
        blob = subprocess.check_output(["git", "show", f":{path}"])
        if len(blob) > SIZE_LIMIT or b"\0" in blob:
            raise ValueError(f"unexpected staged blob: {path}")
        text = blob.decode("utf-8")
        if SECRET.search(text):
            raise ValueError(f"credential pattern detected: {path}")
        files[path] = {"sha256": hashlib.sha256(blob).hexdigest(), "text": text}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(files, stream, ensure_ascii=False, sort_keys=True)
    print(f"Staged source/report allowlist and credential patterns passed for {len(files)} files.")


def words(text):
    return re.findall(r"[^\W_]+", text.casefold())


def shingles(tokens, width):
    return zip(*(tokens[i:] for i in range(width)))


def literals(path, text):
    if path.endswith(".py"):
        return {tuple(words(node.value)) for node in ast.walk(ast.parse(text))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    return {tuple(words(line)) for line in text.splitlines()}


def compare(manifest, selection_path, evidence_path, references, stage_path):
    index = json.loads(manifest.read_bytes())
    size = 10
    public = defaultdict(set)
    short = defaultdict(set)
    for path, record in index.items():
        assert ALLOWED.fullmatch(path) and not SECRET.search(record["text"])
        assert hashlib.sha256(record["text"].encode()).hexdigest() == record["sha256"]
        for gram in shingles(words(record["text"]), size):
            public[gram].add(path)
        for value in literals(path, record["text"]):
            short[value].add(path)
    matches = defaultdict(set)

    def scan(source, text):
        if isinstance(text, str):
            for gram in shingles(words(text), size):
                for path in public.get(gram, ()):
                    matches[path].add(source)

    labels = json.loads((selection_path / "evaluation_private.json").read_bytes())
    chosen = json.loads((selection_path / "selection.json").read_bytes())
    if set(chosen["training_ids"]) != {row["id"] for row in labels}:
        raise ValueError("expected training pilot selection only")
    for row in labels:
        scan("question", row["question"])
        answers = row["answers"]
        for answer in ([answers] if isinstance(answers, str) else answers):
            scan("answer", answer)
            key = tuple(words(answer))
            if len(key) >= 2:
                for path in short.get(key, ()):
                    matches[path].add("answer_literal")
    for text in json.loads(evidence_path.read_bytes()).values():
        scan("evidence", text)
    with references.open(encoding="utf-8") as stream:
        for line in stream:
            ref = json.loads(line)
            blob = Path(ref["path"]).read_bytes()
            if hashlib.sha256(blob).hexdigest() != ref["sha256"]:
                raise ValueError("original trace changed")
            trace = json.loads(blob)
            for event in trace["tool_events"]:
                scan("return", event["exact_result"])
            for actor in trace["rounds"]:
                scan("actor_answer_or_reasoning", actor.get("content"))
                scan("actor_answer_or_reasoning", actor.get("reasoning"))
    # Cross-check the emitted visible-text representation too.
    with stage_path.open(encoding="utf-8") as stream:
        for line in stream:
            for event in json.loads(line)["tool_events"]:
                scan("stage_return", event["return_text"])
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    print(json.dumps({"files": len(index), "manifest_sha256": digest,
                      "flagged_paths": {key: sorted(value) for key, value in sorted(matches.items())}}))
    return bool(matches)


def main():
    command = argparse.ArgumentParser()
    sub = command.add_subparsers(dest="mode", required=True)
    sub.add_parser("staged").add_argument("manifest", type=Path)
    on_cluster = sub.add_parser("compare")
    for name in ("manifest", "selection", "evidence", "references", "stages"):
        on_cluster.add_argument(name, type=Path)
    args = command.parse_args()
    if args.mode == "staged":
        staged(args.manifest)
        return 0
    return int(compare(args.manifest, args.selection, args.evidence, args.references, args.stages))


if __name__ == "__main__":
    sys.exit(main())
