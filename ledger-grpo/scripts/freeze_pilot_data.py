"""Freeze one training batch and independent pilot evaluation, under CPU Slurm."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    import pyarrow.parquet as pq
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-source", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--decrypt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    old = json.loads((args.old_source / "PLAN.json").read_bytes())
    excluded = {qid for group in old["training"] for qid in group}
    if len(excluded) != 160:
        raise ValueError("old training exclusion set changed")
    train_ids = old["training"][0]
    shards = sorted(args.questions.glob("test-*.parquet"))
    ids = [str(qid) for shard in shards for qid in pq.read_table(shard, columns=["query_id"])["query_id"].to_pylist()]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question IDs")
    eval_ids = sorted(set(ids)-excluded, key=lambda qid: hashlib.sha256(("ledger-pilot-eval-20261111:" + qid).encode()).digest())[:16]
    if len(eval_ids) != 16 or set(eval_ids) & set(train_ids):
        raise ValueError("independent evaluation split unavailable")
    public = {"seed": 20261111, "training_ids": train_ids, "evaluation_ids": eval_ids,
              "excluded_old_training_ids": sorted(excluded), "official_source_split": "test",
              "purpose": "exploratory algorithm pilot; not official benchmark training/test split",
              "selection": "metadata IDs frozen before evaluation question/answer decoding",
              "generation": {"temperature": 1., "top_p": 1., "top_k": 0, "thinking": True,
                             "context": 65536, "guard": 256, "max_tokens_per_call": 10000,
                             "max_actor_calls": 20, "queries": 16, "samples_per_query": 8},
              "training": {"steps_per_arm": 1, "arms": ["outcome", "ledger"], "lr": 1e-6,
                           "tis_cap": 2, "grad_clip": 1., "kl": 0., "loss_reduction": "global_token_mean",
                           "budget_failure_policy": "outcome_only", "training_seed": 20261109},
              "interpretation": "single-update single-seed feasibility, not a convergence or noninferiority study"}
    write(args.output / "SPLIT_FREEZE.json", public)
    source = args.decrypt.read_text()
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"derive_key", "decrypt_string"}]
    password = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "DEFAULT_CANARY" for t in n.targets))
    namespace = {"base64": base64, "hashlib": hashlib}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(args.decrypt), "exec"), namespace)
    selected = {}
    for shard in shards:
        for row in pq.read_table(shard, columns=["query_id", "query", "answer"]).to_pylist():
            qid = str(row["query_id"])
            if qid not in eval_ids:
                continue
            question = namespace["decrypt_string"](row["query"], password)
            gold = namespace["decrypt_string"](row["answer"], password)
            if not question.strip() or not gold.strip():
                raise ValueError("empty evaluation question/answer")
            selected[qid] = {"query_id": qid, "question": question, "gold": gold,
                             "question_sha256": hashlib.sha256(question.encode()).hexdigest()}
    train_rows = [old["questions"][qid] for qid in train_ids]
    if {r["question_sha256"] for r in train_rows} & {r["question_sha256"] for r in selected.values()}:
        raise ValueError("question text crosses train/evaluation boundary")
    write(args.output / "PRIVATE_PLAN.json", dict(public, training_rows=train_rows,
                                                evaluation_rows=[selected[qid] for qid in eval_ids]))
    write(args.output / "SOURCE_IDENTITIES.json", {
        "old_plan": hashlib.sha256((args.old_source / "PLAN.json").read_bytes()).hexdigest(),
        "decrypt": hashlib.sha256(args.decrypt.read_bytes()).hexdigest(),
        "question_shards": {p.name: hashlib.file_digest(p.open("rb"), "sha256").hexdigest() for p in shards}})
    print(json.dumps({"state": "completed", "train_questions": 16, "evaluation_questions": 16,
                      "excluded_old_questions": 160, "optimizer_steps": 0}), flush=True)


if __name__ == "__main__":
    main()
