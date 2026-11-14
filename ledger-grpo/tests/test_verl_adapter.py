"""CPU contract tests; the DataProto/verl doubles do not emulate training."""

from contextlib import contextmanager
from collections import UserDict
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import torch


class DataProtoStub:
    def __init__(self):
        self.batch = {
            "outcome_scores": torch.tensor([1.0, 0.0, 0.0, 0.0]),
            "response_mask": torch.tensor([[1, 0, 1], [1, 1, 0], [1, 1, 1], [1, 1, 1]]),
            "span_redundancy": torch.zeros(4, 3),
            "grounding_scores": torch.zeros(4),
            "span_deviation": torch.zeros(4, 3),
            "token_level_rewards": torch.full((4, 3), 123.0),
        }
        self.non_tensor_batch = {"uid": ["a", "a", "b", "b"]}
        self.meta_info = {}


@contextmanager
def fake_verl(original=None):
    """Only the public registry and legacy dispatch boundary are doubled."""
    modules = {name: types.ModuleType(name) for name in (
        "verl", "verl.trainer", "verl.trainer.ppo",
        "verl.trainer.ppo.core_algos", "verl.trainer.ppo.ray_trainer",
    )}
    core = modules["verl.trainer.ppo.core_algos"]
    trainer = modules["verl.trainer.ppo.ray_trainer"]
    core.ADV_ESTIMATOR_REGISTRY = {}

    def register(name):
        def decorate(fn):
            if name in core.ADV_ESTIMATOR_REGISTRY and core.ADV_ESTIMATOR_REGISTRY[name] is not fn:
                raise ValueError("estimator conflict")
            core.ADV_ESTIMATOR_REGISTRY[name] = fn
            return fn
        return decorate

    def upstream(data, adv_estimator, gamma=1.0, lam=1.0, num_repeat=1,
                 norm_adv_by_std_in_grpo=True, config=None):
        data.meta_info["delegated"] = (adv_estimator, gamma, lam, num_repeat)
        return data

    core.register_adv_est = register
    trainer.compute_advantage = original or upstream
    modules["verl.trainer.ppo"].core_algos = core
    modules["verl.trainer.ppo"].ray_trainer = trainer
    with patch.dict(sys.modules, modules):
        yield core, trainer


