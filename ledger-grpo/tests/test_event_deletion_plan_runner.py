import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from run_event_deletion_plan import branch_schedule, execute_schedule


class EventDeletionPlanRunnerTest(unittest.TestCase):
    def setUp(self):
        self.event = dict(sample_id='sample', event_id='2', trajectory_sha256='1'*64,
                          normal_prompt_sha256='2'*64, delete_prompt_sha256='3'*64, continuation_round=8)
        self.case = dict(case_id='E001', event=self.event.copy(), blocks=[
            {'seed': seed, 'order': ['normal', 'delete'] if seed % 2 else ['delete', 'normal']}
            for seed in range(1, 5)])
        self.plan = dict(protocol='browsecomp-event-calibration-plan-v1', audit_sha256='4'*64, cases=[self.case])
        self.audit = dict(protocol='browsecomp-matched-single-event-prefix-v1', pairs=[self.event])

    def test_keeps_frozen_pairs_order_and_paths(self):
        jobs = branch_schedule(self.plan, self.audit, '4'*64)
        self.assertEqual(len(jobs), 8)
        self.assertEqual([(j['seed'],j['condition']) for j in jobs[:4]],
                         [(1, 'normal'), (1, 'delete'), (2, 'delete'), (2, 'normal')])
        self.assertEqual(jobs[3]['relative_path'], 'E001/seed-2/normal')
        self.assertEqual(jobs[3]['prefix_sha256'], self.event['normal_prompt_sha256'])

    def test_rejects_wrong_audit_or_seed(self):
        with self.assertRaises(ValueError):
            branch_schedule(self.plan, self.audit, '5'*64)
        self.case['blocks'][0]['seed'] = 2
        with self.assertRaises(ValueError):
            branch_schedule(self.plan, self.audit, '4'*64)

    def test_rejects_different_event(self):
        self.case['event']['continuation_round'] = 9
        with self.assertRaises(ValueError):
            branch_schedule(self.plan, self.audit, '4'*64)

    def test_parallel_lanes_preserve_every_case_order(self):
        schedule = [dict(case_id=f'E00{i}', seed=seed, condition=condition)
                    for i in range(1, 5) for seed in (1, 2) for condition in ('normal', 'delete')]
        observed = []

        def worker(job, actor):
            observed.append((job, actor))
            return '1'*64

        with TemporaryDirectory() as tmp:
            result = execute_schedule(schedule, ('actor-a','actor-b'), worker, Path(tmp)/'results.jsonl')
        self.assertEqual(result['completed_branches'], len(schedule))
        self.assertEqual(result['failed_cases'], {})
        for case in ('E001','E002','E003','E004'):
            actual = [(job, actor) for job, actor in observed if job['case_id'] == case]
            self.assertEqual([job for job,_ in actual], [job for job in schedule if job['case_id']==case])
            self.assertEqual(len({actor for _,actor in actual}),1)

    def test_failed_case_keeps_other_cases_and_does_not_fake_receipts(self):
        jobs = [dict(case_id=f'E00{i}', index=index) for i in (1,2) for index in range(3)]
        def worker(job, actor):
            if job['case_id']=='E001' and job['index']==1:
                raise RuntimeError('test interruption')
            return '2'*64

        with TemporaryDirectory() as tmp:
            result = execute_schedule(jobs, ('actor-a','actor-b'), worker, Path(tmp)/'results.jsonl')
        self.assertEqual(result['completed_branches'],4)
        self.assertEqual(set(result['failed_cases']),{'E001'})
