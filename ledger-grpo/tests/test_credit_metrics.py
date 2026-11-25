"""Dataset-free checks of credit logs and their denominators."""
import copy
import importlib
import unittest


def example():
    trajectories = [
        {"qid": "synthetic", "rollout": 0, "outcome": {"Y": True, "submitted": True},
         "tokens": {1: 1, 2: 1, "F": 2}, "returned_tokens": {1: 5, 2: 3},
         "conds": ["A", "c1"], "derived": [{"chain": {"answer": "object-a"},
         "view": {"A": ["✔", [], True], "c1": ["✔", [], True]}}]},
        {"qid": "synthetic", "rollout": 1, "outcome": {"Y": False, "submitted": False},
         "tokens": {1: 2, "F": 2}, "returned_tokens": {1: 7}, "conds": ["A"], "derived": []},
    ]
    credits = [
        dict(A_hat=1., A={1: 2., 2: 0., "F": 1.}, nu={1: .25, 2: .25, "F": .5},
             role={1: "C", 2: "R", "F": "F"}, e={1: .2, 2: .05, "F": 0.},
             P={1: [(.1, "采纳E1"), (.1, "取到E1"), (.05, "取到E2(未被用)"), (.02, "采纳反证E3")]},
             R={2: [(.05, "浪费:原地打转、严格重复")]}, log={"infeasible": False, "dropped": 0.}),
        dict(A_hat=-1., A={1: -1., "F": -1.}, nu={1: .5, "F": .5},
             role={1: "K", "F": "F"}, e={1: 0., "F": 0.}, P={}, R={},
             log={"infeasible": False, "dropped": 0., "unmatched_units": 1}),
    ]
    return trajectories, credits


