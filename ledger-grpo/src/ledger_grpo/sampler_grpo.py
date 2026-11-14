"""Project complete native SAGE and SciCode recordings to GRPO scoring inputs."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from .event_replay import delivered_repeat_witnesses
from .hf_native import native_turn_layout
from .native_capture import native_chat_request, native_chat_segment
from .sampler_tool_adapter import _FIELDS, canonical_sampler_return, measure_sampler_batch, sampler_repeat_receipt


_BUDGET_STOPS = {
    "sage": {"ACTOR_CALL_BUDGET_STOP", "TOTAL_GENERATION_BUDGET_STOP", "TOOL_BUDGET_STOP"},
    "scicode": {"ACTOR_BUDGET_STOP", "GLOBAL_ACTOR_BUDGET_BEFORE_STEP"},
}


def _exchange(folder, number, kind):
    prefix = folder / f"round_{number:02d}_{kind}"
    body_path, receipt_path = (prefix.with_suffix(suffix).resolve(strict=True) for suffix in (".body", ".json"))
    if any(not path.is_relative_to(folder) for path in (body_path, receipt_path)):
        raise ValueError("exchange artifact path escapes the original sampler directory")
    body = json.loads(body_path.read_bytes())
    if body != json.loads(receipt_path.read_bytes()):
        raise ValueError(f"recorded {kind} body differs from the JSON receipt")
    return body


def _stage_events(dataset, source, stage_index):
    call_key, _ = _FIELDS[dataset]
    batches, identities = defaultdict(list), set()
    calls = {r["round"]: r.get("tool_calls") or () for r in source.get("rounds", ())}
    for event in source.get("tool_events", ()):
        number = int(event["batch_id"][1:])
        ordinal = event["batch_ordinal"]
        local_id = event["event_id"]
        if local_id in identities or ordinal != len(batches[number])+1 or ordinal > len(calls.get(number, ())):
            raise ValueError("dispatched event is not in the recorded call order")
        call = calls[number][ordinal-1]
        if (call["id"], call["name"], call["arguments"]) != (event[call_key], event["name"], event["arguments"]):
            raise ValueError("tool event differs from the recorder's dispatch")
        identities.add(local_id)
        batches[number].append(dict(event, event_id=f"{stage_index}:{local_id}"))
    return batches


def adapt_sampler_trajectory(dataset, artifact_root, *, traj_id, task_id, outcome, tokenizer, process_frames=None):
    """Return one scoring row, its native inputs, and measurement coverage."""
    if dataset not in _BUDGET_STOPS:
        raise ValueError("expected the SAGE or SciCode sampler format")
    if (type(outcome) is not int or outcome not in (0, 1)
            or any(not isinstance(value, str) or not value for value in (traj_id, task_id))):
        raise ValueError("a bound binary outcome and nonempty sample and task IDs are required")
    root = Path(artifact_root).resolve(strict=True)
    trajectory_path = (root / "trajectory.json").resolve(strict=True)
    if not trajectory_path.is_relative_to(root):
        raise ValueError("trajectory artifact path escapes the original sampler directory")
    source_bytes = trajectory_path.read_bytes()
    raw = json.loads(source_bytes)
    stages = raw["steps"] if dataset == "scicode" else [raw]
    if process_frames is not None and (not isinstance(process_frames, list) or len(process_frames) != len(stages)):
        raise ValueError('process frames must cover the recorded stages')
    stop = raw["stop_reason"]
    submitted = (raw.get("status") == "SUBMITTED" and stop == "MODEL_SUBMIT_STOP" if dataset == "scicode"
                 else stop == "MODEL_FINAL_STOP" and raw.get("final_validity_state") == "VALID_FINAL"
                 and bool(raw.get("final_answer")))
    termination = "normal" if submitted else "budget_exhausted" if stop in _BUDGET_STOPS[dataset] else "unknown"
    if outcome and not submitted:
        raise ValueError("only a normal submission can have a positive outcome")

    counts = Counter(recorded_events=0, measured_events=0, observed_repeats=0)
    recording_complete = bool(stages)
    segments, batches, process_sources = [], [], []
    for index, source in enumerate(stages, 1):
        folder = root
        if dataset == "scicode":
            if source["step_index"] != index:
                raise ValueError("SciCode stages must be in original order")
            folder = (root / f"step_{index:02d}").resolve()
            if not folder.is_relative_to(root):
                raise ValueError("step artifact path escapes the original trajectory")
        stage_events = _stage_events(dataset, source, index)
        counts["recorded_events"] += sum(map(len, stage_events.values()))
        rounds, replay_events = [], {}
        revision, draft = 0, hashlib.sha256(b"").hexdigest()
        for number, row in enumerate(source.get("rounds", ()), 1):
            if row["round"] != number:
                raise ValueError("recorded sampler rounds are not contiguous")
            if row["http_status"] != 200 or row.get("native_capture", {}).get("valid") is not True:
                recording_complete = False
                rounds.append({"round_id": number, "request_sent": False, "response_received": False})
                continue
            request, response = (_exchange(folder, number, kind) for kind in ("request", "response"))
            if request != native_chat_request(request):
                raise ValueError("request does not use the frozen native capture fields")
            segment = native_chat_segment(response)
            rounds.append({"round_id": number, "request_sent": True, "response_received": True,
                           "actor_visible_messages": request["messages"], "request": request, "response": response,
                           "call_index": len(segments) if segment["completion_ids"] else None})
            if segment["completion_ids"]:
                segments.append(segment)
            replay_events[number] = []
            for event in stage_events.get(number, ()):
                normalized, revision, draft = sampler_repeat_receipt(dataset, event, revision=revision, draft=draft)
                replay_events[number].append(normalized)
                if dataset == "sage" and event["observation"].get("error") == "OPEN_ERROR":
                    recording_complete = False
        repeats = delivered_repeat_witnesses(rounds, replay_events, event_key=lambda e: e["repeat_key"],
                                            normalize_return=canonical_sampler_return)
        counts["observed_repeats"] += len(repeats)
        if process_frames is not None:
            process_sources.append((index, rounds, stage_events, process_frames[index-1]))
        for current, following in zip(rounds, rounds[1:]):
            events = stage_events.get(current["round_id"])
            if events and current.get("call_index") is not None and following.get("response_received") is True:
                batches.append((current, following, events, repeats))
    native = {"id": traj_id, "query_id": task_id, "reward": outcome, "terminal": stop, "segments": segments}
    layout = native_turn_layout(native)
    measured = []
    for current, following, events, repeats in batches:
        turn = layout["turns"][current["call_index"]]
        try:
            receipts = measure_sampler_batch(dataset, current["response"], events, next_request=following["request"],
                                             next_response=following["response"], tokenizer=tokenizer, offset=turn["token_start"])
        except ValueError:
            counts["unmeasurable_events_with_next_response"] += len(events)
            continue
        for receipt in receipts:
            earlier = repeats.get(receipt["event_id"])
            measured.append(dict(receipt, turn_id=turn["turn_id"], known_at=turn["turn_id"],
                                 label="R2b" if earlier else None, prior_event_id=earlier))
    counts["measured_events"] = len(measured)
    row = {"traj_id": traj_id, "task_id": task_id, "outcome": outcome, "recording_complete": recording_complete,
           "termination_reason": termination, "grounding": None, "response_mask": layout["response_mask"],
           "events": measured}
    coverage = dict(counts, source_trajectory_id=raw['trajectory_id'],
                    source_trajectory_sha256=hashlib.sha256(source_bytes).hexdigest())
    if process_frames is not None:
        from .sampler_process import project_sampler_process

        projections = [project_sampler_process(dataset, stage, rounds, stage_events, layout, measured, frame,
                                               traj_id=traj_id, task_id=task_id)
                       for stage, rounds, stage_events, frame in process_sources]
        coverage['process_traces'] = [projection for projection in projections if projection is not None]
        coverage['process_unavailable_stages'] = len(projections)-len(coverage['process_traces'])
    return row, native, coverage
