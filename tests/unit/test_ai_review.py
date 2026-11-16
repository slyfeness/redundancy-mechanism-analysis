from hashlib import sha256

import pytest

from redundancy_judge.ai_review import audit_ai_reviews, review_units, spot_check_list
from redundancy_judge.build_grpo_inputs import build_grpo_inputs, freeze_identity
from redundancy_judge.cli import freeze_config, write_jsonl
from redundancy_judge.common import atomic_json, read_json
from redundancy_judge.review_workflow import execute
from test_build_grpo_inputs import FREEZE, event, record


POLICY = {"review_mode": "ai", "ai_review": {"primary_reviewer": "codex", "spot_checker": "claude-opus-5-5",
          "authorized_by": "user", "criteria_sha256": sha256(b"criteria").hexdigest()}}


def judgment(eid, label="R2b", decision="positive"):
    return {"event_id": eid, "label": label, "decision": decision, "synthetic": False, "provenance": FREEZE}


def review(uid, eid, decision="positive", checker=False, **extra):
    return {"unit_id": uid, "event_id": eid, "decision": decision, "necessary": False, "independent": True,
            "reason": "test review", "source": "ai_review", "reviewer_id": "claude-opus-5-5" if checker else "codex",
            "adjudication": checker, **extra}


def test_ai_review_uses_only_r2b_and_retains_complete_units():
    rows = [judgment("e1"), judgment("e2", "R1"), judgment("e3", "R2a"), judgment("e4", decision="negative")]
    plan = [{"event_id": "e4", "label": "R2b", "sample_kind": "natural"},
            {"event_id": "e3", "label": "R2a", "sample_kind": "natural"}]
    assert review_units(rows, plan) == {"R2b:e4:natural": "e4", "R2b:e1:full_positive": "e1"}
    report = audit_ai_reviews(rows, plan, [], [], POLICY)
    assert report["status"] == "PENDING_AI_REVIEW"
    assert report["labels"]["R1"]["status"] == report["labels"]["R2a"]["status"] == "record_only"
    assert report["approved_labels"] == {}


def test_ai_review_approval_and_false_positive_gate():
    rows = [judgment("e1"), judgment("e2")]
    codex = [review(f"R2b:{eid}:full_positive", eid) for eid in ("e1", "e2")]
    checked = [review(r["unit_id"], r["event_id"], checker=True) for r in codex]
    report = audit_ai_reviews(rows, [], codex, checked, POLICY)
    approved = report["approved_labels"]["R2b"]
    assert approved["status"] == "ai_approved"
    assert approved["event_ids"] == ["e1", "e2"]
    assert report["review_mode"] == "ai" and report["ai_review"] == POLICY["ai_review"]
    assert "B_plus" in report["skipped_checks"]
    changed = [{**checked[0], "decision": "negative"}, checked[1]]
    failed = audit_ai_reviews(rows, [], codex, changed, POLICY)
    assert failed["status"] == "FAIL" and failed["approved_labels"] == {}
    assert failed["disagreements"][0]["adjudicated_decision"] == "negative"


def test_ai_review_never_accepts_human_source_or_invented_spot_reviews():
    rows = [judgment("e1")]
    item = review("R2b:e1:full_positive", "e1")
    with pytest.raises(ValueError, match="AI review"):
        audit_ai_reviews(rows, [], [{**item, "source": "human"}], [], POLICY)
    assert audit_ai_reviews(rows, [], [item], [], POLICY)["approved_labels"] == {}
    with pytest.raises(ValueError, match="spot"):
        audit_ai_reviews(rows, [], [item], [review("other", "e1", checker=True)], POLICY)


def test_ai_spot_selection_reconciles_all_nonpositives_before_sampling():
    rows = [review(f"u{i}", f"e{i}", "negative" if i < 3 else "positive") for i in range(52)]
    choices = spot_check_list(rows)
    assert len(choices) == 40
    assert {row["unit_id"] for row in choices if row["selection"] == "all_nonpositive"} == {"u0", "u1", "u2"}
    assert spot_check_list(list(reversed(rows))) == choices


def test_m9_ai_approval_requires_mode_policy_and_reviewed_event_id():
    rows = [record("a", "W", events=[event("ea", "R2b", 1, 3)], synthetic=False),
            record("b", "C", synthetic=False)]
    provenance = freeze_identity({**FREEZE, **POLICY})
    approved = {"R2b": {"status": "ai_approved", "provenance": provenance, "synthetic": False, "event_ids": ["ea"]}}

    def debits(options, approvals):
        return build_grpo_inputs(rows, options, approved_labels=approvals)["groups"][0]["trajectories"][0]["event_debits"]

    assert debits({}, approved) == []
    assert len(debits(POLICY, approved)) == 1
    assert debits(POLICY, {"R2b": {**approved["R2b"], "event_ids": ["other"]}}) == []
    assert debits(POLICY, {"R2b": {**approved["R2b"], "status": "PASS"}}) == []


def test_workflow_freezes_ai_criteria_and_waits_for_spot_check(tmp_path):
    config = {**POLICY, "mode": "real", "code_commit": "xyz", "run_dir": str(tmp_path),
              "judge": {"model": "local", "version": "local:v1"}}
    assert freeze_config(config)["ai_review"] == POLICY["ai_review"]
    criteria = tmp_path / "criteria.txt"
    criteria.write_bytes(b"criteria")
    frozen = tmp_path / "run_manifest.json"
    atomic_json(frozen, {"synthetic": False})
    write_jsonl(tmp_path / "stage_judgments.jsonl", [{
        "event_id": "e1", "question_id": "q", "trajectory_id": "t", "split": "audit", "stage_id": "s",
        "synthetic": False, "protections": [], "provenance": FREEZE,
        "labels": [judgment("e1"), judgment("e1", "R1"), judgment("e1", "R2a")],
    }])
    config.update(ai_criteria=str(criteria))
    assert execute("export-review", config) == 0
    assert not (tmp_path / "human_review_template.csv").exists()
    assert execute("audit", config) == 0
    assert read_json(tmp_path / "approved_labels.json") == {}
    assert read_json(tmp_path / "acceptance.json")["status"] == "PENDING_AI_REVIEW"
    criteria.write_bytes(b"different")
    with pytest.raises(ValueError, match="criteria differ"):
        execute("audit", config)
