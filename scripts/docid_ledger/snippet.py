"""Bind visible search passages to the frozen traces and measure passage coverage."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import median

from check import annotations, batches, corpus_index, decode, decoded_id, file_sha, jsonl, read_json, write_new
from ledger import document_id, normalized, records


SEED = "20261117|"


def digest(text):
    return sha256(text.encode()).hexdigest()


def select_ids(identifiers, limit):
    return sorted(identifiers, key=lambda identifier: (digest(SEED + identifier), identifier))[:limit]


def hits(text):
    value = records(text)
    result = []
    for row in value:
        identifier = document_id(row.get("docid"))
        passage = row.get("snippet")
        if identifier is None or not isinstance(passage, str):
            raise ValueError("search return missing its structured docid or snippet")
        result.append((identifier, passage))
    return result


def passage_key(qid, docid, text):
    return qid, docid, digest(normalized(text))


def stability(groups):
    one = sum(len(hashes) == 1 for hashes in groups.values())
    total = len(groups)
    return {"groups": total, "one": one, "multiple": total - one, "one_ratio": one / total if total else None,
            "multiple_ratio": (total - one) / total if total else None}


def distribution(items):
    values = sorted(items)
    if not values:
        return dict.fromkeys(("min", "p05", "p25", "median", "p75", "p95", "max", "mean"))

    def percentile(q):
        index = q * (len(values) - 1)
        lower = int(index)
        return values[lower] + (index - lower) * (values[min(lower + 1, len(values) - 1)] - values[lower])

    return {"min": values[0], "p05": percentile(.05), "p25": percentile(.25), "median": median(values),
            "p75": percentile(.75), "p95": percentile(.95), "max": values[-1], "mean": sum(values) / len(values)}


def wanted_lengths(paths, index, key, wanted):
    lengths = {}
    for row in batches(paths, ["docid", "text"]):
        raw = row["docid"]
        identifier = decoded_id(raw, index, key)
        if identifier in wanted:
            text = row["text"] if raw == identifier else decode(row["text"], key)
            lengths[identifier] = len(text)
    if lengths.keys() != wanted or any(size <= 0 for size in lengths.values()):
        raise ValueError("missing or empty full corpus documents")
    return lengths


def measure(config):
    assets = Path(config["dataset_assets"])
    for relative, expected in config["asset_snapshot_sha256"].items():
        if file_sha(assets / relative) != expected:
            raise RuntimeError("the checked corpus/annotation snapshot has changed")
    frozen = read_json(config["phase1_manifest"])["freeze"]
    if (file_sha(Path(config["input_index"])) != frozen["input_index_sha256"]
            or file_sha(Path(config["frozen_constraints"])) != frozen["frozen_constraints_sha256"]):
        raise RuntimeError("frozen trajectory inventory or v4 constraint identity differs")
    inventory = jsonl(config["input_index"])
    questions = {str(row["question_id"]): row["question"] for row in inventory}
    if len(questions) != 100 or set(Counter(str(row["question_id"]) for row in inventory).values()) != {4}:
        raise RuntimeError("expected 400 frozen trajectories across 100 queries")
    constraints = {str(row["question_id"]): row for row in jsonl(config["frozen_constraints"])}
    if constraints.keys() != questions.keys() or any(row["question_sha256"] != digest(questions[qid])
                                                     for qid, row in constraints.items()):
        raise RuntimeError("v4 constraint text differs from inventory")
    chosen = select_ids(questions, 10)
    card = (assets / "questions/README.md").read_text(encoding="utf-8")
    key = sha256(re.search(r'^CANARY = "([^"]+)"$', card, re.M)[1].encode()).digest()
    corp = sorted((assets / "corpus/data").glob("*.parquet"))
    data = sorted((assets / "questions/data").glob("*.parquet"))
    index = corpus_index(corp, key)
    qrels = annotations(data, questions, index, key)
    pilot_tasks = {}
    for row in batches(data, ["query_id", "query", "answer"]):
        qid = str(row["query_id"])
        if qid in chosen:
            answer = row["answer"] if row["query"] == questions[qid] else decode(row["answer"], key)
            pilot_tasks[qid] = {"question": questions[qid], "answer": answer,
                                "constraints": constraints[qid]["constraints"]}
    if set(pilot_tasks) != set(chosen):
        raise RuntimeError("cannot bind every pilot query to a reference answer")
    receipts = jsonl(config["visibility_receipts"])
    visibility = {(row["trajectory_id"], str(row["recorded_event_id"])): row for row in receipts}
    observed = set()
    pairs_by_trace, pairs_by_query = defaultdict(set), defaultdict(set)
    evidence_keys, pilot_passages, pilot_tracks = set(), {}, []
    sizes = Counter()
    visible_returns = 0
    for row in inventory:
        tid, qid = row["trajectory_id"], str(row["question_id"])
        raw = Path(row["path"]).read_bytes()
        if sha256(raw).hexdigest() != row["sha256"]:
            raise RuntimeError("frozen raw trace digest mismatch")
        track = []
        for event in json.loads(raw)["tool_events"]:
            identity = (tid, str(event["event_id"]))
            receipt = visibility[identity]
            if (identity in observed or event["tool_name"] != "search-server-search"
                    or receipt["tool_name"] != event["tool_name"] or receipt["round_id"] != event["round_id"]):
                raise RuntimeError("tool event binding mismatch")
            observed.add(identity)
            payload = event.get("exact_result")
            visible = receipt["visible_next"]
            eligible = []
            passages = []
            if visible:
                if receipt["return_text"] != payload or receipt["error"]:
                    raise RuntimeError("visible return does not match the frozen raw tool response")
                visible_returns += 1
                passages = hits(payload)
                for docid, text in passages:
                    if docid not in index.ids:
                        raise RuntimeError("search docid absent from the frozen corpus")
                    sizes[docid, len(text)] += 1
                    pkey = passage_key(qid, docid, text)
                    pairs_by_trace[tid, docid].add(pkey[2])
                    pairs_by_query[qid, docid].add(pkey[2])
                    if docid in qrels[qid]["evidence_docs"]:
                        evidence_keys.add(pkey)
                        if qid in chosen:
                            pid = ":".join(pkey)
                            eligible.append(pid)
                            pilot_passages.setdefault(pid, {"query_id": qid, "docid": docid, "passage": text})
            if qid in chosen:
                track.append({"id": ":".join(identity), "round": event["round_id"], "visible": visible,
                              "query": json.loads(event["exact_arguments"])["query"],
                              "return_hash": digest(payload) if isinstance(payload, str) else None,
                              "hits": passages, "passages": sorted(set(eligible))})
        if qid in chosen:
            pilot_tracks.append({"trajectory_id": tid, "query_id": qid, "events": track})
    if observed != visibility.keys() or len(visibility) != len(receipts) or visible_returns != 4872:
        raise RuntimeError("visible search inventory does not match the sealed source")
    full_lengths = wanted_lengths(corp, index, key, {docid for docid, _ in sizes})
    exact, ratios = [], []
    for (docid, size), count in sizes.items():
        exact.extend([size] * count)
        ratios.extend([size / full_lengths[docid]] * count)
    summary = {
        "queries": len(questions), "trajectories": len(inventory), "visible_returns": visible_returns,
        "passage_occurrences": len(exact), "unique_corpus_docids": len(full_lengths),
        "passage_characters": distribution(exact), "passage_to_full_character_ratio": distribution(ratios),
        "ratio_over_one": sum(ratio > 1 for ratio in ratios),
        "by_trajectory_docid": stability(pairs_by_trace), "by_query_docid": stability(pairs_by_query),
        "unique_evidence_passages_100_queries": len(evidence_keys),
        "unique_evidence_passages_10_queries": len(pilot_passages),
        "model_requests": 0,
    }
    return summary, {"query_ids": chosen, "tasks": pilot_tasks, "passages": pilot_passages, "tracks": pilot_tracks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700)
    summary, packet = measure(read_json(args.config))
    write_new(args.output / "snippet_check.json", summary)
    write_new(args.output / "inputs.private.json", packet)


if __name__ == "__main__":
    main()
