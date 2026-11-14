from copy import deepcopy

import pytest

from redundancy_judge.build_grpo_inputs import build_grpo_inputs


FREEZE = {
    "schema_version": "1",
    "code_commit": "1234",
    "model_version": "judge-rev",
    "prompt_sha256": "b" * 64,
    "config_sha256": "c" * 64,
}


def event(event_id, label, start, end, **flags):
    return {
        "event_id": event_id, "label": label, "stage_type": "tool",
        "decision": "positive", "reward_eligible": True,
        "charge_token_spans": [[start, end]],
        "event_cost": {"generated_tokens": end - start, "returned_tokens": 3, "tool_calls": 1},
        **flags,
    }


def record(name, result, events=(), *, g=0.4, synthetic=True, **fields):
    return {
        "trajectory_id": name, "question_id": "q", "result": result, "g": g,
        "termination_reason": "budget_exhausted" if result == "N" else "normal",
        "recording_complete": True, "result_source": "independent receipt",
        "token_alignment_status": "verified", "policy_token_count": 9,
        "policy_token_spans": [[1, 4], [6, 9]], "events": list(events),
        "synthetic": synthetic, "provenance": FREEZE, **fields,
    }


def approvals(*labels, synthetic=True):
    return {label: {"status": "PASS", "provenance": FREEZE, "synthetic": synthetic} for label in labels}


def preview(rows, config=None, *, labels=("R1", "R2b")):
    result = build_grpo_inputs(rows, config, approvals(*labels))
    return result["groups"][0]["trajectories"]


def test_all_wrong_leave_one_out_and_prices_are_zero():
    left, right = preview([record("a", "W", [event("1", "R1", 1, 2)]), record("b", "N", g=None)])
    for row in (left, right):
        assert row["outcome_advantage"] == 0
        assert row["peer_gate"] == 0
        assert row["token_advantages"] == [0.0] * 9
    assert left["event_debits"][0]["debit"] == 0


def test_one_success_only_peers_can_be_charged_and_masks_exclude_observations():
    left, right = preview([record("a", "C", [event("1", "R2b", 1, 3)]),
                           record("b", "N", [event("2", "R1", 2, 4)], g=None)])
    assert left["peer_gate"] == 0
    assert left["token_advantages"] == pytest.approx([0, 1.04, 1.04, 1.04, 0, 0, 1.04, 1.04, 1.04])
    assert right["peer_gate"] == 1
    assert right["policy_mask"] == [0, 1, 1, 1, 0, 0, 1, 1, 1]
    assert right["token_advantages"] == pytest.approx([0, -1.04, -1.09, -1.09, 0, 0, -1.04, -1.04, -1.04])


def test_all_correct_same_g_can_be_penalized_locally_and_final_stage_is_excluded():
    left, right = preview([record("a", "C", [event("1", "R1", 1, 3),
                                               event("2", "R2b", 6, 8, stage_type="final")]),
                           record("b", "C")])
    assert left["outcome_advantage"] == right["outcome_advantage"] == 0
    assert left["token_advantages"] == pytest.approx([0, -.05, -.05, 0, 0, 0, 0, 0, 0])
    assert right["token_advantages"] == [0.0] * 9


def test_mixed_different_g_and_no_local_prices_restore_exact_leave_one_out():
    rows = [record("a", "C", [event("1", "R1", 1, 2)], g=.2),
            record("b", "C", g=.8), record("c", "W")]
    scores = preview(rows, {"prices": {"R1": 0, "R2b": 0}})
    assert [row["outcome_advantage"] for row in scores] == pytest.approx([.48, .57, -1.05])
    pure = preview(rows, {"w_g": 0, "prices": {"R1": 0, "R2b": 0}})
    assert [row["outcome_advantage"] for row in pure] == pytest.approx([.5, .5, -1])


def test_cost_multiplier_cap_priority_and_protection_do_not_double_charge():
    events = [event("same", "R1", 1, 2), event("same", "R2b", 1, 2),
              event("same", "R2b", 1, 2), event("second", "R2b", 2, 3),
              event("third", "R2b", 6, 7), event("guard", "R2b", 7, 8, protected=True),
              event("diag", "R2a", 8, 9)]
    first, second = preview([record("a", "C", events), record("b", "C")], {
        "price_mode": "cost_weighted",
        "reference_cost": {"median": 2, "split": "dev", "sample_sha256": "a" * 64},
    })
    assert [item["event_id"] for item in first["event_debits"]] == ["same", "second", "third"]
    assert [item["label"] for item in first["event_debits"]] == ["R2b"] * 3
    assert [item["debit"] for item in first["event_debits"]] == pytest.approx([1/6] * 3)
    assert sum(item["debit"] for item in first["event_debits"]) == pytest.approx(.5)
    assert first["token_advantages"] == pytest.approx([0, -1/6, -1/6, 0, 0, 0, -1/6, 0, 0])
    assert second["token_advantages"] == [0.0] * 9


