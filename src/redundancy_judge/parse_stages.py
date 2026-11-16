"""Causal tool-call stages from captured messages, calls, and completion IDs."""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import json
import re

from .adapters.trace import bytes_and_boundaries, sha256


POLICY_COORDINATE = "original_generated_tokens_concatenated"
_CALL = re.compile(rb"<tool_call>\s*<function=([^>]+)>.*?</function>\s*</tool_call>", re.DOTALL)
_TOOL_MARKER = re.compile(rb"</?tool_response>")
_TOOL_RESULT = re.compile(rb"<tool_response>\n(.*?)\n</tool_response>", re.DOTALL)


def _parse_args(value):
    def unique_object(items):
        result = dict(items)
        if len(result) != len(items):
            raise ValueError("Duplicate argument keys")
        return result

    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    try:
        parsed = json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _ids(values):
    return isinstance(values, list) and all(type(item) is int and item >= 0 for item in values)


def _choice(row):
    raw = row.get("raw_response")
    choices = raw.get("choices") if isinstance(raw, dict) else None
    return choices[0] if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) else {}


def _native_layout(rounds, revision, note):
    positions = {}
    offset = 0
    verified = isinstance(revision, str) and bool(revision)
    for index, row in enumerate(rounds):
        if row.get("request_sent") is False and row.get("guard_intercepted") is True:
            continue
        native = row.get("token_accounting") or {}
        ids = native.get("completion_token_ids")
        prompt = native.get("prompt_token_ids")
        choice = _choice(row)
        exact = (row.get("response_received") is True and _ids(ids) and _ids(prompt)
                 and native.get("exact_prompt_token_ids_equal") is True
                 and choice.get("token_ids") == ids and row["raw_response"].get("prompt_token_ids") == prompt
                 and row.get("completion_tokens", len(ids)) == len(ids))
        if not exact:
            verified = False
            note("native_alignment_unverified", round_id=row.get("round_id"))
            continue
        positions[index] = [offset, offset + len(ids)]
        offset += len(ids)
    return (positions, offset) if verified else ({}, None)


def _matching_tool_message(row, event):
    matches = [message for message in row.get("actor_visible_messages", [])
               if message.get("role") == "tool" and message.get("tool_call_id") == event["call_id"]]
    return len(matches) == 1 and matches[0].get("content") == event["_returned_text"]


def _prompt_evidence(row, events, tokenizer, note):
    """Bind prompt tool messages to original native input and count payload IDs.

    Where no decoder is supplied the captured actor-visible messages still prove
    transport visibility. Their native return token cost remains unavailable.
    """
    present = {event["event_id"]: None for event in events if _matching_tool_message(row, event)}
    if tokenizer is None or not present:
        return present
    tokens = row.get("token_accounting") or {}
    prompt = tokens.get("prompt_token_ids")
    if (not _ids(prompt) or tokens.get("exact_prompt_token_ids_equal") is not True
            or row.get("raw_response", {}).get("prompt_token_ids") != prompt):
        return {}
    try:
        native, bounds = tokenizer.native_bytes(prompt)
    except (KeyError, ValueError):
        note("native_prompt_visibility_unverified", round_id=row["round_id"])
        return {}
    by_call = {event["call_id"]: event for event in events if event["event_id"] in present}
    messages = [m for m in row["actor_visible_messages"] if m.get("role") == "tool"]
    results = list(_TOOL_RESULT.finditer(native))
    # Reject every extra marker, including ones embedded in a supplied document
    # or query, before mapping any occurrence position to the matching call ID.
    if (len(results) != len(messages) or sum(1 for _ in _TOOL_MARKER.finditer(native)) != 2 * len(results)
            or any(not isinstance(message.get("content"), str)
                   or message["content"].encode("utf-8") != result[1]
                   for message, result in zip(messages, results))):
        note("native_tool_return_markers_unverified", round_id=row["round_id"])
        return {}
    offsets = list(bounds)
    positions = {}
    for index, result in enumerate(results):
        start, end = result.span(1)
        left = bisect_right(offsets, start) - 1
        right = bisect_left(offsets, end)
        positions[index] = range(left, right) if start < end else range(0)
    token_shares = Counter(token for span in positions.values() for token in span)
    overlaps = {index for index, span in positions.items() if any(token_shares[token] > 1 for token in span)}
    if overlaps:
        note("shared_native_tool_return_tokens", round_id=row["round_id"], affected_returns=len(overlaps))
    return {by_call[message["tool_call_id"]]["event_id"]: None if index in overlaps else len(positions[index])
            for index, message in enumerate(messages) if message.get("tool_call_id") in by_call}


