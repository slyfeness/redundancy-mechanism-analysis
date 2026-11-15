"""Verify 187299 inputs, run one result-label pass and export sample packets."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
from time import perf_counter

from check import annotations, batches, corpus_index, decode, file_sha, jsonl, read_json, write_new
from result_labels import annotate, combine, report
from snippet import hits
from snippet_pilot import LocalJudge, object_schema

PROMPT = Path(__file__).with_name("same_query_prompt.md")
SEED = "20261120|"


def ranked(rows, n):
    return sorted(rows, key=lambda row: (sha256((SEED + row["id"]).encode()).digest(), row["id"]))[:n]


def prepare(snapshot):
    root = Path(snapshot["dataset_assets"])
    corp = sorted((root / "corpus/data").glob("*.parquet"))
    data = sorted((root / "questions/data").glob("*.parquet"))
    card = root / "questions/README.md"
    assets = {path.relative_to(root).as_posix(): file_sha(path) for path in [card, *data, *corp]}
    if assets != snapshot["asset_snapshot_sha256"]:
        raise ValueError("asset SHA-256 differs from 187299")
    inventory_path = Path(snapshot["input_index"])
    index_sha = file_sha(inventory_path)
    if index_sha != read_json(snapshot["phase1_manifest"])["freeze"]["input_index_sha256"]:
        raise ValueError("inventory SHA-256 differs from 187221")
    inventory = jsonl(inventory_path)
    questions = {}
    for row in inventory:
        qid = str(row["question_id"])
        if questions.setdefault(qid, row["question"]) != row["question"]:
            raise ValueError("inconsistent question identity")
    if len(questions) != 100 or set(Counter(str(r["question_id"]) for r in inventory).values()) != {4}:
        raise ValueError("expected 100 questions and 400 trajectories")
    key = sha256(re.search(r'^CANARY = "([^"]+)"$', card.read_text(encoding="utf-8"), re.M)[1].encode()).digest()
    corpus = corpus_index(corp, key)
    qrels = annotations(data, questions, corpus, key)
    answers = {}
    for row in batches(data, ["query_id", "query", "answer"]):
        qid = str(row["query_id"])
        if qid in questions:
            answers[qid] = row["answer"] if row["query"] == questions[qid] else decode(row["answer"], key)
    if answers.keys() != questions.keys():
        raise ValueError("incomplete reference answer lookup")

    visibility_path = Path(snapshot["visibility_receipts"])
    visibility_sha = file_sha(visibility_path)
    receipts = jsonl(visibility_path)
    visibility = {(r["trajectory_id"], str(r["recorded_event_id"])): r for r in receipts}
    tracks, observed = [], set()
    for row in inventory:
        tid, qid = row["trajectory_id"], str(row["question_id"])
        blob = Path(row["path"]).read_bytes()
        if sha256(blob).hexdigest() != row["sha256"]:
            raise ValueError(f"raw trajectory SHA mismatch: {tid}")
        raw = json.loads(blob)
        events = []
        for event in raw["tool_events"]:
            identity = (tid, str(event["event_id"]))
            receipt = visibility[identity]
            if (identity in observed or event["tool_name"] != "search-server-search"
                    or receipt["tool_name"] != event["tool_name"] or receipt["round_id"] != event["round_id"]):
                raise ValueError(f"wrong visibility identity: {identity}")
            observed.add(identity)
            visible = bool(receipt["visible_next"])
            payload = event.get("exact_result")
            if visible and (payload != receipt["return_text"] or receipt["error"]):
                raise ValueError(f"wrong visible return binding: {identity}")
            passages = hits(payload) if visible else []
            if any(docid not in corpus.ids for docid, _ in passages):
                raise ValueError(f"unknown DocID: {identity}")
            events.append({"id": ":".join(identity), "round": event["round_id"], "visible": visible,
                           "query": json.loads(event["exact_arguments"])["query"],
                           "docs": [docid for docid, _ in passages], "hits": passages})
        status = row["result"]
        if status in ("C", "W"):
            outcome = {"C": "correct", "W": "wrong"}[status]
        else:
            final = row["termination_reason"] == "MODEL_FINAL_STOP" and bool(
                (raw["rounds"][-1].get("content") or "").strip())
            outcome = "final_unscored" if final else "no_final"
        labels = qrels[qid]
        tracks.append({"id": tid, "qid": qid, "outcome": outcome,
                       "events": annotate(events, labels["evidence_docs"], labels["gold_docs"])})
    count = sum(len(track["events"]) for track in tracks)
    returned = sum(event["visible"] for track in tracks for event in track["events"])
    if len(visibility) != len(receipts) or observed != visibility.keys() or (count, returned) != (5114, 4872):
        raise ValueError("search counts differ from the sealed source")
    return tracks, questions, answers, qrels, {"input_index_sha256": index_sha,
                                                   "visibility_receipts_sha256": visibility_sha,
                                                   "asset_snapshot_sha256": assets}


def parse_same(value, allowed):
    if (not isinstance(value, dict) or value.keys() != {"reason", "same_as"}
            or not isinstance(value["reason"], str) or not isinstance(value["same_as"], list)
            or any(type(i) is not int or i not in allowed for i in value["same_as"])):
        raise ValueError("invalid query comparison")
    return sorted(set(value["same_as"]))


def compare(tracks, questions, runtime, out):
    cache = out / "model_cache"
    cache.mkdir(mode=0o700)
    judge = LocalJudge(runtime, cache, {"same_query": PROMPT.read_text(encoding="utf-8")})
    work = []
    for track in tracks:
        lookup = {row["id"]: row for row in track["events"]}
        work.extend((row, lookup, questions[track["qid"]]) for row in lookup.values() if row["eligible"])

    def run(item):
        row, lookup, question = item
        prior = [{"number": i, "query": lookup[eid]["query"]} for i, eid in enumerate(row["candidates"], 1)]
        options = list(range(1, len(prior) + 1))
        array = {"type": "array", "items": {"type": "integer", "enum": options or [1, 2, 3]}}
        if not prior:
            array["maxItems"] = 0
        schema = object_schema(reason={"type": "string"}, same_as=array)
        data = {"question": question, "current_query": row["query"], "earlier_queries": prior}
        answer = judge.ask("same_query", row["id"], {"constraints": [{"constraint_id": i} for i in options]},
                           data, schema=schema, validate=parse_same)
        return row["id"], answer

    start = perf_counter()
    with ThreadPoolExecutor(max_workers=runtime["workers"]) as pool:
        comparisons = dict(pool.map(run, work))
    cost = {"requests": len(work), "failed": sum(answer is None for answer in comparisons.values()),
            "retries": 0, "seconds": round(perf_counter() - start, 3)}
    if len(list(cache.glob("*.json"))) != len(work):
        raise RuntimeError("comparison receipt count does not reconcile")
    write_new(out / "comparison_cost.json", cost)
    write_new(out / "comparisons.private.json", comparisons)
    if cost["failed"]:
        raise RuntimeError("one or more query comparisons failed")
    return comparisons, cost


def audit_samples(tracks, questions, answers, qrels, comparisons):
    buckets = {key: [] for key in ("definite_nonexact", "soft", "effective", "ineffective",
                                   "repeat_query", "same_pair", "different_pair")}
    limits = dict(zip(buckets, (20, 20, 15, 15, 10, 15, 15)))
    pointers = {}
    for track in tracks:
        for row in track["events"]:
            eid = row["id"]
            pointers[eid] = track, row
            final = combine(row, comparisons)
            if row["main"] in {"effective", "ineffective", "repeat_query"}:
                buckets[row["main"]].append({"id": eid, "event_id": eid})
            if final == "definite_redundancy" and row["main"] != "repeat_query":
                buckets["definite_nonexact"].append({"id": eid, "event_id": eid})
            if final == "soft_redundancy":
                buckets["soft"].append({"id": eid, "event_id": eid})
            if comparisons is not None and eid in comparisons:
                for i, candidate in enumerate(row["candidates"], 1):
                    group = "same_pair" if i in comparisons[eid] else "different_pair"
                    buckets[group].append({"id": f"{eid}|{candidate}", "event_id": eid, "candidate_id": candidate})

    def pair_details(item):
        track, row = pointers[item["event_id"]]
        qid = track["qid"]
        if "candidate_id" in item:
            candidate = pointers[item["candidate_id"]][1]
            return {**item, "qid": qid, "question": questions[qid],
                    "query": row["query"], "earlier_query": candidate["query"]}
        previous = [past for past in track["events"] if past["round"] < row["round"]]
        intentions = (comparisons or {}).get(row["id"], [])
        return {**item, "qid": qid, "question": questions[qid], "answer": answers[qid],
                "query": row["query"], "flags": row["flags"],
                "evidence": sorted(qrels[qid]["evidence_docs"]), "gold": sorted(qrels[qid]["gold_docs"]),
                "earlier": [{"id": p["id"], "query": p["query"], "docs": p["docs"]} for p in previous],
                "selected": [row["candidates"][i - 1] for i in intentions],
                "other_candidates": row["candidates"], "new_docs": row["new_docs"], "hits": row["hits"]}

    return {key: {"population": len(rows), "samples": [pair_details(row) for row in ranked(rows, limits[key])]}
            for key, rows in buckets.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    start = perf_counter()
    tracks, questions, answers, qrels, identity = prepare(read_json(args.snapshot))
    preparation_seconds = round(perf_counter() - start, 3)
    print("inputs_verified", len(tracks), flush=True)
    comparisons, cost = (compare(tracks, questions, read_json(args.runtime), args.output)
                         if args.runtime else (None, {"requests": 0, "failed": 0, "retries": 0, "seconds": 0}))
    summary, sequences = report(tracks, comparisons)
    summary["comparison_cost"] = cost
    write_new(args.output / "result_labels.json", summary)
    with (args.output / "result_label_sequences.jsonl").open("x", encoding="utf8", newline="\n") as stream:
        for sequence in sequences:
            stream.write(json.dumps(sequence, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_new(args.output / "review.private.json", audit_samples(tracks, questions, answers, qrels, comparisons))
    config = {**identity, "source_snapshot_job": 187299, "source_inventory_job": 187221,
              "source_config_sha256": file_sha(args.snapshot), "code_commit": args.commit,
              "prompt_sha256": file_sha(PROMPT), "preparation_seconds": preparation_seconds,
              "temperature": 0, "reasoning_effort": "low", "workers": 16, "max_num_seqs": 16, "retry_limit": 0,
              "sample_seed": 20261120, "outcome_source": "frozen_historical_independent_answer_review",
              "uses_approximation": int(comparisons is None)}
    write_new(args.output / "config.json", config)
    print("analysis_complete", cost["requests"], flush=True)


if __name__ == "__main__":
    main()
