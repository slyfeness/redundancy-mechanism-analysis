"""Credential storage tests use dummy secrets and temporary paths only."""

from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import os
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import patch


class CredentialTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("ledger_grpo.credentials")
        except ImportError as exc:
            self.fail(f"credential storage is not implemented: {exc}")

    def test_missing_file_returns_none_without_creating_storage(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "absent" / "key.dpapi"
            self.assertIsNone(module.load_deepseek_key(path=path))
            self.assertFalse(path.parent.exists())

    def test_invalid_keys_are_rejected_without_writing_files(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.dpapi"
            for value in (None, "", "   ", "sk-a\nb", "sk-a\x00b", "sk-a\x7fb", "sk-\u2603"):
                with self.subTest(value_type=type(value).__name__), self.assertRaises(module.CredentialError):
                    module.save_deepseek_key(value, path=path)
                self.assertFalse(path.exists())

    def test_atomic_replace_failure_preserves_previous_ciphertext_and_hides_errors(self):
        module = self.api()
        marker = "DUMMY_PRIVATE_ERROR_TEXT"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.dpapi"
            path.write_bytes(b"previous-ciphertext")
            captured = io.StringIO()
            with patch.object(module, "_crypt", return_value=b"new-ciphertext"), patch.object(module.os, "replace", side_effect=OSError(marker)):
                with redirect_stdout(captured), redirect_stderr(captured):
                    try:
                        module.save_deepseek_key("sk-dummy-atomic", path=path)
                    except module.CredentialError as exc:
                        self.assertNotIn(marker, str(exc))
                        self.assertNotIn(marker, "".join(traceback.format_exception(exc)))
                    else:
                        self.fail("replace failure must not report success")
            self.assertEqual(captured.getvalue(), "")
            self.assertEqual(path.read_bytes(), b"previous-ciphertext")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_bad_decrypted_payload_is_an_error_not_missing_credential(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.dpapi"
            path.write_bytes(b"opaque-ciphertext")
            with patch.object(module, "_crypt", return_value=b"not-our-credential-format"):
                with self.assertRaises(module.CredentialError):
                    module.load_deepseek_key(path=path)

    @unittest.skipUnless(os.name == "nt", "requires current-user Windows DPAPI")
    def test_real_dpapi_round_trip_and_overwrite_never_write_plaintext(self):
        module = self.api()
        first, second = "sk-dummy-dpapi-first-934752", "sk-dummy-dpapi-second-281946"
        captured = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "key.dpapi"
            with redirect_stdout(captured), redirect_stderr(captured):
                self.assertIsNone(module.save_deepseek_key("  " + first + "  ", path=path))
                blob = path.read_bytes()
                self.assertNotIn(first.encode("ascii"), blob)
                self.assertEqual(module.load_deepseek_key(path=path), first)
                module.save_deepseek_key(second, path=path)
                self.assertEqual(module.load_deepseek_key(path=path), second)
                self.assertNotEqual(blob, path.read_bytes())
                self.assertNotIn(second.encode("ascii"), path.read_bytes())
            self.assertEqual(captured.getvalue(), "")

    @unittest.skipUnless(os.name == "nt", "requires current-user Windows DPAPI")
    def test_default_location_uses_only_the_explicit_localappdata_directory(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            module.save_deepseek_key("sk-dummy-default-path")
            target = Path(directory) / "LedgerGRPO" / "deepseek-key.dpapi"
            self.assertTrue(target.is_file())
            self.assertEqual(module.load_deepseek_key(), "sk-dummy-default-path")

    @unittest.skipUnless(os.name == "nt", "requires current-user Windows DPAPI")
    def test_real_corrupt_ciphertext_raises_safe_error(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.dpapi"
            path.write_bytes(b"corrupted-dpapi-ciphertext")
            with self.assertRaises(module.CredentialError) as caught:
                module.load_deepseek_key(path=path)
            self.assertNotIn("corrupted-dpapi-ciphertext", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
