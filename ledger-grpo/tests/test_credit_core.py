"""Synthetic, dataset-free tests of the v2.1 credit contract."""
import importlib
import math
import random
import unittest
from collections import Counter


def record(key="E1", strength="直接", about="object-a", adopted=True):
    return {"query": "synthetic query", "targets": [{"object": about}],
            "evidence": [{"key": key, "about": about, "strength": strength,
                          "conditions": [{"id": "A", "effect": "支持"}]}],
            "verdicts": {key: "采纳"} if adopted else {}}


def trajectory(success=True):
    return {"qid": "synthetic", "rollout": 0, "records": [record(), {}],
            "derived": [{}, {"labels": ["原地打转"]}], "conds": ["A", "c1"],
            "outcome": {"Y": success, "submitted": True},
            "tokens": {1: 10, 2: 10, "F": 10}}


class CreditCoreTests(unittest.TestCase):
    def module(self, name):
        try:
            return importlib.import_module("ledger_grpo.credit." + name)
        except ModuleNotFoundError as exc:
            self.fail("Missing credit implementation: " + str(exc))

    def test_config_defaults_presets_and_reward_order_validation(self):
        config = self.module("config")
        expected = {"A": ("outcome", "none"), "A_eff": ("outcome_eff", "none"),
                    "B": ("progress", "none"), "B_W": ("progress_waste", "none"),
                    "C": ("progress", "transfer"), "C_W": ("progress_waste", "transfer"),
                    "C_uniform": ("progress_waste", "transfer_uniform"),
                    "clear_only": ("progress_waste", "clear_only"),
                    "D": ("progress_waste", "shuffled")}
        for name, pair in expected.items():
            cfg = config.CreditConfig.from_preset(name)
            self.assertEqual((cfg.utility, cfg.step_credit), pair)
        for kwargs in ({"g": .4}, {"w_max": .9}, {"H": 0},
                       {"utility": "missing"}, {"step_credit": "missing"},
                       {"ledger_sample_q": 0}):
            with self.assertRaises(ValueError):
                config.CreditConfig(**kwargs)
        self.assertEqual(config.CreditConfig().to_params()["kappa"], 3.)

    def test_closed_form_event_weighted_stage_mass(self):
        C = self.module("allocate")
        nu = {1: .2, 2: .3, 3: .3, "F": .2}
        role = {1: "C", 2: "R", 3: "C", "F": "F"}
        e = {1: .1, 2: .05, 3: .3, "F": 0}
        A, log = C.allocate(list(nu), nu, 1., role, e)
        self.assertAlmostEqual(A[1], 1.)
        self.assertEqual(A[2], 0.)
        self.assertAlmostEqual(A[3], 2.)
        self.assertEqual(A["F"], 1.)
        self.assertEqual(log["mode"], "transfer")

    def test_infeasible_drop_abstain_partial(self):
        C, config = self.module("allocate"), self.module("config")
        nu = {1: .05, 2: .75, "F": .2}
        role, e = {1: "C", 2: "R", "F": "F"}, {1: .1, 2: .05, "F": 0}
        wants = {"drop": (3., 0., .65), "abstain": (1., 1., 0.),
                 "partial": (3., .65 / .75, 0.)}
        for mode, want in wants.items():
            A, log = C.allocate(list(nu), nu, 1., role, e,
                                dict(config.PARAMS, infeasible=mode))
            self.assertTrue(log["infeasible"])
            self.assertAlmostEqual(A[1], want[0])
            self.assertAlmostEqual(A[2], want[1])
            self.assertAlmostEqual(log["dropped"], want[2])
            self.assertEqual(A["F"], 1.)

    def test_random_allocation_properties_10000_combinations(self):
        C = self.module("allocate")
        rng = random.Random(20261125)
        for _ in range(10000):
            units = list(range(1, rng.randint(2, 20) + 1)) + ["F"]
            raw = [rng.randint(1, 300) for _ in units]
            nu = dict(zip(units, (n / sum(raw) for n in raw)))
            role = {u: rng.choice(["C", "R", "K"]) for u in units}
            role[1], role[2], role["F"] = "C", "R", "F"
            e = {u: rng.random() + .001 if role[u] in ("C", "R") else 0. for u in units}
            a = rng.choice([-1., 0., 1.]) * rng.random()
            A, log = C.allocate(units, nu, a, role, e)
            if not log["infeasible"]:
                self.assertLessEqual(abs(sum(nu[u] * A[u] for u in units) - a), 1e-9)
            for u in units:
                self.assertLessEqual(abs(A[u]), 3 * abs(a) + 1e-9)
                if role[u] in ("F", "K"):
                    self.assertEqual(A[u], a)
                if (a > 0 and role[u] == "R") or (a < 0 and role[u] == "C"):
                    self.assertEqual(A[u], 0.)
                if a == 0:
                    self.assertEqual(A[u], 0.)

    def test_allocation_boundary_has_no_receiver(self):
        C = self.module("allocate")
        A, log = C.allocate([1, "F"], {1: .8, "F": .2}, 1.,
                            {1: "R", "F": "F"}, {1: 1., "F": 0.})
        self.assertEqual(A, {1: 0., "F": 1.})
        self.assertTrue(log["no_receiver"])
        self.assertEqual(log["mode"], "drop")

    def test_loo_hand_values_and_degenerate_groups(self):
        U = self.module("utility")
        self.assertEqual(U.loo_advantages([1., 2., 3.]), [-1.5, 0., 1.5])
        self.assertEqual(U.loo_advantages([4.]), [0.])
        self.assertEqual(U.loo_advantages([2.] * 8), [0.] * 8)
        self.assertEqual(U.token_shares([1, "F"], {1: 3, "F": 1}), {1: .75, "F": .25})
        self.assertEqual(U.token_shares([1, "F"], {}), {1: .5, "F": .5})

    def test_progress_never_splices_candidates_and_revival_is_preserved(self):
        U = self.module("utility")
        ds = [{"chain": {"answer": "object-a"}, "view": {"A": ["✔", None, True]}},
              {"chain": {"answer": "object-b"}, "view": {"c1": ["✔", None, True]}},
              {"excluded_now": [{"object": "object-a"}], "chain": {"answer": "object-c"}},
              {"excluded_now": [{"object": "object-b"}]},
              {"chain": {"answer": "object-a"}}]
        self.assertEqual(U.best_candidate_progress(ds, ["A", "c1"]), [.5, .5, .5, 0., .5])

    def test_four_utility_values_are_hand_calculated(self):
        U = self.module("utility")
        config = self.module("config")
        wants = {"outcome": 1., "outcome_eff": .95, "progress": 1.225,
                 "progress_waste": 1.175}
        for mode, want in wants.items():
            val, _ = U.utility_reward([{}], [{}], ["A"],
                                      {"Y": True, "submitted": True}, .05,
                                      config.CreditConfig(H=4, utility=mode))
            self.assertAlmostEqual(val, want, places=14)

    def test_reward_outcome_order_on_random_progress(self):
        U, config = self.module("utility"), self.module("config")
        rng = random.Random(71)
        for mode in ("outcome", "outcome_eff", "progress", "progress_waste"):
            cfg = config.CreditConfig(utility=mode)
            rewards = {"correct": [], "wrong": [], "none": []}
            for _ in range(100):
                T = rng.randint(0, cfg.H)
                ds = [{"chain": {"answer": "object-a"},
                       "view": {"A": ["✔", None, rng.choice([True, False])]}}
                      for _ in range(T)]
                for label, y, submitted in (("correct", True, True), ("wrong", False, True), ("none", False, False)):
                    value, _ = U.utility_reward([{}] * T, ds, ["A"],
                                                {"Y": y, "submitted": submitted}, rng.random(), cfg)
                    rewards[label].append(value)
            self.assertGreater(min(rewards["correct"]), max(rewards["wrong"]))
            self.assertGreater(min(rewards["wrong"]), max(rewards["none"]))

    def test_event_processing_index_and_no_final_fallback(self):
        E = self.module("events")
        for final, expected in ((True, "F"), (False, 2)):
            _, P, _, _ = E.extract_events([{}, record()], [{}, {}], ["A"], {}, final)
            self.assertIn((.125, "采纳E1"), P[expected])
            self.assertIn((.125, "取到E1"), P[2])
        _, P, _, _ = E.extract_events([record(), {}], [{}, {}], ["A"], {}, True)
        self.assertIn((.125, "采纳E1"), P[2])

    def test_condition_budget_uses_only_strength_increments(self):
        E = self.module("events")
        rs = [record("E1", "推断"), record("E2", "直接", "object-b"),
              record("E3", "直接", "object-c")]
        _, P, _, _ = E.extract_events(rs, [{}, {}, {}], ["A"], {}, True)
        self.assertAlmostEqual(sum(m for evs in P.values() for m, _ in evs), .25)
        self.assertNotIn("F", P)

    def test_late_adoption_prevents_omission_and_hindsight_waste(self):
        E = self.module("events")
        rs = [record(adopted=False), {"earlier_adopted": ["E1"]}]
        _, P, R, _ = E.extract_events(rs, [{"missed": ["E1"], "labels": ["原地打转"]}, {}], ["A"], {}, True)
        self.assertIn((.125, "采纳E1(迟)"), P["F"])
        self.assertFalse(any(tag.startswith(("没用", "浪费")) for evs in R.values() for _, tag in evs))

    def test_repeated_omission_geometric_budget(self):
        C = self.module("config")
        gamma = C.PARAMS["gamma_o"]
        self.assertAlmostEqual(sum((1 - gamma) * gamma ** j for j in range(200)), 1.)

    def test_role_mixed_waste_discount_protected_final_and_gate(self):
        C, config = self.module("roles"), self.module("config")
        units = [1, 2, 3, 4, "F"]
        P = {1: [(1., "采纳E1")], 2: [(1., "采纳E2")]}
        R = {1: [(1., "浪费:原地打转")], 2: [(1., "没用E3")],
             3: [(2., "浪费:原地打转")], 4: [(1., "无效排除object-a")]}
        role, e = C.assign_roles(units, P, R, False)
        self.assertEqual(role, {1: "C", 2: "K", 3: "R", 4: "R", "F": "F"})
        self.assertEqual(e[3], .2)
        role, _ = C.assign_roles(units, P, R, False, {1: False}, dict(config.PARAMS, gate_low_conf=True))
        self.assertEqual(role[1], "K")

    def test_clear_only_and_uniform_allocations(self):
        C = self.module("allocate")
        nu = {1: .2, 2: .3, 3: .3, "F": .2}
        role, e = {1: "C", 2: "R", 3: "C", "F": "F"}, {1: .1, 2: .05, 3: .3, "F": 0}
        A, log = C.allocate_mode(list(nu), nu, 1., role, e, step_credit="clear_only")
        self.assertEqual(A, {1: 1., 2: 0., 3: 1., "F": 1.})
        self.assertAlmostEqual(log["dropped"], .3)
        A, _ = C.allocate_mode(list(nu), nu, 1., role, e, step_credit="transfer_uniform")
        self.assertAlmostEqual(A[1] * .2, .4)
        self.assertAlmostEqual(A[3] * .3, .4)
        with self.assertRaises(NotImplementedError):
            C.allocate_mode(list(nu), nu, 1., role, e, step_credit="draco")

    def test_group_presets_and_low_confidence_gate(self):
        G, config = self.module("group"), self.module("config")
        ts = [trajectory(True), trajectory(False)]
        for preset in config.PRESETS:
            out = G.credit_for_group(ts, config.CreditConfig.from_preset(preset))
            self.assertEqual(len(out), 2)
            self.assertTrue(all(math.isfinite(a) for x in out for a in x["A"].values()))
            self.assertTrue(all(x["A"]["F"] == x["A_hat"] for x in out))
        out = G.credit_for_group(ts, config.CreditConfig(gate_low_conf=True), confident=[{1: False}, {1: False}])
        self.assertTrue(all(x["role"][1] == "K" for x in out))

    def test_group_empty_ledger_and_unmatched_units_keep_base_advantage(self):
        G = self.module("group")
        ts = [{"records": [], "derived": [], "conds": [], "outcome": {"Y": y, "submitted": True},
               "tokens": {1: 5, "F": 3}} for y in (True, False)]
        out = G.credit_for_group(ts)
        self.assertTrue(all(x["role"][1] == "K" and x["A"][1] == x["A_hat"] for x in out))
        ts = [dict(trajectory(y), unmatched_units=[1, 2]) for y in (True, False)]
        out = G.credit_for_group(ts)
        self.assertTrue(all(x["role"][1] == "K" and x["role"][2] == "K" for x in out))

    def test_shuffling_preserves_pairs_final_and_determinism(self):
        C = self.module("allocate")
        units = list(range(1, 19)) + ["F"]
        role = {u: ("C", "R", "K")[(u - 1) % 3] for u in units[:-1]}
        role["F"] = "F"
        e = {u: float(u) / 10 if role[u] != "K" else 0. for u in units[:-1]}
        e["F"] = 0.
        tokens = {u: 10 for u in units}
        kwargs = dict(training_step=42, qid="synthetic", rollout=3, unit_types={u: "search" for u in units})
        first = C.shuffle_roles(units, role, e, tokens, **kwargs)
        self.assertEqual(first, C.shuffle_roles(units, role, e, tokens, **kwargs))
        roles, weights, log = first
        self.assertEqual(Counter((role[u], e[u]) for u in units), Counter((roles[u], weights[u]) for u in units))
        self.assertEqual((roles["F"], weights["F"]), ("F", 0.))
        self.assertTrue(all(0 <= x <= 1 for x in log["shuffle_ks"].values()))
        for stratum in (list(range(1, 7)), list(range(7, 13)), list(range(13, 19))):
            self.assertEqual(Counter((role[u], e[u]) for u in stratum), Counter((roles[u], weights[u]) for u in stratum))

    def test_reference_closed_form_verbatim(self):
        self.assertTrue(callable(globals().get("test_allocation_closed_form")), "Reference closed-form test must be copied verbatim")
        globals()["test_allocation_closed_form"]()

    def test_shuffle_singletons_relax_position_then_length_then_type(self):
        C = self.module("allocate")
        for lengths, types, cuts, expected_level in (
            ([10, 10, 10], ["search"] * 3, (10, 10), 1),
            ([1, 2, 3, 4], ["search"] * 4, (1.5, 3.5), 2),
            ([10, 10, 10], ["a", "a", "b"], (10, 10), 3),
        ):
            units = list(range(1, len(lengths) + 1))
            role = {u: "C" if u == 1 else "K" for u in units}
            e = {u: 1. if u == 1 else 0. for u in units}
            _, _, log = C.shuffle_roles(units, role, e, dict(zip(units, lengths)),
                                         unit_types=dict(zip(units, types)), length_cutpoints=cuts)
            self.assertEqual(set(log["shuffle_relaxation"].values()), {expected_level})
            self.assertEqual(sorted(log["shuffle_strata"][0]), units)

    def test_empty_ledger_efficiency_counts_model_calls(self):
        G, config = self.module("group"), self.module("config")
        tr = {"records": [], "derived": [], "conds": [], "outcome": {"Y": True, "submitted": True},
              "tokens": {1: 5, 2: 3, "F": 2}}
        out = G.credit_for_group([tr], config.CreditConfig.from_preset("A_eff"))
        self.assertAlmostEqual(out[0]["U"], .98)

    def test_efficiency_uses_explicit_count_excluding_unfinished_calls(self):
        G, config = self.module("group"), self.module("config")
        tr = {"records": [], "derived": [], "conds": [], "outcome": {"Y": True, "submitted": True},
              "tokens": {1: 5, "F": 2}, "tool_call_count": 0}
        out = G.credit_for_group([tr], config.CreditConfig.from_preset("A_eff"))
        self.assertEqual(out[0]["U"], 1.)

    def test_group_accepts_explicit_batch_tertiles_and_keeps_unmatched_k(self):
        G, config = self.module("group"), self.module("config")
        ts = [dict(trajectory(y), unmatched_units=[1, 2]) for y in (True, False)]
        out = G.credit_for_group(ts, config.CreditConfig.from_preset("D"), length_cutpoints=(2, 30))
        for x in out:
            self.assertEqual(x["log"]["length_cutpoints"], (2, 30))
            self.assertEqual(x["role"], {1: "K", 2: "K", "F": "F"})

    def test_waste_is_charged_once_and_gold_string_hit_is_diagnostic(self):
        E = self.module("events")
        _, P, R, D = E.extract_events([{}], [{"labels": ["重复核实", "原地打转", "严格重复"],
                                             "missed_gold": ["返回:synthetic"]}], ["A"], {}, True)
        self.assertEqual(len(R[1]), 1)
        self.assertEqual(R[1][0][0], .05)
        self.assertEqual(D[1], ["（诊断）返回原文出现正确答案字符串"])
        self.assertFalse(any(P.values()))


