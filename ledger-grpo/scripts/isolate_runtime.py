"""Isolate caches in this pilot's generated server copy, never historical code.

Ordinary import does nothing. The explicit hook wraps the old factory only in
this controller process. It intercepts materialization before the graph factory
reads/compiles the generated copy and before any actor subprocess is launched.
"""
import functools
import hashlib
import importlib
import json
import os
from pathlib import Path


REPLACEMENTS = {
    "VLLM_CACHE_ROOT=str(STORE/'cache/phase05/vllm')":
        "VLLM_CACHE_ROOT=os.environ['VLLM_CACHE_ROOT']",
    "tmp=Path('/file_storage01/home/weiyu/lanyi/q35tmp')/":
        "tmp=Path(os.environ['TMPDIR'])/",
    "+'_'+self.folder.name)": "+'_'+self.folder.name.removeprefix('actor'))",
    "'--model',str(MODEL)": "'--model',os.getenv('LEDGER_ACTOR_MODEL',str(MODEL))",
}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def ipc_path_lengths(tmp_root, rpc_root, job_id):
    """Installed vLLM UUID and Python multiprocessing listener path sizes."""
    actor_tmp = Path(tmp_root) / f'{job_id}_0'
    lengths = {'vllm_uuid_bytes': len(os.fsencode(str(rpc_root))) + 37,
               'multiprocessing_listener_bytes': len(os.fsencode(str(actor_tmp))) + 32}
    if max(lengths.values()) > 107:
        raise ValueError('Temporary or VLLM_RPC_BASE_PATH exceeds the 107-byte IPC limit')
    return lengths


def _paths(output):
    values = {}
    for name in ('LEDGER_PILOT_STORE', 'VLLM_CACHE_ROOT', 'TMPDIR', 'VLLM_RPC_BASE_PATH'):
        value = os.environ.get(name)
        if not value or not Path(value).is_absolute():
            raise ValueError(f'{name} must be an explicit absolute pilot storage path')
        values[name] = Path(value).resolve()
    store = values['LEDGER_PILOT_STORE']
    output = Path(output).resolve()
    paths = [output, values['VLLM_CACHE_ROOT'], values['TMPDIR'], values['VLLM_RPC_BASE_PATH']]
    if any(path == store or not path.is_relative_to(store) for path in paths):
        raise ValueError('Generated server, cache, and temp paths must be inside the independent pilot storage root')
    backend = os.environ.get('LEDGER_HF_BACKEND_SOURCE')
    if backend and any(path.is_relative_to(Path(backend).resolve()) for path in paths):
        raise ValueError('Pilot storage must never overlap the read-only backend source')
    # vLLM 0.19.1 appends '/' and a 36-character UUID. Linux AF_UNIX
    # permits at most 107 path bytes (excluding its terminating null).
    ipc_path_lengths(values['TMPDIR'], values['VLLM_RPC_BASE_PATH'],
                     os.getenv('SLURM_JOB_ID', 'manual'))
    return output, values


def _verify_existing(path, receipt, values):
    try:
        prior = json.loads(receipt.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise RuntimeError('Unreadable runtime isolation receipt; no automatic repair') from error
    if (path.is_symlink() or not path.is_file()
            or prior.get('generated_file') != str(path)
            or prior.get('isolated_sha256') != _digest(path.read_bytes())
            or prior.get('vllm_cache_root') != str(values['VLLM_CACHE_ROOT'])
            or prior.get('tmp_root') != str(values['TMPDIR'])
            or prior.get('vllm_rpc_base_path') != str(values['VLLM_RPC_BASE_PATH'])):
        raise RuntimeError('Runtime isolation receipt/hash/path mismatch; no automatic overwrite')


def _isolate(path, receipt, values):
    if path.is_symlink() or not path.is_file() or path.resolve().parent != path.parent:
        raise ValueError('Materialized server must be a direct regular file in pilot storage')
    original = path.read_bytes()
    source = original.decode('utf-8')
    if any(source.count(old) != 1 for old in REPLACEMENTS):
        raise RuntimeError('Frozen generated-server cache literal boundary changed; refusing to launch')
    for old, new in REPLACEMENTS.items():
        source = source.replace(old, new, 1)
    compile(source, str(path), 'exec')  # Syntax check only, never execute here.
    isolated = source.encode('utf-8')
    pending = path.with_suffix(path.suffix + '.ledger-isolated.tmp')
    with pending.open('xb') as handle:
        handle.write(isolated)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, path)  # Only the fresh, explicitly allowed generated copy.
    payload = {'generated_file': str(path), 'original_sha256': _digest(original),
               'isolated_sha256': _digest(isolated),
               'vllm_cache_root': str(values['VLLM_CACHE_ROOT']), 'tmp_root': str(values['TMPDIR']),
               'vllm_rpc_base_path': str(values['VLLM_RPC_BASE_PATH']),
               'ipc_path_lengths': ipc_path_lengths(values['TMPDIR'], values['VLLM_RPC_BASE_PATH'],
                                                    os.getenv('SLURM_JOB_ID', 'manual')),
               'historical_source_modified': False,
               'changes': ['vllm_cache_root_from_explicit_environment',
                           'temporary_root_from_explicit_environment_with_short_job_actor_suffix',
                           'explicit_vllm_rpc_root_inherited_by_actors',
                           'optional_actor_model_for_cold_publication']}
    with receipt.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def install_runtime_isolation(runtime_module=None):
    """Explicit, idempotent controller hook; runtime_module allows CPU fake tests."""
    module = runtime_module or importlib.import_module('src.stability_controller')
    original_factory = module.graph_server_class
    if getattr(original_factory, '_ledger_runtime_isolation', False):
        return original_factory

    @functools.wraps(original_factory)
    def graph_factory(namespace, output, prefix_cache, resident=False):
        root, values = _paths(output)
        path = root / 'phase10_server_adapted.py'
        receipt = root / 'ISOLATION_RECEIPT.json'
        original_materializer = namespace['server_class']

        def materialize():
            if receipt.exists():
                _verify_existing(path, receipt, values)
                return None  # Old factory uses only the materialized file.
            if path.exists():
                raise FileExistsError('Generated server has no isolation receipt; a fresh output directory is required')
            result = original_materializer()
            _isolate(path, receipt, values)
            return result

        namespace['server_class'] = materialize
        try:
            return original_factory(namespace, output, prefix_cache, resident=resident)
        finally:
            namespace['server_class'] = original_materializer

    graph_factory._ledger_runtime_isolation = True
    module.graph_server_class = graph_factory
    return graph_factory
