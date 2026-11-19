"""Map recorded generations to the unchanged HF training spans."""

from collections import defaultdict
import hashlib
import json
import unicodedata

from ..hf_native import native_turn_layout
from ..native_capture import native_chat_segment
from ..native_tool_coordinates import matches_return_suffix

THINK = (248068, 248069)
TOOL = (248058, 248059)


def normalize_query(query):
    return " ".join("".join(char for char in query.lower()
                            if not unicodedata.category(char).startswith("P")).split())


def envelopes(ids, markers):
    result, start = [], None
    for i, token in enumerate(ids):
        if token == markers[0]:
            if start is not None:
                raise ValueError("incomplete nested tool protocol")
            start = i
        elif token == markers[1]:
            if start is None:
                raise ValueError("incomplete tool protocol: orphan closing token")
            result.append([start, i + 1])
            start = None
    if start is not None:
        raise ValueError("incomplete tool protocol: missing closing token")
    return result


def search_hits(value):
    if isinstance(value, dict):
        value = value.get("results", value.get("result"))
    if isinstance(value, list) and value and all(
            isinstance(row, dict) and row.get("type") == "text" and "text" in row for row in value):
        parts = [json.loads(row["text"]) for row in value]
        return search_hits(parts[0] if len(parts) == 1 and isinstance(parts[0], list) else parts)
    if not isinstance(value, list) or any(not isinstance(row, dict) or "docid" not in row for row in value):
        raise ValueError("malformed search hits")
    return [{"docid": str(row["docid"]), "rank": rank} for rank, row in enumerate(value, 1)]


def tool_event(event, count, visible):
    raw = event.get("exact_result")
    if raw is None and event.get("status") not in {"fail", "timeout", "empty"}:
        raise ValueError("missing tool return or explicit failure")
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False) if raw is not None else ""
    status = event.get("status", "ok")
    if status not in {"ok", "fail", "timeout", "empty"}:
        raise ValueError("unrecognized tool status")
    mcp = event.get("raw_mcp_response")
    if status == "ok" and (isinstance(mcp, dict) and mcp.get("isError")):
        status = "timeout" if "timed out" in text.lower() else "fail"
    if status == "ok" and not text.strip():
        status = "empty"
    args_raw = event["exact_arguments"]
    tool = event["tool_name"].rsplit("-", 1)[-1]
    query, hits, docid, offset, end, body = "", [], None, None, None, None
    if status == "ok":
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            value = json.loads(text)
            if tool == "search":
                query = normalize_query(args["query"])
                hits = search_hits(value)
                if not hits:
                    status = "empty"
            elif tool == "open":
                docid = str(args.get("docid", args.get("doc_id")))
                offset = args.get("start", args.get("offset", 0))
                body = value["text"]
                if type(offset) is not int or not isinstance(body, str) or docid == "None":
                    raise ValueError("invalid open return")
                end = offset + len(body)
            else:
                status = "fail"
        except (ValueError, TypeError, KeyError, AttributeError):
            status = "timeout" if "timed out" in text.lower() or "timeout" in text.lower() else "fail"
    return {"event_id": event["event_id"], "tool": tool, "args_raw": args_raw,
            "query_norm": query, "returned_docids": hits, "opened_docid": docid,
            "open_offset": offset, "open_end": end, "return_text": text,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest() if body is not None else None,
            "return_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "obs_tokens": count, "obs_tokens_source": "next_prompt" if visible else "estimated",
            "status": status, "visible_to_actor": visible}


def bind_observations(current, following, events, count_tokens, markers):
    if not events:
        return []
    if following is None or not following.get("response_received"):
        # No served native prompt proves the actor saw these text bytes.
        return [tool_event(e, count_tokens(e.get("exact_result") or ""), False) for e in events]
    if not matches_return_suffix(following, events):
        raise ValueError("ordered tool returns do not bind to next actor history")
    previous_ids = current["token_accounting"]["prompt_token_ids"]
    prompt_ids = following["token_accounting"]["prompt_token_ids"]
    boundaries = envelopes(prompt_ids, markers)
    if len(boundaries) < len(events):
        raise ValueError("tool return envelopes absent from next original prompt")
    positions = boundaries[-len(events):]
    prefix = next((i for i, (a, b) in enumerate(zip(previous_ids, prompt_ids)) if a != b),
                  min(len(previous_ids), len(prompt_ids)))
    if any(left < prefix for left, _ in positions):
        raise ValueError("tool return attributed to a prior prompt")
    return [tool_event(event, right - left - 2, True)
            for event, (left, right) in zip(events, positions, strict=True)]


