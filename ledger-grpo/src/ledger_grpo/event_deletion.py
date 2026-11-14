"""Build matched BrowseComp-Plus continuation prefixes for one tool event."""

import json

from .browsecomp_adapter import _recorded_search_response
from .native_tool_coordinates import matches_return_suffix


def _render(messages, request, tokenizer):
    normalized = []
    for message in messages:
        if message.get('tool_calls'):
            calls = []
            for call in message['tool_calls']:
                fn = call['function']
                args = fn['arguments']
                calls.append(dict(call, function=dict(fn, arguments=json.loads(args) if isinstance(args, str) else args)))
            message = dict(message, tool_calls=calls)
        normalized.append(message)
    options = {'enable_thinking': True, **(request.get('chat_template_kwargs') or {})}
    ids = tokenizer.apply_chat_template(normalized, tools=request['tools'], tokenize=True,
                                        add_generation_prompt=True, **options)
    return ids.input_ids if hasattr(ids, 'input_ids') else ids


def prepare_event_deletion(current, following, request, events, event_id, tokenizer):
    """Erase one stateless search call and return from a verified original prefix.

    The assistant reasoning generated before the result, parallel siblings and
    earlier messages are held fixed. A continuation must generate a new suffix.
    """
    if (following['round_id'] != current['round_id'] + 1
            or any(row.get('request_sent') is not True or row.get('response_received') is not True
                   or row.get('prompt_truncated') for row in (current, following))):
        raise ValueError('event deletion requires two adjacent observed rounds with intact prompts')
    if not events or any(event['tool_name'] != 'search-server-search' or not _recorded_search_response(event)
                         for event in events):
        raise ValueError('event deletion requires a completed stateless search batch')
    event_ids = [str(event['event_id']) for event in events]
    call_ids = [event['tool_call_id'] for event in events]
    if event_id not in event_ids or len(set(event_ids)) != len(events) or len(set(call_ids)) != len(events):
        raise ValueError('target event must identify one distinct call in the batch')

    messages = request['messages']
    batch_index = len(messages) - len(events) - 1
    if (batch_index < 1 or messages != following['actor_visible_messages']
            or messages[:batch_index] != current['actor_visible_messages']
            or not matches_return_suffix(following, events)):
        raise ValueError('continuation history does not match the original request and dispatched batch')
    assistant = messages[batch_index]
    calls = assistant.get('tool_calls') or []
    if (assistant['role'] != 'assistant' or calls != current['tool_calls']
            or [call['id'] for call in calls] != call_ids):
        raise ValueError('tool call identifiers do not match the original assistant turn')
    for call, event in zip(calls, events, strict=True):
        fn = call['function']
        args = fn['arguments']
        if (fn['name'] != event['tool_name']
                or (json.loads(args) if isinstance(args, str) else args) != json.loads(event['exact_arguments'])):
            raise ValueError('tool call name or arguments differ from the original event')

    recorded = following['token_accounting']
    normal_ids = _render(messages, request, tokenizer)
    if recorded.get('exact_prompt_token_ids_equal') is not True or normal_ids != recorded['prompt_token_ids']:
        raise ValueError('control prefix does not reproduce the original native prompt IDs')
    index = event_ids.index(event_id)
    result_index = batch_index + 1 + index
    edited_assistant = dict(assistant, tool_calls=calls[:index] + calls[index+1:])
    edited = messages[:batch_index] + [edited_assistant] + messages[batch_index+1:result_index] + messages[result_index+1:]
    edited_ids = _render(edited, request, tokenizer)
    if edited_ids == normal_ids:
        raise ValueError('deletion did not change the actor input')
    return {'round_id': following['round_id'], 'event_id': event_id, 'tool_call_id': call_ids[index],
            'normal': {'messages': messages, 'prompt_token_ids': normal_ids},
            'delete': {'messages': edited, 'prompt_token_ids': edited_ids}}
