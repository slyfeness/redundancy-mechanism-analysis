import importlib.util
from pathlib import Path

import pytest

from redundancy_judge.init_task_ledger import initial_ledger
from redundancy_judge.update_evidence_ledger import support_key


def load_diagnostic():
    path = Path(__file__).resolve().parents[2] / "scripts/diagnose_m4_gating.py"
    spec = importlib.util.spec_from_file_location("diagnose_m4_gating", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def observed():
    from redundancy_judge.judge_stage import judge_stage

    m4 = load_diagnostic()
    task = {"constraints": [{"constraint_id": "C1", "text": "built 2000"}], "uncertain": False}
    action = {"arguments": {"query": "Alpha"}, "tool_name": "Search", "deterministic": True,
              "environment": "fixture"}
    first = {"stage_id": "s1", "stage_type": "tool", "parse_status": "ok", "action": action,
             "visible_return_ids": [], "cost": {}}
    second = {**first, "stage_id": "s2", "visible_return_ids": ["e1"]}
    third = {**second, "stage_id": "s3", "visible_return_ids": ["e1", "e2"]}
    events = [{"event_id": f"e{i}", "return_text": value, "visible_next": True}
              for i, value in enumerate(("Alpha built 2000", "Beta was founded 2000.", "Alpha overview"), 1)]
    calls = [m4.ObservedEvidence(response) for response in (
        {"updates": [{"candidate": "Alpha", "constraint_id": "C1", "state": "supported",
                      "quote": "Alpha built 2000", "start": 0, "end": 16}],
         "uncertain": False, "uncertainty_scope": None},
        {"updates": [{"candidate": "Beta", "constraint_id": "C1", "state": "supported",
                      "quote": "Beta was founded 2000.", "start": 1, "end": 22},
                     {"candidate": None, "constraint_id": "C9", "state": "unknown"},
                     {"candidate": "Alpha", "constraint_id": "C1", "state": None}],
         "uncertain": False, "uncertainty_scope": None},
        {"updates": [], "uncertain": False, "uncertainty_scope": None},
    )]
    ledger = initial_ledger(task)
    stages = [first, second, third]
    snapshots, judgments, targets = [], [], []
    for stage, event, call in zip(stages, events, calls):
        target = {"state": "resolved", "candidate": "alpha", "constraint_id": "C1", "intent": "verify"}
        after, delta = m4.update_evidence_ledger(task, ledger, stage, event, call)
        call.span_failures = [0] if stage is second else []
        judgment = judge_stage(task, ledger, after, stage, event, target, delta, None)
        eid = "t:" + event["event_id"]
        judgments.append({**judgment, "event_id": eid})
        targets.append({**target, "event_id": eid})
        snapshots.append({"event_id": eid, "before": ledger, "after": after, "delta": delta})
        ledger = after
    bundle = {"task_specs": task, "stages": [*stages, {"stage_type": "final"}], "tool_events": events,
              "stage_judgments": judgments, "action_targets": targets, "ledger_snapshots": snapshots,
              "input_index": {"trajectory_id": "t"}, "final_candidate": {"candidate": "alpha"},
              "trajectory_summaries": {"g": None}}
    for stage, event in zip(stages, events):
        stage.update(event_ids=[event["event_id"]], parallel_group_id=None)
    calls = {event["event_id"]: call for event, call in zip(events, calls)}
    return m4, bundle, ledger, calls


def test_unknown_state_is_taken_from_cache_and_span_replay_adds_support(observed):
    m4, bundle, ledger, calls = observed
    reasons = m4.RiskOrigins(bundle, calls)
    assert reasons.count(ledger, "global") == {"state_unknown_rejected": 1}
    assert reasons.count(ledger, "support") == {"span_mismatch": 1, "other": 1}
    alternate, repair = m4.replay_repairs(bundle, calls)
    assert repair["span_rows_accepted"] == 1
    assert {row["candidate"] for row in alternate["support"].values()} == {"alpha", "beta"}
    assert bundle["ledger_snapshots"][1]["delta"]["rejected_evidence"][0]["reason"] == m4.SPAN


def test_global_risk_removal_preserves_local_guard_and_other_gates(observed):
    m4, bundle, _, _ = observed
    snap = bundle["ledger_snapshots"][-1]
    args = (bundle["task_specs"], snap["before"], snap["after"], bundle["stages"][2],
            bundle["tool_events"][2], bundle["action_targets"][2], snap["delta"])
    assert not m4.verification_without_global(*args, threshold=0.8)
    decision = bundle["stage_judgments"][2]
    assert m4.non_invocation_gate(args[1], args[3], args[4], args[5], decision) == "global_risk"
    for ledger in (snap["before"], snap["after"]):
        del ledger["unresolved_evidence_risk"]["by_support"][support_key("alpha", "C1")]
    assert m4.verification_without_global(*args, threshold=0.8)
    args[-1]["status"] = "partial_annotation"
    assert not m4.verification_without_global(*args, threshold=0.8)


def test_g_uses_submitted_candidate_and_fixed_denominator(observed):
    m4, bundle, ledger, _ = observed
    assert m4.grounding_gate(bundle, ledger) == "global_risk"
    assert m4.grounding_without_global(bundle, ledger) is None
    bundle["final_candidate"]["candidate"] = "gamma"
    assert m4.grounding_without_global(bundle, ledger) == 0.0
    bundle["stages"].pop()
    assert m4.grounding_gate(bundle, ledger) == "no_final"
    assert m4.grounding_without_global(bundle, ledger) is None


@pytest.mark.parametrize("source,quote,expected", [("abc", "b", (1, 2)), ("aaaa", "aa", None),
                                                     ("abc", "d", None), ("abc", "", None)])
def test_span_repair_only_accepts_a_unique_literal_position(source, quote, expected):
    assert load_diagnostic().unique_span(source, quote) == expected


def test_uncertainty_sample_is_complete_and_text_free():
    from hashlib import sha256

    m4 = load_diagnostic()
    events = [f"t:e{i}" for i in range(40)]
    selected = m4.select_sample(events)
    assert selected == sorted(events, key=lambda eid: sha256(f"20261115|{eid}".encode()).hexdigest())[:30]
    receipt = m4.sample_receipt(selected, dict.fromkeys(selected, "a"))
    assert receipt["a"] == {"count": 30, "event_ids": selected}
    with pytest.raises(ValueError):
        m4.sample_receipt(selected, {selected[0]: "a"})


def test_counterfactual_keeps_observed_reply_after_repair_creates_duplicate(observed):
    m4, bundle, _, calls = observed
    calls["e2"].response["updates"].pop()
    bundle["tool_events"][2]["return_text"] = bundle["tool_events"][1]["return_text"]
    calls["e3"].response["updates"].append({
        "candidate": "Gamma", "constraint_id": "C1", "state": "refuted",
        "quote": "Beta was founded 2000.", "start": 0, "end": 22,
    })
    ledger, _ = m4.replay_repairs(bundle, calls)
    assert ledger["support"][support_key("gamma", "C1")]["state"] == "refuted"
    assert ledger["attempts"][1]["status"] == "ok"


def test_uncertainty_localization_distinguishes_no_scope_from_text_mismatch(observed):
    m4, bundle, _, _ = observed
    task, ledger = bundle["task_specs"], bundle["ledger_snapshots"][0]["after"]
    text = "Alpha built 2000"
    scope = {"candidate": "Alpha", "constraint_id": "C1", "quote": text, "start": 0, "end": len(text)}
    assert m4.localization_details(task, ledger, text, {"updates": [], "uncertainty_scope": None}) == (
        "no_scope_object", False, False)
    assert m4.localization_details(task, ledger, "Alpha dates to 2000", {"updates": [], "uncertainty_scope": scope}) == (
        "scope_constraint_text_not_unique_in_return", False, True)
    assert m4.localization_details(task, ledger, text, {"updates": [], "uncertainty_scope": scope}) == (
        "localized", False, False)