def parse_stages(question_id, trajectory_id, rounds, events, *, count_tokens,
                 observation_markers=(248066, 248067), terminal_status=None):
    """Return stages, dense stage IDs, and original policy segments for validation."""
    segments, segment_by_round = [], {}
    events_by_round = defaultdict(list)
    for event in events:
        events_by_round[event["round_id"]].append(event)
    if len({event["event_id"] for event in events}) != len(events):
        raise ValueError("duplicate tool event id")
    if len({row["round_id"] for row in rounds}) != len(rounds) or len(rounds) > 20:
        raise ValueError("invalid model-call sequence")
    if set(events_by_round) - {row["round_id"] for row in rounds}:
        raise ValueError("tool event without model-call record")
    for i, row in enumerate(rounds):
        if not row.get("response_received"):
            if i != len(rounds) - 1 or terminal_status not in {"CONTEXT_LIMIT_STOP", "GENERATION_LENGTH_STOP"}:
                raise ValueError("missing generation response without budget terminal")
            continue
        segment = native_chat_segment(row["raw_response"])
        accounting = row["token_accounting"]
        if (accounting.get("exact_prompt_token_ids_equal") is not True
                or segment["prompt_ids"] != accounting["prompt_token_ids"]
                or segment["completion_ids"] != accounting["completion_token_ids"]):
            raise ValueError("raw native tokens disagree with recorder")
        if segment["completion_ids"]:
            segment_by_round[i] = len(segments)
            segments.append(segment)
    native = {"id": trajectory_id, "query_id": question_id, "segments": segments}
    layout = native_turn_layout(native)
    stage_ids = [{"trajectory_id": trajectory_id, "span_id": i, "stage_ids": [-1] * len(span["completion_ids"])}
                 for i, span in enumerate(layout["spans"])]
    stages = []
    for i, row in enumerate(rounds):
        unit = i + 1
        segment_index = segment_by_round.get(i)
        span_id, start, stop = None, 0, 0
        ids = []
        if segment_index is not None:
            turn = layout["turns"][segment_index]
            span_id = turn["span_index"]
            axis = layout["spans"][span_id]["axis_start"]
            start, stop = turn["token_start"] - axis, turn["token_end"] - axis
            ids = segments[segment_index]["completion_ids"]
            stage_ids[span_id]["stage_ids"][start:stop] = [unit] * len(ids)
        choice = row["raw_response"]["choices"][0] if row.get("response_received") else {}
        message = choice.get("message") or {}
        calls = message.get("tool_calls") or []
        length_stop = choice.get("finish_reason") == "length" or not row.get("response_received")
        # Tool-looking text in a completed reasoning-only generation is not a dispatched call.
        # A dispatched call, or a partially generated protocol at a length stop, must bind.
        call_ranges = envelopes(ids, TOOL) if calls or length_stop else []
        batch = sorted(events_by_round[row["round_id"]], key=lambda event: event.get("dispatch_order", 0))
        if len(call_ranges) != len(calls) or len(calls) != len(batch):
            raise ValueError("incomplete tool protocol or unpaired tool event")
        for call, event in zip(calls, batch, strict=True):
            fn = call["function"]
            if (call["id"], fn["name"], fn["arguments"]) != (
                    event["tool_call_id"], event["tool_name"], event["exact_arguments"]):
                raise ValueError("tool identity or arguments mismatch")
        content = (message.get("content") or "").strip()
        reasoning = message.get("reasoning") or message.get("reasoning_content")
        kind = ("tool_stage" if calls else "unfinished" if length_stop else "final" if content else
                "empty" if row.get("stop_classification") == "EMPTY_MODEL_STOP" else
                "unfinished" if reasoning else "empty")
        # Opening think can be in the prompt. Trailing delimiters are generated
        # policy tokens, so keep them in a disjoint region even on an empty stop.
        ends = [p for p, token in enumerate(ids) if token == THINK[1]]
        first_call = call_ranges[0][0] if call_ranges else len(ids)
        if reasoning and not calls and not content:
            think_stop = len(ids)
        elif ends and ends[0] < first_call:
            think_stop = ends[0] + 1
        else:
            think_stop = first_call if calls or kind == "unfinished" else 0
        think = [[0, think_stop]] if think_stop else []
        answer, last = [], think_stop
        for left, right in call_ranges:
            if last < left:
                answer.append([last, left])
            last = right
        if last < len(ids):
            answer.append([last, len(ids)])
        shift = lambda spans: [[start + left, start + right] for left, right in spans]
        observed = bind_observations(row, rounds[i+1] if i+1 < len(rounds) else None,
                                     batch, count_tokens, observation_markers)
        for event, coordinates in zip(observed, shift(call_ranges), strict=True):
            event["call_range"] = coordinates
        stages.append({"question_id": question_id, "trajectory_id": trajectory_id, "unit_id": unit,
                       "unit_type": kind, "model_call_index": row["round_id"], "span_id": span_id,
                       "gen_token_range": [start, stop], "think_range": shift(think),
                       "call_range": shift(call_ranges), "answer_range": shift(answer),
                       "generated_tokens": len(ids), "tool_events": observed,
                       "status": row.get("stop_classification") or choice.get("finish_reason") or terminal_status})
    return {"stages": stages, "stage_ids": stage_ids, "native": native}
