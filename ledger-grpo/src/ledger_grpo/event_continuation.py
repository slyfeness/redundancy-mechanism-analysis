"""Regenerate a BrowseComp suffix from one matched event prefix."""

import json

from .event_deletion import _render


def continue_browsecomp(request, branch, *, seed, start_round, max_rounds, context, headroom,
                        tokenizer, sample, search):
    """Use the archived chat settings with a new seed and a fresh suffix.

    The transport supplies the served prompt and completion token IDs. The
    search callback dispatches native calls using the original agent, including
    its feedback for unregistered tools.
    """
    if not 1 <= start_round <= max_rounds:
        raise ValueError('continuation round is outside the original rollout budget')
    messages = branch['messages'][:]
    call_ids = {call['id'] for message in messages for call in (message.get('tool_calls') or ())}
    final = None
    actor_calls = tool_calls = generated_tokens = 0
    terminal = 'SAFETY_CEILING_STOP'
    for round_id in range(start_round, max_rounds + 1):
        payload = dict(request, messages=messages, seed=seed)
        expected = _render(messages, payload, tokenizer)
        if round_id == start_round and expected != branch['prompt_token_ids']:
            raise ValueError('continuation prefix no longer matches the bound native prompt')
        if len(expected) + payload['max_tokens'] + headroom > context:
            terminal = 'CONTEXT_LIMIT_STOP'
            break
        response = sample(payload)
        actor_calls += 1
        if response.get('prompt_token_ids') != expected:
            raise ValueError('served native prompt differs from the prepared input')
        choices = response['choices']
        if len(choices) != 1 or not isinstance(choices[0].get('token_ids'), list):
            raise ValueError('missing single native completion token record')
        choice = choices[0]
        generated_tokens += len(choice['token_ids'])
        if choice['finish_reason'] == 'length':
            terminal = 'GENERATION_LENGTH_STOP'
            break
        message = choice['message']
        calls = message.get('tool_calls') or []
        content = message.get('content') or ''
        if not calls:
            if choice['finish_reason'] == 'stop' and content.strip():
                terminal, final = 'MODEL_FINAL_STOP', content
            else:
                terminal = 'EMPTY_MODEL_STOP'
            break

        assistant = {'role': 'assistant', 'content': content, 'tool_calls': calls}
        reasoning = message.get('reasoning')
        if reasoning is None:
            reasoning = message.get('reasoning_content')
        if reasoning:
            assistant.update(reasoning=reasoning, reasoning_content=reasoning)
        returns = []
        for call in calls:
            fn = call['function']
            identity = call['id']
            if not fn['name'] or not identity or identity in call_ids:
                raise ValueError('continuation requires distinct native tool calls')
            if fn['name'] == 'search-server-search' and not isinstance(json.loads(fn['arguments']), dict):
                raise ValueError('search arguments must be a JSON object')
            call_ids.add(identity)
        for call in calls:
            fn = call['function']
            result = search(fn['name'], fn['arguments'])
            if not isinstance(result, str):
                raise ValueError('search did not produce a visible text return')
            tool_calls += 1
            returns.append({'role': 'tool', 'tool_call_id': call['id'], 'name': fn['name'], 'content': result})
        messages = messages + [assistant] + returns
    return {'terminal': terminal, 'final': final, 'actor_calls': actor_calls, 'tool_calls': tool_calls,
            'generated_tokens': generated_tokens}
