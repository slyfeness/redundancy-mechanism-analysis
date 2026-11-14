"""Behavior tests for conservative, evidence-aware rule decisions."""

import copy
import unittest

from ledger_grpo.rules import RuleConfig, decision_summary, evaluate_turn


def fixture():
    prior = {
        "turn_id": 2,
        "action": {"kind": "search", "query": "alpha university", "target_id": "c1", "method": "web"},
        "observations": [{"evidence_id": "e2", "document_id": "d1", "source_id": "s1", "text": "Alpha joined in 1994.", "version": "1", "representation": "fulltext"}],
    }
    current = copy.deepcopy(prior)
    current["turn_id"] = 7
    current["observations"][0]["evidence_id"] = "e7"
    trace = {
        "traj_id": "t", "task_id": "q", "task": "Find Alpha's university.",
        "constraints": [{"cid": "c1", "text": "Find university", "required": True, "kind": "evidence"}],
        "turns": [prior, current], "submitted_candidate": None, "complete": False,
        "response_mask": [1, 1, 0, 1], "budget_tokens": None,
    }
    before = {
        "constraints": copy.deepcopy(trace["constraints"]), "facts": [],
        "attempts": [{"turn": 2, "kind": "search", "target_id": "c1", "query": "alpha university", "method": "web", "document_keys": ["s1:d1:1:fulltext"], "gain": False}],
        "decisions": [], "artifacts": {}, "seen_documents": ["s1:d1:1:fulltext"],
        "seen_evidence": ["e2"], "revision": 0, "last_gain_turn": None,
    }
    after = copy.deepcopy(before)
    attempt = copy.deepcopy(before["attempts"][0])
    attempt["turn"] = 7
    after["attempts"].append(attempt)
    after["seen_evidence"].append("e7")
    return trace, current, before, after


def supported(before, after):
    fact = {"fid": "f1", "cid": "c1", "candidate_id": "a", "statement": "Alpha joined in 1994.", "state": "supported", "evidence": [{"evidence_id": "e2", "quote": "Alpha joined in 1994."}], "first_supported_turn": 2}
    before["facts"] = [copy.deepcopy(fact)]
    after["facts"] = [copy.deepcopy(fact)]


def label(spans, name):
    return next((span for span in spans if span["label"] == name), None)


class LocalJudge:
    """The only substitute is the explicitly external semantic boundary."""

    def __init__(self, verdict="yes", refs=None):
        self.verdict = verdict
        self.refs = ["e2", "e7"] if refs is None else refs

    def check(self, kind, payload):
        if kind != "R1" or payload["fact"]["fid"] != "f1":
            raise AssertionError("Unexpected semantic question")
        return {"verdict": self.verdict, "evidence_refs": self.refs, "rationale": "Same supported relation is checked again."}


class RepeatAttemptTests(unittest.TestCase):
    def test_repeat_known_return_without_gain_is_r2(self):
        trace, turn, before, after = fixture()
        span = label(evaluate_turn(trace, turn, before, after), "R2")
        self.assertIsNotNone(span)
        self.assertEqual(span["turns"], [7])
        self.assertTrue(span["reward_eligible"])
        self.assertFalse(span["abstain"])

    def test_first_attempt_is_exempt(self):
        trace, turn, before, after = fixture()
        before["attempts"] = []
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "R2"))

    def test_unknown_gain_or_source_or_empty_results_do_not_trigger(self):
        for change in ("gain", "source", "results", "ids"):
            with self.subTest(change=change):
                trace, turn, before, after = fixture()
                if change == "gain":
                    after["attempts"][-1]["gain"] = None
                elif change == "source":
                    turn["observations"][0]["source_id"] = ""
                elif change == "results":
                    turn["observations"] = []
                else:
                    after["attempts"][-1]["document_keys"] = []
                self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "R2"))

    def test_new_document_new_fact_and_fulltext_upgrade_are_protected(self):
        for change in ("document", "fact", "fulltext"):
            with self.subTest(change=change):
                trace, turn, before, after = fixture()
                if change == "document":
                    after["attempts"][-1]["document_keys"] = ["s1:d2:1:fulltext"]
                elif change == "fact":
                    after["revision"] = 1
                else:
                    trace["turns"][0]["observations"][0]["representation"] = "snippet"
                self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "R2"))

    def test_independent_trial_and_justified_retry_are_protected(self):
        for field, value in (("independent_trial", True), ("retry_justification", "Transient connection failure")):
            trace, turn, before, after = fixture()
            turn["action"][field] = value
            self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "R2"))

    def test_same_tokens_in_different_order_are_not_exact_by_default(self):
        trace, turn, before, after = fixture()
        turn["action"]["query"] = "university alpha"
        after["attempts"][-1]["query"] = "university alpha"
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "R2"))
        config = RuleConfig(query_similarity_threshold=0.9)
        self.assertIsNotNone(label(evaluate_turn(trace, turn, before, after, config=config), "R2"))

    def test_case_and_whitespace_normalization_is_allowed(self):
        trace, turn, before, after = fixture()
        turn["action"]["query"] = "  ALPHA   university "
        self.assertIsNotNone(label(evaluate_turn(trace, turn, before, after), "R2"))

    def test_different_target_method_and_kind_are_not_repeats(self):
        for field, value in (("target_id", "c2"), ("method", "archive"), ("kind", "read")):
            trace, turn, before, after = fixture()
            turn["action"][field] = value
            self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "R2"))