def _charge_span(row, action, offset, tokenizer):
    native = row["token_accounting"]["completion_token_ids"]
    try:
        if tokenizer is not None:
            raw, bounds = tokenizer.native_bytes(native)
        else:
            content = (_choice(row).get("logprobs") or {}).get("content")
            if not (isinstance(content, list) and len(content) == len(native)):
                return []
            pieces = [token.get("bytes") for token in content]
            if not all(isinstance(chunk, list) and chunk for chunk in pieces):
                return []
            raw, bounds = bytes_and_boundaries(bytes(chunk) for chunk in pieces)
    except (KeyError, TypeError, ValueError):
        return []
    matches = list(_CALL.finditer(raw))
    if len(matches) != 1 or matches[0][1] != action["tool_name"].encode("utf-8"):
        return []
    block = matches[0]
    start, end = block.span()
    if start not in bounds or end not in bounds:
        return []
    payload = block[0].decode("utf-8", errors="replace")
    # Bind the visible native envelope back to its structured arguments.
    params = re.findall(r"<parameter=([^>]+)>\s*\n?(.*?)\n?\s*</parameter>", payload, re.DOTALL)
    args = action["arguments"]
    if not isinstance(args, dict) or len(params) != len(args):
        return []
    for key, value in params:
        expected = args.get(key)
        if key not in args or value != (expected if isinstance(expected, str) else json.dumps(expected, ensure_ascii=False)):
            return []
    if len({name for name, _ in params}) != len(params):
        return []
    return [[offset + bounds[start], offset + bounds[end]]]


def _normal_events(trajectory, note):
    environment = trajectory["environment"]
    seen_ids, seen_calls = set(), set()
    dispatch_order = -1
    seen_returns = set()
    normalized = []
    for index, event in enumerate(trajectory["tool_events"]):
        recorded_event_id, call_id = str(event.get("event_id", f"unknown:{index}")), event.get("tool_call_id")
        event_id = recorded_event_id
        name, raw_args = event.get("tool_name"), event.get("exact_arguments")
        arguments = _parse_args(raw_args)
        errors = []
        if "event_id" not in event or event_id in seen_ids or not isinstance(call_id, str) or not call_id or call_id in seen_calls:
            errors.append("invalid_call_identity")
        if recorded_event_id in seen_ids:
            event_id = f"duplicate-event:{index}"
        seen_ids.add(recorded_event_id)
        if isinstance(call_id, str):
            seen_calls.add(call_id)
        dispatched = event.get("dispatch_order")
        if type(dispatched) is not int or dispatched <= dispatch_order:
            errors.append("invalid_dispatch_order")
        else:
            dispatch_order = dispatched
        if arguments is None or not isinstance(name, str) or not name:
            errors.append("invalid_tool_arguments")
        exact = event.get("exact_result")
        documents = []
        returned = isinstance(exact, str) and isinstance(event.get("return_utc"), str)
        missing = not returned
        if missing:
            errors.append("missing_return")
        else:
            returned_at = event.get("return_order")
            if type(returned_at) is not int or returned_at < 1 or returned_at in seen_returns:
                errors.append("invalid_return_order")
            else:
                seen_returns.add(returned_at)
            response = event.get("raw_mcp_response")
            if isinstance(response, dict) and response.get("isError") is True:
                errors.append("tool_failure")
            else:
                try:
                    value = json.loads(exact)
                except (ValueError, TypeError):
                    value = None
                if isinstance(value, dict) and "error" in value:
                    errors.append("tool_failure")
                elif value is None and name in environment.get("json_tools", environment.get("deterministic_tools", [])):
                    errors.append("invalid_tool_return")
                else:
                    records = value if isinstance(value, list) else value.get("results", [value]) if isinstance(value, dict) else []
                    if isinstance(records, list):
                        documents = list(dict.fromkeys(
                            document_id for item in records if isinstance(item, dict)
                            if isinstance(document_id := item.get("docid", item.get("document_id")), str)
                            and document_id
                        ))
        for error in errors:
            note(error, event_id=event_id, round_id=event.get("round_id"))
        normalized.append({
            "event_id": event_id, "recorded_event_id": recorded_event_id, "call_id": call_id, "tool_name": name,
            "arguments": arguments, "arguments_raw": raw_args,
            "environment": environment.get("id"),
            "deterministic": bool(environment.get("id") and name in environment.get("deterministic_tools", [])),
            "round_id": event.get("round_id"), "batch_id": event.get("batch_id"),
            "ordinal": event.get("tool_ordinal"), "dispatch_order": dispatched, "return_order": event.get("return_order"),
            "dispatch_time": event.get("dispatch_utc"), "return_time": event.get("return_utc"),
            "source_pointer": f"/tool_events/{index}",
            "return_ref": {"source_pointer": f"/tool_events/{index}/exact_result",
                           "character_span": [0, len(exact)]} if isinstance(exact, str) else None,
            "_returned_text": exact if returned else None,
            "_documents": documents,
            "return_text": None, "error": errors[0] if errors else None, "errors": errors,
            "visible_next": False, "visibility_basis": "not_observed", "return_tokens": None, "document_ids": [],
            "parallel_group_id": None,
        })
    return normalized


