import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import torch


def worker():
    path = Path(__file__).parents[1] / 'scripts/hf_pilot_train.py'
    if not path.exists():
        raise AssertionError('HF pilot worker is missing')
    spec = importlib.util.spec_from_file_location('hf_pilot_train_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalCollective:
    rank, world, device = 0, 1, torch.device('cpu')
    def barrier(self): pass
    def sum(self, value): return value
    def maximum(self, value): return value


class TinyScorer(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.zeros(20))
        self.calls = 0
    def forward(self, ids, positions, observe_entropy=False):
        self.calls += 1
        values = self.weight[ids[0, positions]]
        return values, torch.ones_like(values)
    def clip_grad_norm_(self, maximum):
        return torch.nn.utils.clip_grad_norm_(self.parameters(), maximum)


def prepared():
    return {'records': [
        {'prompt_ids': [1], 'completion_ids': [2, 3], 'action_offsets': [0, 1],
         'vllm_logprobs': [0., 0.], 'action_advantages': torch.tensor([2., -1.]), 'action_mask': torch.tensor([True, True])},
        {'prompt_ids': [4], 'completion_ids': [5], 'action_offsets': [0],
         'vllm_logprobs': [0.], 'action_advantages': torch.tensor([1.]), 'action_mask': torch.tensor([True])},
    ], 'global_token_count': 3, 'skip_update': False, 'metrics': {'valid_trajectory_count': 2}}


class WorkerTests(unittest.TestCase):
    def test_rank_padding_preserves_global_count_and_has_no_credit(self):
        m = worker()
        batch = prepared()
        shard = m.rank_records(batch, rank=3, world=4)
        self.assertEqual(len(shard), 1)
        self.assertFalse(bool(shard[0]['action_mask'].any()))
        self.assertEqual(float(shard[0]['action_advantages'].abs().sum()), 0.)
        self.assertEqual(batch['global_token_count'], 3)
        self.assertTrue(bool(batch['records'][1]['action_mask'].all()))

    def test_one_actual_update_moves_both_signs_and_rejects_reusing_batch(self):
        m, model = worker(), TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        result = m.run_update(prepared(), model, optimizer, LocalCollective(),
                              batch_identity='fresh-batch', update_index=1)
        self.assertEqual(result['state'], 'computed')
        self.assertEqual(result['computed_optimizer_steps'], 1)
        self.assertEqual(result['effective_action_tokens'], 3)
        self.assertGreater(float(model.weight[2].detach()), 0)
        self.assertLess(float(model.weight[3].detach()), 0)
        self.assertEqual(float(model.weight[1].detach()), 0)
        with self.assertRaisesRegex(ValueError, 'reus|already'):
            m.run_update(prepared(), model, optimizer, LocalCollective(), batch_identity='fresh-batch', update_index=2)

    def test_zero_advantages_skip_adam_even_when_momentum_exists(self):
        m, model = worker(), TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        m.run_update(prepared(), model, optimizer, LocalCollective(), batch_identity='a', update_index=1)
        before, calls = model.weight.detach().clone(), model.calls
        batch = prepared()
        for record in batch['records']:
            record['action_advantages'].zero_()
        result = m.run_update(batch, model, optimizer, LocalCollective(), batch_identity='b', update_index=2)
        self.assertEqual(result['state'], 'skipped')
        self.assertEqual(result['skip_reason'], 'all_effective_advantages_zero')
        torch.testing.assert_close(before, model.weight)
        self.assertEqual(model.calls, calls)
        self.assertEqual(int(optimizer.state[model.weight]['step']), 1)

    def test_resumed_adam_matches_continuous_second_update(self):
        m, original, resumed = worker(), TinyScorer(), TinyScorer()
        make = lambda model: torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        live, restored = make(original), make(resumed)
        m.run_update(prepared(),original,live,LocalCollective(),batch_identity='a',update_index=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'checkpoint-rank0.pt'
            torch.save((original.state_dict(),live.state_dict(),torch.get_rng_state()),path)
            class CpuBackend:
                def load_rank(self,model,optimizer,shard,rank,world,step):
                    self.received = shard,rank,world,step
                    weights,state,rng = torch.load(shard,weights_only=True)
                    model.load_state_dict(weights)
                    optimizer.load_state_dict(state)
                    torch.set_rng_state(rng)
            backend=CpuBackend()
            m.restore_stage_optimizer(backend,resumed,restored,
                {'checkpoint':directory,'optimizer_step':1,'consumed_batches':['a']},rank=0,world=1)
            self.assertEqual(backend.received,(path,0,1,1))
            with self.assertRaisesRegex(ValueError,'already'):
                m.run_update(prepared(),resumed,restored,LocalCollective(),batch_identity='a',update_index=2)
            for model,optimizer in ((original,live),(resumed,restored)):
                result=m.run_update(prepared(),model,optimizer,LocalCollective(),batch_identity='b',update_index=2)
                self.assertEqual(result['computed_optimizer_steps'],2)
            torch.testing.assert_close(original.weight,resumed.weight,atol=0,rtol=0)

    def test_skip_update_and_nonfinite_never_step(self):
        m, model = worker(), TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        batch = prepared(); batch['skip_update'] = True
        result = m.run_update(batch, model, optimizer, LocalCollective(), batch_identity='skip', update_index=1)
        self.assertEqual(result['state'], 'skipped')
        self.assertEqual(model.calls, 0)
        with torch.no_grad(): model.weight[2] = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'finite'):
            m.run_update(prepared(), model, optimizer, LocalCollective(), batch_identity='bad', update_index=1)
        self.assertEqual(len(optimizer.state), 0)

    def test_checkpoint_failure_preserves_computed_evidence_without_persisted_marker(self):
        m, model = worker(), TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        class BrokenBackend:
            model_directory = 'unused'
            def save_rank(self, *args): raise OSError('synthetic disk full')
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            result = m.run_update(prepared(), model, optimizer, LocalCollective(), batch_identity='x', update_index=1)
            with self.assertRaises(OSError):
                m.persist_update(model, optimizer, result, BrokenBackend(), LocalCollective(), out, update_index=1)
            self.assertTrue((out/'step-0001/UPDATE_COMPUTED.json').is_file())
            self.assertFalse((out/'checkpoints/step-0001/COMPLETE.json').exists())
            self.assertFalse((out/'step-0001/STEP_COMPLETE.json').exists())

    def test_native_digest_binding_is_required(self):
        m = worker()
        with tempfile.TemporaryDirectory() as folder:
            native, scores = Path(folder)/'native.json', Path(folder)/'scores.pt'
            native.write_text(json.dumps({'trajectories': []}))
            torch.save({}, scores)
            with self.assertRaisesRegex(ValueError, 'binding|digest|sha256'):
                m.load_step_inputs(native, scores)

    def test_optimizer_returned_hook_survives_later_diagnostic_failure(self):
        m, model = worker(), TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        events = []
        def observe(event):
            events.append(event)
            # Simulate corrupt post-step diagnostics, after Adam really updated.
            optimizer.state[model.weight]['step'].fill_(9)
        with self.assertRaisesRegex(RuntimeError, 'executed'):
            m.run_update(prepared(), model, optimizer, LocalCollective(),
                         batch_identity='a', update_index=1, on_optimizer_step=observe)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['state'], 'optimizer_returned')
        self.assertEqual(events[0]['optimizer_step'], 1)
        self.assertEqual(optimizer._ledger_computed_updates, 1)
        self.assertGreater(float(model.weight[2].detach()), 0)

    def test_snapshot_publication_id_is_independent_of_optimizer_step(self):
        m, model = worker(), TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        class Backend:
            model_directory = 'unused'
            def save_rank(self, model, opt, path, rank, world, step):
                self.checkpoint_step = step
                path.write_bytes(b'checkpoint-placeholder')
            def export_policy_snapshot(self, model, model_dir, directory, publication, rank, *, verify_disk):
                self.snapshot_dir, self.publication_id = directory, publication
                self.verify_disk = verify_disk
                (directory / f'step-{publication}.safetensors').write_bytes(b'fake')
                (directory / f'step-{publication}.json').write_text(json.dumps({
                    'snapshot': f'step-{publication}.safetensors', 'file_sha256': 'test-only',
                    'verified_byte_count': 4}))
        backend = Backend()
        with tempfile.TemporaryDirectory() as folder:
            out, shared = Path(folder)/'arm', Path(folder)/'shared'
            result = m.run_update(prepared(), model, optimizer, LocalCollective(), batch_identity='x', update_index=1)
            complete = m.persist_update(model, optimizer, result, backend, LocalCollective(), out,
                                        update_index=1, snapshot_directory=shared, publication_id=2)
            self.assertEqual(backend.checkpoint_step, 1)
            self.assertEqual(backend.publication_id, 2)
            self.assertEqual(backend.snapshot_dir, shared)
            self.assertTrue(backend.verify_disk)
            self.assertEqual(complete['optimizer_step'], 1)
            self.assertEqual(complete['publication_id'], 2)
            self.assertTrue(complete['snapshot_published'])
            self.assertFalse(complete['policy_synced'])
            checkpoint = json.loads((out/'checkpoints/step-0001/COMPLETE.json').read_text())
            self.assertEqual(checkpoint['optimizer_step'], 1)
            self.assertEqual(checkpoint['publication_id'], 2)
            self.assertTrue((shared/'step-2.safetensors').is_file())
            self.assertFalse((shared/'step-1.safetensors').exists())

    def test_existing_publication_is_rejected_without_overwrite(self):
        m = worker()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'step-2.safetensors'
            target.write_bytes(b'original')
            with self.assertRaisesRegex(FileExistsError, 'publication'):
                m.check_snapshot_destination(Path(folder), 2)
            self.assertEqual(target.read_bytes(), b'original')
            with self.assertRaises(ValueError):
                m.check_snapshot_destination(Path(folder), 0)

    def test_snapshot_failure_retains_full_checkpoint_but_not_publication_marker(self):
        m, model = worker(), TinyScorer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-6, weight_decay=0.)
        class Backend:
            model_directory = 'unused'
            def save_rank(self, model, opt, path, rank, world, step): path.write_bytes(b'cp')
            def export_policy_snapshot(self, *args, **kwargs): raise OSError('synthetic snapshot failure')
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            result = m.run_update(prepared(), model, optimizer, LocalCollective(), batch_identity='x', update_index=1)
            with self.assertRaises(OSError):
                m.persist_update(model, optimizer, result, Backend(), LocalCollective(), out,
                                 update_index=1, snapshot_directory=out/'shared', publication_id=2)
            self.assertTrue((out/'step-0001/UPDATE_COMPUTED.json').is_file())
            self.assertTrue((out/'checkpoints/step-0001/COMPLETE.json').is_file())
            self.assertTrue((out/'step-0001/CHECKPOINT_PERSISTED.json').is_file())
            self.assertFalse((out/'step-0001/STEP_COMPLETE.json').exists())


if __name__ == '__main__': unittest.main()
