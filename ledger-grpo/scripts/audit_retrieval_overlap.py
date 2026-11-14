"""Measure search-result overlap using only previously delivered snippets."""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from ledger_grpo.browsecomp_adapter import _recorded_search_response
from ledger_grpo.evaluation import paired_event_diagnostics


ARMS = ("P0", "outcome", "trajectory", "targeted", "shuffled", "uniform")
OVERLAP_METRICS = ("covered_search_events", "fully_seen_events", "fully_seen_new_arguments_events",
                   "fully_seen_without_exact_repeat_events", "partial_overlap_events",
                   "unseen_only_events", "empty_return_events", "exact_repeat_events")


def audit_searches(raw):
    """Use exact (doc ID, excerpt) pairs to track observed material, not relevance."""
    rounds = raw["rounds"]
    positions = {row["round_id"]: index for index, row in enumerate(rounds)}
    if len(positions) != len(rounds):
        raise ValueError("duplicate recorded round ID")
    appearances = defaultdict(list)
    for index, row in enumerate(rounds):
        if row.get("request_sent") is True and row.get("response_received") is True:
            for message in row.get("actor_visible_messages") or ():
                if message.get("role") == "tool" and isinstance(message.get("content"), str):
                    appearances[message.get("tool_call_id"), message["content"]].append(index)

    events = sorted(raw["tool_events"], key=lambda row: (positions[row["round_id"]], row["tool_ordinal"]))
    call_positions = defaultdict(list)
    for event in events:
        call_positions[event["tool_call_id"]].append(positions[event["round_id"]])

    parsed, deliveries, counts = [], [], Counter(dict.fromkeys(OVERLAP_METRICS, 0))
    seen_call_ids = set()
    for event in events:
        here = positions[event["round_id"]]
        call_id = event["tool_call_id"]
        reused = call_id in seen_call_ids
        seen_call_ids.add(call_id)
        if event["tool_name"] != "search-server-search":
            continue
        counts["recorded_search_events"] += 1
        counts["reused_call_id_events"] += int(reused)
        if not _recorded_search_response(event):
            counts["unparsed_search_events"] += 1
            continue
        result = event["exact_result"]
        try:
            arguments = json.loads(event["exact_arguments"])
            documents = json.loads(result)
            if not isinstance(arguments, dict) or not isinstance(documents, list):
                raise ValueError("expected search arguments and result records")
            snippets = {(str(doc["docid"]), doc["snippet"]) for doc in documents}
            if any(not isinstance(snippet, str) for _, snippet in snippets):
                raise ValueError("expected a text excerpt")
        except (KeyError, TypeError, ValueError):
            counts["unparsed_search_events"] += 1
            continue
        args_key = json.dumps(arguments, sort_keys=True)
        parsed.append((here, args_key, result, snippets))
        times = appearances[call_id, result]
        first = bisect_right(times, here)
        later_calls = call_positions[call_id][1:]
        if (not reused and first < len(times) and (not later_calls or times[first] <= later_calls[0])):
            deliveries.append((times[first], args_key, result, snippets))

    deliveries.sort(key=lambda delivery: delivery[0])
    delivered = iter(deliveries)
    next_delivery = next(delivered, None)
    seen_snippets, seen_arguments, seen_actions = set(), set(), set()
    for here, args_key, result, snippets in parsed:
        while next_delivery is not None and next_delivery[0] <= here:
            _, old_arguments, old_result, old_snippets = next_delivery
            seen_arguments.add(old_arguments)
            seen_actions.add((old_arguments, old_result))
            seen_snippets.update(old_snippets)
            next_delivery = next(delivered, None)
        counts["covered_search_events"] += 1
        exact = (args_key, result) in seen_actions
        counts["exact_repeat_events"] += int(exact)
        if not snippets:
            counts["empty_return_events"] += 1
        elif snippets <= seen_snippets:
            counts["fully_seen_events"] += 1
            counts["fully_seen_without_exact_repeat_events"] += int(not exact)
            counts["fully_seen_new_arguments_events"] += int(args_key not in seen_arguments)
        elif snippets & seen_snippets:
            counts["partial_overlap_events"] += 1
        else:
            counts["unseen_only_events"] += 1
    for key in ("recorded_search_events", "unparsed_search_events", "reused_call_id_events"):
        counts.setdefault(key, 0)
    return dict(counts)


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_evaluation(run):
    receipt = json.loads((run/"BASELINE_EVALUATION_RECEIPT.json").read_bytes())
    baseline = run.parent/receipt["run_name"]
    original_p0 = (baseline/"EVAL-P0.json").read_bytes()
    if (hashlib.sha256(original_p0).hexdigest() != receipt["summary_sha256"]
            or json.loads(original_p0) != json.loads((run/"EVAL-P0.json").read_bytes())):
        raise ValueError("frozen P0 receipt does not bind to its native source")

    results, paired_rows = {}, {}
    expected = None
    for arm in ARMS:
        folder = (baseline if arm == "P0" else run)/f"eval-{arm}"
        summary_path = run/f"EVAL-{arm}.json"
        summary = json.loads(summary_path.read_bytes())["rows"]
        manifest_path = folder/"task_manifest.json"
        tasks = json.loads(manifest_path.read_bytes())["tasks"]
        identities = {(str(row["query_id"]), row["run_id"]): (row["seed"], row["question_sha256"]) for row in tasks}
        if expected is None:
            expected = identities
        if (len(summary) != 128 or len(tasks) != 128 or len(identities) != 128 or identities != expected
                or {(r["task_id"], r["sample_id"]) for r in summary} != expected.keys()
                or Counter(qid for qid, _ in expected) != {qid: 8 for qid, _ in expected}):
            raise ValueError("fixed task identities or sampling seeds differ from the frozen baseline")
        totals, rows = Counter(), []
        for source in summary:
            identity = source["task_id"], source["sample_id"]
            path = folder/"trajectories"/source["sample_id"]/"trajectory.json"
            original = path.read_bytes()
            raw = json.loads(original)
            native = raw["metadata"]["task"]
            if ((str(native["query_id"]), native["run_id"]) != identity
                    or (native["seed"], native["question_sha256"]) != expected[identity]):
                raise ValueError("native trajectory differs from the frozen manifest")
            metrics = audit_searches(raw)
            totals.update(metrics)
            rows.append(dict(task_id=identity[0], sample_id=identity[1], **metrics,
                             trajectory_sha256=hashlib.sha256(original).hexdigest()))
        results[arm] = {"summary_sha256": file_sha(summary_path), "manifest_sha256": file_sha(manifest_path),
                        "totals": dict(totals), "sample_count": len(rows), "rows": rows}
        paired_rows[arm] = [dict(source, **row) for source, row in zip(summary, rows, strict=True)]
        print(arm, json.dumps(totals), flush=True)
    extra = tuple(key for key in OVERLAP_METRICS if key != "exact_repeat_events")
    comparisons = {}
    for arm in ARMS:
        if arm != "targeted":
            delta = paired_event_diagnostics(paired_rows[arm], paired_rows["targeted"], additional_metrics=extra)["delta"]
            comparisons[f"targeted_minus_{arm}"] = {key: delta[key] for key in OVERLAP_METRICS}
    return {"source_run": str(run), "protocol": "prefix-visible-exact-docid-and-snippet-overlap-v1",
            "scope": "Frozen evaluation. Successful native search returns only. Overlap does not establish relevance or necessity.",
            "arms": results, "comparisons": comparisons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run, output = args.run.resolve(strict=True), args.output.resolve()
    if output.is_relative_to(run.parent) or output.exists():
        raise ValueError("audit output must be new and outside the frozen runs")
    result = audit_evaluation(run)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, allow_nan=False)


if __name__ == "__main__":
    main()
