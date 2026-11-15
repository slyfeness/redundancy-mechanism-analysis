"""Synthetic cases at the evidence, judgment, and submission boundaries."""

from copy import deepcopy
from pathlib import Path
import json

import pytest
from jsonschema import Draft202012Validator

from redundancy_judge.adapters import model
from redundancy_judge.build_grpo_inputs import build_grpo_inputs
from redundancy_judge.cli import freeze_config
from redundancy_judge.common import JudgeFailure, atomic_json, identity
from redundancy_judge.final_candidate import extract_final_candidate
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.summarize_trajectory import summarize_trajectory
from redundancy_judge.update_evidence_ledger import (
    merge_parallel_updates, support_key, update_evidence_ledger,
)

from test_phase11_ledger_validity import Judge, event, stage


def update_row(candidate="Ada", constraint_id="C1", state="supported", quote="Ada has X"):
    return {"candidate": candidate, "constraint_id": constraint_id, "state": state,
            "quote": quote, "start": 0, "end": len(quote), "resolves_conflict": False}


def apply(task, ledger, n, text, rows, *, uncertain=False, document=None):
    observation = {**event(n, text), "source_id": document or f"doc-{n}"}
    judge = Judge({"evidence_update": {"updates": rows, "uncertain": uncertain}})
    return update_evidence_ledger(task, ledger, stage(n), observation, judge)


@pytest.fixture
def established():
    task = {"constraints": [{"constraint_id": "C1", "text": "X"}, {"constraint_id": "C2", "text": "Y"}],
            "uncertain": False}
    ledger = {"support": {}, "attempts": [], "documents": [],
              "unresolved_evidence_risk": {"global": [], "by_support": {}}}
    ledger, _ = apply(task, ledger, 1, "Ada has X", [update_row()])
    return task, ledger


def grounding(task, ledger):
    return summarize_trajectory({}, task, ledger, [], [], submitted_candidate="Ada")


TARGET = {"state": "resolved", "candidate": "ada", "constraint_id": "C1", "intent": "verify"}
UNKNOWN = {"state": "unknown", "candidate": None, "constraint_id": None, "intent": "unknown"}


def judge_action(task, before, after, delta, observation, target=TARGET):
    judge = Judge({"r1_verification": {"confirmed": True, "confidence": 1, "protection": None}})
    judgment = judge_stage(task, before, after, stage(4, visible=("1",)), observation, target, delta, judge)
    return judgment, judge.calls


def test_whole_return_uncertainty_is_global_and_blocks_grounding_and_exact_repeat(established):
    task, before = established
    # The same response text previously hit the annotation deduplication path.
    # Use a separately observed return for the overall uncertainty, then repeat it.
    after, delta = apply(task, before, 2, "Unreadable passage", [], uncertain=True)
    risks = after["unresolved_evidence_risk"]
    assert len(risks["global"]) == 1 and not risks["by_support"]
    assert risks["global"][0]["reason"] == "evidence extraction uncertain"
    assert risks["global"][0]["event_id"] == "2"
    assert delta["effective_gain"] is None and after["support"] == before["support"]
    assert grounding(task, after)["g"] is None
    judgment, calls = judge_action(task, after, after, {"status": "ok", "effective_gain": False,
        "new_documents": []}, event(3, "Ada has X"))
    assert judgment["price_label"] is None and not calls


@pytest.mark.parametrize(("bad_row", "global_scope"), [
    (update_row(constraint_id="C999", state="refuted"), True),
    (update_row(candidate=None, state="refuted"), True),
    (update_row(state="unknown"), False),
    (update_row(state="not_a_state"), False),
    (update_row(state=[]), False),
    (None, True),
])
def test_invalid_rows_keep_scope_unknown_gain_and_other_verified_evidence(established, bad_row, global_scope):
    task, before = established
    after, delta = apply(task, before, 2, "Ada has Y", [bad_row,
        update_row(constraint_id="C2", quote="Ada has Y")])
    risks = after["unresolved_evidence_risk"]
    bucket = risks["global"] if global_scope else risks["by_support"][support_key("ada", "C1")]
    assert len(bucket) == 1 and bucket[0]["potential_conflict"]
    assert support_key("ada", "C999") not in risks["by_support"]
    assert after["support"][support_key("ada", "C2")]["state"] == "supported"
    assert delta["effective_gain"] is None
    assert grounding(task, after)["g"] is None
    assert [c["constraint_id"] for c in task["constraints"]] == ["C1", "C2"]


def test_rejected_support_without_verified_change_does_not_become_no_gain(established):
    task, before = established
    _, delta = apply(task, before, 2, "Ada may have X", [update_row(quote="not verbatim")])
    assert delta["effective_gain"] is None


