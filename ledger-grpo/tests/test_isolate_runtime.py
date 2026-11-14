import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ORIGINAL = """# Synthetic source; the factory only reads it, never executes it.
self.env.update(VLLM_CACHE_ROOT=str(STORE/'cache/phase05/vllm'))
self.cmd=['--model',str(MODEL)]
tmp=Path('/file_storage01/home/weiyu/lanyi/q35tmp')/(os.getenv('SLURM_JOB_ID','manual')+'_'+self.folder.name)
self.env['TMPDIR']=str(tmp)
"""


def isolation():
    path = Path(__file__).parents[1] / 'scripts/isolate_runtime.py'
    spec = importlib.util.spec_from_file_location('isolate_runtime_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = self.base/'pilot'
        self.output = self.store/'runs/job/services'
        self.output.mkdir(parents=True)
        self.old = self.base/'historical'
        self.old.mkdir()
        self.old_file = self.old/'runtime.py'
        self.old_file.write_text('immutable old source', encoding='utf-8')
        self.environment = patch.dict(os.environ, {
            'LEDGER_PILOT_STORE': str(self.store), 'LEDGER_HF_BACKEND_SOURCE': str(self.old),
            'VLLM_CACHE_ROOT': str(self.store/'cache/vllm'), 'TMPDIR': str(self.store/'tmp'),
            'VLLM_RPC_BASE_PATH': str(self.store/'i')})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def runtime(self, text=ORIGINAL):
        calls = []
        def materialize():
            calls.append('materialize')
            (self.output/'phase10_server_adapted.py').write_bytes(text.encode('utf-8'))
            return 'original class, not launched'
        def factory(namespace, output, prefix_cache, resident=False):
            namespace['server_class']()
            calls.append('factory')
            return (Path(output)/'phase10_server_adapted.py').read_text(encoding='utf-8')
        return SimpleNamespace(graph_server_class=factory), {'server_class': materialize}, calls

    def test_generated_copy_uses_new_cache_roots_and_records_both_hashes(self):
        m = isolation()
        backend, namespace, calls = self.runtime()
        original_callable = namespace['server_class']
        m.install_runtime_isolation(backend)
        adapted = backend.graph_server_class(namespace, self.output, True, resident=True)
        self.assertEqual(calls, ['materialize', 'factory'])
        self.assertIn("VLLM_CACHE_ROOT=os.environ['VLLM_CACHE_ROOT']", adapted)
        self.assertIn("tmp=Path(os.environ['TMPDIR'])/", adapted)
        self.assertIn("self.folder.name.removeprefix('actor')", adapted)
        self.assertNotIn("cache/phase05/vllm", adapted)
        self.assertNotIn("/lanyi/q35tmp", adapted)
        self.assertIs(namespace['server_class'], original_callable)
        self.assertEqual(self.old_file.read_text(), 'immutable old source')
        receipt = json.loads((self.output/'ISOLATION_RECEIPT.json').read_text())
        self.assertEqual(receipt['original_sha256'], hashlib.sha256(ORIGINAL.encode()).hexdigest())
        self.assertEqual(receipt['isolated_sha256'], hashlib.sha256(adapted.encode()).hexdigest())
        self.assertEqual(receipt['vllm_cache_root'], str((self.store/'cache/vllm').resolve()))
        self.assertFalse(receipt['historical_source_modified'])
        self.assertEqual(receipt['vllm_rpc_base_path'], str((self.store/'i').resolve()))

    def test_overlong_rpc_path_fails_before_materialization(self):
        m = isolation()
        backend, namespace, calls = self.runtime()
        m.install_runtime_isolation(backend)
        with patch.dict(os.environ, {'VLLM_RPC_BASE_PATH': str(self.store / ('x'*80))}):
            with self.assertRaisesRegex(ValueError, '107-byte'):
                backend.graph_server_class(namespace, self.output, True)
        self.assertEqual(calls, [])

    def test_rpc_outside_pilot_storage_fails_before_materialization(self):
        m = isolation()
        backend, namespace, calls = self.runtime()
        m.install_runtime_isolation(backend)
        with patch.dict(os.environ, {'VLLM_RPC_BASE_PATH': str(self.old/'i')}):
            with self.assertRaisesRegex(ValueError, 'pilot|storage'):
                backend.graph_server_class(namespace, self.output, True)
        self.assertEqual(calls, [])

    def test_actual_cluster_paths_cover_both_socket_families(self):
        root = '/file_storage01/home/weiyu/lanyi/projects/ledger-grpo-pilot'
        self.assertEqual(isolation().ipc_path_lengths(root+'/tmp', root+'/i/182425', '182425'),
                         {'vllm_uuid_bytes': 105, 'multiprocessing_listener_bytes': 104})
        with self.assertRaisesRegex(ValueError, '107-byte'):
            isolation().ipc_path_lengths(root+'/tmp', root+'/i/123456789', '123456789')

    def test_install_and_materialization_are_idempotent_without_rewriting(self):
        m = isolation()
        backend, namespace, calls = self.runtime()
        m.install_runtime_isolation(backend)
        wrapper = backend.graph_server_class
        m.install_runtime_isolation(backend)
        self.assertIs(backend.graph_server_class, wrapper)
        first = wrapper(namespace, self.output, True)
        receipt = (self.output/'ISOLATION_RECEIPT.json').read_bytes()
        second = wrapper(namespace, self.output, True)
        self.assertEqual(first, second)
        self.assertEqual(calls.count('materialize'), 1)
        self.assertEqual((self.output/'ISOLATION_RECEIPT.json').read_bytes(), receipt)

    def test_outside_output_or_cache_fails_before_original_materializer(self):
        m = isolation()
        backend, namespace, calls = self.runtime()
        m.install_runtime_isolation(backend)
        with self.assertRaisesRegex(ValueError, 'pilot|storage'):
            backend.graph_server_class(namespace, self.old, True)
        with patch.dict(os.environ, {'VLLM_CACHE_ROOT': str(self.old/'cache')}):
            with self.assertRaisesRegex(ValueError, 'pilot|storage'):
                backend.graph_server_class(namespace, self.output, True)
        self.assertEqual(calls, [])

    def test_unknown_source_layout_fails_without_rewriting_materialized_source(self):
        m = isolation()
        for index, source in enumerate((ORIGINAL.replace('cache/phase05/vllm', 'changed/cache'), ORIGINAL+ORIGINAL)):
            with self.subTest(source_length=len(source)):
                self.output = self.store / f'case-{index}'
                self.output.mkdir()
                backend, namespace, calls = self.runtime(source)
                old_callable = namespace['server_class']
                m.install_runtime_isolation(backend)
                with self.assertRaisesRegex(RuntimeError, 'boundary|literal'):
                    backend.graph_server_class(namespace, self.output, True)
                self.assertEqual((self.output/'phase10_server_adapted.py').read_text(), source)
                self.assertFalse((self.output/'ISOLATION_RECEIPT.json').exists())
                self.assertIs(namespace['server_class'], old_callable)

    def test_tampering_with_previously_isolated_file_is_not_overwritten(self):
        m = isolation()
        backend, namespace, calls = self.runtime()
        m.install_runtime_isolation(backend)
        backend.graph_server_class(namespace, self.output, True)
        adapted = self.output/'phase10_server_adapted.py'
        adapted.write_text('modified after receipt', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'hash|receipt'):
            backend.graph_server_class(namespace, self.output, True)
        self.assertEqual(adapted.read_text(), 'modified after receipt')
        self.assertEqual(calls.count('materialize'), 1)

    def test_existing_unreceipted_copy_is_not_reused(self):
        m = isolation()
        backend, namespace, calls = self.runtime()
        (self.output/'phase10_server_adapted.py').write_text(ORIGINAL)
        m.install_runtime_isolation(backend)
        with self.assertRaisesRegex(FileExistsError, 'receipt|fresh'):
            backend.graph_server_class(namespace, self.output, True)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
