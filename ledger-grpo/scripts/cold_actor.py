"""Restart inference with a verified text-only HF snapshot and fresh CUDA state."""

import hashlib
import json
import os
from pathlib import Path


_METADATA = ('config.json', 'tokenizer_config.json', 'tokenizer.json', 'chat_template.jinja',
             'merges.txt', 'vocab.json', 'preprocessor_config.json', 'video_preprocessor_config.json')


def materialize_model(base, snapshots, receipt, output):
    """Use frozen config/tokenizer and the trainer's complete text checkpoint."""
    from safetensors import safe_open
    snapshot_name = receipt['snapshot']
    if Path(snapshot_name).name != snapshot_name or not snapshot_name.endswith('.safetensors'):
        raise ValueError('snapshot receipt must name a direct safetensors file')
    weights = Path(snapshots)/snapshot_name
    if weights.is_symlink() or weights.stat().st_size != receipt['verified_byte_count']:
        raise ValueError('snapshot does not match its verified byte receipt')
    with weights.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != receipt['file_sha256']:
            raise ValueError('snapshot digest differs from trainer receipt')
    base = Path(base).resolve(strict=True)
    index = json.loads((base/'model.safetensors.index.json').read_bytes())['weight_map']
    expected = {key for key in index if key == 'lm_head.weight' or key.startswith('model.language_model.')}
    with safe_open(str(weights), framework='pt', device='cpu') as archive:
        if not expected or set(archive.keys()) != expected:
            raise ValueError('snapshot does not contain the complete frozen text namespace')
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    for name in _METADATA:
        (output/name).symlink_to((base/name).resolve(strict=True))
    (output/'model.safetensors').symlink_to(weights.resolve(strict=True))
    return output.resolve()


def start_cold_actors(services, model_directory, snapshots, receipt, *, log_root):
    """Leave the retriever untouched and replace all actor processes together."""
    from src import stability_controller as runtime
    from src.resident_controller import fingerprint, generated_probe
    from src.resident_rollout import ActorAdmin, ResidentActors

    for server in services.servers:
        server.stop()
    services.servers.clear()
    services.gate.unlink(missing_ok=True)
    log_root = Path(log_root)
    log_root.mkdir(mode=0o700, exist_ok=False)
    model = materialize_model(model_directory, snapshots, receipt, log_root/'model')
    namespace = runtime.runtime(log_root, resident=True, retriever_instrumenter=runtime.instrument_search_timing)
    factory = runtime.graph_server_class(namespace, log_root, prefix_cache=True, resident=True)
    os.environ['LEDGER_ACTOR_MODEL'] = str(model)
    try:
        for index, gpu in enumerate(services.devices):
            services.servers.append(factory(log_root/f'actor{index}', 65536, gpu=gpu, memory=.75))
    finally:
        os.environ.pop('LEDGER_ACTOR_MODEL', None)
    for server in services.servers:
        server.wait()
    workers = [ActorAdmin(server.url, services.secret) for server in services.servers]
    services.actors = ResidentActors(workers, services.gate)
    fingerprints = services.actors.all(fingerprint)
    if any(value != receipt['fingerprint'] for value in fingerprints):
        raise RuntimeError('A cold Actor does not match the verified updated snapshot')
    probes = services.actors.all(generated_probe)
    if any(p['token_ids'] != probes[0]['token_ids'] for p in probes):
        raise RuntimeError('Cold Actors disagree on the deterministic generation probe')
    services.actors.version = receipt['snapshot']
    return {'snapshot': receipt['snapshot'], 'sha256': receipt['file_sha256'],
            'fingerprints': fingerprints, 'probes': probes, 'transport': 'cold_load'}


def main():
    import argparse
    import secrets
    from types import SimpleNamespace

    from isolate_runtime import install_runtime_isolation

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-model', type=Path, required=True)
    parser.add_argument('--snapshot-receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    install_runtime_isolation()
    args.output.mkdir(mode=0o700, exist_ok=False)
    os.chdir(args.output)
    secret, gate = secrets.token_urlsafe(32), args.output/'gate'
    os.environ.update(OCCAM_ACTOR_ADMIN=secret, OCCAM_ACTOR_GATE=str(gate),
                      OCCAM_SNAPSHOT_DIR=str(args.snapshot_receipt.parent))
    services = SimpleNamespace(servers=[], devices=os.environ['CUDA_VISIBLE_DEVICES'].split(','),
                               gate=gate, secret=secret)
    try:
        receipt = json.loads(args.snapshot_receipt.read_bytes())
        result = start_cold_actors(services, args.base_model, args.snapshot_receipt.parent, receipt,
                                   log_root=args.output/'cold')
        (args.output/'RESULT.json').write_text(json.dumps(result), encoding='utf-8')
        print(json.dumps({'state': 'verified', 'actor_count': len(result['fingerprints'])}), flush=True)
    finally:
        for server in services.servers:
            server.stop()


if __name__ == '__main__':
    main()
