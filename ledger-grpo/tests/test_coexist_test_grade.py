from copy import deepcopy

from ledger_grpo.coexist_test_grade import RESULT_SOURCE, normalize_answer, strict_match_updates


def test_normalize_uses_outer_unicode_punctuation_only():
    assert normalize_answer("  （ ＳＴＲＡẞＥ！ ） ") == "strasse"
    assert normalize_answer("  New   York,  ") == "new   york"
    assert normalize_answer("A-B") == "a-b"
    assert normalize_answer("A-B") != normalize_answer("A B")


def test_isolated_grade_keeps_original_outcomes_and_binding():
    core = [{"traj_id": "t", "task_id": "q", "outcome": None, "exclusion_reason": "independent_outcome_unresolved"},
            {"traj_id": "u", "task_id": "q", "outcome": 0}]
    native = {"trajectories": [{"id": "t", "query_id": "q", "reward": None, "terminal": "MODEL_FINAL_STOP"},
                               {"id": "u", "query_id": "q", "reward": 0, "terminal": "CONTEXT_LIMIT_STOP"}]}
    frozen = deepcopy((core, native))
    sidecar, projected_core, projected_native = strict_match_updates(core, native, {"t": "  ＴＥＳＴ！ ", "u": "TEST"},
                                                                   {"q": "test"}, snapshot="trial")
    assert (core, native) == frozen
    assert [row["test_outcome"] for row in sidecar] == [1, 0]
    assert all("outcome" not in item and item["result_source"] == RESULT_SOURCE for item in sidecar)
    assert [row["outcome"] for row in projected_core] == [1, 0]
    assert "exclusion_reason" not in projected_core[0]
    assert projected_native["trajectories"][0]["reward"] == 1
