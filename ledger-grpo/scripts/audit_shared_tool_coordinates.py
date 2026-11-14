"""Compare frozen BrowseComp tool receipts with the shared native-input path."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer

from ledger_grpo.browsecomp_adapter import native_trajectory
from ledger_grpo.hf_native import native_turn_layout


def read(path):
    return json.loads(path.read_bytes())


def source_rounds(raw, artifact):
    by_round = defaultdict(list)
    for event in raw["tool_events"]:
        by_round[event["round_id"]].append(dict(event, event_id=str(event["event_id"])))
    rounds = raw["rounds"]
    observed = [r["round_id"] for r in rounds if r.get("response_received") is True
                and r["token_accounting"]["completion_token_ids"]]
    layout = native_turn_layout(native_trajectory(raw, reward=0))
    starts = {rid: row["token_start"] for rid, row in zip(observed, layout["turns"], strict=True)}
    for index, current in enumerate(rounds):
        if current.get("response_received") is not True:
            continue
        events = sorted(by_round[current["round_id"]], key=lambda event: event["tool_ordinal"])
        following = rounds[index+1] if index+1 < len(rounds) else None
        if events and following and following.get("response_received") is True:
            path = Path(following["raw_request_path"]).resolve()
            if not path.is_relative_to(artifact):
                raise ValueError("request evidence is outside its original trajectory")
            request = read(path)
            if request["messages"] != following["actor_visible_messages"]:
                raise ValueError("original request differs from the bound model-visible history")
            yield current, following, request, events, starts[current["round_id"]]


def measure(mode, tokenizer, raw, artifact):
    result, counts = {}, Counter()
    for current, following, request, events, offset in source_rounds(raw, artifact):
        counts.update(batches=1, events=len(events))
        if mode == "stored":
            from ledger_grpo.browsecomp_events import _call_ranges, _return_counts

            spans = _call_ranges(current, events, offset, tokenizer=tokenizer)
            costs = _return_counts(following, events, tokenizer, artifact) if spans is not None else None
            rows = [{"event_id": event["event_id"], "event_tokens": [start, stop],
                     "event_cost": {"generated_tokens": stop-start, "returned_tokens": count, "tool_calls": 1}}
                    for event, (start, stop), count in zip(events, spans, costs, strict=True)] if costs is not None else None
        else:
            from ledger_grpo.native_tool_coordinates import recorded_tool_coordinates

            try:
                rows = recorded_tool_coordinates(current["raw_response"], events, next_request=request,
                                                 next_response=following["raw_response"], tokenizer=tokenizer, offset=offset)
            except ValueError:
                rows = None
        result[str(current["round_id"])] = rows
        if rows is not None:
            counts["measured_batches"] += 1
            counts["measured_events"] += len(rows)
            for row in rows:
                counts["returned_tokens"] += row["event_cost"]["returned_tokens"]
                counts["event_generation_tokens"] += row["event_cost"]["generated_tokens"]
    return result, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stored", "served"), required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    batch = args.run / "scored/NATIVE_BATCH.json"
    entries = read(batch)["trajectories"]
    if len(entries) != 32 or len({row["id"] for row in entries}) != 32:
        raise ValueError("expected the frozen 32-trajectory training batch")
    totals, trajectories = Counter(), {}
    for entry in entries:
        artifact = (args.run / "train-P0/trajectories" / entry["id"]).resolve()
        original = (artifact / "trajectory.json").read_bytes()
        raw = json.loads(original)
        task = raw["metadata"]["task"]
        if (str(task["query_id"]), task["run_id"]) != (str(entry["query_id"]), entry["id"]):
            raise ValueError("native trajectory and training batch identity mismatch")
        rows, counts = measure(args.mode, tokenizer, raw, artifact)
        totals.update(counts)
        trajectories[entry["id"]] = {"trajectory_sha256": hashlib.sha256(original).hexdigest(), "rounds": rows}
    report = {"batch_sha256": hashlib.sha256(batch.read_bytes()).hexdigest(), "trajectories": trajectories,
              "totals": totals}
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, sort_keys=True, allow_nan=False)
    print(args.mode, json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