class AdapterTests(unittest.TestCase):
    def adapter(self):
        try:
            return importlib.import_module("ledger_grpo.verl_adapter")
        except ModuleNotFoundError as exc:
            self.fail(f"The explicit verl adapter is not implemented: {exc}")

    def test_apply_masks_all_wrong_groups_and_tool_tokens(self):
        data = DataProtoStub()
        original = data.batch["response_mask"].clone()
        result = self.adapter().apply_to_batch(data, {"ledger_span": {"process_enabled": False}})
        self.assertIs(result, data)
        self.assertTrue(torch.equal(data.batch["ledger_response_mask"], original))
        self.assertTrue(torch.equal(data.batch["response_mask"],
                                    torch.tensor([[1, 0, 1], [1, 1, 0], [0, 0, 0], [0, 0, 0]])))
        self.assertGreater(float(data.batch["advantages"][0, 0]), 0)
        self.assertLess(float(data.batch["advantages"][1, 0]), 0)
        self.assertEqual(float(data.batch["advantages"][0, 1]), 0)
        self.assertEqual(float(data.batch["advantages"][2:].abs().sum()), 0)
        self.assertIn("ledger_grpo", data.meta_info)

    def test_outcome_is_required_even_when_token_rewards_exist(self):
        data = DataProtoStub()
        del data.batch["outcome_scores"]
        with self.assertRaisesRegex(ValueError, "outcome_scores"):
            self.adapter().apply_to_batch(data, None)

    def test_task_id_is_accepted_but_missing_group_ids_rejected(self):
        data = DataProtoStub()
        data.non_tensor_batch["task_id"] = data.non_tensor_batch.pop("uid")
        self.adapter().apply_to_batch(data, None)
        self.assertGreater(float(data.batch["advantages"][0, 0]), 0)
        data.non_tensor_batch.clear()
        with self.assertRaisesRegex(ValueError, "uid|task_id"):
            self.adapter().apply_to_batch(data, None)

    def test_unknown_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown|Unknown"):
            self.adapter().apply_to_batch(DataProtoStub(), {"ledger_span": {"typo_weight": 2}})

    def test_nested_configuration_mappings_are_normalized(self):
        config = UserDict({"algorithm": UserDict({"ledger_span": UserDict({
            "deviation_weights": UserDict({"D1": 0.1, "D2": 0.15, "D3": 0.1, "D4": 0.15}),
        })})})
        try:
            data = self.adapter().apply_to_batch(DataProtoStub(), config)
        except ValueError as exc:
            self.fail(f"A valid nested configuration mapping was rejected: {exc}")
        self.assertGreater(float(data.batch["advantages"][0, 0]), 0)

    def test_original_response_mask_is_not_overwritten_on_reuse(self):
        data = DataProtoStub()
        original = data.batch["response_mask"].clone()
        adapter = self.adapter()
        adapter.apply_to_batch(data, None)
        adapter.apply_to_batch(data, None)
        self.assertTrue(torch.equal(data.batch["ledger_response_mask"], original))

    def test_no_valid_rows_cannot_reach_an_optimizer(self):
        adapter = self.adapter()
        data = DataProtoStub()
        data.batch["outcome_scores"].zero_()
        with self.assertRaisesRegex(RuntimeError, "valid|skip|Skip") as caught:
            adapter.apply_to_batch(data, None)
        self.assertIsInstance(caught.exception, adapter.NoValidTrainingRows)
        self.assertNotIn("advantages", data.batch)

    def test_explicit_process_config_reaches_span_adjustment(self):
        data = DataProtoStub()
        data.batch["span_redundancy"][0, 0] = 0.5
        self.adapter().apply_to_batch(data, {"ledger_span": {
            "process_enabled": True, "batch_scale": False,
            "efficiency_weight": 0.0, "grounding_weight": 0.0,
        }})
        self.assertAlmostEqual(float(data.batch["advantages"][0, 0]),
                               0.5 * float(data.batch["advantages"][0, 2]), places=6)

    def test_controls_reach_loss_tensors_and_preserve_effective_mask(self):
        def score(mode):
            data = DataProtoStub()
            data.batch["span_redundancy"][0, 0] = 1.0
            return self.adapter().apply_to_batch(data, {"ledger_span": {
                "process_enabled": True, "batch_scale": False,
                "efficiency_weight": 0.0, "grounding_weight": 0.0,
                "control": mode, "seed": 7,
            }})

        targeted = score("targeted")
        baseline = float(targeted.batch["advantages"][0, 2])
        for mode in ("uniform", "shuffle", "trajectory"):
            with self.subTest(mode=mode):
                result = score(mode)
                values = result.batch["advantages"]
                self.assertEqual(float(values[0, 1]), 0)
                self.assertEqual(float(values[2:].abs().sum()), 0)
                self.assertTrue(torch.equal(values, result.batch["returns"]))
                self.assertEqual(result.meta_info["ledger_grpo"]["control"], mode)
                self.assertEqual(result.meta_info["ledger_grpo"]["control_seed"], 7)
                if mode == "uniform":
                    self.assertAlmostEqual(float(values[0, 0]), baseline / 2, places=6)
                    self.assertAlmostEqual(float(values[0, 2]), baseline / 2, places=6)
                elif mode == "trajectory":
                    self.assertAlmostEqual(float(values[0, 0]), baseline, places=6)
                    self.assertAlmostEqual(float(values[0, 2]), baseline, places=6)
                else:
                    self.assertTrue(torch.equal(values, score(mode).batch["advantages"]))
                    self.assertTrue(torch.equal(values[0].sort().values,
                                                targeted.batch["advantages"][0].sort().values))

    def test_control_configuration_is_validated_before_mutation(self):
        for options in ({"control": "span-shuffle"}, {"seed": True}, {"seed": -1}, {"seed": 1.5}):
            with self.subTest(options=options):
                data = DataProtoStub()
                with self.assertRaisesRegex(ValueError, "control|seed"):
                    self.adapter().apply_to_batch(data, {"ledger_span": options})
                self.assertNotIn("advantages", data.batch)

    def test_plain_import_does_not_install_bridge(self):
        with fake_verl() as (core, trainer):
            original = trainer.compute_advantage
            importlib.reload(self.adapter())
            self.assertIs(trainer.compute_advantage, original)
            self.assertNotIn("span_grpo", core.ADV_ESTIMATOR_REGISTRY)

    def test_explicit_registration_is_idempotent_and_routes_only_our_name(self):
        adapter = self.adapter()
        with fake_verl() as (core, trainer):
            adapter.register_verl_bridge()
            installed = trainer.compute_advantage
            adapter.register_verl_bridge()
            self.assertIs(trainer.compute_advantage, installed)
            self.assertIn("span_grpo", core.ADV_ESTIMATOR_REGISTRY)
            mine = trainer.compute_advantage(DataProtoStub(), "span_grpo", config={"ledger_span": {}})
            self.assertIn("advantages", mine.batch)
            other = trainer.compute_advantage(DataProtoStub(), "grpo", gamma=0.8, lam=0.7, num_repeat=4)
            self.assertEqual(other.meta_info["delegated"], ("grpo", 0.8, 0.7, 4))
            self.assertNotIn("advantages", other.batch)

    def test_bare_registered_estimator_rejects_missing_payload(self):
        with fake_verl() as (core, _):
            self.adapter().register_verl_bridge()
            with self.assertRaisesRegex(ValueError, "payload|apply_to_batch|bridge"):
                core.ADV_ESTIMATOR_REGISTRY["span_grpo"](
                    token_level_rewards=torch.zeros(2, 3), response_mask=torch.ones(2, 3),
                    index=["a", "a"], config=None,
                )

    def test_registered_dispatch_propagates_control_configuration(self):
        with fake_verl() as (_, trainer):
            self.adapter().register_verl_bridge()
            data = DataProtoStub()
            data.batch["span_redundancy"][0, 0] = 1.0
            trainer.compute_advantage(data, "span_grpo", config={"ledger_span": {
                "process_enabled": True, "control": "uniform",
            }})
            self.assertGreater(float(data.batch["advantages"][0, 0]), 0)
            self.assertEqual(float(data.batch["advantages"][0, 0]), float(data.batch["advantages"][0, 2]))
            self.assertEqual(data.meta_info["ledger_grpo"]["control"], "uniform")

    def test_incompatible_signature_is_rejected_without_mutation(self):
        def incompatible(data):
            return data
        with fake_verl(incompatible) as (core, trainer):
            with self.assertRaisesRegex(RuntimeError, "signature|Signature|compatible"):
                self.adapter().register_verl_bridge()
            self.assertIs(trainer.compute_advantage, incompatible)
            self.assertEqual(core.ADV_ESTIMATOR_REGISTRY, {})

    def test_v1_mode_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "v1|V1"):
            self.adapter().apply_to_batch(DataProtoStub(), {"trainer": {"use_v1": True}})

    def test_v1_callsite_is_rejected_even_without_full_trainer_config(self):
        def v1_caller(data):
            return dispatcher(data, "span_grpo")
        with fake_verl() as (_, trainer):
            self.adapter().register_verl_bridge()
            call = types.FunctionType(v1_caller.__code__, {
                "__name__": "verl.trainer.ppo.v1.utils",
                "dispatcher": trainer.compute_advantage,
            })
            with self.assertRaisesRegex(RuntimeError, "v1|V1"):
                call(DataProtoStub())

    def test_non_token_mean_loss_is_rejected_when_full_config_is_available(self):
        config = {"actor_rollout_ref": {"actor": {"loss_agg_mode": "seq-mean-token-mean"}}}
        with self.assertRaisesRegex(RuntimeError, "token-mean"):
            self.adapter().apply_to_batch(DataProtoStub(), config)


if __name__ == "__main__":
    unittest.main()