class ReverificationTests(unittest.TestCase):
    def test_r1_requires_local_semantic_confirmation(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        turn["action"]["fact_id"] = "f1"
        diagnostic = label(evaluate_turn(trace, turn, before, after), "R1")
        self.assertIsNotNone(diagnostic)
        self.assertTrue(diagnostic["abstain"])
        self.assertFalse(diagnostic["reward_eligible"])
        confirmed = label(evaluate_turn(trace, turn, before, after, judge=LocalJudge()), "R1")
        self.assertTrue(confirmed["reward_eligible"])
        self.assertEqual(set(confirmed["evidence_refs"]), {"e2", "e7"})

    def test_semantic_no_does_not_become_r1(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        turn["action"]["fact_id"] = "f1"
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after, judge=LocalJudge("no")), "R1"))

    def test_uncertain_missing_or_future_citations_abstain(self):
        for verdict, refs in (("uncertain", ["e2", "e7"]), ("yes", ["e2"]), ("yes", ["e2", "e7", "e_future"])):
            trace, turn, before, after = fixture()
            supported(before, after)
            turn["action"]["fact_id"] = "f1"
            span = label(evaluate_turn(trace, turn, before, after, judge=LocalJudge(verdict, refs)), "R1")
            self.assertIsNotNone(span)
            self.assertTrue(span["abstain"])
            self.assertEqual(span["confidence"], 0.0)
            self.assertFalse(span["reward_eligible"])

    def test_refuted_fact_or_unknown_prior_source_does_not_trigger_r1(self):
        for change in ("refuted", "source", "independence"):
            trace, turn, before, after = fixture()
            supported(before, after)
            turn["action"]["fact_id"] = "f1"
            if change == "refuted":
                after["facts"][0]["state"] = "refuted"
            elif change == "source":
                trace["turns"][0]["observations"][0]["source_id"] = ""
            else:
                before["facts"][0]["independent_sources"] = 0
                after["facts"][0]["independent_sources"] = 0
            self.assertIsNone(label(evaluate_turn(trace, turn, before, after, judge=LocalJudge()), "R1"))


