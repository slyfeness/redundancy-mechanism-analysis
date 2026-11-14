import unittest

from ledger_grpo.event_calibration_plan import freeze_event_cases


class EventCalibrationPlanTest(unittest.TestCase):
    def setUp(self):
        self.tasks = {f'q{query}-{rep}': f'q{query}' for query in (1, 2) for rep in (1, 2, 3)}
        self.events = [dict(sample_id=sample, event_id=str(turn), continuation_round=turn,
                            parallel_calls=1, trajectory_sha256='1'*64)
                       for sample in self.tasks for turn in (2, 3, 10, 11)]

    def design(self, heldout=('heldout',)):
        return freeze_event_cases(self.events, self.tasks, heldout, seed=20261111, max_rounds=20)

    def test_freezes_distinct_trajectories_depth_and_common_seed_order(self):
        plan = self.design()
        self.assertEqual(plan, self.design())
        self.assertEqual(plan['eligible_events'], 24)
        self.assertEqual(len(plan['cases']), 4)
        self.assertEqual(len({case['event']['sample_id'] for case in plan['cases']}), 4)
        self.assertEqual(len({block['seed'] for case in plan['cases'] for block in case['blocks']}), 16)
        for case in plan['cases']:
            self.assertEqual({tuple(block['order']) for block in case['blocks']}, {('normal','delete'), ('delete','normal')})
            self.assertEqual(sum(block['order'][0] == 'normal' for block in case['blocks']), 2)
        for task in ('q1', 'q2'):
            self.assertEqual({case['depth'] for case in plan['cases'] if case['task_id'] == task}, {'earlier','later'})

    def test_rejects_heldout_overlap(self):
        with self.assertRaisesRegex(ValueError, 'held-out'):
            self.design(heldout=('q1',))

    def test_excludes_parallel_and_too_late_events(self):
        self.events[0]['parallel_calls'] = 2
        self.events[-1]['continuation_round'] = 20
        self.assertEqual(self.design()['eligible_events'], 22)

    def test_input_reordering_does_not_change_sample(self):
        original = self.design()
        self.events.reverse()
        self.assertEqual(self.design(), original)

    def test_calibration_selection_rejects_duplicates_and_ineligible_events(self):
        chosen = {'sample_id': 'q1-1', 'event_id': '3'}
        def freeze(selection):
            return freeze_event_cases(self.events, self.tasks, [], seed=20261111, max_rounds=20,
                                      selection=selection)
        cases = freeze([chosen])['cases']
        self.assertEqual([case['event']['event_id'] for case in cases], ['3'])
        self.assertEqual(len(cases[0]['blocks']), 4)
        with self.assertRaisesRegex(ValueError, 'unique, eligible'):
            freeze([chosen, chosen])
        with self.assertRaisesRegex(ValueError, 'unique, eligible'):
            freeze([dict(chosen, event_id='20')])