def _link_legacy(stages, blocks, trajectory, positions, note):
    rounds = {row["round_id"]: (index, row) for index, row in enumerate(trajectory["rounds"])}
    seen = set()
    for block in blocks:
        legacy_id = block.get("uid")
        if not isinstance(legacy_id, str) or not legacy_id or legacy_id in seen:
            note("invalid_legacy_identity")
            continue
        seen.add(legacy_id)
        if block.get("rollout_id") != trajectory["trajectory_id"] or block.get("source_sha256") != trajectory["input_sha256"]:
            note("legacy_source_mismatch", legacy_block_id=legacy_id)
            continue
        index, row = rounds.get(block.get("round_id"), (None, {}))
        text = row.get("reasoning_content") or ""
        ids = (row.get("token_accounting") or {}).get("completion_token_ids") or []
        a, b = block.get("start_char"), block.get("end_char")
        start, end = block.get("native_start_token"), block.get("native_end_token")
        if (block.get("source_field") != "reasoning_content" or index not in positions
                or not all(type(value) is int for value in (a, b, start, end))
                or not (0 <= a < b <= len(text) and 0 <= start < end <= len(ids))
                or sha256(text[a:b].encode("utf-8")) != block.get("sha256")
                or ids[start:end] != block.get("native_token_ids")):
            note("legacy_coordinates_unverified", legacy_block_id=legacy_id)
            continue
        offset = positions[index][0]
        for stage in stages:
            overlap = [[max(left, start + offset), min(right, end + offset)]
                       for left, right in stage["policy_token_spans"]
                       if max(left, start + offset) < min(right, end + offset)]
            if overlap:
                align = "verified_overlap"
                stage["legacy_mapping_status"] = align
                stage["legacy_mapping"].append({
                    "legacy_block_id": legacy_id, "overlap_policy_spans": overlap,
                    "legacy_character_span": [a, b], "legacy_round_tokens": [start, end],
                    "source_sha256": block["source_sha256"], "status": align,
                })