class CreditMetricsTests(unittest.TestCase):
    def collect(self, *args, **kwargs):
        try:
            module = importlib.import_module("ledger_grpo.credit.metrics")
        except ModuleNotFoundError as exc:
            self.fail("Missing metrics implementation: " + str(exc))
        return module.collect_credit_metrics(*args, **kwargs)

    def test_outcomes_progress_tokens_and_groups(self):
        trajectories, credits = example()
        result = self.collect(trajectories, credits)
        self.assertEqual(result["result"]["accuracy"], .5)
        self.assertEqual(result["result"]["evidence_accuracy"], {"0.5": .5, "0.75": .5, "1.0": .5})
        self.assertEqual(result["result"]["unsubmitted_rate"], .5)
        self.assertEqual(result["result"]["tool_model_calls"], 3)
        self.assertEqual(result["result"]["generated_tokens"], 8)
        self.assertEqual(result["result"]["returned_tokens"], 15)
        self.assertEqual(result["result"]["judge_calls"], 0)
        self.assertEqual(result["groups"]["mixed_rate"], 1.)

    def test_credit_token_denominators_ratios_and_effective_size(self):
        trajectories, credits = example()
        result = self.collect(trajectories, credits)["credit"]
        self.assertEqual(result["role_unit_counts"], {"C": 1, "R": 1, "K": 1, "F": 2})
        self.assertEqual(result["role_token_fractions"], {"C": .125, "R": .125, "K": .25, "F": .5})
        self.assertEqual(result["zeroed_token_fraction"], .125)
        self.assertEqual(result["advantage_ratio_max"], 2.)
        self.assertAlmostEqual(result["advantage_ratio_p95"], 1.65)
        self.assertAlmostEqual(result["effective_token_fraction_median"], 5 / 6)
        self.assertEqual(result["conservation_max_abs"], 0.)
        self.assertEqual(result["unmatched_units"], 1)
        self.assertEqual(result["A_hat_distribution"]["mean"], 0.)

    def test_event_families_and_waste_labels_do_not_repeat_mass(self):
        trajectories, credits = example()
        result = self.collect(trajectories, credits)["credit"]
        self.assertEqual(result["events"]["P1"], {"count": 2, "amount": .2})
        self.assertEqual(result["events"]["P2"], {"count": 1, "amount": .05})
        self.assertEqual(result["events"]["P3"], {"count": 1, "amount": .02})
        self.assertEqual(result["events"]["W"], {"count": 1, "amount": .05})
        self.assertEqual(result["waste_labels"]["原地打转"]["count"], 1)
        self.assertEqual(result["waste_labels"]["严格重复"]["count"], 1)

    def test_policy_modules_and_shuffled_ks(self):
        trajectories, credits = example()
        credits[0]["log"]["shuffle_ks"] = {"C_length": .1, "C_position": .2, "R_length": .3, "R_position": .4}
        result = self.collect(trajectories, credits, policy={"entropy": 2., "kl": .01, "clip_fraction": .2, "gradient_norm": 3.},
                              modules={"process_selected_units": 1, "process_selected_tokens": 2, "auxiliary_loss": .25,
                                       "ledger_sample_fraction": .5, "ledger_correction_weight": 2.})
        self.assertEqual(result["policy"]["gradient_norm"], 3.)
        self.assertEqual(result["modules"]["auxiliary_loss"], .25)
        self.assertEqual(result["modules"]["shuffle_ks_mean"]["R_position"], .4)

    def test_explicit_grouping_zero_advantage_and_drop(self):
        trajectories, credits = example()
        credits[0]["A_hat"] = 0.
        credits[0]["A"] = {1: 0., 2: 0., "F": 0.}
        credits[1]["log"].update(infeasible=True, dropped=.2)
        result = self.collect(trajectories, credits, groups=[[0], [1]])
        self.assertEqual(result["groups"]["zero_advantage_rate"], .5)
        self.assertEqual(result["groups"]["all_correct_rate"], .5)
        self.assertEqual(result["groups"]["all_wrong_rate"], .5)
        self.assertEqual(result["groups"]["all_unsubmitted_rate"], .5)
        self.assertEqual(result["credit"]["infeasible_rate"], .5)
        self.assertEqual(result["credit"]["dropped_mass"], .2)

    def test_pure_function_and_empty_inputs(self):
        trajectories, credits = example()
        before = copy.deepcopy((trajectories, credits))
        self.collect(trajectories, credits)
        self.assertEqual((trajectories, credits), before)
        result = self.collect([], [])
        self.assertEqual(result["result"]["accuracy"], 0.)
        self.assertIsNone(result["policy"]["kl"])
        self.assertEqual(result["credit"]["advantage_ratio_max"], 0.)
        with self.assertRaises(ValueError):
            self.collect(trajectories, [])

    def test_all_error_omission_families_and_zero_base_signal(self):
        trajectories, credits = example()
        labels = ["排除正确答案object-a", "无效排除object-b", "无据断言(被用于决策)",
                  "没用E9", "冲突不改", "有证据不交卷"]
        credits[1]["R"] = {1: [(1., label) for label in labels]}
        credits[1]["P"] = {1: [(.5, "有效排除object-c")]}
        credits[1]["A_hat"] = 0.
        result = self.collect(trajectories, credits)["credit"]
        for family in ("E1", "E2", "E3", "O1", "O3", "O4"):
            self.assertEqual(result["events"][family], {"count": 1, "amount": 1.})
        self.assertEqual(result["events"]["P3"]["count"], 2)
        self.assertEqual(result["nonzero_advantage_with_zero_base_tokens"], 4)

    def test_schema_objects_and_explicit_groups(self):
        schema = importlib.import_module("ledger_grpo.credit.schema")
        trajectories, credits = example()
        objects = []
        for tr in trajectories:
            offset = 0
            units = []
            for uid, count in tr["tokens"].items():
                units.append(schema.Unit(uid, [(offset, offset + count)], count,
                                         tr["returned_tokens"].get(uid, 0)))
                offset += count
            objects.append(schema.Trajectory(tr["qid"], tr["rollout"], units, tr["outcome"],
                                             derived=tr["derived"], conds=tr["conds"]))
        result = self.collect(objects, credits, groups=[schema.Group("synthetic", objects)])
        self.assertEqual(result["result"]["returned_tokens"], 15)
        self.assertEqual(result["groups"]["count"], 1)
        with self.assertRaises(ValueError):
            self.collect(objects, credits, groups=[[0], [0]])

    def test_extra_ledger_records_are_not_counted_as_model_calls(self):
        trajectories, credits = example()
        credits[0]["role"][3] = "K"
        credits[0]["A"][3] = 1.
        credits[0]["nu"][3] = 0.
        result = self.collect(trajectories, credits)["credit"]
        self.assertEqual(result["role_unit_counts"]["K"], 1)

    def test_unfinished_call_is_excluded_from_tool_call_metric(self):
        trajectories, credits = example()
        trajectories[0]["tool_call_count"] = 1
        result = self.collect(trajectories, credits)
        self.assertEqual(result["result"]["tool_model_calls"], 2)


if __name__ == "__main__":
    unittest.main()
