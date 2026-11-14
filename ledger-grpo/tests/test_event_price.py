import unittest
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import torch

from ledger_grpo.event_price import EventPriceConfig, score_event_prices, scheduled_price_fraction
from ledger_grpo.hf_native import single_step_token_loss


def row(identity, outcome, *, task='q', budget=False, label=None, ground=None, complete=True):
    events = [dict(event_id='search1', turn_id=2, known_at=2, event_tokens=[1,3], label=label,
                   event_cost=dict(generated_tokens=2, returned_tokens=7, tool_calls=1))]
    return dict(traj_id=identity, task_id=task, outcome=outcome, response_mask=[1,1,1,0,1],
                events=events, grounding=ground, recording_complete=complete,
                termination_reason='budget_exhausted' if budget else 'normal')


class RevisedCreditTests(unittest.TestCase):
    config = EventPriceConfig(group_size=2, loss_denominator=16, median_event_cost=10.)

    def test_truncated_failure_gets_local_debit_with_successful_peer(self):
        rows = [row('a',1,label='R2b',ground=.5), row('b',0,budget=True,label='R2b')]
        result = score_event_prices(rows,self.config)
        expected = torch.tensor([[1.05,1.05,1.05,0,1.05],[-1.05,-1.15,-1.15,0,-1.05]])
        torch.testing.assert_close(result['advantages'],expected)
        self.assertEqual(result['metrics']['charged_budget_events'],1)
        self.assertEqual(result['loss_denominator'],16)

    def test_all_wrong_is_retained_and_tool_failure_excludes_group(self):
        rows = [row('a',0,label='R2b'), row('b',0,budget=True,label='R2b'),
                row('c',1,task='bad'), row('d',0,task='bad',complete=False)]
        result = score_event_prices(rows,self.config)
        self.assertEqual(result['valid_rows'].tolist(),[True,True,False,False])
        self.assertTrue(result['skip_update'])
        self.assertEqual(result['metrics']['charged_events'],0)

    def test_cap_and_uniform_control_independent_of_judge_labels(self):
        rows = [row('a',1),row('b',0,budget=True)]
        result = score_event_prices(rows,self.config,arm='uniform')
        self.assertEqual(result['metrics']['charged_events'],1)
        self.assertAlmostEqual(float(result['advantages'][1,1]),-1.02,places=6)
        config = EventPriceConfig(group_size=2,loss_denominator=16,median_event_cost=1.,trajectory_cap=.04)
        rows[1]['events'][0]['label']='R2b'
        self.assertAlmostEqual(score_event_prices(rows,config)['charged'][0]['price'],.04)

    def test_future_and_observation_tokens_cannot_be_charged(self):
        rows = [row('a',1),row('b',0,budget=True,label='R2b')]
        rows[1]['events'][0]['known_at']=3
        with self.assertRaisesRegex(ValueError,'observation boundary'):
            score_event_prices(rows,self.config)
        rows[1]['events'][0].update(known_at=2,event_tokens=[2,4])
        with self.assertRaisesRegex(ValueError,'policy tokens'):
            score_event_prices(rows,self.config)

    def test_fixed_loss_denominator_and_schedule(self):
        logits = torch.tensor([-1.,-1.],requires_grad=True)
        result = single_step_token_loss(logits,logits.detach(),torch.tensor([.5,.5]),torch.tensor([True,True]),
                                        global_token_count=2,world_size=1,loss_denominator=8)
        result['loss'].backward()
        torch.testing.assert_close(logits.grad,torch.tensor([-.0625,-.0625]))
        self.assertEqual([scheduled_price_fraction(i,warmup=1,ramp=2) for i in range(1,5)],[0.,.5,1.,1.])

    def test_default_semantic_events_do_not_charge_and_explicit_prices_need_calibration(self):
        rows = [row('a',1), row('b',0,label='R1')]
        self.assertEqual(score_event_prices(rows,self.config)['charged'], [])
        config = EventPriceConfig(2, 16, 10., r1_price=.05)
        for arm in ('targeted','shuffled','trajectory'):
            with self.subTest(arm=arm), self.assertRaisesRegex(ValueError,'calibration'):
                score_event_prices(rows,config,arm=arm)
        self.assertEqual(score_event_prices(rows,config,arm='outcome')['charged'],[])

    def test_generic_cli_reuses_event_bound_calibration(self):
        from ledger_grpo.cli import main

        def calibration_case(event, positive):
            return dict(case_id=event, event_id=event, trajectory_sha256='b'*64, label='R2a',
                prediction='positive' if positive else 'negative', human_verdict='redundant' if positive else 'necessary',
                original_correct=True, guide_confounded=False, deletions=[
                    dict(condition_id='delete', repetition_id=i, comparable=True, correct=positive,
                         intervention_scope='single_tool_event', target_event_id=event, target_trajectory_sha256='b'*64)
                    for i in range(4)])

        with TemporaryDirectory() as tmp:
            p = Path(tmp)
            rows, config, cases, report = (p / name for name in ('rows.jsonl','config.json','cases.jsonl','calibration.json'))
            rows.write_text('\n'.join(json.dumps(item) for item in (row('a',1),row('b',0,label='R2a'))),encoding='utf-8')
            config.write_text(json.dumps(dict(group_size=2,loss_denominator=16,median_event_cost=10.,r2a_price=.05)),encoding='utf-8')
            cases.write_text('\n'.join(json.dumps(item) for item in (calibration_case('redundant',True),
                                                                    calibration_case('necessary',False))),encoding='utf-8')
            args = ['score-events','--rows',str(rows),'--config',str(config)]
            with self.assertRaisesRegex(ValueError,'calibration'):
                main([*args,'--output',str(p/'rejected.json')])
            main(['audit-events','--for-pricing','--cases',str(cases),'--output',str(report)])
            out = p/'scored.json'
            main([*args,'--output',str(out),'--semantic-calibration',str(report)])
            result = json.loads(out.read_bytes())
            self.assertEqual(result['charged'][0]['price'], .05)
            self.assertEqual(result['semantic_calibration_sha256'], {'R2a': hashlib.sha256(cases.read_bytes()).hexdigest()})
            engineering = [dict(json.loads(line), calibration_scope='engineering')
                           for line in cases.read_text(encoding='utf-8').splitlines()]
            engineering_cases, engineering_report = p/'engineering.jsonl', p/'engineering-report.json'
            engineering_cases.write_text('\n'.join(map(json.dumps,engineering)),encoding='utf-8')
            main(['audit-events','--for-pricing','--cases',str(engineering_cases),'--output',str(engineering_report)])
            engineering_metrics = json.loads(engineering_report.read_bytes())['R2a']
            self.assertEqual((engineering_metrics['precision'], engineering_metrics['bplus_mark_rate']), (1.,0.))
            with self.assertRaisesRegex(ValueError,'engineering'):
                main([*args,'--output',str(p/'engineering-scores.json'),'--semantic-calibration',str(engineering_report)])
            with cases.open('ab') as handle:
                handle.write(b'\n')
            with self.assertRaisesRegex(ValueError,'calibration'):
                main([*args,'--output',str(p/'changed.json'),'--semantic-calibration',str(report)])
