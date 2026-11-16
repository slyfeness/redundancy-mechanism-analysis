from run_exam_v3 import compare_v2


def test_compare_v2_tracks_all_new_and_removed_r1_events():
    assert compare_v2(["q:1", "q:3"], ["q:1", "q:2"]) == {
        "both_r1": ["q:1"], "v2_only": ["q:2"], "v3_only": ["q:3"],
    }
