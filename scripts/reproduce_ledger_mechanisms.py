"""Run nine synthetic mechanisms against the original Phase 1 functions."""

import argparse
from pathlib import Path

from redundancy_judge.adapters.model import RESPONSE_SCHEMAS
from redundancy_judge.common import JudgeFailure, atomic_json, exact_quote
from redundancy_judge.init_task_ledger import init_task_ledger
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.resolve_action_target import resolve_action_target
from redundancy_judge.summarize_trajectory import summarize_trajectory
from redundancy_judge.update_evidence_ledger import refresh_gaps, support_key, update_evidence_ledger


REV = "4ab6908d68a6ab1a9ec33c9db2454669ca737721"
Q = "Name the entity founded in 2000 and located in Tokyo."
TEXT = "Alpha was founded in 2000. Alpha is located in Tokyo."
STAGE = {"stage_type": "tool", "stage_id": "S1", "parse_status": "ok",
         "action": {"tool_name": "search", "arguments": {"query": "Alpha"}}}


class FixtureJudge:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def ask(self, kind, payload):
        self.requests.append(kind)
        return self.response


def task_fixture():
    return init_task_ledger(Q, FixtureJudge({"constraints": [
        {"quote": "founded in 2000"}, {"quote": "located in Tokyo"}], "uncertain": False}))


def update(task, ledger, text, rows, event_id="1"):
    mock = FixtureJudge({"uncertain": False, "updates": rows})
    return update_evidence_ledger(task, ledger, STAGE,
                                  {"event_id": event_id, "return_text": text, "visible_next": True}, mock)


def row(candidate, cid, quote, state="supported"):
    return {"candidate": candidate, "constraint_id": cid, "quote": quote, "state": state,
            "resolves_conflict": False}


def summary(task, ledger, candidate):
    values = summarize_trajectory({}, task, ledger, [], [], submitted_candidate=candidate)
    return {key: values[key] for key in ("g", "grounding_issue", "supported_constraints")}


