from ledger import DocumentIndex, Observation, evidence_exposure, keyword_decision, proposal_events, search_repeat
from check import full_open, kind_of, open_and_search_gate

from collections import Counter, defaultdict
from hashlib import sha256


def test_docids_from_structured_search_and_exact_unambiguous_metadata():
    index = DocumentIndex()
    index.add("1", "First page", "https://example.test/one")
    index.add("2", "Shared title", "https://example.test/two")
    index.add("3", "Shared title", "https://example.test/three")
    assert index.identify('[{"docid":"1","snippet":"irrelevant id 3"},{"document_id":2}]') == {
        "1": "direct", "2": "direct"
    }
    assert index.identify('---\ntitle: First page\n---\nBody') == {"1": "title"}
    assert index.identify('{"title":"Shared title"}') == {}
    assert index.identify('{"title":"Shared title","url":"https://example.test/two"}') == {"2": "url"}
    assert index.identify('{"docid":null,"title":"First page"}') == {"1": "title"}
    assert not index.identify('Page text says docid: 1')


def obs(eid, round_id, kind, docs=(), query=None, visible=True):
    return Observation(eid, round_id, kind, tuple(docs), query, visible)


def test_exposure_uses_only_visible_events_and_strictly_earlier_rounds():
    events = [
        obs("s1", 1, "search", ("1",), "Ａ b c d e"),
        obs("o1", 1, "open", ("1",)), obs("o2", 1, "open", ("1",)),
        obs("s2", 2, "search", ("1",), "a b c d e"),
        obs("s3", 2, "search", ("1", "2"), "a b c d"),
        obs("o3", 2, "open", ("1", "2")), obs("o4", 3, "open", ("3",), visible=False),
        obs("o5", 4, "open", ("4",)), obs("o6", 5, "open", ("4",)),
    ]
    report = evidence_exposure(events, {"1", "2", "3"}, {"1", "3"})
    assert report["first_seen"] == {"1": 1, "2": 2}
    assert report["first_opened"] == {"1": 1, "2": 2}
    assert report["gold_seen"] == report["gold_opened"] == 1
    assert report["seen_recall"] == report["opened_recall"] == 2 / 3
    assert report["signals"] == {"repeat_open_evidence": 1, "repeat_open_other": 1, "search_no_new_evidence": 1,
                                 "search_exact_repeat": 1, "search_jaccard_repeat": 1}


def test_jaccard_and_exact_repeats_are_disjoint_and_casefolded():
    assert search_repeat("Straße\tA", ["STRASSE a"]) == "search_exact_repeat"
    assert search_repeat("one two three four", ["one two three four five"]) == "search_jaccard_repeat"
    assert search_repeat("one two three", ["one two three four"]) is None
    assert search_repeat("a", [""]) is None


def test_keyword_rules_treat_ambiguous_keywords_as_pending():
    keywords = {"C1": ["ＢＡＲ", "å b"], "C2": ["red fox", "straße"]}
    assert keyword_decision("search BAR", keywords, {"C1"}) == "r1"
    assert keyword_decision("embargo", keywords, {"C1"}) == "neither"
    assert keyword_decision("bar STRASSE", keywords, {"C1"}) == "pending"
    assert keyword_decision("red   fox", keywords, {"C1"}) == "neither"


def test_r1_a_requires_nonempty_support_and_r1_b_does_not_see_same_round_open():
    events = [
        obs("s1", 1, "search", ("1",), "red fox"),
        obs("o1", 2, "open", ("1",)), obs("s2", 2, "search", (), "red fox"),
        obs("o2", 3, "open", ("1", "2", "3")),
        obs("s3", 3, "search", (), "red fox"),
        obs("s4", 4, "search", (), "red fox city"),
    ]
    report = proposal_events(events, {"1": {"C1"}, "2": set(), "3": {"C1", "C2"}},
                             {"C1": ["red fox"], "C2": ["city"]})
    assert report["first_seen"] == {"C1": 1}
    assert report["first_confirmed"] == {"C1": 2, "C2": 3}
    assert [item["docid"] for item in report["r1_a"]] == ["1"]
    assert [item["event_id"] for item in report["searches"]] == ["s3", "s4"]
    assert [item["decision"] for item in report["searches"]] == ["r1", "r1"]


def test_gate_requires_a_measured_open_ratio_and_does_not_mark_missing_as_zero_percent():
    groups = defaultdict(Counter, search=Counter(calls=5, returns=5, identified=5))
    missing = open_and_search_gate(groups)
    assert missing["passed"] == 0 and missing["by_kind"]["open"]["return_docid_ratio"] is None
    groups["open"] = Counter(calls=5, returns=5, identified=3)
    assert open_and_search_gate(groups)["passed"] == 0
    groups["open"]["identified"] = 4
    assert open_and_search_gate(groups)["passed"] == 1


def test_open_fulltext_check_can_use_known_parameter_but_rejects_snippet():
    assert kind_of("retrieval_open_document") == "open"
    full = "The full document.\n"
    hashes = {"1": sha256(full.encode()).digest()}
    assert full_open(full, {}, {"1"}, hashes) == ("1",)
    assert full_open(full[:5], {"1": "direct"}, set(), hashes) == ()
