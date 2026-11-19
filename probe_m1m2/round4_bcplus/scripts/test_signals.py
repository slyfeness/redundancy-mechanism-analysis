import unittest

from signals import add_progress, outcomes, peer_weights, stage_advantages


def stage(key, *, z=0.0, budget=1.0, gain=0, idle=0.0, tokens=10):
    return {"event_key": key, "z_before_any": z, "b_before": budget, "c_new_any": gain,
            "idle": idle, "generated_tokens": tokens}


class SignalTests(unittest.TestCase):
    def test_all_wrong_can_have_outcome_signal_from_submission_penalty(self):
        group = [{"correct": False, "submitted": i < 4} for i in range(8)]
        rho, values = outcomes(group)
        self.assertEqual(rho, 0)
        self.assertAlmostEqual(values[0], 1/3)
        self.assertAlmostEqual(values[-1], -1/3)
        group[0]["correct"] = None
        self.assertIsNone(outcomes(group))

    def test_one_peer_per_trajectory_and_strict_threshold(self):
        target = stage("source")
        peers = peer_weights(target, [[stage("weak", z=.3), stage("best", z=.1)],
                                      [stage("at_cutoff", z=.5)], [stage("another", budget=.75)]], "z_before_any")
        self.assertEqual([row["event_key"] for _, row in peers], ["best", "another"])

    def test_gated_idle_vanishes_and_ungated_gives_negative_advantage(self):
        traces = [[stage("repeat", idle=2)], [stage("control")]]
        gated = stage_advantages(traces, [0, 0], 0, "any", False)
        ungated = stage_advantages(traces, [0, 0], 0, "any", True)
        self.assertEqual(gated["repeat"]["A"], 0)
        self.assertAlmostEqual(ungated["repeat"]["A"], -.12)

    def test_first_path_is_token_centered(self):
        traces = [[stage("gain", gain=2, tokens=30), stage("idle", idle=2, tokens=10)]]
        result = stage_advantages(traces, [1], .5, "any", False)
        self.assertAlmostEqual(result["gain"]["A_re"] * 30 + result["idle"]["A_re"] * 10, 40)

    def test_open_only_and_parallel_history(self):
        stages = [
            {"round": 1, "docids": ["d"], "return_parsed": True, "tool": "search", "observation_visible": True},
            {"round": 1, "docids": ["d", "g"], "return_parsed": True, "tool": "search", "observation_visible": True},
            {"round": 2, "docids": ["d"], "return_parsed": True, "tool": "open", "observation_visible": False},
        ]
        self.assertEqual(add_progress(stages, {"d", "e"}, {"g"}), {"any": 2, "open": 1})
        self.assertEqual([s["c_new_any"] for s in stages], [1, 1, 0])
        self.assertEqual([s["c_new_open"] for s in stages], [0, 0, 1])
        self.assertEqual([s["z_before_any"] for s in stages], [0, 0, 1])


if __name__ == "__main__":
    unittest.main()
