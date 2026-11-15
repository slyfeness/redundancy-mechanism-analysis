from result_labels import annotate, combine, report


def event(i, round_id, query, docs=(), visible=True):
    return {"id": f"1__rep1:{i}", "round": round_id, "query": query,
            "docs": list(docs), "visible": visible}


def test_label_priority_and_visible_evidence():
    events = [
        event(1, 1, "Ａ   B", ["e1", "n1"]),
        event(2, 2, "a b", ["e2"], False),
        event(3, 3, "a b", ["e2"]),
        event(4, 4, "different", ["e1", "e2"]),
        event(5, 5, "another", ["e1", "n2"]),
        event(6, 6, "new search", ["n3"]),
        event(7, 7, "new wording", ["n3", "e3"]),
    ]
    rows = annotate(events, {"e1", "e2", "e3"}, {"e2"})
    assert [r["main"] for r in rows] == [
        "effective", "no_return", "repeat_query", "no_new_information", "repeat_evidence",
        "ineffective", "effective",
    ]
    assert rows[2]["new_docs"] == ["e2"]
    assert rows[2]["flags"]["new_gold"] and not rows[1]["flags"]["new_gold"]


def test_earlier_rounds_only_and_all_flags():
    rows = annotate([
        event(1, 1, "Ａ b c d e", ["e1", "e2"]),
        event(2, 1, "a b c d e", ["e1", "e2"]),
        event(3, 2, "a b c d", ["e1", "e2", "e3"]),
        event(4, 3, "x", ["e1", "e2", "e3"]),
    ], {"e1", "e3"}, {"e1"})
    assert rows[0]["main"] == rows[1]["main"] == "effective"
    assert rows[0]["flags"]["same_round_repeat"] and rows[1]["flags"]["new_gold"]
    assert not rows[1]["flags"]["result_overlap"] and not rows[1]["flags"]["query_similarity"]
    assert rows[2]["flags"]["result_overlap"] and rows[2]["flags"]["query_similarity"]
    assert rows[2]["overlap_event_id"] == rows[0]["id"]
    assert rows[3]["candidates"] == [rows[j]["id"] for j in (2, 0, 1)]


def test_final_labels_and_fallback():
    rows = annotate([
        event(1, 1, "x", ["e1"]),
        event(2, 2, "y", ["e1", "n1"]),
        event(3, 3, "z", ["e1", "n1"]),
        event(4, 4, "z w", ["e1", "n1", "e2"]),
        event(5, 5, "z", ["e1", "n1"]),
    ], {"e1", "e2"}, set())
    semantic = {rows[1]["id"]: [], rows[2]["id"]: [1], rows[3]["id"]: [1]}
    assert [combine(r, semantic) for r in rows] == [
        "effective", "soft_redundancy", "definite_redundancy", "rephrased_success", "definite_redundancy",
    ]
    assert [combine(r, None) for r in rows] == [
        "effective", "soft_redundancy", "definite_redundancy", "effective", "definite_redundancy",
    ]


def test_report_excludes_unavailable_denominators_and_same_round_from_timing():
    rows = annotate([
        event(1, 1, "x", ["e1"]),
        event(2, 1, "y", ["e1"]),
        event(3, 2, "x", ["e1"]),
        event(4, 3, "z", visible=False),
    ], {"e1"}, {"e1"})
    report_data, _ = report([{"id": "1__rep1", "qid": "1", "outcome": "correct", "events": rows}], None)
    assert report_data["timing"]["after_first_gold"]["searches"] == 2
    assert report_data["timing"]["after_all_evidence"]["searches"] == 2
    assert report_data["per_trajectory"]["1__rep1"]["strict_ratio"] == 1 / 3
    assert report_data["consistency"] is None
