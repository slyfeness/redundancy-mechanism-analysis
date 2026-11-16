import pytest

from redundancy_judge.audit_judge import audit_judge
from redundancy_judge.cli import write_jsonl
from redundancy_judge.common import atomic_json, read_json
from redundancy_judge.review_workflow import execute


FREEZE = {
    "schema_version": "1", "code_commit": "abcd",
    "model_version": "judge-rev", "prompt_sha256": "a" * 64, "config_sha256": "b" * 64,
}


def judgment(event, label, decision="positive", **extra):
    return {
        "event_id": event, "question_id": "q:" + event, "label": label, "decision": decision,
        "reward_eligible": decision == "positive", "provenance": FREEZE, "synthetic": False,
        **extra,
    }


def review(event, label, human_decision="positive", **fields):
    return {
        "event_id": event, "label": label, "human_decision": human_decision,
        "necessary": False, "sample_kind": "natural", "selection_probability": 1.0,
        "source": "human", "reviewer_id": "annotator", "independent": True,
        **fields,
    }


def ratio(metrics, key):
    return metrics[key]["estimate"]


def test_empty_human_reviews_do_not_fabricate_precision_or_approvals():
    output = audit_judge([judgment("1", "R1"), judgment("2", "R2b")])
    assert output["status"] == "PENDING_HUMAN_REVIEW"
    assert output["approved_labels"] == {}
    for report in output["labels"].values():
        assert report["natural"]["precision"]["estimate"] is None


def test_docid_review_plan_is_accepted_without_granting_approval(tmp_path, monkeypatch):
    monkeypatch.setattr("redundancy_judge.review_workflow.write_blind_packets", lambda *_: None)
    rows = [judgment("e1", label, reward_eligible=False) for label in ("R1", "R2b", "R2a")]
    write_jsonl(tmp_path / "stage_judgments.jsonl", [{
        "event_id": "e1", "question_id": "q1", "trajectory_id": "t1", "stage_id": "s1",
        "split": "audit", "protections": [], "synthetic": False, "provenance": FREEZE, "labels": rows,
    }])
    atomic_json(tmp_path / "run_manifest.json", {"synthetic": False})
    config = {"run_dir": str(tmp_path), "phase1_mode": "docid"}
    assert execute("export-review", config) == 0
    assert execute("audit", config) == 0
    report = read_json(tmp_path / "acceptance.json")
    assert report["status"] == "PENDING_HUMAN_REVIEW"
    assert set(report["labels"]) == {"R2a", "R2b"}
    assert report["labels"]["R2a"]["review_plan"]["planned"] == 1
    assert report["approved_labels"] == {}


