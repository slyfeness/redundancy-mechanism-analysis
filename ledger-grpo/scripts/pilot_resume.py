"""Bind a fresh on-policy stage to a completed four-rank checkpoint."""

import hashlib
import json
from pathlib import Path
import re


def _read(path):
    return json.loads(path.read_bytes())


def _sha(value):
    return isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) is not None


def bind_checkpoint(path, *, runs_root, world_size=4):
    supplied = Path(path)
    checkpoint = supplied.resolve(strict=True)
    if supplied.is_symlink() or not checkpoint.is_relative_to(Path(runs_root).resolve()):
        raise ValueError('resume checkpoint must belong to the pilot run store')
    marker_path = checkpoint/'COMPLETE.json'
    marker_bytes = marker_path.read_bytes()
    marker = json.loads(marker_bytes)
    step = marker['optimizer_step']
    if (type(step) is not int or step < 1 or checkpoint.name != f'step-{step:04d}'
            or checkpoint.parent.name != 'checkpoints' or marker['world_size'] != world_size
            or set(marker['contents']) != {'model','optimizer','cpu_rng','cuda_rng'}):
        raise ValueError('resume requires a complete model, Adam and RNG checkpoint of matching topology')
    shards = {f'checkpoint-rank{i}.pt' for i in range(world_size)}
    if len(marker['shards']) != world_size or {v['name'] for v in marker['shards']} != shards:
        raise ValueError('resume checkpoint lacks the complete rank shard set')
    for shard in marker['shards']:
        actual = checkpoint/shard['name']
        if actual.is_symlink() or not actual.is_file() or actual.stat().st_size != shard['bytes'] or shard['bytes'] <= 0:
            raise ValueError('resume rank shard does not match checkpoint receipt')
    arm_root = checkpoint.parent.parent
    prior = arm_root/checkpoint.name
    inputs, complete = _read(prior/'INPUTS.json'), _read(prior/'STEP_COMPLETE.json')
    snapshot = complete['snapshot_receipt']
    publication = marker['publication_id']
    directory = Path(complete['snapshot_directory']).resolve()
    if (inputs['optimizer_step'] != step or complete.get('persisted_optimizer_steps') != step
            or complete.get('snapshot_published') is not True or complete['publication_id'] != publication
            or snapshot['snapshot'] != f'step-{publication}.safetensors' or not _sha(snapshot['file_sha256'])
            or not directory.is_relative_to(arm_root.parent) or _read(directory/f'step-{publication}.json') != snapshot):
        raise ValueError('resume source does not bind to a verified snapshot of the same update')
    older = (inputs.get('resume') or {}).get('consumed_batches',[])
    batches = [*older,inputs['native_batch_sha256']]
    if len(batches) != step or len(set(batches)) != step or not all(_sha(x) for x in batches):
        raise ValueError('resume source has incomplete or repeated native batch lineage')
    return {'checkpoint':str(checkpoint), 'checkpoint_receipt_sha256':hashlib.sha256(marker_bytes).hexdigest(),
            'optimizer_step':step, 'control':inputs['control'], 'consumed_batches':batches,
            'snapshot_directory':str(directory), 'snapshot_receipt':snapshot,
            'backend':_read(prior/'BACKEND.json')}


def bind_fresh_batch(parent, manifest):
    if manifest['native_batch_sha256'] in parent['consumed_batches']:
        raise ValueError('resume must use fresh native trajectories')
    if manifest.get('policy_snapshot_sha256') != parent['snapshot_receipt']['file_sha256']:
        raise ValueError('resume rollouts were not bound to the checkpoint policy snapshot')
