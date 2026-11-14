"""Measure tool envelopes and returns on actual Qwen native token coordinates."""

import json
import re

from .native_capture import native_chat_segment


_CALL = re.compile(rb'<tool_call>\s*<function=([^>]+)>.*?</function>\s*</tool_call>', re.DOTALL)
_RESULT = re.compile(r'<tool_response>\n(.*?)\n</tool_response>', re.DOTALL)


def _aligned_tool_envelopes(chunks):
    matches, pieces = [], []
    bounds = {0: 0}
    cursor = 0
    for index, chunk in enumerate(chunks+[None]):
        if isinstance(chunk, list) and chunk:
            pieces.append(bytes(chunk))
            cursor += len(chunk)
            bounds[cursor] = index+1
            continue
        for match in _CALL.finditer(b''.join(pieces)):
            if match.start() not in bounds or match.end() not in bounds:
                return None
            matches.append((match[0], match[1], bounds[match.start()], bounds[match.end()]))
        cursor, bounds, pieces = 0, {0: index+1}, []
    return matches


def call_ranges(row, events, offset, *, tokenizer=None):
    choice = row['raw_response']['choices'][0]
    chunks = [x.get('bytes') for x in choice['logprobs']['content']]
    if any(chunk is not None and not isinstance(chunk, list) for chunk in chunks):
        return None
    matches = _aligned_tool_envelopes(chunks)
    parsed = row.get('tool_calls') or []
    if matches is None or len(matches) != len(events) or len(parsed) != len(events):
        return None
    if not all(chunks):
        native = row.get('token_accounting', {}).get('completion_token_ids')
        if tokenizer is None or not isinstance(native, list) or len(native) != len(chunks) or native != choice.get('token_ids'):
            return None
        decoded = tokenizer.decode(native, skip_special_tokens=False).encode()
        if [match[0] for match in _CALL.finditer(decoded)] != [body for body, _, _, _ in matches]:
            return None
    spans = []
    for (_, name, start, stop), call, event in zip(matches, parsed, events, strict=True):
        fn = call['function']
        if (call['id'] != event['tool_call_id'] or fn['name'] != event['tool_name']
                or name != fn['name'].encode() or json.loads(fn['arguments']) != json.loads(event['exact_arguments'])):
            return None
        spans.append([offset+start, offset+stop])
    return spans


def matches_return_suffix(row, events):
    history = row.get('actor_visible_messages') or []
    if len(history) < len(events):
        return False
    suffix = history[-len(events):]
    return all(msg.get('role') == 'tool' and msg.get('tool_call_id') == e['tool_call_id']
               and msg.get('content') == e['exact_result'] for msg,e in zip(suffix,events,strict=True))


def prompt_return_counts(rendered, prompt_ids, events, tokenizer):
    matches = list(_RESULT.finditer(rendered))[-len(events):]
    if len(matches) != len(events) or any(m[1] != e['exact_result'] for m,e in zip(matches,events,strict=True)):
        return None
    encoded = tokenizer(rendered, add_special_tokens=False, return_offsets_mapping=True)
    if encoded['input_ids'] != prompt_ids:
        return None
    used = set()
    counts = []
    for match in matches:
        left,right = match.span(1)
        positions = {i for i,(start,stop) in enumerate(encoded['offset_mapping'])
                     if start < stop and start < right and stop > left}
        if used & positions or (left < right and not positions):
            return None
        used.update(positions)
        counts.append(len(positions))
    return counts


def recorded_tool_coordinates(response, events, *, next_request, next_response, tokenizer, offset=0):
    """Bind a complete dispatched batch to a recorded next request and native prompt."""
    if not events:
        return []
    if type(offset) is not int or offset < 0:
        raise ValueError("policy offset must be a nonnegative integer")
    for key in ("event_id", "tool_call_id"):
        ids = [event[key] for event in events]
        if any(not isinstance(identity, str) or not identity for identity in ids) or len(set(ids)) != len(ids):
            raise ValueError("tool event and call IDs must be unique strings in the batch")
    if not isinstance(next_request, dict) or not isinstance(next_response, dict):
        raise ValueError("tool returns require a recorded next request and response")
    if not matches_return_suffix({"actor_visible_messages": next_request.get("messages")}, events):
        raise ValueError("next request does not contain the ordered dispatched tool results")

    current = native_chat_segment(response)
    next_prompt_ids = native_chat_segment(next_response)["prompt_ids"]
    calls = response["choices"][0]["message"].get("tool_calls")
    row = {"raw_response": response, "tool_calls": calls,
           "token_accounting": {"completion_token_ids": current["completion_ids"]}}
    spans = call_ranges(row, events, offset, tokenizer=tokenizer)
    if spans is None:
        raise ValueError("native tool envelopes do not bind to the complete dispatched batch")
    rendered = tokenizer.decode(next_prompt_ids, skip_special_tokens=False)
    returned = prompt_return_counts(rendered, next_prompt_ids, events, tokenizer)
    if returned is None:
        raise ValueError("actual prompt IDs do not bind to the ordered tool returns")
    return [{"event_id": event["event_id"], "event_tokens": [start, stop],
             "event_cost": {"generated_tokens": stop-start, "returned_tokens": count, "tool_calls": 1}}
            for event, (start, stop), count in zip(events, spans, returned, strict=True)]