def test_labels_are_separate_and_natural_estimates_use_inverse_probability_weights():
    rows = [judgment("1", "R1"), judgment("2", "R1"), judgment("3", "R2b"),
            judgment("4", "R1", "abstain")]
    humans = [review("1", "R1"), review("2", "R1", "negative", selection_probability=.25),
              review("3", "R2b"), review("4", "R1")]
    report = audit_judge(rows, humans)
    assert ratio(report["labels"]["R1"]["natural"], "precision") == .2
    assert ratio(report["labels"]["R1"]["natural"], "recall") == .5
    assert ratio(report["labels"]["R1"]["natural"], "abstention_rate") == pytest.approx(1/6)
    assert ratio(report["labels"]["R2b"]["natural"], "precision") == 1
    assert report["labels"]["R1"]["status"] == "FAIL"
    assert report["labels"]["R2b"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_independent_challenges_and_actual_deletion_transition_denominators():
    rows = [judgment(str(i), "R1", "negative" if i == 2 else "positive") for i in range(1, 7)]
    humans = [review("1", "R1"), review("2", "R1", "negative", necessary=True),
              review("3", "R1", "negative", sample_kind="protection", necessary=True,
                     protection_reason="conflict_resolution")]
    links = [
        {"event_id": "1", "original_result": "C", "branch_results": ["W", "W", "N", "C"],
         "mapping_reliable": True, "reviewed": True},
        {"event_id": "2", "original_result": "C", "branch_results": ["W", "W", "W", "C"],
         "mapping_reliable": True, "reviewed": True},
        {"event_id": "3", "original_result": "W", "branch_results": ["C", "C", "C", "W"],
         "mapping_reliable": True, "reviewed": True},
        {"event_id": "4", "original_result": "C", "branch_results": ["C", "C", "C", "N"],
         "mapping_reliable": True, "reviewed": True},
        {"event_id": "5", "original_result": "C", "branch_results": ["W"] * 4,
         "mapping_reliable": True, "reviewed": True, "function_reconstructed": True},
        {"event_id": "6", "original_result": "C", "branch_results": ["W"] * 4,
         "mapping_reliable": True, "reviewed": True, "successor_guidance": True},
    ]
    report = audit_judge(rows, humans, links)["labels"]["R1"]
    assert ratio(report["natural"], "necessary_false_positive_rate") == 0
    assert ratio(report["protection"], "necessary_false_positive_rate") == 1
    assert report["natural"]["necessary_false_positive_rate"]["ci95"][1] > 0
    assert ratio(report["legacy"], "bplus_mark_rate") == .5
    assert ratio(report["legacy"], "bplus_contamination") == pytest.approx(1/3)
    assert report["legacy"]["link_counts"] == {"B+": 2, "B-": 1, "A": 1,
                                                "function_reconstructed": 1, "successor_guidance": 1}


def test_nonhuman_or_independent_disagreements_do_not_supply_ground_truth():
    rows = [judgment("1", "R1"), judgment("2", "R1"), judgment("3", "R1")]
    reviews = [
        review("1", "R1", source="llm"),
        review("2", "R1", reviewer_id="a"), review("2", "R1", "negative", reviewer_id="b"),
        review("3", "R1", source="human", independent=False),
    ]
    report = audit_judge(rows, reviews)
    assert report["labels"]["R1"]["natural"]["precision"]["estimate"] is None
    assert report["status"] == "PENDING_HUMAN_REVIEW"
    assert {row["reason"] for row in report["unresolved_reviews"]} == {
        "not_independent_human_review", "adjudication_required",
    }


def test_adjudicated_disagreement_is_retained_with_resolved_precision_estimate():
    row = judgment("1", "R1")
    reviews = [
        review("1", "R1", reviewer_id="a"),
        review("1", "R1", "negative", reviewer_id="b"),
        review("1", "R1", "negative", reviewer_id="c", adjudication=True),
    ]
    report = audit_judge([row], reviews)
    assert ratio(report["labels"]["R1"]["natural"], "precision") == 0
    assert report["disagreements"][0]["reviewer_ids"] == ["a", "b"]
    assert report["disagreements"][0]["adjudicator_id"] == "c"


def test_many_events_in_one_question_do_not_falsely_certify_zero_risk():
    rows = [judgment(str(i), "R1", question_id="same") for i in range(30)]
    reviews = [review(str(i), "R1") for i in range(30)]
    report = audit_judge(rows, reviews, config={"bootstrap_samples": 100, "min_positive_events": 1,
                                                "min_positive_questions": 1})
    metric = report["labels"]["R1"]["natural"]["precision"]
    assert metric["ci95"][0] < .9
    assert metric["questions"] == 1
    assert report["approved_labels"] == {}


def test_development_reviews_are_kept_out_of_the_independent_audit():
    rows = [judgment("1", "R1", split="audit"), judgment("2", "R1", split="dev")]
    reviews = [review("1", "R1"), review("2", "R1", "negative")]
    output = audit_judge(rows, reviews)
    assert output["labels"]["R1"]["events"] == 1
    assert ratio(output["labels"]["R1"]["natural"], "precision") == 1
    assert output["unresolved_reviews"][0]["reason"] == "review_outside_audit_split"


def test_human_abstention_cannot_issue_a_false_positive_or_approval():
    output = audit_judge([judgment("1", "R1")], [review("1", "R1", "abstain")])
    assert output["labels"]["R1"]["status"] == "PENDING_HUMAN_REVIEW"
    assert output["labels"]["R1"]["failure_cases"] == []


def test_automatic_abstention_and_eligible_coverage_are_reported_without_humans():
    output = audit_judge([judgment("1", "R1"), judgment("2", "R1", "abstain"),
                          judgment("3", "R1", protected=True)])
    population = output["labels"]["R1"]["automatic"]
    assert ratio(population, "abstention_rate") == pytest.approx(1/3)
    assert ratio(population, "priceable_coverage") == pytest.approx(1/3)


def test_unfinished_frozen_review_plan_withholds_an_otherwise_supported_label():
    rows = []
    humans = []
    links = []
    for i in range(100):
        rows.extend([judgment(f"pos{i}", "R1"), judgment(f"neg{i}", "R1", "negative")])
        humans.extend([review(f"pos{i}", "R1"), review(f"neg{i}", "R1", "negative", necessary=True),
                       review(f"neg{i}", "R1", "negative", sample_kind="protection", necessary=True)])
        links.extend([{"event_id": event_id, "original_result": "C", "branch_results": outcomes,
                       "mapping_reliable": True, "reviewed": True}
                      for event_id, outcomes in [(f"pos{i}", ["C"] * 4), (f"neg{i}", ["W"] * 4)]])
    settings = {"bootstrap_samples": 50}
    baseline = audit_judge(rows, humans, links, config=settings)
    assert baseline["approved_labels"]["R1"]["status"] == "PASS"
    plan = [{key: row[key] for key in ("event_id", "label", "sample_kind")} for row in humans]
    plan.append({"event_id": "pos0", "label": "R1", "sample_kind": "protection"})
    output = audit_judge(rows, humans, links, planned_reviews=plan, config=settings)
    assert output["labels"]["R1"]["status"] == "PENDING_HUMAN_REVIEW"
    assert output["labels"]["R1"]["review_plan"]["outstanding"] == [plan[-1]]
    assert output["approved_labels"] == {}


def test_zero_bound_reports_risk_even_with_complete_question_level_census():
    rows = [judgment(str(i), "R1", "negative") for i in range(20)]
    reviews = [review(str(i), "R1", "negative", necessary=True) for i in range(20)]
    metric = audit_judge(rows, reviews)["labels"]["R1"]["natural"]["necessary_false_positive_rate"]
    assert metric["estimate"] == 0
    assert metric["ci95"][1] == pytest.approx(.161125158, abs=1e-8)


@pytest.mark.parametrize("option", [
    {"min_precision": .89}, {"max_necessary_false_positive_rate": .06}, {"max_bplus_mark_rate": .06},
])
def test_audit_settings_cannot_weaken_fixed_quality_thresholds(option):
    with pytest.raises(ValueError, match="weaken"):
        audit_judge([], config=option)
