"""Regression tests for normalized provenance and final submission grounding."""

import copy
import unittest

from ledger_grpo.ledger import grounding_score
from ledger_grpo.pipeline import analyze_trajectory
from ledger_grpo.rules import decision_summary
from ledger_grpo.schema import actor_view, validate_trajectory


def trace_fixture():
    return {
        "traj_id": "schema", "task_id": "question", "task": "Identify the supported candidate",
        "constraints": [{"cid": "c", "text": "Identity", "kind": "evidence", "required": True}],
        "outcome": 1, "complete": True, "response_mask": [1, 1],
        "turns": [
            {"turn_id": 1, "token_start": 0, "token_end": 1,
             "action": {"kind": "search", "target_id": "c", "query": "identity"},
             "observations": [{"evidence_id": "e1", "document_id": "d1", "source_id": "s1", "text": "Ada satisfies the requirement."}]},
            {"turn_id": 4, "token_start": 1, "token_end": 2,
             "action": {"kind": "submit", "candidate_id": "ada"}, "observations": []},
        ],
    }


class NormalizationTests(unittest.TestCase):
    def test_nested_unknown_metadata_cannot_reach_judge(self):
        raw = trace_fixture()
        raw["privileged"] = {"answer": "SECRET_TOP"}
        raw["constraints"][0]["gold_answer"] = "SECRET_CONSTRAINT"
        raw["turns"][0]["gold_answer"] = "SECRET_TURN"
        raw["turns"][0]["action"]["extra"] = {"gold_answer": "SECRET_ACTION"}
        raw["turns"][0]["observations"][0]["extra"] = "SECRET_OBSERVATION"
        raw["turns"][0]["artifact"] = {"artifact_id": "a", "operation": "write", "version": "v1", "gold_answer": "SECRET_ARTIFACT"}
        original = copy.deepcopy(raw)

        class Inspector:
            leaked = False

            def extract(self, payload):
                self.leaked |= "SECRET_" in str(payload)
                return {"facts": []}

        inspector = Inspector()
        result = analyze_trajectory(raw, judge=inspector)
        self.assertTrue(result["qa"]["parse_ok"])
        self.assertFalse(inspector.leaked)
        normalized = validate_trajectory(raw)
        self.assertEqual(normalized["privileged"], {"answer": "SECRET_TOP"})
        self.assertNotIn("SECRET_", str(actor_view(normalized)))
        self.assertEqual(raw, original)

    def test_control_flags_are_preserved_with_strict_types(self):
        raw = trace_fixture()
        raw["turns"][0]["action"].update(independent_trial=True, retry_justification="Transient failure")
        action = validate_trajectory(raw)["turns"][0]["action"]
        self.assertTrue(action["independent_trial"])
        self.assertEqual(action["retry_justification"], "Transient failure")
        for key, value in (("independent_trial", "false"), ("retry_justification", True), ("candidate_id", []), ("fact_id", 3)):
            with self.subTest(key=key):
                damaged = trace_fixture()
                damaged["turns"][0]["action"][key] = value
                with self.assertRaises(ValueError):
                    validate_trajectory(damaged)

    def test_final_submission_identity_is_inferred_without_leaking_it_early(self):
        raw = trace_fixture()
        normalized = validate_trajectory(raw)
        self.assertEqual(normalized["submitted_candidate"], "ada")
        self.assertNotIn("submitted_candidate", actor_view(normalized))
        raw["submitted_candidate"] = "eve"
        with self.assertRaisesRegex(ValueError, "submit"):
            validate_trajectory(raw)

    def test_only_last_real_submission_can_determine_final_candidate(self):
        raw = trace_fixture()
        raw["turns"][0]["action"] = {"kind": "submit", "candidate_id": "eve"}
        self.assertEqual(validate_trajectory(raw)["submitted_candidate"], "ada")
        raw["turns"][1]["action"] = {"kind": "submit"}
        self.assertIsNone(validate_trajectory(raw)["submitted_candidate"])

    def test_malformed_nested_values_fail_as_validation_errors(self):
        for location in ("turn", "observation", "conclusion", "representation", "artifact_passed", "action_kind", "privileged"):
            with self.subTest(location=location):
                raw = trace_fixture()
                if location == "turn":
                    raw["turns"][0] = "not a turn"
                elif location == "observation":
                    raw["turns"][0]["observations"] = ["not an observation"]
                elif location == "conclusion":
                    raw["turns"][0]["conclusion"] = {"gold": "text"}
                elif location == "representation":
                    raw["turns"][0]["observations"][0]["representation"] = "unknown-mode"
                elif location == "artifact_passed":
                    raw["turns"][0]["artifact"] = {"artifact_id": "a", "operation": "write", "version": "v1", "passed": "false"}
                elif location == "action_kind":
                    raw["turns"][0]["action"]["kind"] = {}
                else:
                    raw["privileged"] = ["untyped metadata"]
                with self.assertRaises(ValueError):
                    validate_trajectory(raw)

    def test_explicit_privileged_observation_is_rejected_not_relabelled(self):
        raw = trace_fixture()
        raw["turns"][0]["observations"][0]["privileged"] = True
        with self.assertRaisesRegex(ValueError, "privileged"):
            validate_trajectory(raw)

    def test_null_artifact_becomes_absence(self):
        raw = trace_fixture()
        raw["turns"][0]["artifact"] = None
        self.assertNotIn("artifact", validate_trajectory(raw)["turns"][0])


