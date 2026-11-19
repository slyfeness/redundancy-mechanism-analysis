"""Freeze the ID split before projecting the sampled questions."""
import hashlib
import json
import os
import random
import re
import sys
from base64 import b64decode
from pathlib import Path

from pyarrow.parquet import ParquetFile


SPLIT_SEED = 20261118
SAMPLE_SEED = 20261119
ACTOR_SEED = 20261110


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def split_ids(ids):
    if len(ids) != 830 or len(set(ids)) != 830:
        raise ValueError("Expected 830 unique official question IDs")
    ordered = sorted(ids, key=int)
    random.Random(SPLIT_SEED).shuffle(ordered)
    train, test = ordered[:664], ordered[664:]
    return {"train": train, "test": test}, random.Random(SAMPLE_SEED).sample(train, 50)


def dump(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main(snapshot, out):
    config = json.loads(snapshot.read_bytes())
    assets = Path(config["dataset_assets"])
    card = assets / "questions/README.md"
    files = sorted((assets / "questions/data").glob("*.parquet"))
    assert len(files) == 6
    for path in (card, *files):
        assert digest(path) == config["asset_snapshot_sha256"][path.relative_to(assets).as_posix()]
    ids = [str(qid) for path in files for qid in ParquetFile(path).read(columns=["query_id"])[0].to_pylist()]
    split, chosen = split_ids(ids)
    out.mkdir(mode=0o700, exist_ok=False)
    dump(out / "split.json", split)
    key = hashlib.sha256(re.search(r'^CANARY = "([^"]+)"$', card.read_text(encoding="utf-8"), re.M)[1].encode()).digest()

    def decode(value):
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(b64decode(value, validate=True))).decode()

    def docids(items):
        ids = [row["docid"] for row in items]
        return sorted({d if d.isdecimal() else decode(d) for d in ids}, key=int)

    selected = {}
    for path in files:
        parquet = ParquetFile(path)
        fields = [parquet.schema.column(i).path for i in range(len(parquet.schema))]
        labels = [field for field in fields if field.split(".")[0] in {"evidence_docs", "gold_docs"}
                  and field.endswith(".docid")]
        assert len(labels) == 2
        for group in range(parquet.num_row_groups):
            group_ids = parquet.read_row_group(group, columns=["query_id"])[0].to_pylist()
            selected_positions = [i for i, qid in enumerate(group_ids) if str(qid) in chosen]
            if not selected_positions:
                continue
            rows = parquet.read_row_group(group, columns=["query_id", "query", "answer", *labels]).take(
                selected_positions).to_pylist()
            for row in rows:
                qid = str(row["query_id"])
                assert qid not in selected and qid in chosen
                selected[qid] = {
                    "id": qid, "question": decode(row["query"]), "answers": [decode(row["answer"])],
                    "evidence_docs": docids(row["evidence_docs"]), "gold_docs": docids(row["gold_docs"]),
                }
    assert len(selected) == len(chosen) == 50 and not (selected.keys() & set(split["test"]))
    ordered = [selected[qid] for qid in chosen]
    tasks = [
        {"query_id": row["id"], "repetition_id": rep + 1, "seed": ACTOR_SEED + index * 8 + rep,
         "run_id": f"{row['id']}__rep{rep + 1}", "question_sha256": hashlib.sha256(row["question"].encode()).hexdigest()}
        for index, row in enumerate(ordered) for rep in range(8)
    ]
    assert len({task["run_id"] for task in tasks}) == 400
    dump(out / "actor_questions.json", [{k: row[k] for k in ("id", "question")} for row in ordered])
    dump(out / "evaluation_private.json", ordered)
    dump(out / "task_manifest.json", {"tasks": tasks})
    dump(out / "selection.json", {"split_seed": SPLIT_SEED, "sample_seed": SAMPLE_SEED,
         "actor_seed_base": ACTOR_SEED, "training_ids": chosen, "train_count": 664, "test_count": 166,
         "split_sha256": digest(out / "split.json"), "test_questions_decoded": 0, "reused_trajectories": 0,
         "job_id": int(os.environ["SLURM_JOB_ID"]), "questions_snapshot_verified": True})
    print("prepared 50 train questions and 400 tasks", flush=True)


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