class DiagnosticTests(unittest.TestCase):
    def test_r3_repeated_decision_is_diagnostic_and_tool_calls_protect_it(self):
        trace, turn, before, after = fixture()
        trace["turns"][0]["action"]["kind"] = "decision"
        trace["turns"][0]["observations"] = []
        turn["action"] = {"kind": "decision", "decision_key": "accept-a"}
        turn["observations"] = []
        before["decisions"] = [{"turn": 2, "key": "accept-a", "summary": "Accept a", "revision": 0}]
        span = label(evaluate_turn(trace, turn, before, after), "R3")
        self.assertIsNotNone(span)
        self.assertFalse(span["reward_eligible"])
        trace["turns"].insert(1, {"turn_id": 4, "action": {"kind": "test"}, "observations": []})
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "R3"))

    def test_d2_submission_uses_actual_selected_candidate(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        turn["action"] = {"kind": "submit", "candidate_id": "b"}
        span = label(evaluate_turn(trace, turn, before, after), "D2")
        self.assertIsNotNone(span)
        self.assertFalse(span["reward_eligible"])
        turn["action"]["candidate_id"] = "a"
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "D2"))

    def test_refuted_fact_requires_real_target_use_for_d3(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        before["facts"][0]["state"] = "refuted"
        after["facts"][0]["state"] = "refuted"
        turn["action"]["candidate_id"] = "a"
        span = label(evaluate_turn(trace, turn, before, after), "D3")
        self.assertIsNotNone(span)
        self.assertFalse(span["reward_eligible"])
        turn["action"]["candidate_id"] = "b"
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "D3"))

    def test_d1_requires_explicit_use_of_known_refuted_fact(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        before["facts"][0]["state"] = "refuted"
        after["facts"][0]["state"] = "refuted"
        turn["action"]["fact_id"] = "f1"
        span = label(evaluate_turn(trace, turn, before, after), "D1")
        self.assertIsNotNone(span)
        self.assertFalse(span["reward_eligible"])
        before["facts"][0]["state"] = "unknown"
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after), "D1"))

    def test_d4_version_mismatch_is_opt_in_and_requires_artifact_contract(self):
        trace, turn, before, after = fixture()
        trace["constraints"] = [{"cid": "code", "kind": "artifact", "required": True, "artifact_id": "solution"}]
        before["constraints"] = after["constraints"] = copy.deepcopy(trace["constraints"])
        turn["action"] = {"kind": "submit", "target_id": "code"}
        turn["artifact"] = {"artifact_id": "solution", "operation": "submit", "version": "old"}
        trace["turns"][0]["action"] = {"kind": "test", "target_id": "code"}
        trace["turns"][0]["artifact"] = {"artifact_id": "solution", "operation": "test", "version": "new", "passed": True}
        after["artifacts"] = {"solution": {"current_version": "new", "last_verified_version": "new", "last_tested_version": "new", "last_test_passed": True, "submitted_version": "old", "test_turn": 2, "submit_turn": 7}}
        span = label(evaluate_turn(trace, turn, before, after), "D4")
        self.assertIsNotNone(span)
        self.assertFalse(span["reward_eligible"])
        enabled = label(evaluate_turn(trace, turn, before, after, config=RuleConfig(enable_artifact_d4=True)), "D4")
        self.assertTrue(enabled["reward_eligible"])
        self.assertEqual(set(enabled["evidence_refs"]), {"turn:2", "turn:7"})
        after["artifacts"]["solution"]["test_turn"] = 4
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after, config=RuleConfig(enable_artifact_d4=True)), "D4"))
        after["artifacts"]["solution"]["test_turn"] = 2
        after["artifacts"]["solution"]["submitted_version"] = "new"
        self.assertIsNone(label(evaluate_turn(trace, turn, before, after, config=RuleConfig(enable_artifact_d4=True)), "D4"))

    def test_rule_evaluation_does_not_mutate_inputs(self):
        values = fixture()
        original = copy.deepcopy(values)
        evaluate_turn(*values)
        self.assertEqual(values, original)


