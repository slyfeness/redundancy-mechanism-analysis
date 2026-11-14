import unittest
from unittest.mock import patch

from ledger_grpo.event_continuation import continue_browsecomp


class EventContinuationTest(unittest.TestCase):
    def setUp(self):
        self.prefix = [{'role': 'user', 'content': 'question'}]
        self.branch = {'messages': self.prefix, 'prompt_token_ids': [1]}
        self.request = {'messages': [{'role': 'user', 'content': 'archived request'}],
                        'seed': 42, 'max_tokens': 10, 'temperature': 1.0, 'tools': []}
        self.calls = []
        self.searches = []
        self.tool = {'id': 'new', 'type': 'function', 'function': {'name': 'search-server-search',
                     'arguments': '{"query":"new search"}'}}
        render = patch('ledger_grpo.event_continuation._render', self.tokenize)
        render.start()
        self.addCleanup(render.stop)

    def tokenize(self, messages, request, tokenizer):
        return [len(messages)]

    def sample(self, request):
        self.calls.append(request)
        message = {'tool_calls': [self.tool], 'reasoning': 'new reasoning'} if len(self.calls) == 1 else {'content': 'new answer'}
        return {'prompt_token_ids': [len(request['messages'])],
                'choices': [{'message': message, 'finish_reason': 'tool_calls' if 'tool_calls' in message else 'stop', 'token_ids': [8]}]}

    def search(self, name, arguments):
        self.searches.append((name, arguments))
        return 'fresh tool return'

    def run_branch(self, **options):
        settings = dict(seed=123, start_round=19, max_rounds=20, context=64, headroom=5,
                        tokenizer=None, sample=self.sample, search=self.search)
        return continue_browsecomp(self.request, self.branch, **(settings | options))

    def test_generates_new_suffix_and_keeps_original_sampling(self):
        result = self.run_branch()
        self.assertEqual(result['terminal'], 'MODEL_FINAL_STOP')
        self.assertEqual(result['final'], 'new answer')
        self.assertEqual(result['actor_calls'], 2)
        self.assertEqual(result['generated_tokens'], 2)
        self.assertEqual(self.calls[0]['messages'], self.prefix)
        self.assertEqual(self.calls[1]['messages'][-1]['content'], 'fresh tool return')
        self.assertEqual(self.calls[1]['messages'][-2]['reasoning_content'], 'new reasoning')
        self.assertEqual([c['seed'] for c in self.calls], [123, 123])
        self.assertEqual(self.calls[1]['max_tokens'], 10)
        self.assertEqual(len(self.prefix), 1)
        self.assertEqual(self.request['seed'], 42)

    def test_context_guard_and_round_budget(self):
        result = self.run_branch(context=15)
        self.assertEqual((result['terminal'], result['actor_calls']), ('CONTEXT_LIMIT_STOP', 0))
        self.assertFalse(self.calls)
        result = self.run_branch(start_round=20)
        self.assertEqual((result['terminal'], result['actor_calls']), ('SAFETY_CEILING_STOP', 1))
        self.assertEqual(len(self.searches), 1)

    def test_prompt_mismatch_stops_before_tool_dispatch(self):
        def wrong_prompt(request):
            return dict(self.sample(request), prompt_token_ids=[99])

        with self.assertRaisesRegex(ValueError, 'native prompt'):
            self.run_branch(sample=wrong_prompt)
        self.assertFalse(self.searches)

    def test_unknown_tool_feedback_is_visible_to_the_next_round(self):
        self.tool['function'] = {'name': 'answer', 'arguments': '{"answer":"unverified"}'}

        def dispatch(name, arguments):
            self.searches.append((name, arguments))
            return 'Tool answer does not exists.'

        result = self.run_branch(search=dispatch)
        self.assertEqual(result['terminal'], 'MODEL_FINAL_STOP')
        self.assertEqual(self.searches, [('answer', '{"answer":"unverified"}')])
        self.assertEqual(self.calls[1]['messages'][-1], {
            'role': 'tool', 'tool_call_id': 'new', 'name': 'answer', 'content': 'Tool answer does not exists.'})

    def test_tool_id_already_present_in_prefix_cannot_dispatch(self):
        self.prefix[0]['tool_calls'] = [self.tool]
        with self.assertRaisesRegex(ValueError, 'distinct native'):
            self.run_branch()
        self.assertFalse(self.searches)