@pytest.mark.parametrize(("scope_candidate", "scope_constraint", "quote", "is_local"), [
    ("Ada", "C1", "Ada's X status is unclear", True),
    ("Ada", "C999", "Ada's X status is unclear", False),
    ("Bert", "C1", "Ada's X status is unclear", False),
    ("Bert", "C1", "Bert's X status is unclear", False),
    ("Ada", "C1", "Ada's X status", False),
    ("Ada", "C1", "Ada's Y status is unclear", False),
    ("Ada", "C1", "Ada's X and Y status is unclear", False),
])
def test_overall_uncertainty_requires_verifiable_scope(established, scope_candidate, scope_constraint, quote, is_local):
    task, ledger = established
    response = {"uncertain": True, "updates": [], "uncertainty_scope": {
        "candidate": scope_candidate, "constraint_id": scope_constraint, "quote": quote,
        "start": 0, "end": len(quote)}}
    full_return = "Ada's X status is unclear" if quote == "Ada's X status" else quote
    after, delta = update_evidence_ledger(task, ledger, stage(2), event(2, full_return),
                                         Judge({"evidence_update": response}))
    risks = after["unresolved_evidence_risk"]
    assert bool(risks["by_support"]) is is_local and bool(risks["global"]) is not is_local
    assert delta["effective_gain"] is None and grounding(task, after)["g"] is None


def test_missing_scope_cannot_silently_claim_no_gain_in_phase11(established):
    task, before = established
    judge = Judge({"evidence_update": {"updates": [], "uncertain": False}})
    judge.protocol_version = model.LEGACY_JUDGE_PROTOCOL_VERSION
    after, delta = update_evidence_ledger(task, before, stage(2), event(2, "Unreadable"), judge)
    assert delta["effective_gain"] is None
    assert after["unresolved_evidence_risk"]["global"]


@pytest.mark.parametrize(("constraint", "target", "blocked"), [
    ("C1", TARGET, True), ("C2", TARGET, False), ("C2", UNKNOWN, True),
])
def test_history_guards_r1_and_r2b_with_scope(constraint, target, blocked, established):
    task, before = established
    risky, _ = apply(task, before, 2, "Potential refutation", [update_row(constraint_id=constraint,
        state="refuted", quote="invalid quote")])
    repeated = {**event(3, "Ada has X"), "source_id": "doc-1"}
    after, delta = update_evidence_ledger(task, risky, stage(3), repeated, Judge({}))
    judgment, calls = judge_action(task, risky, after, delta, repeated, target)
    assert judgment["pricing_blocked_by_risk"] is blocked
    labels = {label["label"]: label for label in judgment["labels"]}
    if blocked:
        assert judgment["risk_guard_reason"] and judgment["risk_guard_refs"]
        assert judgment["price_label"] is None and not calls
        assert all(labels[k]["decision"] == "abstain" and not labels[k]["reward_eligible"] for k in ("R1", "R2b"))
    else:
        assert judgment["price_label"] == "R2b"
        assert labels["R1"]["decision"] == labels["R2b"]["decision"] == "positive"


def test_related_risk_without_exact_repeat_still_blocks_semantic_verification(established):
    task, before = established
    risky, _ = apply(task, before, 2, "Potential refutation", [update_row(state="refuted", quote="bad")])
    after, delta = apply(task, risky, 3, "A detail about X", [])
    judgment, calls = judge_action(task, risky, after, delta, event(3, "A detail about X"))
    assert not calls and judgment["diagnostics"]["r1_funnel"]["reason"] == "unresolved_evidence_risk"


def test_post_action_risk_is_relevant_even_outside_predispatch_constraint(established):
    task, before = established
    after, delta = apply(task, before, 2, "X and Y", [update_row(constraint_id="C2", state="unknown")])
    result, _ = judge_action(task, before, after, delta, event(2, "X and Y"))
    assert result["pricing_blocked_by_risk"]


def test_old_risk_on_exact_return_remains_relevant_when_target_scope_differs(established):
    task, before = established
    risky, _ = apply(task, before, 2, "Ada has X or Y", [update_row(constraint_id="C2", state="unknown")])
    updated, delta = apply(task, risky, 3, "Ada has X or Y", [])
    judgment, calls = judge_action(task, risky, updated, delta, event(3, "Ada has X or Y"))
    assert judgment["pricing_blocked_by_risk"] and not calls


