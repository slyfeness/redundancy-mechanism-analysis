"""Project only the frozen training IDs before decoding task fields."""

from argparse import ArgumentParser
from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256, file_digest
import json
import os
from pathlib import Path
import re
import sys

SPLIT_SHA = "f2f49b77abd8a7c64c4f0640f6add75506afc58720a6888982df9873438ddf67"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def train_selection(root):
    frozen = root.parent / "round4_bcplus/selection"
    path = frozen / "split.json"
    roster = read(path)
    if digest(path) != SPLIT_SHA or read(frozen / "selection.json")["split_sha256"] != SPLIT_SHA:
        raise ValueError("frozen round4 split changed")
    train, heldout = set(roster["train"]), set(roster["test"])
    if len(train) != 664 or len(heldout) != 166 or train & heldout:
        raise ValueError("invalid frozen membership")
    return train, heldout, read(frozen / "evaluation_private.json")


def train_labels(root, assets):
    from pyarrow.parquet import ParquetFile

    train, heldout, original = train_selection(root)
    card = assets / "questions/README.md"
    files = sorted((assets / "questions/data").glob("*.parquet"))
    if len(files) != 6:
        raise ValueError("expected six original question shards")
    seed = re.search(r'^CANARY = "([^"]+)"$', card.read_text(encoding="utf-8"), re.M)
    if not seed:
        raise ValueError("official decoder metadata missing")
    mask = sha256(seed[1].encode()).digest()

    def decode(value):
        return bytes(byte ^ mask[i % len(mask)] for i, byte in enumerate(b64decode(value, validate=True))).decode()

    def ids(items):
        values = [str(row["docid"]) for row in items]
        return sorted({v if v.isdecimal() else decode(v) for v in values}, key=int)

    selected, official = {}, set()
    for path in files:
        parquet = ParquetFile(path)
        schema = [parquet.schema.column(i).path for i in range(len(parquet.schema))]
        columns = [field for field in schema if field.split(".")[0] in {"evidence_docs", "gold_docs"}
                   and field.endswith(".docid")]
        if len(columns) != 2:
            raise ValueError("annotation schema mismatch")
        for group in range(parquet.num_row_groups):
            group_ids = list(map(str, parquet.read_row_group(group, columns=["query_id"])[0].to_pylist()))
            if len(set(group_ids)) != len(group_ids) or official.intersection(group_ids):
                raise ValueError("duplicate official question id")
            official.update(group_ids)
            positions = [i for i, qid in enumerate(group_ids) if qid in train]
            if not positions:
                continue
            # Only projected training rows reach Python or the decoder.
            table = parquet.read_row_group(group, columns=["query_id", "query", "answer", *columns])
            for row in table.take(positions).to_pylist():
                qid = str(row["query_id"])
                if qid not in train or qid in heldout:
                    raise ValueError("non-training question reached the decoder")
                selected[qid] = {"id": qid, "question": decode(row["query"]), "answers": [decode(row["answer"])],
                                 "evidence_docs": ids(row["evidence_docs"]), "gold_docs": ids(row["gold_docs"])}
    if official != train | heldout or selected.keys() != train:
        raise ValueError("question roster mismatch")
    if any(row != selected[row["id"]] for row in original):
        raise ValueError("official projection differs from the 50 frozen training receipts")
    return dict(sorted(selected.items(), key=lambda pair: int(pair[0]))), {row["id"] for row in original}


def main():
    parser = ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--v4", type=Path, required=True)
    parser.add_argument("--v61", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.v61 / "judge_v61"))
    from prepare import collect_docs
    sys.path.insert(0, str(args.v4 / "judge_v4"))
    import pilot as v4
    from transformers import AutoTokenizer

    root = args.root
    assets = root.parents[2] / "新实验/assets/browsecomp-plus"
    questions, round4 = train_labels(root, assets)
    bodies, additional = collect_docs(root, questions)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, model_max_length=1_000_000)

    def size(item):
        docid, text = item
        numbered = v4.sentences(text, "g1")
        gold = [{"id": s["id"], "text": s["text"]} for s in numbered]
        return docid, (len(tokenizer.encode(text, add_special_tokens=False)),
                       len(tokenizer.encode(json.dumps(gold, ensure_ascii=False), add_special_tokens=False)))

    with ThreadPoolExecutor(max_workers=8) as pool:
        document_sizes = dict(pool.map(size, bodies.items()))
    estimate = {}
    for qid, q in questions.items():
        gold = set(q["gold_docs"]) | set(q["evidence_docs"])
        estimate[qid] = {"assertions": sum(document_sizes[d][0] for d in q["evidence_docs"]),
                         "gold": sum(document_sizes[d][1] for d in gold)}
    args.out.mkdir(mode=0o700, exist_ok=False)
    v4.dump(args.out / "questions.json", questions)
    v4.dump(args.out / "documents.json", bodies)
    v4.dump(args.out / "estimates.json", estimate)
    receipt = {"train": len(questions), "heldout_decoded": 0, "round4_questions": len(round4),
               "round4_ids": sorted(round4, key=int), "distinct_documents": len(bodies),
               "new_corpus_documents": additional, "split_sha256": SPLIT_SHA,
               "question_sha256": digest(args.out / "questions.json"),
               "document_sha256": digest(args.out / "documents.json"),
               "stage2_source": "supplement-m1-192125",
               "over_110k_assertion": sum(q["assertions"] > 110_000 for q in estimate.values()),
               "over_110k_gold": sum(q["gold"] > 110_000 for q in estimate.values()),
               "max_assertion_tokens": max(q["assertions"] for q in estimate.values()),
               "max_gold_tokens": max(q["gold"] for q in estimate.values())}
    v4.dump(args.out / "PREP.json", receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != "round4_ids"}), flush=True)


if __name__ == "__main__":
    main()
