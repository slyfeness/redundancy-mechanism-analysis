from fix_pilot import choose_scheme, compare_pairs, gates, plan_targets, verdict_ids

import pytest


def test_selection_prefers_recall_within_three_points_of_best_precision():
    data = {
        "original": {"precision": 0.91, "relative_recall": 0.95},
        "P2": {"precision": 0.94, "relative_recall": 0.80},
        "V": {"precision": 0.90, "relative_recall": 0.99},
    }
    assert choose_scheme(data) == "original"
    assert choose_scheme({"P2": data["P2"], "V": data["V"]}) == "P2"
    assert compare_pairs({"x", "y"}, {"x", "z", "w"}, 2) == {
        "calls": 2, "labeled_pairs": 2, "correct_pairs": 1, "precision": 0.5,
        "relative_recall": 1 / 3, "gold_pairs": 3}


def test_target_replay_only_requests_changed_nonempty_prefix():
    old = {"e1": {"confirmed": ["C1"]}, "e2": {"confirmed": ["C1"]},
           "e3": {"confirmed": ["C1"]}, "e4": {"confirmed": []}}
    new = [{"id": "e1", "confirmed": ["C1"]}, {"id": "e2", "confirmed": ["C2"]},
           {"id": "e3", "confirmed": []}, {"id": "e4", "confirmed": ["C2"]}]
    reused, changed, ineligible = plan_targets(old, new, {"e1": ["C1"], "e2": [], "e3": ["C1"]})
    assert reused == {"e1": ["C1"]}
    assert [row["id"] for row in changed] == ["e2", "e4"] and ineligible == 1


def test_same_and_precision_recall_are_hard_gates_semantic_is_fallback():
    result = gates({"precision": .90, "relative_recall": .85}, 17, 20, 22, 28)
    assert result["run_full"] == 1 and result["use_intersection"] == 1
    assert gates({"precision": .90, "relative_recall": .84}, 17, 20, 23, 28)["run_full"] == 0
    assert gates({"precision": .93, "relative_recall": .90}, 16, 20, 23, 28)["run_full"] == 0


def test_verifier_has_explicit_yes_and_no_and_invalid_replies_fail():
    assert verdict_ids({"reason": "fixture", "verdict": "yes"}, {"C1"}) == ["C1"]
    assert verdict_ids({"reason": "fixture", "verdict": "no"}, {"C1"}) == []
    with pytest.raises(ValueError):
        verdict_ids({"reason": "fixture", "verdict": "unknown"}, {"C1"})
