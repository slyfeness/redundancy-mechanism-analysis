"""Replay the common exact-repeat rule on sealed SAGE and SciCode archives."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from ledger_grpo.event_replay import delivered_repeat_witnesses
from ledger_grpo.sampler_tool_adapter import canonical_sampler_return, sampler_repeat_receipt


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bound_json(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("archive path escapes its root")
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"archive digest mismatch: {relative}")
    return json.loads(data)


def read_round(root, names, hashes, source, counts):
    request, response = [bound_json(root, name, hashes[name]) if name in hashes else None for name in names]
    choices = response.get("choices") or [] if response else []
    choice = choices[0] if choices else {}
    logprobs = (choice.get("logprobs") or {}).get("content") or []
    counts.update(rounds=1, requests_bound=int(request is not None), responses_bound=int(response is not None),
                  native_prompt_ids_rounds=int(bool(response and response.get("prompt_token_ids"))),
                  native_completion_ids_rounds=int(bool(choice.get("token_ids"))),
                  native_logprobs_with_bytes_rounds=int(bool(logprobs) and all(bool(x.get("bytes")) for x in logprobs)))
    return {"round_id": source["round"], "request_sent": request is not None,
            "response_received": source["http_status"] == 200 and bool(choice),
            "actor_visible_messages": request["messages"] if request else ()}


def replay(rounds, events_by_round, counts):
    events = {event["event_id"]: event for group in events_by_round.values() for event in group}
    if len(events) != sum(map(len, events_by_round.values())):
        raise ValueError("duplicate tool event identity")
    witnesses = delivered_repeat_witnesses(
        rounds, events_by_round,
        event_key=lambda e: e["repeat_key"],
        normalize_return=canonical_sampler_return,
    )
    counts.update(tool_events=len(events), repeat_eligible_events=sum(e["repeat_key"] is not None for e in events.values()),
                  exact_visible_repeats=len(witnesses))
    for current in witnesses:
        counts[f"repeat_{events[current]['name']}"] += 1
    return witnesses


def audit_sage(root):
    manifest = root / "SAMPLE_MANIFEST.json"
    native = root / "NATIVE_EXPORT_RECEIPT.json"
    records = json.loads(manifest.read_bytes())["selected_ledger_records"]
    receipt = json.loads(native.read_bytes())
    hashes = {row["archive_member"]: row["sha256"] for row in receipt["records"]}
    if len(hashes) != len(receipt["records"]):
        raise ValueError("duplicate SAGE raw archive member")
    total, examples = Counter(), []
    for record in records:
        key = record["batch"] + "__" + record["pilot_id"]
        trajectory = bound_json(root, f"RAW/{key}/trajectory.json", record["raw_trajectory_sha256"])
        counts, rounds, events_by_round = Counter(), [], defaultdict(list)
        pending = iter(trajectory["tool_events"])
        for source in trajectory["rounds"]:
            round_id = source["round"]
            base = f"NATIVE/{key}/R{round_id:03d}"
            rounds.append(read_round(root, [f"{base}_{suffix}.json" for suffix in ("request", "response")],
                                     hashes, source, counts))
            for call in source.get("tool_calls", ()):
                event = next(pending)
                if (call["id"], call["name"], call["arguments"]) != (
                        event["tool_call_id"], event["name"], event["arguments"]):
                    raise ValueError("SAGE tool response is not paired with its original call")
                normalized, _, _ = sampler_repeat_receipt("sage", event, draft=None, revision=0)
                events_by_round[round_id].append(normalized)
        if next(pending, None) is not None:
            raise ValueError("SAGE tool result has no original call")
        examples.append({"sample": key, "trajectory_sha256": record["raw_trajectory_sha256"],
                         "witnesses": replay(rounds, events_by_round, counts), "counts": dict(counts)})
        total.update(counts)
    return {"trajectories": len(records), "totals": dict(total), "rows": examples,
            "manifest_sha256": digest(manifest.read_bytes()), "native_receipt_sha256": digest(native.read_bytes())}


def audit_scicode(root):
    manifest = root / "SOURCE_MANIFEST.json"
    source = json.loads(manifest.read_bytes())
    hashes = {row["archive_path"]: row["sha256"] for row in source["files"]}
    if len(hashes) != len(source["files"]):
        raise ValueError("duplicate SciCode raw archive member")
    total, examples = Counter(), []
    for record in source["targets"]:
        key = record["target_id"]
        base = f"sources/{key}"
        trajectory = bound_json(root, f"{base}/trajectory.json", record["trajectory_sha256"])
        if trajectory["target_id"] != key:
            raise ValueError("SciCode trajectory identity mismatch")
        counts, by_step = Counter(), {}
        for step in trajectory["steps"]:
            step_id = step["step_index"]
            rounds, events_by_round = [], defaultdict(list)
            round_calls = {}
            for original in step.get("rounds", ()):
                round_id = original["round"]
                prefix = f"{base}/step_{step_id:02d}/round_{round_id:02d}"
                rounds.append(read_round(root, [f"{prefix}_{suffix}.json" for suffix in ("request", "response")],
                                         hashes, original, counts))
                round_calls[round_id] = original.get("tool_calls") or []
            draft, revision = digest(b""), 0
            for event in step.get("tool_events", ()):
                round_id = int(event["batch_id"][1:])
                call = round_calls[round_id][event["batch_ordinal"]-1]
                if (call["id"], call["name"], call["arguments"]) != (event["call_id"], event["name"], event["arguments"]):
                    raise ValueError("SciCode tool result is not paired with its original call")
                normalized, revision, draft = sampler_repeat_receipt("scicode", event, draft=draft, revision=revision)
                events_by_round[round_id].append(normalized)
            witnesses = replay(rounds, events_by_round, counts)
            if witnesses:
                by_step[str(step_id)] = witnesses
        total.update(counts)
        examples.append({"sample": key, "trajectory_sha256": record["trajectory_sha256"],
                         "witnesses_by_step": by_step, "counts": dict(counts)})
    return {"trajectories": len(examples), "totals": dict(total), "rows": examples,
            "manifest_sha256": digest(manifest.read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sage", type=Path, required=True)
    parser.add_argument("--scicode", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"SAGE": audit_sage(args.sage.resolve(strict=True)),
              "SciCode": audit_scicode(args.scicode.resolve(strict=True)),
              "scope": "Exact visible tool-result replay on existing archives. No native pricing or task-policy update."}
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, allow_nan=False)
    print(json.dumps({key: value["totals"] for key, value in result.items() if isinstance(value, dict)}))


if __name__ == "__main__":
    main()