def test_overlapping_distinct_events_skip_debits_without_rewriting_result_credit():
    first, _ = preview([record("a", "C", [event("1", "R1", 1, 3), event("2", "R2b", 2, 4)]),
                        record("b", "W")])
    assert first["outcome_advantage"] == pytest.approx(1.04)
    assert first["event_debits"] == []
    assert {row["reason"] for row in first["excluded_events"]} == {"overlapping_charge_spans"}


@pytest.mark.parametrize("change, reason", [
    ({"recording_complete": False}, "incomplete_log"),
    ({"termination_reason": "infrastructure_failure"}, "invalid_outcome_or_termination"),
    ({"result_source": None}, "missing_independent_result"),
    ({"token_alignment_status": "unverified"}, "unverified_token_alignment"),
    ({"g": None}, "unverified_grounding"),
])
def test_bad_input_excludes_whole_group_under_an_explicit_reason(change, reason):
    bad = record("a", "C")
    bad.update(change)
    output = build_grpo_inputs([bad, record("b", "W")], approved_labels=approvals())
    assert output["groups"] == []
    assert output["excluded"][0]["row_reasons"]["a"] == reason


def test_synthetic_approval_and_stale_approval_do_not_price_real_data():
    rows = [record("a", "C", [event("1", "R1", 1, 2)], synthetic=False),
            record("b", "C", synthetic=False)]
    wrong_freeze = deepcopy(approvals("R1", synthetic=False))
    wrong_freeze["R1"]["provenance"] = {**FREEZE, "prompt_sha256": "z" * 64}
    for approved in ({}, approvals("R1"), wrong_freeze):
        output = build_grpo_inputs(rows, approved_labels=approved)
        assert output["groups"][0]["trajectories"][0]["event_debits"] == []
        assert output["formal_training_usable"] is False
        assert output["optimizer_steps"] == 0
    output = build_grpo_inputs(rows, approved_labels=approvals("R1", synthetic=False))
    assert output["groups"][0]["trajectories"][0]["event_debits"][0]["debit"] == pytest.approx(.05)
    assert output["formal_training_usable"] is False


def test_grounding_and_cost_provenance_are_only_bypassed_in_explicit_fixed_price_mode():
    rows = [record("a", "C", g=None), record("b", "W", g=None)]
    assert preview(rows, {"w_g": 0})[0]["outcome_advantage"] == 1.0
    for reference in (None, {"median": 1, "split": "audit", "sample_sha256": "a" * 64}):
        with pytest.raises(ValueError, match="development"):
            build_grpo_inputs(rows, {"price_mode": "cost_weighted", "reference_cost": reference})


def test_unverified_price_position_cannot_debit_masked_tokens():
    first, _ = preview([record("a", "C", [event("1", "R1", 3, 7)]), record("b", "C")])
    assert first["event_debits"] == []
    assert first["excluded_events"][0]["reason"] == "invalid_charge_token_spans"


def test_verified_policy_axis_preserves_independent_budget_reason():
    _, row = preview([record("a", "C"), record("b", "N", g=None,
        raw_termination_reason="CONTEXT_LIMIT_STOP")])
    assert row["Y"] == 0
    assert row["raw_termination_reason"] == "CONTEXT_LIMIT_STOP"


def test_withheld_debits_explain_mismatched_provenance_on_the_trajectory_and_event():
    candidate = event("1", "R1", 1, 2, provenance=FREEZE)
    rows = [record("a", "C", [candidate], synthetic=False),
            record("b", "C", synthetic=False)]
    rows[0]["provenance"] = {**FREEZE, "code_commit": "other"}
    output = build_grpo_inputs(rows, approved_labels=approvals("R1", synthetic=False))
    assert output["groups"][0]["trajectories"][0]["event_debits"] == []


def test_distinct_results_can_be_all_final_and_still_have_full_policy_credit():
    rows = [record("a", "C", g=0, policy_token_count=3, policy_token_spans=[[1, 3]]),
            record("b", "W", policy_token_count=2, policy_token_spans=[[1, 2]])]
    correct, wrong = preview(rows)
    assert correct["token_advantages"] == [0, 1, 1]
    assert wrong["token_advantages"] == [0, -1]


def test_complete_empty_final_is_valid_n_and_is_not_a_budget_stop():
    rows = [record("a", "C"),
            record("b", "N", [event("1", "R1", 1, 2)], termination_reason="empty_final")]
    _, empty = preview(rows, {"budget_failure_disables_local_prices": True})
    assert empty["Y"] == 0
    assert empty["budget_process_disabled"] is False
    assert empty["event_debits"][0]["debit"] == pytest.approx(.05)


def test_conflicting_result_and_explicit_y_exclude_the_group():
    result = build_grpo_inputs([record("a", "C", Y=0), record("b", "N", Y=0)])
    assert result["groups"] == []
    assert result["excluded"][0]["row_reasons"]["a"] == "inconsistent_independent_y"


def test_expected_group_size_retains_group_membership_in_exclusion_receipt():
    result = build_grpo_inputs([record("a", "C"), record("b", "N")], {"group_size": 4})
    assert result["groups"] == []
    assert result["excluded"][0]["trajectory_ids"] == ["a", "b"]
    assert result["excluded"][0]["group_reasons"] == ["incomplete_question_group"]
