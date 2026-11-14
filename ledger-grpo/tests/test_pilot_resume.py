"""A scheduled branch must inherit the warmup policy and use fresh trajectories."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from event_price_pilot import ARMS, schedule_stage, training_config
from pilot_resume import bind_checkpoint, bind_fresh_batch


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


class ResumeTests(unittest.TestCase):
    def test_semantic_pricing_recomputes_event_matched_calibration(self):
        settings = {'credit': dict(group_size=8, loss_denominator=32768, median_event_cost=1., r1_price=.05),
                    'price_schedule': dict(update=1, warmup=0, ramp=1)}
        claimed = dict(precision=1., bplus_mark_rate=0., bplus_contamination=0.)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'events.jsonl'
            receipt = dict(claimed, cases_path=str(path), evaluation_manifest_sha256='a'*64)
            settings['semantic_calibration'] = {'R1': receipt}
            with self.assertRaisesRegex(ValueError, 'calibration'):
                training_config(settings)

            def case(event_id, prediction, human, continued):
                return dict(case_id=event_id, label='R1', prediction=prediction, human_verdict=human,
                            original_correct=True, guide_confounded=False,
                            trajectory_sha256='b'*64, event_id=event_id,
                            deletions=[dict(condition_id='delete', repetition_id=rep, comparable=True,
                                            correct=continued, intervention_scope='single_tool_event',
                                            target_trajectory_sha256='b'*64, target_event_id=event_id)
                                       for rep in range(4)])

            cases = [case('repeat', 'positive', 'redundant', True), case('necessary', 'negative', 'necessary', False)]

            def freeze():
                path.write_text(''.join(json.dumps(row)+'\n' for row in cases), encoding='utf-8')
                receipt['evaluation_manifest_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

            freeze()
            self.assertEqual(training_config(settings)[1], ['R1'])
            from ledger_grpo.cli import main
            audited = path.with_suffix('.json')
            main(['audit-events', '--for-pricing', '--cases', str(path), '--output', str(audited)])
            settings['semantic_calibration'] = json.loads(audited.read_bytes())
            self.assertEqual(training_config(settings)[1], ['R1'])
            settings['semantic_calibration'] = {'R1': receipt}
            path.write_bytes(path.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError, 'calibration'):
                training_config(settings)
            cases[1]['deletions'][0]['target_event_id'] = 'another_event'
            freeze()
            with self.assertRaisesRegex(ValueError, 'calibration'):
                training_config(settings)
            cases[1]['deletions'][0]['target_event_id'] = 'necessary'
            cases[1]['prediction'] = 'positive'
            freeze()
            with self.assertRaisesRegex(ValueError, 'calibration'):
                training_config(settings)

    def test_shared_warmup_then_ramp_and_batch_binding(self):
        settings={'credit':dict(group_size=8,loss_denominator=32768,median_event_cost=1.,r1_price=0.),
                  'price_schedule':dict(update=1,warmup=1,ramp=2),'arms':list(ARMS)}
        with tempfile.TemporaryDirectory() as tmp:
            runs=Path(tmp)/'runs'; run=runs/'pilot-warmup'; arm=run/'outcome'; checkpoint=arm/'checkpoints/step-0001'
            checkpoint.mkdir(parents=True)
            self.assertEqual(schedule_stage(settings,runs_root=runs),(None,('outcome',)))
            config,_=training_config(settings)
            self.assertEqual((config.price_fraction,config.grounding_weight),(0.,0.))
            write(run/'EVENT_PRICE_SETTINGS.json',settings)
            shards=[dict(name=f'checkpoint-rank{i}.pt',bytes=1) for i in range(4)]
            for shard in shards: (checkpoint/shard['name']).write_bytes(b'x')
            write(checkpoint/'COMPLETE.json',dict(optimizer_step=1,publication_id=1,world_size=4,
                  contents=['model','optimizer','cpu_rng','cuda_rng'],shards=shards))
            snapshots=run/'policy-snapshots'; receipt=dict(snapshot='step-1.safetensors',file_sha256='b'*64)
            write(snapshots/'step-1.json',receipt)
            write(arm/'step-0001/STEP_COMPLETE.json',dict(persisted_optimizer_steps=1,snapshot_published=True,
                  publication_id=1,snapshot_directory=str(snapshots),snapshot_receipt=receipt))
            write(arm/'step-0001/INPUTS.json',dict(optimizer_step=1,native_batch_sha256='a'*64,control='outcome'))
            write(arm/'step-0001/BACKEND.json',{})
            next_settings=dict(settings,price_schedule=dict(update=2,warmup=1,ramp=2),resume_from=str(checkpoint))
            parent,arms=schedule_stage(next_settings,runs_root=runs)
            self.assertEqual(arms,ARMS)
            config,_=training_config(next_settings)
            self.assertEqual((config.price_fraction,config.grounding_weight),(.5,.1))
            bind_fresh_batch(parent,dict(native_batch_sha256='c'*64,policy_snapshot_sha256='b'*64))
            with self.assertRaisesRegex(ValueError,'fresh'):
                bind_fresh_batch(parent,dict(native_batch_sha256='a'*64,policy_snapshot_sha256='b'*64))
            with self.assertRaisesRegex(ValueError,'policy snapshot'):
                bind_fresh_batch(parent,dict(native_batch_sha256='c'*64,policy_snapshot_sha256='f'*64))
            with self.assertRaisesRegex(ValueError,'frozen price schedule'):
                schedule_stage(dict(next_settings,price_schedule=dict(update=2,warmup=1,ramp=3)),runs_root=runs)
            (checkpoint/'checkpoint-rank3.pt').write_bytes(b'partial')
            with self.assertRaisesRegex(ValueError,'rank shard'):
                bind_checkpoint(checkpoint,runs_root=runs)
