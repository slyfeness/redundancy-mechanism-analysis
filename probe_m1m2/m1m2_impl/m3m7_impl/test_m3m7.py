import unittest
from dataclasses import replace

import torch
from ledger_grpo.ledgercredit.m3m7 import (Config, assign, exact_repeats, map_scores, redistribute)
from ledger_grpo.hf_native import prepare_native_records


def unit(tid, uid=1, *, cost=3146, win=0, credit=0, repeat=False, kind="stage", submitted=True):
    return {"trajectory_id": tid, "query_id": "x", "unit_id": uid, "unit_type": kind,
            "gen_start": 0 if uid == 1 else 3, "gen_end": 2 if uid == 1 else 4,
            "n_gen": 2 if uid == 1 else 1, "n_ret": cost - (2 if uid == 1 else 1),
            "C_new": credit, "R": win, "submitted": submitted, "I_N": int(repeat),
            "z_pre": 0., "b_pre": 1. if uid == 1 else .95}


class FormulaTest(unittest.TestCase):
    def test_hand_computation(self):
        for actual, expected in zip(redistribute(1., [.5, .5, -.1, 0], [1]*4, .3),
                                    [1.0825, 1.0825, .9025, .9325]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(1.0825 + Config().omega * .3, 1.1725)

    def test_leave_one_and_only_success(self):
        rows = [unit(str(i), win=1, cost=3146*c) for i, c in enumerate((10,14,22))]
        _, tracks = assign(rows, Config())
        self.assertEqual([tracks[str(i)]["B"] for i in range(3)], [14,10,10])
        _, tracks = assign([unit("won", win=1), unit("lost")], Config())
        self.assertIsNone(tracks["won"]["B"])
        self.assertEqual(tracks["won"]["reward"], 1.)

    def test_all_wrong_kappa_and_unique_peers(self):
        rows = [unit("A", repeat=True), unit("B", credit=1), unit("B", 2, credit=2), unit("C", credit=1)]
        values, _ = assign(rows, Config())
        self.assertEqual(values[0]["u"], 0.)
        self.assertEqual(values[0]["peers"], [("B",1), ("C",1)])
        self.assertEqual(values[0]["A_st"], -1.)
        self.assertEqual(assign(rows, replace(Config(),kappa=.3))[0][0]["u"], -.3)

    def test_weighted_conservation_and_sign(self):
        rows = [unit("A",win=1,credit=2),unit("A",2,win=1,kind="final"),
                unit("B",repeat=True),unit("B",2,credit=2),unit("C")]
        result, meta = assign(rows, Config())
        for tid, row in meta.items():
            selected = [r for r in result if r["trajectory_id"] == tid]
            self.assertLess(abs(sum(r["A_re"]*r["n_gen"] for r in selected)/sum(r["n_gen"] for r in selected)-row["A_out"]),1e-9)
            self.assertTrue(all(r["A_re"]*row["A_out"] > 0 for r in selected if row["A_out"]))

    def test_strict_repeat_only_visible_prior_and_parallel_prefix(self):
        def event(query, returned, fed=True):
            return {"tool":"search","args_raw":{"query":query},"return_text":returned,"fed_to_model":fed}
        stages = [[event("A","x",False), event("B","y"),event("B","y")],
                  [event("A","x"),event("B","Y")],
                  [event("B","y"),event("b","y")]]
        self.assertEqual(exact_repeats(stages), [[],[],[0]])

    def test_actual_token_mapping_and_outcome_only_equivalence(self):
        segments = [{"prompt_ids":[1,2],"completion_ids":[3,4],"vllm_logprobs":[-.2,-.3]},
                    {"prompt_ids":[1,2,3,4,8],"completion_ids":[5],"vllm_logprobs":[-.2]}]
        traces = [{"id":tid,"query_id":"x","segments":segments} for tid in ("A","B")]
        rows = [unit(tid,i,win=int(tid=="A"),credit=2) for tid in ("A","B") for i in (1,2)]
        cfg = replace(Config(), eta=0., omega=0., beta_c=0.)
        score = map_scores(traces, assign(rows,cfg)[0], cfg)
        want = torch.tensor([[1,1,0,1],[-1,-1,0,-1]], dtype=torch.float32)
        self.assertTrue(torch.equal(score["advantages"],want))
        self.assertTrue(torch.equal(score["effective_response_mask"], want!=0))
        prepared = prepare_native_records(traces,score)
        self.assertEqual(prepared["global_token_count"],sum(r["n_gen"] for r in rows))
        self.assertEqual(prepared["records"][0]["action_offsets"],[0,1,3])