C = importlib.import_module("ledger_grpo.credit.allocate")

def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_allocation_closed_form():
    p = dict(C.PARAMS, kappa=3.0, infeasible="drop")
    units = [1, 2, 3, "F"]
    nu = {1: 0.2, 2: 0.3, 3: 0.3, "F": 0.2}
    role = {1: "C", 2: "R", 3: "C", "F": "F"}
    e = {1: 0.1, 2: 0.05, 3: 0.3, "F": 0.0}
    A, log = C.allocate(units, nu, 1.0, role, e, p)
    # movable budget = 1.0 * (0.2+0.3+0.3) = 0.8, receivers 1 and 3 by event size 0.1 : 0.3
    check(abs(A["F"] - 1.0) < 1e-12, "final unit keeps the trajectory advantage")
    check(A[2] == 0.0, "responsible unit gives up positive credit")
    check(abs(0.2 * A[1] - 0.2) < 1e-9 and abs(0.3 * A[3] - 0.6) < 1e-9, f"stage totals follow event sizes: {A}")
    check(abs(sum(nu[u] * A[u] for u in units) - 1.0) < 1e-9, "conservation")
    A, log = C.allocate(units, nu, 0.0, role, e, p)
    check(all(v == 0.0 for v in A.values()), "zero advantage stays zero")
    # infeasible: receivers hold few tokens
    nu2 = {1: 0.05, 2: 0.75, 3: 0.0, "F": 0.2}
    A, log = C.allocate([1, 2, "F"], nu2, 1.0, {1: "C", 2: "R", "F": "F"}, {1: 0.1, 2: 0.05, "F": 0}, p)
    check(log["infeasible"] and abs(A[1] - 3.0) < 1e-9 and A[2] == 0.0 and log["dropped"] > 0, f"infeasible drop: {A} {log}")
    A, log = C.allocate([1, 2, "F"], nu2, 1.0, {1: "C", 2: "R", "F": "F"}, {1: 0.1, 2: 0.05, "F": 0}, dict(p, infeasible="abstain"))
    check(all(abs(v - 1.0) < 1e-12 for v in A.values()), "infeasible abstain keeps the base advantage")


if __name__ == "__main__":
    unittest.main()
