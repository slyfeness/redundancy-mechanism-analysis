import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from ledger_grpo.browsecomp_adapter import adapt_trajectory, extract_constraints, _observations, submitted_candidate, _recorded_search_response
from ledger_grpo.browsecomp_events import _call_ranges, collect_tool_events


def recorder_fixture():
    def response(prompt, completion):
        return {'response_received': True,
                'token_accounting': {'prompt_token_ids': prompt, 'completion_token_ids': completion,
                                     'exact_prompt_token_ids_equal': True},
                'raw_response': {'choices': [{'logprobs': {'content': [{'logprob': -1.} for _ in completion]}}]}}
    first = dict(response([1], [2, 3]), round_id=1, content='Thinking and searching.',
                 tool_calls=[{'id': 'call-1'}])
    final = dict(response([1, 2, 3, 99], [4, 5]), round_id=2,
                 content='**Exact Answer:** Ada Lovelace', tool_calls=[])
    return {'metadata': {'task': {'run_id': 'q1__rep1', 'query_id': 1, 'gold': 'private-gold'},
                         'terminal_status': 'MODEL_FINAL_STOP'},
            'rounds': [first, final], 'tool_events': [
                {'round_id': 1, 'tool_ordinal': 0, 'event_id': 1, 'tool_call_id': 'call-1',
                 'tool_name': 'batch_search', 'exact_arguments': json.dumps({'query': 'name'}),
                 'exact_result': json.dumps([{'docid': 'document-a', 'snippet': 'Visible line\nsecond line.'}]),
                 'retrieved_documents': [{'snippet': 'private-gold'}]}]}


CONSTRAINTS = [{'cid': 'c1', 'text': 'Who is named?', 'required': True, 'kind': 'evidence'}]