def parse_stages(trajectory, format_config=None, legacy_blocks=None):
    """Return causal stages, individual events, exact positions and explicit gaps."""
    rounds = trajectory["rounds"]
    anomalies = []

    def note(code, **fields):
        anomalies.append({"code": code, **fields})

    tokenizer = (format_config or {}).get("tokenizer")
    docid = (format_config or {}).get("phase1_mode") == "docid"
    if tokenizer is not None and tokenizer.revision != trajectory["tokenizer_revision"]:
        note("tokenizer_revision_mismatch")
        tokenizer = None
    positions, count = _native_layout(rounds, trajectory["tokenizer_revision"], note)
    round_ids = [r.get("round_id") for r in rounds]
    if not all(type(i) is int for i in round_ids) or round_ids != list(range(1, len(rounds) + 1)):
        note("round_order_unverified")
        positions, count = {}, None
    events = _normal_events(trajectory, note)
    by_round = defaultdict(list)
    round_counts = Counter(round_id for round_id in round_ids if type(round_id) is int)
    for event in events:
        by_round[event["round_id"]].append(event)
        if not round_counts[event["round_id"]]:
            note("orphan_tool_event", event_id=event["event_id"], round_id=event["round_id"])

    visible_by_round = {}
    associated_by_index = {}
    previous_events = []
    for index, row in enumerate(rounds):
        visible_by_round[index] = _prompt_evidence(row, previous_events, tokenizer, note)
        if index > 0:
            for event in associated_by_index[index - 1]:
                if event["event_id"] in visible_by_round[index]:
                    event["visible_next"] = True
                    event["visibility_basis"] = "native_prompt_verified" if tokenizer else "recorded_prompt_message"
                    event["return_text"] = event["_returned_text"]
                    event["return_tokens"] = visible_by_round[index][event["event_id"]]
                    if docid and event["tool_name"] == "search-server-search":
                        from .docid import passages_from_return
                        event["document_ids"] = list(passages_from_return(event["return_text"]))
                    else:
                        event["document_ids"] = event["_documents"]
                elif event["_returned_text"] is not None:
                    note("return_not_visible_in_next_prompt", event_id=event["event_id"], round_id=event["round_id"])
        associated = by_round.pop(row.get("round_id"), [])
        associated_by_index[index] = associated
        if round_counts[row.get("round_id")] > 1:
            for event in associated:
                event["errors"].append("ambiguous_round_identity")
                event["error"] = event["error"] or "ambiguous_round_identity"
        previous_events.extend(e for e in associated if e["_returned_text"] is not None)
        if index + 1 == len(rounds) and any(event["_returned_text"] is not None for event in associated):
            note("return_not_reinjected_at_termination", round_id=row.get("round_id"))

    stages = []
    pending = []
    for index, row in enumerate(rounds):
        pending.append(index)
        number = row.get("round_id")
        associated = associated_by_index[index]
        calls = row.get("tool_calls") or []
        if not calls and not associated and index + 1 < len(rounds):
            continue
        normal = (index + 1 == len(rounds) and not calls and not associated
                  and trajectory["termination_reason"] == "MODEL_FINAL_STOP"
                  and row.get("response_received") and isinstance(row.get("content"), str)
                  and bool(row["content"].strip()))
        stage_type = "tool" if calls or associated else "final" if normal else "partial"
        order = len(stages) + 1
        stage_id = f"{trajectory['trajectory_id']}:S{order:03}"
        call_ids = [call.get("id") for call in calls]
        group = f"{stage_id}:parallel" if max(len(calls), len(associated)) > 1 else None
        protocol_ok = len(calls) == len(associated)
        for ordinal, (call, event) in enumerate(zip(calls, associated), start=1):
            function = call.get("function") or {}
            protocol_ok &= (
                call.get("id") == event["call_id"] and ordinal == event["ordinal"]
                and row.get("batch_id") == event["batch_id"]
                and function.get("name") == event["tool_name"]
                and _parse_args(function.get("arguments")) == event["arguments"])
        if not protocol_ok:
            note("call_event_mismatch", round_id=number, call_ids=call_ids)
        for event in associated:
            event["parallel_group_id"] = group
        spans = [positions[i] for i in pending if i in positions and positions[i][0] < positions[i][1]]
        policy_count = [rounds[i].get("completion_tokens") for i in pending]
        returned_counts = [event["return_tokens"] for event in associated]
        valid = protocol_ok and not any(event["errors"] for event in associated)
        parse_status = ("incomplete" if stage_type == "partial" or "missing_return" in
                        {error for event in associated for error in event["errors"]}
                        else "ok" if valid else "protocol_error")
        action = None
        charge = []
        if protocol_ok and len(associated) == 1:
            action = {key: associated[0][key] for key in ("tool_name", "arguments", "call_id", "event_id",
                                                         "environment", "deterministic", "dispatch_time")}
            if parse_status == "ok" and associated[0]["visible_next"] and index in positions:
                charge = _charge_span(row, action, positions[index][0], tokenizer)
        text_refs = [{"source_pointer": f"/rounds/{i}/{field}", "character_span": [0, len(rounds[i][field])]}
                     for i in pending for field in ("reasoning_content", "content")
                     if isinstance(rounds[i].get(field), str)]
        stages.append({
            "stage_id": stage_id, "stage_type": stage_type, "order": order, "round_ids": [round_ids[i] for i in pending],
            "call_ids": call_ids, "event_ids": [event["event_id"] for event in associated],
            "parallel_group_id": group,
            "policy_spans": spans, "policy_token_spans": spans, "policy_coordinate": POLICY_COORDINATE,
            "charge_token_spans": charge, "charge_strategy": "native_call_only" if charge else "unavailable",
            "return_refs": [event["return_ref"] for event in associated if event["return_ref"] is not None],
            "strategy_refs": text_refs, "visible_return_ids": list(visible_by_round[index]),
            "cost": {"policy_tokens": sum(policy_count) if all(type(n) is int for n in policy_count) else None,
                     "return_tokens": sum(returned_counts) if all(type(n) is int for n in returned_counts) else None,
                     "tool_calls": len(calls)},
            "legacy_mapping": [], "legacy_mapping_status": "unavailable",
            "parse_status": parse_status, "action": action,
            "strategy_text": "\n".join(rounds[i]["reasoning_content"] for i in pending
                                       if isinstance(rounds[i].get("reasoning_content"), str)),
            "pre_action_text": "\n".join(rounds[i][key] for i in pending
                                         for key in ("reasoning_content", "content")
                                         if isinstance(rounds[i].get(key), str)),
            "final_text": row["content"] if normal else None,
            "known_at": row.get("finished_utc"),
        })
        pending = []
    if trajectory["guard_attempts"]:
        note("unsent_context_guard", count=len(trajectory["guard_attempts"]))
    if trajectory["termination_reason"] != "MODEL_FINAL_STOP":
        note("nonfinal_termination", reason=trajectory["termination_reason"])
    elif not stages or stages[-1]["stage_type"] != "final":
        note("missing_final", reason=trajectory["termination_reason"])
    if legacy_blocks:
        _link_legacy(stages, legacy_blocks, trajectory, positions, note)
    for event in events:
        del event["_returned_text"]
        del event["_documents"]
    policy_spans = [[0, count]] if count else []
    return {
        "stages": stages, "tool_events": events, "position_map": {
            "policy_coordinate": POLICY_COORDINATE,
            "rounds": [{"round_id": round_ids[i], "source_pointer": f"/rounds/{i}/token_accounting/completion_token_ids",
                        "policy_token_span": position} for i, position in positions.items()],
            "tokenizer_sha256": tokenizer.sha256 if tokenizer else None,
        },
        "anomalies": anomalies, "token_alignment_status": "verified" if count is not None else "unverified",
        "policy_token_spans": policy_spans, "policy_token_count": count,
        "recording_complete": bool(rounds) and all(
            row.get("response_received") is True for row in rounds
        ) and not any(event["errors"] for event in events) and not any(
            row["code"] in {"orphan_tool_event", "round_order_unverified", "call_event_mismatch", "missing_final"}
            for row in anomalies
        ),
    }
