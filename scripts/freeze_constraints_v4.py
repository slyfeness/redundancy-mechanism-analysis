"""Write one private, immutable constraint file from the v4 full trial."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata


SOURCE = {
    "run": "187016",
    "commit": "477d1c0fd294797c3cfb85a525e38edac4d73aeb",
    "extract_prompt_sha256": "7c3d351c45ff7261388221f3b188d944b2ab9c3d8803c95e844a74480f3b8eda",
    "audit_prompt_sha256": "af39a0804fd8eef41a7a09a61afff6197f2627326430b2aceecef8ad83b3d9a3",
}
RESULTS_SHA256 = "bd68a3c28936e0715c7f2a5faa26713405d4bbc4d51387f164507c8b75245491"
INDEX_SHA256 = "c4b0a41ddb7d875601053b11c576f4226cdcb16fb962dbf999ae0ddd73bd6742"
STOP_WORDS = frozenset("""
a an and are as at be been being but by can could did do does for from had has have how i if in into
is it its may of on or our shall should so than that the their them then there these they this those
to up was we were what when where which who whom whose will with would you your
""".split())


def norm(text):
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def keyword_matches(question, keyword):
    if not keyword:
        return []
    return [
        match.span()
        for match in re.finditer(re.escape(keyword), question)
        if (not keyword[0].isalnum() or match.start() == 0 or not question[match.start() - 1].isalnum())
        and (not keyword[-1].isalnum() or match.end() == len(question) or not question[match.end()].isalnum())
    ]


def content_words(text):
    return set(re.findall(r"[^\W_]+", norm(text))) - STOP_WORDS


def audit_drop_reason(item, question, format_words):
    if not item["keywords"] or any(not keyword_matches(question, norm(k)) for k in item["keywords"]):
        return "audit_keyword_not_in_question"
    words = content_words(item["text"])
    denominator = min(len(words), len(format_words))
    if denominator and 5 * len(words & format_words) >= 3 * denominator:
        return "audit_duplicates_answer_format"
    return None


def freeze_rows(trial_rows, index_rows, *, expected_questions=100):
    questions = {}
    for row in index_rows:
        qid, question = str(row["question_id"]), row["question"]
        if questions.setdefault(qid, question) != question:
            raise ValueError(f"inconsistent Phase 1 question hash for ID {qid}")
    if len(questions) != expected_questions:
        raise ValueError(f"expected {expected_questions} unique Phase 1 questions, found {len(questions)}")
    frozen = {}
    for row in trial_rows:
        qid = str(row["question_id"])
        if qid in frozen or qid not in questions:
            raise ValueError(f"duplicate or unknown trial question ID {qid}")
        question = questions[qid]
        question_hash = sha256(question.encode("utf-8")).hexdigest()
        if row["question_sha256"] != question_hash or row["question"] != question:
            raise ValueError(f"question SHA-256 mismatch for ID {qid}")
        if row["error"] or row["audit_error"]:
            raise ValueError(f"v4 trial was incomplete for ID {qid}")
        extract = row["extraction"]
        notes = {key: extract[key] for key in ("answer_type", "answer_format", "global_notes")}
        normalized_question = norm(question)
        format_words = content_words(notes["answer_format"])
        constraints, dropped = [], []
        sources = [item["source"] for item in row["constraints"]]
        if set(sources) - {"extract", "audit"} or sources != sorted(sources, key=("extract", "audit").index):
            raise ValueError(f"unexpected v4 item order or origin for ID {qid}")
        for item in row["constraints"]:
            origin = item["source"]
            reason = audit_drop_reason(item, normalized_question, format_words) if origin == "audit" else None
            if reason:
                dropped.append({"text": item["text"], "origin": origin, "reason": reason})
                continue
            constraints.append({"constraint_id": f"C{len(constraints) + 1}", "text": item["text"],
                                "keywords": item["keywords"], "origin": origin, "certain": item["certain"]})
        frozen[qid] = {"question_id": qid, "question_sha256": question_hash, **notes, "constraints": constraints,
                       "dropped": dropped, "provenance": {**SOURCE, "objections": row["not_constraints"]}}
    if questions.keys() != frozen.keys():
        raise ValueError(f"missing v4 rows for {len(questions.keys() - frozen.keys())} Phase 1 questions")
    return [frozen[qid] for qid in questions]


def read_sealed_jsonl(path, expected_hash):
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected_hash:
        raise ValueError(f"unrecognized input SHA-256 for {path.name}")
    return [json.loads(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--input-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = freeze_rows(read_sealed_jsonl(args.results, RESULTS_SHA256),
                       read_sealed_jsonl(args.input_index, INDEX_SHA256))
    data = "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with args.output.open("xb") as stream:
        stream.write(data)
    args.output.chmod(0o400)
    reasons = Counter(item["reason"] for row in rows for item in row["dropped"])
    print(json.dumps({"questions": len(rows), "retained": sum(len(row["constraints"]) for row in rows),
                      "dropped": sum(reasons.values()), "dropped_by_reason": dict(reasons),
                      "frozen_constraints_sha256": sha256(data).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
