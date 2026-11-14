"""Behavioral tests for provenance, temporal visibility and process eligibility."""
import copy
import importlib
import unittest


def fixture():
    return {
        "traj_id": "trace-1", "task_id": "q1", "task": "Find Ada's year of joining.",
        "constraints": [{"cid": "c1", "text": "Joining year", "required": True}],
        "outcome": 1, "complete": True, "submitted_candidate": "ada",
        "response_mask": [1, 1, 0, 0, 1, 1, 0, 0, 1, 1],
        "turns": [
            {"turn_id": 1, "token_start": 0, "token_end": 4,
             "action": {"kind": "search", "target_id": "c1", "query": "Ada joining year"},
             "observations": [{"evidence_id": "e1", "document_id": "d1", "source_id": "archive",
                               "text": "Ada joined in 1994.", "representation": "fulltext"}]},
            {"turn_id": 3, "token_start": 4, "token_end": 8,
             "action": {"kind": "search", "target_id": "c1", "query": "Ada joining year"},
             "observations": [{"evidence_id": "e2", "document_id": "d1", "source_id": "archive",
                               "text": "Ada joined in 1994.", "representation": "fulltext"}]},
            {"turn_id": 7, "token_start": 8, "token_end": 10,
             "action": {"kind": "submit"}, "observations": []}
        ]
    }


class PipelineTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("ledger_grpo.pipeline")
        except ImportError as exc:
            self.fail(f"trajectory pipeline is not implemented: {exc}")

    def test_repeated_attempt_marks_only_current_policy_tokens(self):
        p = self.api()
        report = p.analyze_trajectory(fixture(), deltas={1: {"facts": []}, 3: {"facts": []}, 7: {"facts": []}})
        self.assertTrue(report["qa"]["parse_ok"])
        spans = [s for s in report["spans"] if s["label"] == "R2" and not s["abstain"]]
        self.assertEqual([s["turns"] for s in spans], [[3]])
        inputs = p.build_process_inputs(fixture(), report)
        self.assertEqual(inputs["redundancy"], [0, 0, 0, 0, 1, 1, 0, 0, 0, 0])
        self.assertAlmostEqual(inputs["redundant_fraction"], 1 / 3)

    def test_candidate_change_protects_a_repeated_query_on_the_same_requirement(self):
        p = self.api()
        trace = fixture()
        trace['turns'][0]['action']['candidate_id'] = 'ada'
        trace['turns'][1]['action']['candidate_id'] = 'eve'
        report = p.analyze_trajectory(trace, deltas={i: {'facts': []} for i in (1, 3, 7)})
        self.assertFalse(any(s['label'] == 'R2' and s['reward_eligible'] for s in report['spans']))

    def test_valid_citations_support_grounding_but_source_text_does_not_set_outcome(self):
        p = self.api()
        trace = fixture()
        fact = {"fid": "f1", "cid": "c1", "candidate_id": "ada", "statement": "Joined in 1994",
                "state": "supported", "evidence": [{"evidence_id": "e1", "quote": "Ada joined in 1994."}]}
        report = p.analyze_trajectory(trace, deltas={1: {"facts": [fact]}, 3: {"facts": []}, 7: {"facts": []}})
        self.assertEqual(report["metrics"]["grounding_score"], 1.0)
        self.assertEqual(report["ledger"]["facts"][0]["first_supported_turn"], 1)
        self.assertEqual(trace, fixture())

    def test_forged_quote_disables_process_without_overwriting_outcome(self):
        p = self.api()
        fact = {"fid": "f1", "cid": "c1", "candidate_id": "ada", "statement": "Joined in 2001",
                "state": "supported", "evidence": [{"evidence_id": "e1", "quote": "Joined in 2001"}]}
        trace = fixture()
        report = p.analyze_trajectory(trace, deltas={1: {"facts": [fact]}})
        self.assertFalse(report["qa"]["citations_verified"])
        self.assertFalse(p.build_process_inputs(trace, report)["process_valid"])
        self.assertEqual(trace["outcome"], 1)

    def test_future_citation_is_rejected_even_if_text_matches(self):
        p = self.api()
        fact = {"fid": "f1", "cid": "c1", "candidate_id": "ada", "statement": "Joined in 1994",
                "state": "supported", "evidence": [{"evidence_id": "e2", "quote": "Ada joined in 1994."}]}
        report = p.analyze_trajectory(fixture(), deltas={1: {"facts": [fact]}})
        self.assertFalse(report["qa"]["citations_verified"])
        self.assertEqual(report["ledger"]["facts"], [])

    def test_missing_delta_is_unknown_and_not_a_zero_gain_claim(self):
        p = self.api()
        report = p.analyze_trajectory(fixture())
        self.assertFalse(p.build_process_inputs(fixture(), report)["process_valid"])
        self.assertFalse(any(s["reward_eligible"] for s in report["spans"]))

    def test_later_extraction_failure_preserves_prefix_event_receipt(self):
        report = self.api().analyze_trajectory(fixture(), deltas={1: {'facts': []}, 3: {'facts': []}})
        span = next(s for s in report['spans'] if s['label'] == 'R2')
        self.assertEqual(span['known_at'],3)
        self.assertTrue(span['prefix_reward_eligible'])
        self.assertFalse(span['reward_eligible'])

    def test_duplicate_span_does_not_double_charge(self):
        p = self.api()
        trace = fixture()
        report = p.analyze_trajectory(trace, deltas={i: {"facts": []} for i in (1, 3, 7)})
        span = next(s for s in report["spans"] if s["label"] == "R2")
        report["spans"].append(copy.deepcopy(span))
        self.assertAlmostEqual(p.build_process_inputs(trace, report)["redundant_fraction"], 1 / 3)

    def test_privileged_data_cannot_flow_to_ledger_extractor(self):
        p = self.api()
        trace = fixture()
        trace["privileged"] = {"answer": "SECRET_ANSWER", "gold_evidence": "SECRET_EVIDENCE"}

        class Extractor:
            def extract(self, payload):
                text = str(payload)
                if "SECRET_" in text or "outcome" in payload:
                    raise AssertionError("privileged information leaked to redundancy ledger")
                return {"facts": []}

        report = p.analyze_trajectory(trace, judge=Extractor())
        self.assertTrue(report["qa"]["parse_ok"])

    def test_invalid_token_mapping_fails_closed(self):
        p = self.api()
        trace = fixture()
        trace["turns"][1]["token_start"] = 2
        with self.assertRaises(ValueError):
            p.analyze_trajectory(trace)

    def test_batch_honors_configured_d4_weight(self):
        from ledger_grpo.advantages import AdvantageConfig
        p = self.api()
        trace = fixture()
        report = p.analyze_trajectory(trace, deltas={i: {"facts": []} for i in (1, 3, 7)})
        report["spans"].append({"turns": [7], "label": "D4", "confidence": .5,
                                "abstain": False, "reward_eligible": True,
                                "evidence_refs": ["turn:7"]})
        config = AdvantageConfig(process_enabled=True, deviation_weights={"D1": .1, "D2": .15, "D3": .1, "D4": .04})
        result = p.score_batch([trace], [report], config=config, enable_artifact_d4=True)
        self.assertEqual(result["process_inputs"][0]["deviations"][-2:], [.02, .02])
        self.assertEqual(result["config"]["deviation_weights"]["D4"], .04)

    def test_d4_weight_must_be_finite_and_nonnegative(self):
        p = self.api()
        trace = fixture()
        report = p.analyze_trajectory(trace, deltas={i: {"facts": []} for i in (1, 3, 7)})
        for weight in (-1, float("nan"), float("inf"), True):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                p.build_process_inputs(trace, report, d4_weight=weight)

    def test_batch_records_defaults_and_exposes_safe_loss_mask(self):
        p = self.api()
        traces = [fixture(), fixture()]
        traces[1].update(traj_id="failed", task_id="q2", outcome=0)
        reports = [p.analyze_trajectory(t, deltas={i: {"facts": []} for i in (1, 3, 7)}) for t in traces]
        result = p.score_batch(traces, reports)
        self.assertEqual(result["config"]["process_enabled"], False)
        self.assertEqual(result["effective_response_mask"][0].tolist(), [bool(x) for x in traces[0]["response_mask"]])
        self.assertFalse(bool(result["effective_response_mask"][1].any()))

    def test_batch_rejects_duplicate_trajectory_identifiers(self):
        p = self.api()
        trace = fixture()
        report = p.analyze_trajectory(trace, deltas={i: {"facts": []} for i in (1, 3, 7)})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            p.score_batch([trace, copy.deepcopy(trace)], [report, copy.deepcopy(report)])

    def test_batch_rejects_missing_scoring_columns(self):
        p = self.api()
        trace = fixture()
        report = p.analyze_trajectory(trace, deltas={i: {"facts": []} for i in (1, 3, 7)})
        for key in ("outcome", "response_mask", "traj_id", "task_id"):
            damaged = copy.deepcopy(trace)
            del damaged[key]
            with self.subTest(trace_key=key), self.assertRaises(ValueError):
                p.score_batch([damaged], [report])
        for key in ("ledger", "spans", "qa", "trace_digest", "traj_id", "task_id"):
            damaged = copy.deepcopy(report)
            del damaged[key]
            with self.subTest(report_key=key), self.assertRaises(ValueError):
                p.score_batch([trace], [damaged])


if __name__ == "__main__":
    unittest.main()
