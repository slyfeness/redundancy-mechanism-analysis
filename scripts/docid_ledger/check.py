"""Read the frozen BrowseComp-Plus inventory and emit numeric/ID-only checks."""

import argparse
import base64
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import median

from ledger import DocumentIndex, Observation, SIGNALS, document_id, evidence_exposure, metadata, records


THRESHOLD = 0.8


def jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def file_sha(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode(value, key):
    raw = base64.b64decode(value, validate=True)
    return bytes(byte ^ key[i % len(key)] for i, byte in enumerate(raw)).decode()


def batches(paths, columns):
    from pyarrow import parquet

    for path in paths:
        for batch in parquet.ParquetFile(path).iter_batches(columns=columns, batch_size=128):
            yield from batch.to_pylist()


def corpus_index(paths, key):
    index = DocumentIndex()
    for row in batches(paths, ["docid"]):
        value = row["docid"]
        identifier = value if value.isascii() and value.isdecimal() else decode(value, key)
        if not identifier.isascii() or not identifier.isdecimal() or identifier in index.ids:
            raise ValueError("corpus contains invalid or duplicate docids")
        index.add(identifier)
    return index


def decoded_id(value, index, key):
    if value in index.ids:
        return value
    identifier = decode(value, key)
    if identifier not in index.ids:
        raise ValueError("official qrels contain a docid outside the recorded corpus")
    return identifier


def annotations(paths, questions, index, key):
    from pyarrow import parquet

    schema = parquet.ParquetFile(paths[0]).schema
    fields = [schema.column(i).path for i in range(len(schema))]
    selected = ["query_id", "query"] + [
        path for path in fields if path.split(".")[0] in {"evidence_docs", "gold_docs"} and path.endswith(".docid")
    ]
    matches = {}
    for row in batches(paths, selected):
        qid = str(row["query_id"])
        if qid not in questions:
            continue
        if qid in matches:
            raise ValueError("duplicate official query ID")
        if row["query"] != questions[qid] and decode(row["query"], key) != questions[qid]:
            raise ValueError(f"official query identity differs from frozen trajectory query {qid}")
        matches[qid] = {
            field: {decoded_id(item["docid"], index, key) for item in row[field] or []}
            for field in ("evidence_docs", "gold_docs")
        }
    if matches.keys() != questions.keys():
        raise ValueError("official query IDs do not cover the frozen inventory")
    return matches


def load_aliases(paths, index, key, *, include_text_hash):
    text_hashes = {}
    for row in batches(paths, ["docid", "url", "text"]):
        raw_id = row["docid"]
        identifier = decoded_id(raw_id, index, key)
        plaintext = raw_id == identifier
        url, text = row["url"], row["text"]
        if not plaintext:
            url, text = decode(url, key) if url else url, decode(text, key)
        index.add(identifier, metadata(text).get("title"), url)
        if include_text_hash:
            text_hashes[identifier] = sha256(text.encode()).digest()
    return text_hashes


def kind_of(tool):
    name = re.sub(r"[-_.:/]+", "-", tool.casefold())
    suffix = name.split("-")[-1]
    if suffix == "search":
        return "search"
    if suffix in {"open", "opendocument", "getdocument"} or name.endswith(("open-document", "get-document")):
        return "open"
    return "other"


def arg_docids(args, index):
    result = set()
    for key in ("docid", "document_id", "docids", "document_ids"):
        value = args.get(key)
        values = value if isinstance(value, list) else [value]
        result.update(identifier for item in values if (identifier := document_id(item)) in index.ids)
    return result


def full_open(payload, returned_ids, arguments, text_hashes):
    """Confirm that a returned document equals its full corpus text."""
    entries = records(payload)
    if isinstance(payload, str) and (not entries or entries == [metadata(payload)]):
        entries = [{"text": payload}]
    result = []
    candidates = set(returned_ids) or arguments
    for row in entries:
        text = row.get("text", row.get("content"))
        if not isinstance(text, str):
            continue
        digest = sha256(text.encode()).digest()
        explicit = document_id(row.get("docid", row.get("document_id")))
        possible = {explicit} & candidates if explicit is not None else candidates
        matched = [identifier for identifier in possible if text_hashes.get(identifier) == digest]
        if len(matched) == 1:
            result.extend(matched)
    return tuple(sorted(set(result)))


def distribution(values, *, histogram=False):
    result = {"min": min(values), "median": median(values), "max": max(values),
              "mean": sum(values) / len(values)} if values else {"min": None, "median": None, "max": None, "mean": None}
    if histogram:
        result["histogram"] = dict(sorted(Counter(values).items()))
    return result


def tool_record(counts):
    returned = counts["returns"]
    return {
        "calls": counts["calls"], "returns": returned, "returns_missing": counts["calls"] - returned,
        "returns_with_direct_docid": counts["direct"], "returns_with_any_docid": counts["identified"],
        "return_docid_ratio": counts["identified"] / returned if returned else None,
        "mean_docids_per_return": counts["docids"] / returned if returned else None,
        "returns_without_direct_id_with_url": counts["url"],
        "returns_without_direct_id_with_title": counts["title"],
        "returns_mapped_without_direct_id": counts["mapped"],
        "calls_with_docid_argument": counts["argument"],
        "visible_returns": counts["visible"],
        "verified_full_open_returns": counts["full_open"],
        "verified_full_open_from_argument_only": counts["open_argument_only"],
    }


def open_and_search_gate(by_kind):
    groups = {kind: tool_record(by_kind[kind]) for kind in ("search", "open")}
    return {"threshold": THRESHOLD, "passed": int(all(
                row["return_docid_ratio"] is not None and row["return_docid_ratio"] >= THRESHOLD
                for row in groups.values())),
            "by_kind": groups}


def analyze(config, output):
    inventory_path = Path(config["input_index"])
    inventory = jsonl(inventory_path)
    constraints = jsonl(config["frozen_constraints"])
    frozen = read_json(config["phase1_manifest"])["freeze"]
    if (file_sha(inventory_path) != frozen["input_index_sha256"]
            or file_sha(Path(config["frozen_constraints"])) != frozen["frozen_constraints_sha256"]):
        raise ValueError("frozen input digest differs from 187221")
    questions = {}
    trajectories = Counter()
    for row in inventory:
        qid = str(row["question_id"])
        if questions.setdefault(qid, row["question"]) != row["question"]:
            raise ValueError("inconsistent frozen question text")
        trajectories[qid] += 1
    if len(questions) != 100 or list(set(trajectories.values())) != [4]:
        raise ValueError("expected exactly four trajectories for each of 100 frozen queries")
    by_qid = {str(row["question_id"]): row for row in constraints}
    if len(by_qid) != len(constraints) or by_qid.keys() != questions.keys() or any(
            row["question_sha256"] != sha256(questions[qid].encode()).hexdigest() for qid, row in by_qid.items()):
        raise ValueError("v4 question identities differ from the frozen inventory")
    visible_rows = jsonl(config["visibility_receipts"])
    visibility = {(row["trajectory_id"], str(row["recorded_event_id"])): row for row in visible_rows}
    if len(visibility) != len(visible_rows):
        raise ValueError("duplicate visibility receipt")
    assets = Path(config["dataset_assets"])
    question_paths = sorted((assets / "questions/data").glob("*.parquet"))
    corpus_paths = sorted((assets / "corpus/data").glob("*.parquet"))
    card = assets / "questions/README.md"
    canary = re.search(r'^CANARY = "([^"]+)"$', card.read_text(encoding="utf-8"), re.M)
    if not question_paths or not corpus_paths or not canary:
        raise ValueError("locally sealed official asset or decoding identifier missing")
    key = sha256(canary[1].encode()).digest()
    index = corpus_index(corpus_paths, key)
    qrels = annotations(question_paths, questions, index, key)
    config["asset_snapshot_sha256"] = {
        path.relative_to(assets).as_posix(): file_sha(path) for path in [card, *question_paths, *corpus_paths]
    }
    by_tool, by_kind = defaultdict(Counter), defaultdict(Counter)
    populations = {qid: {"query_id": qid, **{field: len(ids) for field, ids in values.items()}}
                   for qid, values in qrels.items()}
    observed, results = set(), []
    aliases_loaded = False
    text_hashes = {}
    for row in inventory:
        tid, qid = row["trajectory_id"], str(row["question_id"])
        data = Path(row["path"]).read_bytes()
        if sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"frozen raw trajectory digest mismatch for {tid}")
        raw = json.loads(data)
        events = []
        for event in raw["tool_events"]:
            eid, tool = str(event["event_id"]), event["tool_name"]
            kind = kind_of(tool)
            identity = (tid, eid)
            evidence = visibility[identity]
            if (identity in observed or evidence["tool_name"] != tool or evidence["round_id"] != event["round_id"]):
                raise ValueError(f"raw event differs from visibility receipt for {tid}:{eid}")
            observed.add(identity)
            args = json.loads(event["exact_arguments"])
            returned = isinstance(event.get("exact_result"), str) and isinstance(event.get("return_utc"), str)
            payload = event.get("exact_result") if returned else None
            if evidence["visible_next"] and evidence["return_text"] != payload:
                raise ValueError(f"visible result differs from frozen raw return for {tid}:{eid}")
            success = returned and not (event.get("raw_mcp_response") or {}).get("isError", False)
            argument = arg_docids(args, index) if kind == "open" else set()
            identified = index.identify(payload) if success else {}
            direct = any(value == "direct" for value in identified.values())
            entries = records(payload) if success and not direct else []
            has_url = any(isinstance(record.get("url"), str) and record["url"].strip() for record in entries)
            has_title = any(isinstance(record.get("title"), str) and record["title"].strip() for record in entries)
            include_text_hash = kind == "open" and success
            if ((has_url or has_title) and not aliases_loaded) or (include_text_hash and not text_hashes):
                text_hashes = load_aliases(corpus_paths, index, key, include_text_hash=include_text_hash)
                aliases_loaded = True
                identified = index.identify(payload)
            opened = full_open(payload, identified, argument, text_hashes) if include_text_hash else ()
            delta = Counter(calls=1, returns=int(returned), direct=int(direct), identified=int(bool(identified)),
                            docids=len(identified), url=int(has_url), title=int(has_title),
                            mapped=int(bool(identified) and not direct), argument=int(bool(argument)),
                            visible=int(evidence["visible_next"]), full_open=int(bool(opened)),
                            open_argument_only=int(bool(opened) and not identified))
            by_tool[tool].update(delta)
            by_kind[kind].update(delta)
            events.append(Observation(eid, event["round_id"], kind,
                                      opened if kind == "open" else tuple(identified),
                                      args.get("query"), bool(evidence["visible_next"]) and success))
        labels = qrels[qid]
        exposure = evidence_exposure(events, labels["evidence_docs"], labels["gold_docs"])
        results.append({"trajectory_id": tid, "query_id": qid, **exposure})
    if observed != visibility.keys():
        raise ValueError("raw tool event inventory differs from phase1 visibility receipts")
    report = {
        "questions": len(questions),
        "trajectories": len(inventory),
        "model_calls": 0,
        "tools": {tool: tool_record(counts) for tool, counts in sorted(by_tool.items())},
        "coverage": {
            "corpus_documents": len(index.ids),
            "questions_with_evidence": sum(row["evidence_docs"] > 0 for row in populations.values()),
            "questions_with_gold": sum(row["gold_docs"] > 0 for row in populations.values()),
            "evidence_docs_per_question": distribution([row["evidence_docs"] for row in populations.values()]),
            "gold_docs_per_question": distribution([row["gold_docs"] for row in populations.values()]),
            "per_question": sorted(populations.values(), key=lambda row: row["query_id"]),
        },
        "exposure": {
            "seen_recall": distribution([row["seen_recall"] for row in results if row["seen_recall"] is not None],
                                        histogram=True),
            "opened_recall": distribution([row["opened_recall"] for row in results if row["opened_recall"] is not None],
                                          histogram=True),
            "trajectories_with_gold_seen": sum(row["gold_seen"] > 0 for row in results),
            "trajectories_with_gold_opened": sum(row["gold_opened"] > 0 for row in results),
            "per_trajectory": results,
        },
        "redundancy": {},
        "gate": open_and_search_gate(by_kind),
    }
    for signal in SIGNALS:
        values = [row["signals"][signal] for row in results]
        report["redundancy"][signal] = {"total": sum(values), "affected_trajectories": sum(value > 0 for value in values),
                                        "per_trajectory": distribution(values, histogram=True)}
    write_new(output / "docid_check.json", report)
    write_new(output / "config.json", config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700)
    analyze(read_json(args.config), args.output)


if __name__ == "__main__":
    main()
