"""Bind the v6 scope and prepare the labelled-only Gold Judge inputs."""

from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path
import sys

FROZEN = "judge-v6-192949/results"
FREEZE_SHA = "84308847dd3d710d764078ad5f00251d9fe9bd537155ddc5d1936b22ab05f4d6"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def bind(root, v6_control):
    baseline = root / FROZEN
    if digest(baseline / "FROZEN.json") != FREEZE_SHA:
        raise ValueError("unrecognized v6 freeze receipt")
    frozen = read(baseline / "FROZEN.json")
    if (digest(v6_control / "judge_v6/judgement.py") != frozen["sources_sha256"]["judgement.py"]
            or digest(baseline / "plan.json") != frozen["plan_sha256"]
            or digest(baseline / "private_prompts.json") != frozen["private_prompts_sha256"]):
        raise ValueError("frozen v6 scope, prompt or settlement changed")
    return read(baseline / "plan.json"), frozen


def collect_docs(root, questions):
    cache = read(root / "docs-192072/evidence_docs.json")
    needed = {str(docid) for row in questions.values() for key in ("gold_docs", "evidence_docs")
              for docid in row[key]}
    selected = {key: cache[key] for key in needed & cache.keys()}
    missing = needed - selected.keys()
    if missing:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        corpus = root.parents[2] / "新实验/assets/browsecomp-plus/corpus"
        domain = pa.array(sorted(missing), type=pa.string())
        for path in sorted(corpus.rglob("*.parquet")):
            for batch in pq.ParquetFile(path).iter_batches(columns=["docid", "text"], batch_size=2048):
                match = pc.is_in(pc.cast(batch.column(0), pa.string()), value_set=domain)
                for row in batch.filter(match).to_pylist():
                    docid = str(row["docid"])
                    if docid in selected:
                        raise ValueError("duplicate corpus document id")
                    selected[docid] = row["text"]
    if selected.keys() != needed:
        raise ValueError(f"{len(needed - selected.keys())} labelled documents missing")
    return selected, len(missing)


def passages(v4, source, labels):
    gold, evidence = ([str(docid) for docid in labels[key]] for key in ("gold_docs", "evidence_docs"))
    result = []
    for index, docid in enumerate(dict.fromkeys(gold + evidence), 1):
        pid, text = f"g{index}", source[docid]
        result.append({"id": pid, "unit_id": index, "docid": docid, "text": text,
                       "labels": [label for label, group in (("gold", gold), ("evidence", evidence)) if docid in group],
                       "sentences": v4.sentences(text, pid)})
    return result


def main():
    parser = ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--v4-control", type=Path, required=True)
    parser.add_argument("--v6-control", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.v4_control / "judge_v4"))
    import pilot as v4

    plan, frozen = bind(args.root, args.v6_control)
    labels, _, outcomes = v4.previous_driver.training(args.root)
    selected = {qid: labels[qid] for qid in plan["questions"]}
    tids = plan["old_trajectories"] + plan["new_trajectories"]
    if len(selected) != 20 or len(set(tids)) != 40 or any(
            outcomes[tid]["question_id"] != plan["trajectory_question"][tid] for tid in tids):
        raise ValueError("v6 training sample mismatch")
    source, recovered = collect_docs(args.root, selected)
    gold = {qid: passages(v4, source, labels) for qid, labels in selected.items()}
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True, model_max_length=1_000_000)
    sizes = {}
    for qid, docs in gold.items():
        view = [{"sentences": [{"id": s["id"], "text": s["text"]} for s in doc["sentences"]]} for doc in docs]
        sizes[qid] = len(tok.encode(json.dumps(view, ensure_ascii=False), add_special_tokens=False))
    if max(sizes.values()) > 112_000:
        print(json.dumps({"oversize_question_ids": [qid for qid, size in sizes.items() if size > 112_000],
                          "gold_input_max_tokens": max(sizes.values())}), flush=True)
        raise ValueError("complete labelled context exceeds the reserved Judge input budget")
    args.out.mkdir(mode=0o700, exist_ok=False)
    v4.dump(args.out / "gold_passages.json", gold)
    receipt = {"plan_sha256": frozen["plan_sha256"], "judge_source_sha256": frozen["sources_sha256"]["judgement.py"],
               "gold_sha256": digest(args.out / "gold_passages.json"), "questions": len(selected),
               "trajectories": len(tids), "distinct_corpus_documents": len(source),
               "recovered_gold_documents": recovered, "max_gold_input_tokens": max(sizes.values()),
               "full_documents": True}
    v4.dump(args.out / "PREP.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
