import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from frozen_event_calibration import bind_predictions, bind_review, build_rows, read_branches, remaining_cases, result_requests
from ledger_grpo.evaluation import audit_event_labels


def encoded(value):
    return json.dumps(value).encode()


class FrozenEventCalibrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packet = encoded({'cases': [{'case_id': 'E001', 'history': [{'ref': 'M001'}],
                                          'target': [{'ref': 'M002'}, {'ref': 'M003'}]}]})
        self.packet_sha = hashlib.sha256(self.packet).hexdigest()
        self.plan = {'blind_review_sha256': self.packet_sha, 'cases': [{'case_id': 'E001'}]}
        self.review = {'packet_sha256': self.packet_sha, 'reviewer': 'Reviewer 1', 'cases': {'E001': {
            'R1': {'verdict': 'redundant', 'evidence': ['M001','M003'], 'rationale': 'Same evidence.'},
            'R2a': {'verdict': 'uncertain', 'evidence': [], 'rationale': ''}}}}
        self.audit_sha, self.plan_sha = 'a'*64, 'b'*64
        self.job = {'case_id': 'E001', 'sample_id': 'q__rep1', 'event_id': '2', 'trajectory_sha256': 'c'*64,
                    'seed': 1, 'condition': 'normal', 'continuation_round': 5, 'prefix_sha256': 'd'*64,
                    'relative_path': 'E001/seed-1/normal'}
        self.schedule = [self.job, dict(self.job, condition='delete', relative_path='E001/seed-1/delete')]
        self.folder = self.root/self.job['relative_path']
        self.folder.mkdir(parents=True)
        identity = {k: v for k, v in self.job.items() if k not in {'relative_path','case_id'}}
        identity['audit_sha256'] = self.audit_sha
        suffix = encoded({'metadata': {'branch': identity, 'terminal_status': 'MODEL_FINAL_STOP'},
                          'rounds': [{'response_received': True, 'content': 'Answer'}]})
        (self.folder/'trajectory.json').write_bytes(suffix)
        branch = encoded({'identity': identity, 'terminal': 'MODEL_FINAL_STOP', 'final': 'Answer',
                          'suffix_trajectory_sha256': hashlib.sha256(suffix).hexdigest()})
        (self.folder/'BRANCH_RESULT.json').write_bytes(branch)
        self.completed = dict(self.job, branch_result_sha256=hashlib.sha256(branch).hexdigest())
        (self.root/'PLAN_RECEIPT.json').write_bytes(encoded({'plan_sha256': self.plan_sha, 'audit_sha256': self.audit_sha,
                                                           'schedule': self.schedule}))
        (self.root/'COMPLETED_BRANCHES.jsonl').write_bytes(encoded(self.completed)+b'\n')

    def read(self):
        return read_branches(self.root, self.schedule, self.plan_sha, self.audit_sha)

    def test_review_binds_to_packet_and_visible_messages(self):
        self.assertEqual(bind_review(self.plan, self.packet, self.review)['E001']['R1']['verdict'], 'redundant')
        with self.assertRaises(ValueError):
            bind_review(self.plan, self.packet+b' ', self.review)
        self.review['cases']['E001']['R1']['evidence'] = ['M004']
        with self.assertRaises(ValueError):
            bind_review(self.plan, self.packet, self.review)

    def test_partial_execution_is_neither_complete_nor_fabricated(self):
        rows = self.read()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['result']['final'], 'Answer')
        self.assertEqual(rows[0]['branch_result_sha256'], self.completed['branch_result_sha256'])

    def test_resume_selects_only_unstarted_cases(self):
        other = [dict(job, case_id='E002', relative_path=job['relative_path'].replace('E001', 'E002'))
                 for job in self.schedule]
        with self.assertRaisesRegex(ValueError, 'partially completed'):
            remaining_cases(self.schedule + other, self.read())
        self.assertEqual(remaining_cases(self.schedule + other, self.schedule), other)

    def test_parallel_completion_retains_stable_grading_index(self):
        other = dict(self.job, case_id='E002', relative_path='E002/seed-1/normal')
        self.schedule.insert(0, other)
        (self.root/'PLAN_RECEIPT.json').write_bytes(encoded({'plan_sha256': self.plan_sha, 'audit_sha256': self.audit_sha,
                                                           'schedule': self.schedule}))
        rows = self.read()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['index'], 1)

    def test_branch_and_trajectory_content_are_checked(self):
        branch = self.folder/'BRANCH_RESULT.json'
        old = branch.read_bytes()
        branch.write_bytes(old.replace(b'Answer',b'Other answer'))
        with self.assertRaises(ValueError):
            self.read()
        branch.write_bytes(old)
        suffix = self.folder/'trajectory.json'
        suffix.write_bytes(suffix.read_bytes()+b' ')
        with self.assertRaises(ValueError):
            self.read()

    def test_only_verified_final_submissions_form_result_requests(self):
        rows = self.read()
        requests = result_requests(rows + [dict(rows[0], result={'terminal': 'CONTEXT_LIMIT_STOP'})],
                                   {'E001': 'q'}, {'q': {'question': 'Question', 'gold': 'Answer'}})
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['branch_result_sha256'], self.completed['branch_result_sha256'])
        changed = result_requests(rows, {'E001': 'q'}, {'q': {'question': 'Question', 'gold': 'Other'}})
        self.assertNotEqual(changed[0]['request_sha256'], requests[0]['request_sha256'])

    def test_missing_semantic_evaluation_does_not_prove_zero_bplus_mark_rate(self):
        event = {**{key:self.job[key] for key in ('sample_id','event_id','trajectory_sha256','continuation_round')},
                 'normal_prompt_sha256': 'd'*64, 'delete_prompt_sha256': 'e'*64}
        plan = {'cases': [{'case_id':'E001', 'task_id':'q', 'event':event}]}
        prediction = {'case_id':'E001', 'event_id':'2', 'trajectory_sha256':'c'*64, 'turn_id':4,
                      'judge':{'mode':'unavailable'}, 'predictions': {
                          label:{'prediction':'uncertain','reason':'prefix_judge_unavailable'} for label in ('R1','R2a')}}
        predictions, mode = bind_predictions(plan, self.plan_sha, {'mode':'live_semantic_prefix',
                                             'plan_sha256':self.plan_sha, 'cases':[prediction]})
        branches, grades = [], {}
        base_identity = self.read()[0]['result']['identity']
        for seed in (1,2,3,4):
            for condition in ('normal','delete'):
                sha = f'{seed}-{condition}'
                ident = dict(base_identity, seed=seed, condition=condition,
                             prefix_sha256=event[f'{condition}_prompt_sha256'], runtime_sha256='f'*64)
                branches.append(dict(case_id='E001', branch_result_sha256=sha,
                                     result={'identity':ident,'terminal':'MODEL_FINAL_STOP'}))
                grades[sha] = condition == 'normal'
        batch = {'trajectories':[{'id':'q__rep1','query_id':'q','reward':1}]}
        rows = build_rows(plan,self.audit_sha,batch,self.review['cases'],predictions,mode,branches,grades)
        metrics = audit_event_labels(rows, require_event_binding=True)['R1']
        self.assertEqual(metrics['counts']['B_plus'], 1)
        self.assertIsNone(metrics['bplus_mark_rate'])
