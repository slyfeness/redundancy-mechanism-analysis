"""Synthetic coordinate and schema tests; no dataset examples."""
import unittest

from ledger_grpo.credit.schema import Unit, Trajectory, Group, validate_record, validate_derived
from ledger_grpo.credit.tokens import write_token_advantages, units_from_stages
from ledger_grpo.credit.datasets import BCPlusAdapter, SAGEAdapter


class CreditTokenTests(unittest.TestCase):
    def test_prompt_returns_parallel_calls_and_final_have_exact_ownership(self):
        stages = [
            dict(model_call_index=1, span_id=0, gen_token_range=[2, 5], generated_tokens=3,
                 unit_type='tool_stage', tool_events=[dict(tool_name='lookup', obs_tokens=4)]),
            dict(model_call_index=1, span_id=0, gen_token_range=[2, 5], generated_tokens=3,
                 unit_type='tool_stage', tool_events=[dict(tool_name='read', obs_tokens=2)]),
            dict(model_call_index=2, span_id=0, gen_token_range=[11, 13], generated_tokens=2,
                 unit_type='final', tool_events=[])]
        units = units_from_stages(stages)
        self.assertEqual([u.unit_id for u in units], [1, 'F'])
        self.assertEqual(units[0].returned_tokens, 6)
        self.assertEqual(units[0].generated_tokens, 3)
        tr = Trajectory('synthetic', 0, units, {'Y': True, 'submitted': True},
                        response_mask=[0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1])
        result = write_token_advantages(tr, {1: 2., 'F': -1.})
        self.assertEqual(result['advantages'].tolist(), [0, 0, 2, 2, 2, 0, 0, 0, 0, 0, 0, -1, -1])
        self.assertEqual(result['mask'].tolist(), [bool(x) for x in tr.response_mask])
        self.assertAlmostEqual(tr.to_credit_dict()['costs'][1], 9 / 3146)

    def test_final_only_and_no_final_are_supported(self):
        for uid in ('F', 1):
            tr = Trajectory('q', 0, [Unit(uid, [(1, 3)], 2)], {'Y': False, 'submitted': uid == 'F'},
                            response_mask=[0, 1, 1])
            self.assertEqual(write_token_advantages(tr, {uid: .5})['advantages'].tolist(), [0, .5, .5])

    def test_missing_overlapping_or_observation_positions_fail_closed(self):
        cases = [([Unit(1, [(1, 2)], 1)], [0, 1, 1]),
                 ([Unit(1, [(1, 3)], 2), Unit('F', [(2, 3)], 1)], [0, 1, 1]),
                 ([Unit(1, [(0, 3)], 3)], [0, 1, 1])]
        for units, mask in cases:
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                write_token_advantages(Trajectory('q', 0, units, {'Y': 0, 'submitted': False}, response_mask=mask),
                                       {u.unit_id: 1. for u in units})

    def test_incomplete_ledger_is_distinct_from_explicit_mismatch(self):
        tr = Trajectory('q', 0, [Unit(1, [(0, 1)], 1), Unit(2, [(2, 3)], 1)],
                        {'Y': False, 'submitted': False}, records=[{'step': 1}], derived=[{'step': 1}],
                        conds=['A'], response_mask=[1, 0, 1])
        from ledger_grpo.credit.group import ledger_complete
        self.assertFalse(ledger_complete(tr.to_credit_dict()))
        self.assertEqual(tr.to_credit_dict()['unmatched_units'], [])
        tr.records = [{'step': 1}, {'step': 2}]
        tr.derived = [{'step': 1}, {'step': 2}]
        tr.metadata['unmatched_units'] = [2]
        self.assertEqual(tr.to_credit_dict()['unmatched_units'], [2])
        with self.assertRaises(ValueError):
            Group('other', [tr])
        other = Trajectory('other', 0, [Unit('F', [(0, 1)], 1)], {'Y': False, 'submitted': True}, response_mask=[1])
        self.assertEqual(len(Group('mechanism-only', [tr, other], allow_mixed_qids=True)), 2)

    def test_schema_parses_literals_and_rejects_bad_field_type_and_enum(self):
        self.assertEqual(validate_derived({'step': 1, 'labels': "['有进展']", 'view': "{'A': ('✔', ['E1'], True)}"})['labels'], ['有进展'])
        with self.assertRaises(ValueError):
            validate_record({'step': '1'})
        with self.assertRaises(ValueError):
            validate_record({'step': 1, 'evidence': [{'key': 'E1', 'strength': 'unsupported', 'conditions': []}]})

    def test_schema_preserves_recorded_sentence_step_and_unknown_decision_forms(self):
        row = {'step': 1, 'strict': [1], 'evidence': [{'key': 'E1', 'sents': ['S1'], 'strength': '直接'}],
               'excluded': [{'object': 'candidate', 'valid': '看不出'}]}
        self.assertEqual(validate_record(row), row)
        row = {'step': 1, 'excluded_role_only': "['candidate']", 'view': "{'A': ('○', [], False)}",
               'targets': "[('candidate', 'A', False)]"}
        self.assertEqual(validate_derived(row)['excluded_role_only'], ['candidate'])

    def test_bcplus_scores_program_side_and_other_adapters_are_explicit_stubs(self):
        adapter = BCPlusAdapter()
        with self.assertRaises(ValueError):
            adapter.score('blue', ['blue'])
        adapter = BCPlusAdapter(scorer=BCPlusAdapter.normalized_exact_match)
        self.assertTrue(adapter.score('  BLUE  ', ['blue']))
        self.assertFalse(adapter.score('red', ['blue']))
        self.assertEqual(adapter.identify_answer({'content': 'answer', 'tool_calls': []}), 'answer')
        self.assertIsNone(adapter.identify_answer({'content': 'not final', 'tool_calls': [{'id': 'x'}]}))
        with self.assertRaises(NotImplementedError):
            SAGEAdapter().parse_model_calls({})

    def test_unfinished_content_is_kept_as_unknown_not_final_or_submission(self):
        row = {'native': {'id': 'r', 'query_id': 'q', 'segments': [
                    {'prompt_ids': [1], 'completion_ids': [2, 3], 'vllm_logprobs': [0., 0.]}]},
               'stages': [dict(model_call_index=1, span_id=0, gen_token_range=[0, 2], generated_tokens=2,
                               unit_type='unfinished', tool_events=[])],
               'terminal_status': 'GENERATION_LENGTH_STOP',
               'rounds': [{'raw_response': {'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]}}]}
        tr = BCPlusAdapter().parse_model_calls(row)
        self.assertEqual(tr.outcome, {'Y': False, 'submitted': False})
        self.assertEqual(tr.units[0].kind, 'unfinished')
        self.assertNotEqual(tr.units[0].unit_id, 'F')
        self.assertEqual(tr.to_credit_dict()['tool_call_count'], 0)
        self.assertEqual(tr.to_credit_dict()['unmatched_units'], [1])
        self.assertEqual(write_token_advantages(tr, {1: -.2})['advantages'].tolist(), [-.2, -.2])


if __name__ == '__main__':
    unittest.main()
