"""Check the exact public index and the two authorized private exports."""

from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve()
BASE = HERE.parent.parent / "check_public.py"
spec = importlib.util.spec_from_file_location("public_guard", BASE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
guard.ALLOWED = re.compile(
    r"probe_m1m2/m1m2_impl/judge_v5_bounded/(?:bounded\.py|run\.py|run\.sbatch|privacy\.py|test_bounded\.py|COUNTS\.txt)"
)
CLAIM_FIELDS = {"query_id", "question", "entities", "conditions", "answer_relation"}
VERDICT_FIELDS = {"trajectory_id", "assertion_id", "status", "reason", "citations"}
PASSAGE_FIELDS = {"sentence_id", "text", "before", "after"}


def rows(path):
    with path.open(encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def read(path):
    return json.loads(path.read_bytes())


def check(manifest, root, results, *, version="v5", validate_claims=None):
    from bounded import QUESTION_IDS, validate

    if validate_claims is None:
        validate_claims = validate
    claims_name, verdicts_name = f"claims_{version}.jsonl", f"verdicts_{version}.jsonl"
    index = read(manifest)
    grams, exact = defaultdict(set), defaultdict(set)
    for path, blob in index.items():
        text = blob["text"]
        if (not guard.ALLOWED.fullmatch(path) or guard.SECRET.search(text)
                or hashlib.sha256(text.encode()).hexdigest() != blob["sha256"]):
            raise ValueError("unexpected public index content")
        for gram in guard.shingles(guard.words(text), 9):
            grams[gram].add(path)
        for literal in guard.literals(path, text):
            if len(literal) >= 2:
                exact[literal].add(path)
    flags = defaultdict(set)

    def scan(kind, text):
        if not isinstance(text, str):
            return
        words = guard.words(text)
        for path in exact.get(tuple(words), ()):
            flags[path].add(kind)
        for gram in guard.shingles(words, 9):
            for path in grams.get(gram, ()):
                flags[path].add(kind)

    plan = read(results / "plan.json")
    tids = set(plan["old"]) | set(plan["new"])
    specs = {r["query_id"]: r for r in rows(results / claims_name)}
    if len(tids) != 20 or set(specs) != set(QUESTION_IDS):
        raise ValueError("wrong private export scope")
    original = root / "judge-v5-brzogs/inputs/inputs.jsonl"
    for row in rows(original):
        qid = row["query_id"]
        if qid not in specs:
            continue
        export = specs[qid]
        if export["question"] != row["question"]:
            raise ValueError("private export changed the original question")
        if set(export) == CLAIM_FIELDS:
            if validate_claims(qid, export["question"], {k:v for k,v in export.items() if k != "question"}):
                raise ValueError("exported assertion failed validation")
        elif (set(export) != CLAIM_FIELDS | {"validation_errors"} or export["conditions"] or
              export["entities"] or export["answer_relation"] is not None):
            raise ValueError("wrong private claim fields")
        scan("question", row["question"])
        answers = row["reference_answers"]
        for answer in [answers] if isinstance(answers, str) else answers:
            scan("reference_answer", answer)
        for doc in row["evidence_documents"]:
            scan("source_document", doc["text"])
        for claim in export["conditions"]:
            scan("generated_claim", claim["claim"])

    for ref in rows(root / "supplement-m1-192125/rollouts_ref.jsonl"):
        if ref["trajectory_id"] not in tids:
            continue
        blob = Path(ref["path"]).read_bytes()
        if hashlib.sha256(blob).hexdigest() != ref["sha256"]:
            raise ValueError("original trajectory digest mismatch")
        trace = json.loads(blob)
        for event in trace["tool_events"]:
            scan("tool_return", event["exact_result"])
        for turn in trace["rounds"]:
            scan("actor_text", turn.get("content"))
            scan("actor_text", turn.get("reasoning"))

    exported = set()
    for verdict in rows(results / verdicts_name):
        tid, cid = verdict["trajectory_id"], verdict["assertion_id"]
        if tid not in tids or set(verdict) != VERDICT_FIELDS or (tid, cid) in exported:
            raise ValueError("wrong private verdict fields or identity")
        exported.add((tid, cid))
        for item in verdict["citations"]:
            if set(item) != PASSAGE_FIELDS or any(len(item[key].split()) > 50 for key in ("before", "after")):
                raise ValueError("private context exceeds its scope")
            for key in ("text", "before", "after"):
                scan("private_citation", item[key])
        generated_fallback = (verdict["status"] == "unknown" and not verdict["citations"]
                              and verdict["reason"] in {"No assertion passed validation.",
                                                        "No verified citation was returned."})
        if not generated_fallback:
            scan("judge_reason", verdict["reason"])
    expected = {(tid, cid) for tid in tids for cid in
                ([claim["id"] for claim in specs[tid.split("__rep")[0]]["conditions"]] or [None])}
    if exported != expected:
        raise ValueError("private verdict coverage mismatch")

    hashes = {}
    for name in (claims_name, verdicts_name):
        blob = (results / name).read_bytes()
        if guard.SECRET.search(blob.decode()):
            raise ValueError("credential pattern in private export")
        hashes[name] = hashlib.sha256(blob).hexdigest()
    print(json.dumps({"flagged_paths": {p: sorted(k) for p, k in flags.items()},
                      "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                      "private_sha256": hashes, "verdict_rows": len(exported)}))
    return bool(flags)


if __name__ == "__main__":
    if sys.argv[1] == "staged":
        guard.staged(Path(sys.argv[2]))
    else:
        sys.exit(check(*map(Path, sys.argv[2:])))
