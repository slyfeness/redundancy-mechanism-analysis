import unittest

from ledger_grpo.event_deletion import prepare_event_deletion


class FixtureTokenizer:
    def apply_chat_template(self, messages, *, tools, tokenize, add_generation_prompt, enable_thinking):
        return [ord(c) for c in repr((messages, tools, tokenize, add_generation_prompt, enable_thinking))]


class EventDeletionTest(unittest.TestCase):
    def setUp(self):
        self.tokenizer = FixtureTokenizer()
        self.events = [dict(event_id=str(i), tool_call_id=f'call-{i}', tool_name='search-server-search',
                            exact_arguments=f'{{"query": "q{i}"}}', exact_result=f'observation-{i}',
                            raw_mcp_response={'isError': False, 'content': [{'type': 'text', 'text': f'observation-{i}'}]})
                       for i in (1, 2)]
        self.calls = [dict(id=e['tool_call_id'], type='function',
                           function={'name': e['tool_name'], 'arguments': e['exact_arguments']}) for e in self.events]
        self.prefix = [{'role': 'user', 'content': 'question'}]
        self.returns = [dict(role='tool', tool_call_id=e['tool_call_id'], name=e['tool_name'],
                             content=e['exact_result']) for e in self.events]

    def pair(self, target='1', n=2, *, mismatched_prompt=False, next_round=3, changed_history=False):
        assistant = dict(role='assistant', reasoning_content='Pre-return reasoning', content='', tool_calls=self.calls[:n])
        messages = self.prefix + [assistant] + self.returns[:n]
        if changed_history:
            messages = [{'role': 'user', 'content': 'different task'}] + messages[1:]
        request = {'messages': messages, 'tools': [{'type': 'function'}], 'seed': 42,
                   'chat_template_kwargs': {'enable_thinking': True}}
        current = {'round_id': 2, 'request_sent': True, 'response_received': True,
                   'actor_visible_messages': self.prefix, 'tool_calls': self.calls[:n]}
        normalized = messages[:1] + [dict(assistant, tool_calls=[dict(call, function=dict(call['function'],
                      arguments={'query': f'q{i}'})) for i, call in enumerate(self.calls[:n], 1)])] + self.returns[:n]
        native = self.tokenizer.apply_chat_template(normalized, tools=request['tools'], tokenize=True,
                                                   add_generation_prompt=True, enable_thinking=True)
        following = {'round_id': next_round, 'request_sent': True, 'response_received': True,
                     'actor_visible_messages': messages, 'token_accounting': {
                         'exact_prompt_token_ids_equal': True, 'prompt_token_ids': native + [0] if mismatched_prompt else native}}
        result = prepare_event_deletion(current, following, request, self.events[:n], target, self.tokenizer)
        return result, request

    def test_preserves_parallel_sibling_and_pre_return_reasoning(self):
        result, request = self.pair()
        self.assertEqual(result['normal']['messages'], request['messages'])
        edited = result['delete']['messages']
        self.assertEqual(edited[0], self.prefix[0])
        self.assertEqual(edited[1]['tool_calls'], self.calls[1:])
        self.assertEqual(edited[1]['reasoning_content'], 'Pre-return reasoning')
        self.assertEqual(edited[2:], self.returns[1:])
        self.assertEqual(len(request['messages'][1]['tool_calls']), 2)
        self.assertNotEqual(result['normal']['prompt_token_ids'], result['delete']['prompt_token_ids'])

    def test_single_call_removal_retains_the_reasoning_turn(self):
        result, _ = self.pair(n=1)
        edited = result['delete']['messages']
        self.assertEqual(len(edited), 2)
        self.assertEqual(edited[1]['tool_calls'], [])
        self.assertEqual(edited[1]['reasoning_content'], 'Pre-return reasoning')

    def test_rejects_mismatched_source(self):
        for options in ({'mismatched_prompt': True}, {'next_round': 4}, {'changed_history': True}, {'target': '3'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.pair(**options)
