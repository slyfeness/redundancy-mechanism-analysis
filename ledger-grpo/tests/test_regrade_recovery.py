from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from regrade_pilot import recover_verdicts, write


class RegradeRecoveryTests(unittest.TestCase):
    def test_retains_completed_receipts_even_if_balance_is_unavailable(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            earlier = root / "earlier"
            output = root / "new"
            output.mkdir()
            receipt_dir = earlier / "receipts" / "targeted"
            receipt_dir.mkdir(parents=True)
            identity = {"grader_template_sha256": "pinned"}
            write(earlier / "JUDGE_IDENTITY.json", identity)
            accepted = {"request_sha256": "first", "correct": True,
                        "served_model": "deepseek-flash", "attempts": [{"status": 200}]}
            write(receipt_dir / "000.json", accepted)
            write(receipt_dir / "001.json", dict(accepted, request_sha256="wrong-request"))
            requests = {"targeted": [
                {"arm": "targeted", "index": 0, "request_sha256": "first"},
                {"arm": "targeted", "index": 1, "request_sha256": "second"},
            ]}
            judge = Mock()
            with patch("regrade_pilot._balance_available", return_value=False):
                recovered, state = recover_verdicts(output, requests, [earlier], identity, "key", judge)
            self.assertEqual(state, "balance_unavailable")
            self.assertEqual(recovered, {"first": accepted})
            self.assertTrue((output / "receipts/targeted/000.json").is_file())
            self.assertFalse((output / "receipts/targeted/001.json").exists())
            judge.assert_not_called()

    def test_fully_reused_receipts_do_not_need_balance_or_new_calls(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            earlier = root / "earlier"
            receipt_dir = earlier / "receipts" / "outcome"
            receipt_dir.mkdir(parents=True)
            output = root / "new"
            output.mkdir()
            identity = {"grader_template_sha256": "pinned"}
            write(earlier / "JUDGE_IDENTITY.json", identity)
            receipt = {"request_sha256": "only", "correct": False,
                       "served_model": "deepseek-flash", "attempts": [{"status": 200}]}
            write(receipt_dir / "000.json", receipt)
            requests = {"outcome": [{"arm": "outcome", "index": 0, "request_sha256": "only"}]}
            judge = Mock()
            with patch("regrade_pilot._balance_available") as balance:
                recovered, state = recover_verdicts(output, requests, [earlier], identity, "key", judge)
            self.assertEqual(state, "completed")
            self.assertEqual(recovered, {"only": receipt})
            balance.assert_not_called()
            judge.assert_not_called()
