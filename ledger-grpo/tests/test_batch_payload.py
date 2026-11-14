"""Native rollout alignment and atomic attachment, without importing verl."""

import copy
import importlib
import importlib.util
from types import SimpleNamespace
import unittest

import torch

from ledger_grpo.advantages import AdvantageConfig
from ledger_grpo.examples import synthetic_examples
from ledger_grpo.pipeline import analyze_trajectory
from ledger_grpo.rules import RuleConfig
from ledger_grpo.verl_adapter import apply_to_batch


def inputs():
    traces, deltas = synthetic_examples()
    reports = [analyze_trajectory(t, deltas=deltas[t["traj_id"]], rule_config=RuleConfig(enable_artifact_d4=True)) for t in traces]
    width = max(len(t["response_mask"]) for t in traces) + 2
    mask = torch.tensor([t["response_mask"] + [0] * (width - len(t["response_mask"])) for t in traces])
    data = SimpleNamespace(
        batch={"response_mask": mask, "existing": torch.arange(len(traces))},
        non_tensor_batch={"traj_id": [t["traj_id"] for t in traces], "uid": [t["task_id"] for t in traces]},
        meta_info={"untouched": True},
    )
    return data, traces, reports


class BatchPayloadTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("ledger_grpo.batch_payload").attach_reports
        except ImportError as exc:
            self.fail(f"report attachment is not implemented: {exc}")

    def test_reports_align_by_identity_before_adapter_computes_advantages(self):
        attach = self.api()
        data, traces, reports = inputs()
        mask = data.batch["response_mask"].clone()
        metadata = copy.deepcopy(data.non_tensor_batch)
        cfg = AdvantageConfig(process_enabled=True, batch_scale=False)
        result = attach(data, list(reversed(traces)), reports[2:] + reports[:2], config=cfg, enable_artifact_d4=True)
        self.assertIs(result, data)
        self.assertEqual(data.non_tensor_batch, metadata)
        self.assertNotIn("advantages", data.batch)
        self.assertEqual(data.batch["outcome_scores"].tolist(), [1, 1, 0, 1, 1, 0])
        self.assertTrue(torch.equal(data.batch["response_mask"], mask))
        self.assertEqual(data.batch["span_redundancy"][0, 4:8].tolist(), [1, 1, 0, 0])
        self.assertEqual(float(data.batch["span_redundancy"][1].sum()), 0.0)
        for key in ("outcome_scores", "span_redundancy", "grounding_scores", "span_deviation", "process_valid", "training_valid"):
            self.assertEqual(data.batch[key].device, mask.device)
            self.assertFalse(data.batch[key].requires_grad)
        apply_to_batch(data, cfg)
        self.assertEqual(data.batch["advantages"].shape, mask.shape)
        self.assertEqual(float(data.batch["advantages"][mask == 0].abs().sum()), 0.0)
        self.assertEqual(data.batch["advantages"][0, 4:6].tolist(), [0.0, 0.0])
        self.assertGreater(float(data.batch["advantages"][0, 0]), 0.0)

    def test_d4_uses_the_same_advantage_configuration_weight(self):
        attach = self.api()
        data, traces, reports = inputs()
        cfg = AdvantageConfig(deviation_weights={"D1": .1, "D2": .15, "D3": .1, "D4": .04})
        attach(data, traces, reports, config=cfg, enable_artifact_d4=True)
        self.assertAlmostEqual(float(data.batch["span_deviation"][3, 4]), .04, places=6)
        self.assertEqual(float(data.batch["span_deviation"][4].sum()), 0.0)

    def test_misaligned_native_rows_are_rejected_without_partial_updates(self):
        attach = self.api()
        data, traces, reports = inputs()
        data.non_tensor_batch["traj_id"][0], data.non_tensor_batch["traj_id"][1] = data.non_tensor_batch["traj_id"][1], data.non_tensor_batch["traj_id"][0]
        original = data.batch
        snapshot = {key: value.clone() for key, value in original.items()}
        with self.assertRaisesRegex(ValueError, "mask"):
            attach(data, traces, reports)
        self.assertIs(data.batch, original)
        self.assertEqual(set(data.batch), set(snapshot))
        for key in snapshot:
            self.assertTrue(torch.equal(data.batch[key], snapshot[key]))

    def test_mask_mismatch_or_insufficient_width_is_rejected_atomically(self):
        attach = self.api()
        for change in ("policy", "padding", "width", "stale_original"):
            with self.subTest(change=change):
                data, traces, reports = inputs()
                if change == "policy":
                    data.batch["response_mask"][0, 0] = 0
                elif change == "padding":
                    data.batch["response_mask"][0, -1] = 1
                elif change == "width":
                    data.batch["response_mask"] = data.batch["response_mask"][:, :2]
                else:
                    data.batch["ledger_response_mask"] = torch.zeros_like(data.batch["response_mask"])
                original = data.batch
                with self.assertRaisesRegex(ValueError, "mask|width"):
                    attach(data, traces, reports)
                self.assertIs(data.batch, original)
                self.assertNotIn("outcome_scores", data.batch)

    def test_missing_duplicate_or_wrong_group_identity_is_rejected_atomically(self):
        attach = self.api()
        for change in ("missing_id", "duplicate_data", "duplicate_trace", "duplicate_report", "missing_report", "group", "both_groups"):
            with self.subTest(change=change):
                data, traces, reports = inputs()
                if change == "missing_id":
                    del data.non_tensor_batch["traj_id"]
                elif change == "duplicate_data":
                    data.non_tensor_batch["traj_id"][1] = data.non_tensor_batch["traj_id"][0]
                elif change == "duplicate_trace":
                    traces[1] = traces[0]
                elif change == "duplicate_report":
                    reports[1] = reports[0]
                elif change == "missing_report":
                    reports.pop()
                elif change == "group":
                    data.non_tensor_batch["uid"][0] = "different-question"
                else:
                    data.non_tensor_batch["task_id"] = ["wrong"] * len(traces)
                original = data.batch
                with self.assertRaises(ValueError):
                    attach(data, traces, reports)
                self.assertIs(data.batch, original)
                self.assertNotIn("outcome_scores", data.batch)

    def test_task_id_column_is_supported_and_missing_groups_fail(self):
        attach = self.api()
        data, traces, reports = inputs()
        data.non_tensor_batch["task_id"] = data.non_tensor_batch.pop("uid")
        attach(data, traces, reports)
        self.assertEqual(data.batch["outcome_scores"].numel(), len(traces))
        data, traces, reports = inputs()
        del data.non_tensor_batch["uid"]
        with self.assertRaisesRegex(ValueError, "uid|task_id"):
            attach(data, traces, reports)

    def test_late_report_failure_does_not_replace_existing_payload(self):
        attach = self.api()
        data, traces, reports = inputs()
        data.batch["outcome_scores"] = torch.full((len(traces),), 9.)
        reports[-1]["trace_digest"] = "invalid"
        original = data.batch
        with self.assertRaises(ValueError):
            attach(data, traces, reports)
        self.assertIs(data.batch, original)
        self.assertEqual(data.batch["outcome_scores"].tolist(), [9.] * len(traces))

    @unittest.skipUnless(importlib.util.find_spec("tensordict"), "optional tensordict is not installed")
    def test_real_tensordict_container_when_available(self):
        from tensordict import TensorDict
        attach = self.api()
        data, traces, reports = inputs()
        data.batch = TensorDict(data.batch, batch_size=[len(traces)])
        attach(data, traces, reports)
        self.assertIsInstance(data.batch, TensorDict)
        self.assertEqual(data.batch["span_redundancy"].shape, data.batch["response_mask"].shape)


if __name__ == "__main__":
    unittest.main()