class AdapterTests(unittest.TestCase):
    def test_native_call_ranges_cross_check_incomplete_byte_log_against_original_ids(self):
        tool = 'search-server-search'
        arguments = '{"query":"example"}'
        call = f'<tool_call><function={tool}>{arguments}</function></tool_call>'
        ids = list(map(ord, 'x'+call+'y'))

        class Tokenizer:
            def decode(self, tokens, *, skip_special_tokens):
                return ''.join(map(chr, tokens))

        event = dict(tool_name=tool, tool_call_id='call-1', exact_arguments=arguments)
        logprobs = [{'bytes': [value]} for value in ids]
        logprobs[0]['bytes'] = []
        logprobs[-1]['bytes'] = []
        row = {'raw_response': {'choices': [{'token_ids': ids, 'logprobs': {'content': logprobs}}]},
               'token_accounting': {'completion_token_ids': ids.copy()},
               'tool_calls': [dict(id='call-1', function=dict(name=tool, arguments=arguments))]}
        self.assertEqual(_call_ranges(row, [event], 10, tokenizer=Tokenizer()), [[11, 11+len(call)]])
        row['token_accounting']['completion_token_ids'][0] = 0
        self.assertIsNone(_call_ranges(row, [event], 10, tokenizer=Tokenizer()))
        row['token_accounting']['completion_token_ids'] = ids.copy()
        logprobs[12]['bytes'] = []
        self.assertIsNone(_call_ranges(row, [event], 10, tokenizer=Tokenizer()))

    def test_exact_repeat_needs_prior_return_in_a_successful_model_request(self):
        tool = 'search-server-search'
        arguments = '{"query":"same query"}'
        result = '[{"docid":"a","snippet":"same result"}]'
        completion = f'<tool_call><function={tool}>{arguments}</function></tool_call>'

        def tokenize(text, **kwargs):
            return {'input_ids': list(map(ord, text)), 'offset_mapping': [(i, i+1) for i in range(len(text))]}

        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp)
            rounds, events, turns = [], [], []
            for number, visible in enumerate(((), (), ('c1', 'c2'), ('c3',)), 1):
                rendered = ''.join(f'<tool_response>\n{result}\n</tool_response>' for _ in visible)
                prompt = artifact/f'prompt-{number}.txt'
                prompt.write_bytes(rendered.encode())
                row = {'round_id': number, 'request_sent': True, 'response_received': True,
                       'actor_visible_messages': [dict(role='tool', tool_call_id=cid, content=result) for cid in visible],
                       'token_accounting': {'serialized_prompt_path': str(prompt), 'exact_prompt_token_ids_equal': True,
                                            'prompt_token_ids': tokenize(rendered)['input_ids']}}
                rounds.append(row)
                if number == 4:
                    break
                cid = f'c{number}'
                row['tool_calls'] = [dict(id=cid, function=dict(name=tool, arguments=arguments))]
                row['raw_response'] = {'choices': [{'logprobs': {'content': [{'bytes': [char]} for char in completion.encode()]}}]}
                turns.append(dict(turn_id=number, token_start=(number-1)*len(completion)))
                events.append(dict(round_id=number, event_id=number, tool_ordinal=0, tool_name=tool, tool_call_id=cid,
                                   exact_arguments=arguments, exact_result=result,
                                   raw_mcp_response={'isError': False, 'content': [{'type': 'text', 'text': result}]}))

            measured, coverage = collect_tool_events({'rounds': rounds, 'tool_events': events}, {'turns': turns}, {},
                                                      tokenize, artifact_root=artifact)
            self.assertEqual([(event['event_id'], event['label'], event['prior_event_id']) for event in measured],
                             [('2', None, None), ('3', 'R2b', '1')])
            self.assertEqual(coverage['observed_exact_repeats'], 1)

            guard = dict(rounds[-1], round_id=None, attempted_round_id=4,
                         request_sent=False, response_received=False, guard_intercepted=True,
                         stop_classification='CONTEXT_LIMIT_STOP')
            stopped = {'rounds': rounds[:-1], 'tool_events': events, 'unsent_guard_attempts': [guard],
                       'metadata': {'terminal_status': 'CONTEXT_LIMIT_STOP'}}
            measured, coverage = collect_tool_events(stopped, {'turns': turns}, {}, tokenize, artifact_root=artifact)
            terminal = next(event for event in measured if event['event_id'] == '3')
            self.assertEqual(terminal['label'], 'R2b')
            self.assertEqual(terminal['event_cost'], {'generated_tokens': len(completion), 'returned_tokens': 0, 'tool_calls': 1})
            self.assertEqual(coverage['terminal_guard_measured_tool_events'], 1)
            guard['response_received'] = None
            measured, _ = collect_tool_events(stopped, {'turns': turns}, {}, tokenize, artifact_root=artifact)
            self.assertEqual([event['event_id'] for event in measured], ['2'])

    def test_recorded_budget_failure_requires_actual_mcp_content(self):
        self.assertFalse(_recorded_search_response({"exact_result": "[]", "raw_mcp_response": {}}))
        self.assertFalse(_recorded_search_response({"exact_result": "[]", "raw_mcp_response": {"isError": False, "content": []}}))
        self.assertTrue(_recorded_search_response({"exact_result": "[]", "raw_mcp_response": {
            "isError": False, "content": [{"type": "text", "text": "[]"}]}}))

    def test_constraint_quote_rejects_added_fact(self):
        class Fake:
            def _request(self, *args):
                return {"clauses": ["unknown gold answer"]}
        with self.assertRaises(ValueError):
            extract_constraints("Who won the event in 2020?", Fake())

    def test_observation_uses_only_returned_data(self):
        event = {"event_id": 2, "exact_result": json.dumps([{ "docid": "a", "snippet": "line\none"}]),
                 "retrieved_documents": [{"docid": "secret", "snippet": "gold"}]}
        result = _observations(event)
        self.assertEqual(result[0]["text"], "line\none")
        self.assertEqual(result[0]["document_id"], "a")
        self.assertNotIn("gold", str(result))

    def test_candidate_requires_explicit_line(self):
        self.assertEqual(submitted_candidate("Reason\n**Exact Answer:** Ada LOVELACE\nConfidence: 90%"), "ada lovelace")
        self.assertIsNone(submitted_candidate("Probably Ada, but not submitted"))

    def test_document_identity_does_not_manufacture_independent_source_chains(self):
        result = _observations({'event_id': 1, 'exact_result': json.dumps([
            {'docid': 'a', 'snippet': 'A'}, {'docid': 'b', 'snippet': 'B'}])})
        self.assertEqual([row['document_id'] for row in result], ['a', 'b'])
        self.assertEqual({row['source_id'] for row in result}, {'browsecomp-corpus'})

    def test_unknown_result_retains_visible_text_without_inventing_provenance(self):
        for text in ('service unavailable', '{"error":"rate limit"}'):
            with self.subTest(text=text):
                result = _observations({'event_id': 9, 'exact_result': text,
                                        'retrieved_documents': [{'snippet': 'private-gold'}]})
                self.assertEqual(result[0]['text'], text)
                self.assertEqual(result[0]['source_id'], '')
                self.assertNotIn('private-gold', json.dumps(result))

    def test_native_tool_json_and_turn_coordinates_do_not_include_observation_gap(self):
        trace, native = adapt_trajectory(recorder_fixture(), 'Who is named?', CONSTRAINTS, outcome=1)
        self.assertEqual(trace['response_mask'], [1, 1, 0, 1, 1])
        self.assertEqual([(turn['token_start'], turn['token_end']) for turn in trace['turns']], [(0, 2), (3, 5)])
        self.assertEqual(trace['turns'][0]['action']['kind'], 'search')
        self.assertEqual(trace['turns'][0]['action']['method'], 'batch_search')
        self.assertEqual(trace['turns'][0]['observations'][0]['text'], 'Visible line\nsecond line.')
        self.assertEqual(trace['submitted_candidate'], 'ada lovelace')
        self.assertTrue(trace['complete'])
        self.assertEqual(native['segments'][1]['prompt_ids'], [1, 2, 3, 99])
        self.assertNotIn('private-gold', json.dumps(trace))

    def test_truncated_answer_line_is_not_a_final_submission(self):
        raw = recorder_fixture()
        raw['metadata']['terminal_status'] = 'CONTEXT_LIMIT'
        trace, _ = adapt_trajectory(raw, 'Who is named?', CONSTRAINTS, outcome=0)
        self.assertFalse(trace['complete'])
        self.assertIsNone(trace['submitted_candidate'])
        self.assertEqual(trace['turns'][-1]['action']['kind'], 'decision')

    def test_unmatched_tool_call_and_duplicate_event_are_rejected(self):
        for issue in ('wrong_id', 'duplicate'):
            with self.subTest(issue=issue):
                raw = recorder_fixture()
                if issue == 'wrong_id':
                    raw['tool_events'][0]['tool_call_id'] = 'unrequested'
                else:
                    duplicate = deepcopy(raw['tool_events'][0])
                    duplicate['event_id'] = 2
                    raw['tool_events'].append(duplicate)
                with self.assertRaises(ValueError):
                    adapt_trajectory(raw, 'Who is named?', CONSTRAINTS, outcome=0)

    def test_constraint_payload_contains_only_task_and_preserves_exact_negation(self):
        seen = []
        class Fake:
            def _request(self, prompt, payload):
                seen.append(payload)
                return {'clauses': ['not before 1990']}
        result = extract_constraints('Name the event held not before 1990.', Fake())
        self.assertEqual(seen, [{'task': 'Name the event held not before 1990.'}])
        self.assertEqual(result[0]['text'], 'not before 1990')

    def test_missing_final_candidate_disables_group_process_without_dropping_outcome(self):
        import torch
        from ledger_grpo.advantages import AdvantageConfig
        from ledger_grpo.pipeline import analyze_trajectory, score_batch
        traces = []
        for index, outcome in enumerate((1, 0)):
            raw = recorder_fixture()
            raw['metadata']['task']['run_id'] = f'q1__rep{index+1}'
            if index == 0:
                raw['rounds'][-1]['content'] = 'I believe the answer is Ada Lovelace.'
            trace, _ = adapt_trajectory(raw, 'Who is named?', CONSTRAINTS, outcome=outcome)
            traces.append(trace)
        reports = [analyze_trajectory(trace, deltas={1: {'facts': []}, 2: {'facts': []}}) for trace in traces]
        result = score_batch(traces, reports, config=AdvantageConfig(process_enabled=True))
        self.assertEqual(result['metrics']['qa_disabled_groups'], ['1'])
        self.assertEqual(result['valid_rows'].tolist(), [True, True])
        self.assertTrue(torch.equal(result['efficiency_advantage'], torch.zeros(2)))
        self.assertGreater(float(result['accuracy_advantage'][0]), 0.)
        self.assertLess(float(result['accuracy_advantage'][1]), 0.)


if __name__ == "__main__":
    unittest.main()