def test_clean_duplicate_remains_r2b_and_unapproved_label_cannot_be_charged(established):
    task, before = established
    repeated = event(2, "Ada has X")
    after, delta = update_evidence_ledger(task, before, stage(2), repeated, Judge({}))
    judgment, _ = judge_action(task, before, after, delta, repeated, UNKNOWN)
    assert judgment["price_label"] == "R2b"
    provenance = {**freeze_config({"judge": {"version": "fixture"}, "code_commit": "fixture"}),
                  "prompt_sha256": "a" * 64}
    annotation = summarize_trajectory({"question_id": "q", "trajectory_id": "a", "result": "C",
        "termination_reason": "normal", "recording_complete": True, "result_source": "synthetic receipt",
        "synthetic": True, "policy_token_count": 3, "policy_token_spans": [[0, 3]],
        "token_alignment_status": "verified", "provenance": provenance}, task, after, [stage(4)], [judgment],
        submitted_candidate="Ada")
    peer = {**annotation, "trajectory_id": "b", "events": []}
    preview = build_grpo_inputs([annotation, peer], approved_labels={})
    assert preview["groups"] and not preview["formal_training_usable"]
    assert not any(row["event_debits"] for row in preview["groups"][0]["trajectories"])
    assert preview["optimizer_steps"] == 0
    synthetic_approval = {"R2b": {"status": "PASS", "provenance": provenance, "synthetic": True}}
    approved_preview = build_grpo_inputs([annotation, peer], approved_labels=synthetic_approval)
    assert approved_preview["groups"][0]["trajectories"][0]["event_debits"][0]["debit"] > 0
    assert not approved_preview["formal_training_usable"]


def test_ordinary_success_and_parallel_merge_preserve_prior_risks(established):
    task, before = established
    global_error = apply(task, before, 2, "Uncertain", [], uncertain=True)
    scoped_error = apply(task, before, 3, "Possibly refuted", [update_row(state="refuted", quote="bad")])
    good = apply(task, before, 4, "Ada has Y", [update_row(constraint_id="C2", quote="Ada has Y")])
    combined = merge_parallel_updates(task, before, [global_error, scoped_error, good])
    historical = deepcopy(combined["unresolved_evidence_risk"])
    assert len(historical["global"]) == 1 and len(historical["by_support"][support_key("ada", "C1")]) == 1
    subsequent, delta = apply(task, combined, 5, "Ada has X again", [update_row()])
    assert delta["status"] == "ok" and subsequent["unresolved_evidence_risk"] == historical
    assert grounding(task, subsequent)["g"] is None


def answer(text, quote, anchor, *, start=None, anchor_start=None):
    start = text.find(quote) if start is None else start
    anchor_start = text.find(anchor) if anchor_start is None else anchor_start
    return {"quote": quote, "start": start, "end": start + len(quote), "anchor": anchor,
            "anchor_start": anchor_start, "anchor_end": anchor_start + len(anchor)}


@pytest.mark.parametrize("text", ["Final answer: Ada.", "**Final answer:** Ada.", "<answer>Ada</answer>", "Ada"])
def test_verifiable_answer_structures_emit_anchor_source(text):
    candidate = extract_final_candidate("Who?", text, Judge({"final_candidate": answer(text, "Ada", text)}))
    assert candidate["candidate"] == "Ada"
    assert candidate["anchor_source"]["quote"] == text


@pytest.mark.parametrize(("text", "anchor", "quote_start", "anchor_start"), [
    ("Final answer: Ada.", "Invented anchor", 14, 0),
    ("Ada was considered. Final answer: Ada.", "Final answer: Ada.", 0, None),
    ("Ada was considered. Final answer: Bert.", "Ada was considered.", 0, None),
    ("Final answer: Ada or Bert.", "Final answer: Ada or Bert.", None, None),
    ("Final answer: Ada.\nAnswer: Bert.", "Answer: Bert.", None, None),
    ("Final answer: Ada.\nFinal answer: Ada.", "Final answer: Ada.", None, None),
    ("Final answer: Ada, Bert.", "Final answer: Ada, Bert.", None, None),
    ("Final answer: Ada / Bert.", "Final answer: Ada / Bert.", None, None),
    ("Final answer: Ada、Bert.", "Final answer: Ada、Bert.", None, None),
    ("Example: `Final answer: Ada.`", "Final answer: Ada.", None, None),
    ("Example:\nFinal answer: Ada.", "Final answer: Ada.", None, None),
    ("Final answer: perhaps Ada.", "Final answer: perhaps Ada.", None, None),
    ("Final answer: Ada.\nBert", "Final answer: Ada.", None, None),
])
def test_invalid_or_ambiguous_answer_anchors_cannot_emit_candidate(text, anchor, quote_start, anchor_start):
    quote = "Bert" if anchor == "Answer: Bert." else "Ada"
    with pytest.raises(JudgeFailure):
        extract_final_candidate("Who?", text, Judge({"final_candidate": answer(
            text, quote, anchor, start=quote_start, anchor_start=anchor_start)}))