class ArtifactGroundingTests(unittest.TestCase):
    def test_grounding_and_decision_share_strict_artifact_contract(self):
        trace = {"constraints": [{"cid": "c", "text": "Verified final artifact", "required": True, "kind": "artifact", "artifact_id": "a"}], "submitted_candidate": None, "turns": []}
        base = {"current_version": "v1", "submitted_version": "v1", "last_verified_version": "v1", "last_tested_version": "v1", "last_test_passed": True}
        cases = [({}, 1.0), ({"current_version": "v2"}, 0.0), ({"last_tested_version": "v2"}, 0.0), ({"last_test_passed": False}, 0.0), ({"submitted_version": None}, 0.0)]
        for change, expected in cases:
            with self.subTest(change=change):
                record = dict(base, **change)
                ledger = {"constraints": trace["constraints"], "artifacts": {"a": record}, "facts": []}
                self.assertEqual(grounding_score(trace, ledger), expected)
                self.assertEqual(decision_summary(trace, ledger)["status"] == "sufficient", expected == 1.0)

    def test_old_pass_does_not_cover_rewrite_or_later_failed_test(self):
        for sequence in (
            [("write", "v1", None), ("test", "v1", True), ("write", "v2", None), ("submit", "v1", None)],
            [("test", "v1", True), ("test", "v1", False), ("submit", "v1", None)],
        ):
            trace = {"traj_id": "artifact", "task_id": "code", "task": "Submit tested version", "constraints": [{"cid": "c", "text": "Verified artifact", "kind": "artifact", "artifact_id": "a"}], "outcome": 1, "response_mask": [1] * len(sequence), "turns": []}
            for i, (operation, version, passed) in enumerate(sequence, 1):
                artifact = {"artifact_id": "a", "operation": operation, "version": version}
                if passed is not None:
                    artifact["passed"] = passed
                trace["turns"].append({"turn_id": i, "token_start": i - 1, "token_end": i, "action": {"kind": operation, "target_id": "c"}, "artifact": artifact})
            report = analyze_trajectory(trace, deltas={i: {"facts": []} for i in range(1, len(sequence) + 1)})
            self.assertEqual(report["metrics"]["grounding_score"], 0.0)
            self.assertEqual(report["decision"]["status"], "critical_gap")


if __name__ == "__main__":
    unittest.main()
