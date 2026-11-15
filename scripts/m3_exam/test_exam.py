from run_exam import choose_passages, make_trials, passage_schema, judge_labels, summarize


def event(eid, round_number, docs, visible=True):
    return {"event_id": f"x:{eid}", "trajectory_id": "x", "round": round_number,
            "parallel_index": eid, "query": "alpha", "reasoning": "", "visible": visible,
            "returned_docids": docs, "main_label": "effective"}


def passage(docid, text, evidence=False):
    return {"docid": docid, "passage": text, "is_evidence": evidence}


def test_visibility_and_same_round_do_not_leak():
    rows = [event(1, 1, ["1"]), event(2, 1, ["2"]), event(3, 2, ["3"], False), event(4, 3, ["4"])]
    sources = {("q", p["docid"]): p for p in [
        passage("1", "alpha", True), passage("2", "beta"), passage("3", None), passage("4", "alpha later", True)]}
    trials = make_trials(rows, {"x": "q"}, {"q": "synthetic question"}, sources)
    by_event = {(t["event_id"], t["variant"]): [r["id"] for r in t["passages"]] for t in trials}
    assert all(by_event[f"x:{i}", v] == [] for i in (1, 2) for v in ("A", "B"))
    assert by_event["x:3", "A"] == ["P1"]
    assert by_event["x:4", "A"] == ["P1"]
    assert by_event["x:4", "B"] == ["P1", "P2"]


def test_bm25_top_five_and_a_uses_same_scores():
    seen = {str(i): passage(str(i), "zebra zebra" if i == 8 else "other topic", i % 2 == 0)
            for i in range(1, 9)}
    variants = choose_passages(seen, "zebra")
    assert [r["id"] for r in variants["B"]] == ["P8", "P1", "P2", "P3", "P4"]
    assert [r["id"] for r in variants["A"]] == ["P2", "P4", "P6", "P8"]
    assert variants["B"][0]["bm25_score"] == variants["A"][-1]["bm25_score"] > 0


def test_category_and_ids_determine_r1_or_contradiction():
    allowed = {"P42"}
    assert judge_labels("already_seen", ["P42"], allowed) == (True, False)
    assert judge_labels("already_seen", [], allowed) == (False, True)
    assert judge_labels("already_seen", ["P99"], allowed) == (False, True)
    assert judge_labels("new_information", ["P42"], allowed) == (False, True)
    assert judge_labels("new_candidate", [], allowed) == (False, False)


def test_schema_empty_and_nonempty_ids():
    empty = passage_schema([])
    assert list(empty["properties"]) == ["seeking", "reason", "category", "passage_ids"]
    assert empty["additionalProperties"] is False
    assert empty["properties"]["passage_ids"]["maxItems"] == 0
    assert passage_schema(["P2"])["properties"]["passage_ids"]["items"]["enum"] == ["P2"]


def test_summary_does_not_count_failures_as_disagreement_or_negatives():
    def row(variant, category, r1=False, failed=False):
        return {"event_id": "x:1", "variant": variant,
                "parsed": {"category": category} if category else None,
                "new_r1": r1, "format_conflict": False, "failure": "error" if failed else None,
                "request_characters": 100, "passage_characters": 80, "seconds": 1.0}
    stats = summarize([row("A", "already_seen", True), row("B", None, failed=True)],
                      [event(1, 1, [])], {"x:1": {"raw": "explore", "recorded": "unknown"}}, 2)
    assert stats["variants"]["A"]["new_r1"] == 1
    assert stats["variants"]["B"]["failures"] == 1
    assert stats["new_r1_agreement"]["paired_valid"] == 0
    assert stats["new_r1_agreement"]["both_false"] == 0
