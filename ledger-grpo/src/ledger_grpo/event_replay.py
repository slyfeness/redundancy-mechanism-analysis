"""Find exact repeats with a witness in the model's observed prefix."""


def delivered_repeat_witnesses(rounds, events_by_round, *, event_key, normalize_return=None):
    """Return current event ID to first visible matching event ID.

    The adapter supplies equality and eligibility through event_key. Tool
    messages must bind by call ID and result. Returns from siblings in a single
    assistant batch become available only in a later model request.
    """
    pending, seen, repeats = {}, {}, {}
    call_ids = set()
    for row in rounds:
        if row.get('request_sent') is True and row.get('response_received') is True:
            for message in row.get('actor_visible_messages') or ():
                if message.get('role') != 'tool' or not isinstance(message.get('content'), str):
                    continue
                call_id = message.get('tool_call_id')
                witness = pending.get(call_id)
                if witness is None:
                    continue
                content = message['content']
                if normalize_return is not None:
                    content = normalize_return(content)
                if witness[0] == content:
                    _, key, identity = pending.pop(call_id)
                    seen.setdefault(key, identity)
        for event in events_by_round.get(row['round_id'], ()):
            call_id = event['tool_call_id']
            new_call_id = call_id not in call_ids
            call_ids.add(call_id)
            if not new_call_id:
                pending.pop(call_id, None)
            key = event_key(event)
            if key is None:
                continue
            identity = str(event['event_id'])
            if key in seen:
                repeats[identity] = seen[key]
            if new_call_id:
                pending[call_id] = (event['exact_result'], key, identity)
    return repeats