def test_modern_protocol_can_disambiguate_discussion_but_legacy_needs_a_unique_verified_quote():
    text = "Ada was considered. Final answer: Ada."
    candidate = extract_final_candidate("Who?", text, Judge({"final_candidate": answer(
        text, "Ada", "Final answer: Ada.", start=34)}))
    assert candidate["source"]["start"] == 34
    assert extract_final_candidate("Who?", "Ada", Judge({"final_candidate": {"quote": "Ada"}}))["candidate"] == "Ada"
    for final, response in [(text, {"quote": "Ada", "start": 34, "end": 37, "anchor": "Final answer: Ada."}),
                            ("Ada", {"quote": "Ada", "anchor": "invented"})]:
        with pytest.raises(JudgeFailure):
            extract_final_candidate("Who?", final, Judge({"final_candidate": response}))


def test_old_response_cache_key_cannot_be_reused_in_new_protocol(tmp_path):
    prompts = Path(__file__).resolve().parents[2] / "prompts"
    config = {"url": "http://127.0.0.1:9/v1", "model": "fixture", "version": "fixture"}
    freeze = freeze_config({"judge": config, "code_commit": "fixture"})
    judge = model.ModelJudge(config, prompts, tmp_path, freeze, replay_only=True)
    payload = {"question": "Who?", "final_text": "Ada"}
    body = {"model": "fixture", "temperature": 0, "max_tokens": 4096, "reasoning_effort": "low",
            "messages": [{"role": "system", "content": judge.prompts["final_candidate"]},
                         {"role": "user", "content": model.canonical(payload)}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "final_candidate", "strict": True,
                "schema": model.RESPONSE_SCHEMAS["final_candidate"]}}}
    old_schema = model.LEGACY_RESPONSE_SCHEMAS["final_candidate"]
    old_body = {**body, "response_format": {"type": "json_schema", "json_schema": {
        "name": "final_candidate", "strict": True, "schema": old_schema}}}
    legacy_key = identity([model.LEGACY_JUDGE_PROTOCOL_VERSION, freeze, judge.prompt_sha256, old_body])
    receipt = tmp_path / legacy_key[:2] / f"{legacy_key}.json"
    atomic_json(receipt, {"cache_key": legacy_key, "response": {"quote": "Ada", "anchor": "Ada"}})
    original = receipt.read_bytes()
    with pytest.raises(JudgeFailure, match="replay cache entry is missing"):
        judge.ask("final_candidate", payload)
    assert receipt.read_bytes() == original and len(list(tmp_path.rglob("*.json"))) == 1
    assert model.RESPONSE_SCHEMAS["final_candidate"]["required"] == ["quote"]
    current_key = identity([model.JUDGE_PROTOCOL_VERSION, freeze, judge.prompt_sha256, body])
    invalid_receipt = tmp_path / current_key[:2] / f"{current_key}.json"
    atomic_json(invalid_receipt, {"cache_key": current_key, "response": {"quote": "Ada"}})
    with pytest.raises(JudgeFailure, match="cache identity mismatch"):
        judge.ask("final_candidate", payload)
    atomic_json(invalid_receipt, {"cache_key": current_key, "protocol_version": model.JUDGE_PROTOCOL_VERSION,
                                 "response": {}})
    with pytest.raises(JudgeFailure, match="missing required fields"):
        judge.ask("final_candidate", payload)
    atomic_json(invalid_receipt, {"cache_key": current_key, "protocol_version": model.JUDGE_PROTOCOL_VERSION,
                                 "response": {"quote": "Ada"}})
    assert judge.ask("final_candidate", payload) == {"quote": "Ada"}


def test_risk_output_schema_enforces_abstention_and_preserves_legacy_records(established):
    task, before = established
    schema_path = Path(__file__).resolve().parents[2] / "src/redundancy_judge/schemas/phase1.schema.json"
    schema = json.loads(schema_path.read_bytes())
    validate = lambda name: Draft202012Validator({**schema, "$ref": f"#/$defs/{name}"})
    after, delta = apply(task, before, 2, "Unknown", [], uncertain=True)
    judgment, _ = judge_action(task, before, after, delta, event(2, "Unknown"))
    for label in judgment["labels"]:
        label["known_at"] = "fixture"
    clean, _ = judge_action(task, before, before, {"status": "ok", "effective_gain": False,
        "new_documents": []}, {**event(3, "Ada has X"), "return_time": "fixture"})
    legacy = {k: v for k, v in clean.items() if k not in {
        "pricing_blocked_by_risk", "risk_guard_reason", "risk_guard_refs"}}
    assert validate("StageJudgment").is_valid(legacy)
    assert validate("StageJudgment").is_valid(judgment)
    assert not validate("StageJudgment").is_valid({**judgment, "price_label": "R2b"})
    assert not validate("StageJudgment").is_valid({**judgment, "risk_guard_refs": []})
    assert not validate("StageJudgment").is_valid({**legacy, "provenance": {"schema_version": "phase1.1.v2"}})
