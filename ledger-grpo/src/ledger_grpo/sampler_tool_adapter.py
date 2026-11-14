"""Bind SAGE and SciCode sampler records to the common native event format."""

import hashlib
import json

from .native_tool_coordinates import recorded_tool_coordinates


_FIELDS = {"sage": ("tool_call_id", "observation"), "scicode": ("call_id", "model_visible_return")}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def sampler_repeat_receipt(dataset, event, *, revision, draft):
    """Build a repeat key and advance the verified coding draft when it changes."""
    call_key, result_key = _FIELDS[dataset]
    result = event[result_key]
    name, args = event["name"], event["arguments"]
    if dataset == "sage":
        eligible = ((name == "search" and isinstance(result.get("results"), list))
                    or (name == "open" and isinstance(result.get("text"), str)))
    else:
        if name in ("write_code", "submit_code") and result.get("status") == "ACCEPTED":
            draft = hashlib.sha256(args["code"].encode()).hexdigest()
            if result["code_sha256"] != draft:
                raise ValueError("accepted write does not bind to its draft")
            revision += 1
        eligible = name == "read_code" and result.get("status") == "OK"
        if eligible and (result["code_sha256"] != draft or hashlib.sha256(result["current_code"].encode()).hexdigest() != draft):
            raise ValueError("read receipt does not bind to the active draft")
    key = (revision, name, _json(args), _json(result)) if eligible else None
    return {"event_id": event["event_id"], "tool_call_id": event[call_key], "exact_result": _json(result), "name": name,
            "repeat_key": key}, revision, draft


def canonical_sampler_return(text):
    try:
        return _json(json.loads(text))
    except (TypeError, ValueError):
        return None


def measure_sampler_batch(dataset, response, events, *, next_request, next_response, tokenizer, offset=0):
    """Measure a full dispatch batch using the result strings actually sent."""
    if dataset not in _FIELDS:
        raise ValueError("expected the SAGE or SciCode sampler format")
    if not events:
        return []
    call_key, return_key = _FIELDS[dataset]
    messages = next_request.get("messages") if isinstance(next_request, dict) else None
    if not isinstance(messages, list) or len(messages) < len(events):
        raise ValueError("next request lacks the dispatched tool results")
    normalized = []
    for event, message in zip(events, messages[-len(events):], strict=True):
        content = message.get("content")
        if (message.get("role") != "tool" or message.get("tool_call_id") != event[call_key]
                or not isinstance(content, str) or _json(json.loads(content)) != _json(event[return_key])):
            raise ValueError("tool result receipt differs from the actual next request")
        normalized.append({"event_id": event["event_id"], "tool_call_id": event[call_key],
                           "tool_name": event["name"], "exact_arguments": _json(event["arguments"]),
                           "exact_result": content})
    return recorded_tool_coordinates(response, normalized, next_request=next_request, next_response=next_response,
                                     tokenizer=tokenizer, offset=offset)
