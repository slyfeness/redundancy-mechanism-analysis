"""Materialize only the question/DocID relationships from the verified 187299 assets."""

import argparse
from base64 import b64decode
from hashlib import sha256
import json
from pathlib import Path
import re

from pyarrow.parquet import ParquetFile


def digest(path):
    with path.open("rb") as handle:
        return sha256_file(handle)


def sha256_file(handle):
    result = sha256()
    for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def rows(paths, columns):
    for path in paths:
        for batch in ParquetFile(path).iter_batches(columns=columns, batch_size=128):
            yield from batch.to_pylist()


def freeze(snapshot_path, output):
    snapshot = json.loads(snapshot_path.read_bytes())
    assets = Path(snapshot["dataset_assets"])
    card = assets / "questions/README.md"
    corpus = sorted((assets / "corpus/data").glob("*.parquet"))
    questions = sorted((assets / "questions/data").glob("*.parquet"))
    current = {p.relative_to(assets).as_posix(): digest(p) for p in (card, *corpus, *questions)}
    if current != snapshot["asset_snapshot_sha256"]:
        raise ValueError("DocID annotations/corpus differ from 187299")
    inventory_path = Path(snapshot["input_index"])
    freeze_manifest = json.loads(Path(snapshot["phase1_manifest"]).read_bytes())["freeze"]
    if digest(inventory_path) != freeze_manifest["input_index_sha256"]:
        raise ValueError("inventory differs from 187221")
    with inventory_path.open(encoding="utf8") as stream:
        inventory = {str(row["question_id"]): row["question"] for line in stream
                     if line.strip() and (row := json.loads(line))}
    key = sha256(re.search(r'^CANARY = "([^"]+)"$', card.read_text(encoding="utf8"), re.M)[1].encode()).digest()

    def decode(value):
        buffer = b64decode(value, validate=True)
        return bytes(byte ^ key[i % len(key)] for i, byte in enumerate(buffer)).decode()

    docs = set()
    for row in rows(corpus, ["docid"]):
        token = row["docid"]
        identifier = token if token.isascii() and token.isdecimal() else decode(token)
        if not identifier.isascii() or not identifier.isdecimal() or identifier in docs:
            raise ValueError("invalid or duplicate corpus DocID")
        docs.add(identifier)

    def identifier(value):
        result = value if value in docs else decode(value)
        if result not in docs:
            raise ValueError("official label DocID outside corpus")
        return result

    schema = ParquetFile(questions[0]).schema
    fields = [schema.column(i).path for i in range(len(schema))]
    columns = ["query_id", "query"] + [field for field in fields if field.split(".")[0] in {
        "evidence_docs", "gold_docs"} and field.endswith(".docid")]
    matched = {}
    for row in rows(questions, columns):
        qid = str(row["query_id"])
        if qid not in inventory:
            continue
        if qid in matched or (row["query"] != inventory[qid] and decode(row["query"]) != inventory[qid]):
            raise ValueError("official question identity mismatch")
        matched[qid] = {"question_id": qid, **{
            name: sorted({identifier(item["docid"]) for item in row[field] or []}, key=int)
            for name, field in (("evidence", "evidence_docs"), ("gold", "gold_docs"))}}
    if len(inventory) != 100 or matched.keys() != inventory.keys():
        raise ValueError("frozen cohort annotation count differs")
    with output.open("x", encoding="utf8", newline="\n") as stream:
        for qid in sorted(matched, key=int):
            stream.write(json.dumps(matched[qid], separators=(",", ":")) + "\n")
    print("docid_labels_frozen", len(matched), digest(output), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    freeze(args.snapshot, args.output)