def investigate():
    results = {}

    def check(name, functions, inputs, expected, actual):
        results[name] = {"functions": functions, "input": inputs, "expected": expected, "actual": actual,
                         "passed": expected == actual, "synthetic": True}

    quote = "Alpha was founded in 2000."
    duplicate = quote + " " + quote
    errors = []
    for text in (duplicate, "Located in Tokyo."):
        try:
            exact_quote(text, {"quote": quote})
        except JudgeFailure as exc:
            errors.append(str(exc))
    has_span = any("start" in repr(RESPONSE_SCHEMAS[k]) or "end" in RESPONSE_SCHEMAS[k]["properties"]
                   for k in ("task_constraints", "evidence_update", "final_candidate"))
    check("Q1", ["exact_quote"], {"duplicate": duplicate, "absent": "Located in Tokyo.", "quote": quote},
          {"same_error": True, "explicit_span": [0, len(quote)], "schema_has_span": False},
          {"same_error": errors == ["evidence quote absent or ambiguous"] * 2,
           "explicit_span": list(exact_quote(duplicate, {"quote": quote, "start": 0, "end": len(quote)})[k]
                                 for k in ("start", "end")), "schema_has_span": has_span})
    broken = FixtureJudge({"constraints": [{"quote": "founded in 2000"}, {"quote": "not present"}],
                           "uncertain": False})
    broken_task, broken_ledger = init_task_ledger(Q, broken)
    target = resolve_action_target(broken_task, broken_ledger, STAGE, broken)
    check("Q2", ["init_task_ledger", "resolve_action_target"], {"question": Q, "response": broken.response},
          {"task_status": "annotation_error", "constraints": [], "target": "unknown", "target_calls": 0},
          {"task_status": broken_task["status"], "constraints": broken_task["constraints"], "target": target["state"],
           "target_calls": broken.requests.count("action_target")})
    task, initial = task_fixture()
    good = [row("Alpha", "C1", quote), row("Alpha", "C2", "Alpha is located in Tokyo.")]
    fatal = [good[0], row("Beta", "C999", "Alpha")]
    after, delta = update(task, initial, TEXT, fatal)
    check("U1", ["update_evidence_ledger"], {"return": TEXT, "updates": fatal},
          {"status": "annotation_error", "error": "invalid support coordinates or state", "facts": 0},
          {"status": delta["status"], "error": delta["error"], "facts": len(after["support"])})
    mixed = [*good, row("Beta", "C1", "not present")]
    after, delta = update(task, initial, TEXT, mixed)
    expected_summary = {"g": None, "grounding_issue": "incomplete_evidence_updates", "supported_constraints": ["C1", "C2"]}
    check("G1", ["update_evidence_ledger", "summarize_trajectory"], {"return": TEXT, "updates": mixed, "candidate": "Alpha"},
          {"status": "partial_annotation", "gain": True, **expected_summary},
          {"status": delta["status"], "gain": delta["effective_gain"], **summary(task, after, "Alpha")})
    later, later_delta = update(task, after, quote, [good[0]], event_id="2")
    check("G2", ["update_evidence_ledger", "summarize_trajectory"], {"earlier": mixed, "later": good[0]},
          {"status": "ok", **expected_summary}, {"status": later_delta["status"], **summary(task, later, "Alpha")})
    target = {"state": "resolved", "intent": "verify", "candidate": "alpha", "constraint_id": "C1"}
    mock = FixtureJudge({"confirmed": True, "confidence": .99, "protection": None})
    verdict = judge_stage(task, initial, after, STAGE, {"event_id": "1", "return_text": TEXT, "visible_next": True},
                          target, delta, mock)
    r1 = next(row for row in verdict["labels"] if row["label"] == "R1")
    check("R1", ["judge_stage"], {"target": target, "delta_status": delta["status"], "gain": delta["effective_gain"]},
          {"decision": "abstain", "reason": "low_verification_confidence", "r1_calls": 0},
          {"decision": r1["decision"], "reason": r1["abstention_reason"], "r1_calls": len(mock.requests)})
    split = [good[0], row("Beta", "C2", "Alpha is located in Tokyo.")]
    distributed, _ = update(task, initial, TEXT, split)
    refresh_gaps(task, distributed)
    check("S1", ["refresh_gaps", "summarize_trajectory"], {"updates": split},
          {"global": [], "candidate": {"alpha": ["C2"], "beta": ["C1"]}, "g": .5},
          {"global": distributed["open_gaps"], "candidate": distributed["candidate_gaps"],
           "g": summary(task, distributed, "Alpha")["g"]})
    alias_rows = [row("Acme Incorporated", "C1", quote), row("Acme Inc.", "C2", good[1]["quote"])]
    disconnected, _ = update(task, initial, TEXT, alias_rows)
    check("S2", ["update_evidence_ledger", "summarize_trajectory"], {"updates": alias_rows, "same_entity_in_fixture": True},
          {"keys": 2, "g": .5, "grounding_issue": None, "supported_constraints": ["C1"]},
          {"keys": len(disconnected["support"]), **summary(task, disconnected, "Acme Incorporated")})
    contradicted, _ = update(task, distributed, "Alpha was not founded in 2000.",
                             [row("Alpha", "C1", "Alpha was not founded in 2000.", "refuted")], event_id="2")
    fact = contradicted["support"][support_key("alpha", "C1")]
    check("GUARD", ["update_evidence_ledger"], {"refutation": "Alpha was not founded in 2000."},
          {"state": "conflicted", "evidence": 2}, {"state": fact["state"], "evidence": len(fact["evidence"])})
    return {"source_commit": REV, "synthetic": True, "model_network_requests": 0, "dataset_replays": 0,
            "optimizer_steps": 0, "checks": results, "passed": sum(x["passed"] for x in results.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    opts = parser.parse_args()
    findings = investigate()
    atomic_json(opts.output, findings)
    for name, result in findings["checks"].items():
        print(name, "PASS" if result["passed"] else "FAIL", result["actual"])
    raise SystemExit(0 if findings["passed"] == 9 else 1)