class DecisionTests(unittest.TestCase):
    def test_complete_flag_without_submission_does_not_claim_submitted(self):
        trace, turn, before, after = fixture()
        trace["complete"] = True
        self.assertFalse(decision_summary(trace, after)["submitted"])

    def test_artifact_contract_requires_submission_and_current_passing_version(self):
        for change in ("no_submission", "changed_current", "latest_failed", "different_latest_test"):
            with self.subTest(change=change):
                trace, turn, before, after = fixture()
                after["constraints"] = [{"cid": "code", "required": True, "kind": "artifact", "artifact_id": "solution"}]
                record = {"current_version": "v1", "submitted_version": "v1", "last_verified_version": "v1", "last_tested_version": "v1", "last_test_passed": True}
                if change == "no_submission":
                    record.pop("submitted_version")
                elif change == "changed_current":
                    record["current_version"] = "v2"
                elif change == "latest_failed":
                    record["last_test_passed"] = False
                else:
                    record["last_tested_version"] = "v2"
                after["artifacts"] = {"solution": record}
                self.assertEqual(decision_summary(trace, after)["status"], "critical_gap")

    def test_zero_independent_sources_cannot_satisfy_evidence_contract(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        trace["submitted_candidate"] = "a"
        after["facts"][0]["independent_sources"] = 0
        self.assertEqual(decision_summary(trace, after)["status"], "critical_gap")

    def test_required_gap_is_not_forced_submission_when_budget_exhausted(self):
        trace, turn, before, after = fixture()
        trace["budget_tokens"] = 1
        result = decision_summary(trace, after)
        self.assertEqual(result["status"], "critical_gap")
        self.assertIn(result["suggested_action"], ("continue", "pivot", "review"))
        self.assertFalse(result["forced_stop"])

    def test_complete_supported_contract_suggests_submit(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        trace["submitted_candidate"] = "a"
        result = decision_summary(trace, after)
        self.assertEqual(result["status"], "sufficient")
        self.assertEqual(result["suggested_action"], "submit")

    def test_empty_contract_is_unknown_not_vacuously_sufficient(self):
        trace, turn, before, after = fixture()
        trace["constraints"] = []
        after["constraints"] = []
        self.assertEqual(decision_summary(trace, after)["status"], "incomplete")

    def test_saturation_is_opt_in_and_uses_attempt_count_not_turn_id(self):
        trace, turn, before, after = fixture()
        self.assertEqual(decision_summary(trace, after)["status"], "critical_gap")
        result = decision_summary(trace, after, RuleConfig(saturation_count=2))
        self.assertEqual(result["status"], "saturated")
        self.assertEqual(result["suggested_action"], "pivot")
        self.assertFalse(result["forced_stop"])

    def test_refuted_selected_candidate_has_conflict_priority(self):
        trace, turn, before, after = fixture()
        supported(before, after)
        after["facts"][0]["state"] = "refuted"
        trace["submitted_candidate"] = "a"
        result = decision_summary(trace, after)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["suggested_action"], "review")


class RuleConfigurationTests(unittest.TestCase):
    def test_rule_gates_require_actual_boolean_and_numeric_types(self):
        with self.assertRaises(ValueError):
            RuleConfig(enable_artifact_d4='false')
        with self.assertRaises(ValueError):
            RuleConfig(query_similarity_threshold=True)

    def test_invalid_similarity_cannot_enable_unbounded_matching(self):
        for value in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RuleConfig(query_similarity_threshold=value)

    def test_saturation_requires_at_least_two_actual_attempts(self):
        for value in (0, 1, True, 2.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RuleConfig(saturation_count=value)


class RuleIntegrationTests(unittest.TestCase):
    def test_r1_refresh_of_same_evidence_stays_compatible_with_pipeline(self):
        from ledger_grpo.pipeline import analyze_trajectory, build_process_inputs
        trace, turn, before, after = fixture()
        supported(before, after)
        trace["outcome"] = 1
        trace["submitted_candidate"] = "a"
        trace["complete"] = True
        trace["response_mask"] = [1, 1, 1, 1]
        for index, item in enumerate(trace["turns"]):
            item["token_start"], item["token_end"] = index * 2, index * 2 + 2
        turn["action"]["fact_id"] = "f1"
        fact = {key: value for key, value in before["facts"][0].items() if key != "first_supported_turn"}
        refresh = copy.deepcopy(fact)
        refresh["evidence"][0]["evidence_id"] = "e7"
        report = analyze_trajectory(trace, deltas={2: {"facts": [fact]}, 7: {"facts": [refresh]}}, judge=LocalJudge())
        self.assertTrue(report["qa"]["parse_ok"])
        span = label(report["spans"], "R1")
        self.assertIsNotNone(span)
        self.assertTrue(span["reward_eligible"])
        self.assertEqual(build_process_inputs(trace, report)["redundancy"], [0, 0, 1, 1])

    def test_enabled_d4_can_be_converted_to_process_inputs(self):
        from ledger_grpo.pipeline import analyze_trajectory, build_process_inputs
        trace = {
            "traj_id": "artifact", "task_id": "code", "task": "Submit a verified solution",
            "constraints": [{"cid": "c", "text": "Verified solution", "required": True, "kind": "artifact", "artifact_id": "solution"}],
            "outcome": 0, "complete": True, "response_mask": [1, 1],
            "turns": [
                {"turn_id": 2, "token_start": 0, "token_end": 1, "action": {"kind": "test", "target_id": "c"}, "artifact": {"artifact_id": "solution", "version": "v2", "operation": "test", "passed": True}},
                {"turn_id": 7, "token_start": 1, "token_end": 2, "action": {"kind": "submit", "target_id": "c"}, "artifact": {"artifact_id": "solution", "version": "v1", "operation": "submit"}},
            ],
        }
        report = analyze_trajectory(trace, deltas={2: {"facts": []}, 7: {"facts": []}}, rule_config=RuleConfig(enable_artifact_d4=True))
        self.assertTrue(report["qa"]["parse_ok"])
        self.assertEqual(build_process_inputs(trace, report, enable_artifact_d4=True)["deviations"], [0, 0.15])


if __name__ == "__main__":
    unittest.main()
