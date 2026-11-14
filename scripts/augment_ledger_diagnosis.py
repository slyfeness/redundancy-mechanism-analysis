"""Compute supplemental event rollups from sealed diagnosis records."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import re

from diagnose_phase1_ledger import digest, stat_rows
from redundancy_judge.cli import jsonl, write_jsonl
from redundancy_judge.common import atomic_json, candidate_name


def augment(private):
    gates = jsonl(private / "r1_reason_reconciliation.jsonl")
    calls = jsonl(private / "model_call_trace.jsonl")
    ground = jsonl(private / "grounding_blockers.jsonl")
    targets = {row["event_id"]: row for row in calls if row["component"] == "action_target"}
    targets_by_reason = defaultdict(list)
    for event in gates:
        if event["primary_route"] != "target_unresolved":
            continue
        call = targets.get(event["event_id"])
        flags = []
        if not call:
            flags.append("target_not_invoked")
        else:
            value = call.get("response", {})
            confidence = value.get("confidence")
            if call.get("error"):
                flags.append("cached_error")
            if value.get("intent") == "unknown":
                flags.append("intent_unknown")
            if type(confidence) in (int, float) and confidence < .8:
                flags.append("target_confidence_below_frozen_threshold")
            if not candidate_name(value.get("candidate")):
                flags.append("candidate_missing")
            if not value.get("constraint_id"):
                flags.append("constraint_id_missing")
            elif not flags and value.get("constraint_id"):
                flags.append("invalid_field_or_constraint_outside_frozen_task")
        for flag in flags or ["unexplained"]:
            targets_by_reason[flag].append(event)
    cases = jsonl(private / "real_cases.jsonl")
    aliases = []
    for number, row in enumerate(ground, 1):
        for link in row["possible_candidate_name_links"]:
            candidate, other = link["final_candidate"], link["other_candidate"]
            named = re.compile(re.escape(other) + r"\s+was born\s+" + re.escape(candidate), re.I)
            abbreviation = re.fullmatch(re.escape(other) + r" \(([a-z]+)\)", candidate)
            acronym = "".join(term[0] for term in other.split())
            evidence = next((ref for ref in link["evidence"] if named.search(ref["quote"]) or (
                abbreviation and acronym == abbreviation[1] and candidate in ref["quote"].casefold())), None)
            if evidence is None:
                continue
            aliases.append({"private_grounding_row": number, "split": row["split"],
                            "constraint_id": link["constraint_id"], "alias_state": link["state"],
                            "main_state": row["constraint_states"][link["constraint_id"]]["state"],
                            "same_entity_evidence_sha256": sha256(evidence["quote"].encode()).hexdigest(),
                            "frozen_g_valid": row["g"] is not None})
    return {
        "target_unresolved_overlapping_flags": {reason: stat_rows(rows)
                                                for reason, rows in sorted(targets_by_reason.items())},
        "model_call_trace_sha256": digest(private / "model_call_trace.jsonl"),
        "full_trace_file_presence": {path.name: path.is_file() for path in (
            private / "all_annotation_errors.jsonl", private / "grounding_blockers.jsonl")},
        "no_final_terminal": dict(Counter(row["raw_termination_reason"] for row in ground if not row["has_final"])),
        "relevant_error_relation": dict(Counter(
            item["relation"] for row in ground if row["candidate"] for item in row["evidence_errors_relation"])),
        "development_cases_by_type": dict(Counter(row["case_kind"] for row in cases if row["split"] == "dev")),
        "verified_names": aliases,
        "verified_cross_key_supported_rows": sum(
            r["alias_state"] == "supported" and r["main_state"] == "unknown" for r in aliases),
        "verified_alias_affected_grounding_rows": len({r["private_grounding_row"] for r in aliases
            if r["alias_state"] == "supported" and r["main_state"] == "unknown"}),
    }


def select_cases(rows, identity, limit=5):
    selected = {}
    priority = {"dev": 0, "calibration": 1, "audit": 2}
    for row in sorted(rows, key=lambda row: priority[row["split"]]):
        selected.setdefault(identity(row), row)
        if len(selected) == limit:
            break
    return list(selected.values())


def case_evidence(private, output, summary):
    protected = output / "controlled"
    public = output / "sanitized"
    protected.mkdir(parents=True)
    public.mkdir()
    replay = private / "replay"
    quote_rows = jsonl(private / "quote_error_breakdown.jsonl")
    grounding = jsonl(private / "grounding_blockers.jsonl")
    routes = jsonl(private / "r1_reason_reconciliation.jsonl")
    risks = jsonl(private / "ledger_state_risks.jsonl")
    case_groups = {
        "Q1_multiple_matches": [r for r in quote_rows if r["match_class"] == "multiple"],
        "Q1_zero_matches": [r for r in quote_rows if r["match_class"] == "zero"],
        "Q2_task_constraint_abort": [r for r in quote_rows if r["component"] == "task_constraints"],
        "U1_batch_rejection": jsonl(private / "batch_failure_impact.jsonl"),
        "G1_retained_support_failed_history": [r for r in grounding if r["valid_support_count"] and
                                               "historical_evidence_error" in r["blockers"]],
        "G2_later_support_failed_history": [r for r in grounding if r["has_later_final_candidate_evidence"]],
        "R1_reason_mismatch": [r for r in routes if not r["called"] and
                              r["original_reason"] == "low_verification_confidence"],
        "R1_unresolved_action_target": [r for r in routes if r["primary_route"] == "target_unresolved"],
        "S1_distributed_gaps": [r for r in risks if r["kind"] == "distributed_open_gaps"],
        "S2_verified_name_link": [grounding[r["private_grounding_row"] - 1] for r in summary["verified_names"]],
        "GUARD_conflict_transition": [r for r in risks if r["kind"] == "conflict_transition"],
    }
    tool_events = {f"{r['trajectory_id']}:{r['event_id']}": r for r in jsonl(replay / "tool_events.jsonl")}
    snapshots = {r["event_id"]: r for r in jsonl(replay / "ledger_snapshots.jsonl") if r["event_id"]}
    traces = defaultdict(list)
    for row in jsonl(private / "model_call_trace.jsonl"):
        key = row["event_id"] or (row["component"], row["trajectory_id"] or row["question_id"])
        traces[key].append(row)
    ground_by_id = {r["trajectory_id"]: r for r in grounding}
    route_by_id = {r["event_id"]: r for r in routes}
    finals = {r["trajectory_id"]: r for r in jsonl(replay / "stages.jsonl") if r["stage_type"] == "final"}
    specs = {r["trajectory_id"]: r for r in jsonl(replay / "task_specs.jsonl")}
    events_by_trajectory = defaultdict(list)
    for event_id, event in tool_events.items():
        events_by_trajectory[event["trajectory_id"]].append(event_id)
    details, indices = [], []
    for mechanism, rows in case_groups.items():
        key = "question_id" if mechanism.startswith("Q2") else "trajectory_id"
        for row in select_cases(rows, lambda row: row[key]):
            trajectory = row["trajectory_id"]
            g = ground_by_id[trajectory]
            related = [row["event_id"]] if row.get("event_id") else []
            if mechanism.startswith("Q2"):
                related += events_by_trajectory[trajectory][:1]
            if mechanism.startswith(("G1", "G2")):
                related += [r["event_id"] for r in g["evidence_errors_relation"] if r["relation"] == "relevant"]
            if mechanism.startswith("S2"):
                alias_rows = [r for r in summary["verified_names"] if grounding[
                    r["private_grounding_row"] - 1]["trajectory_id"] == trajectory]
                quote_hashes = {r["same_entity_evidence_sha256"] for r in alias_rows}
                related += [f"{trajectory}:{ref['event_id']}"
                            for link in g["possible_candidate_name_links"] for ref in link["evidence"]
                            if sha256(ref["quote"].encode()).hexdigest() in quote_hashes]
            event_evidence = []
            for eid in dict.fromkeys(related):
                event = tool_events[eid]
                event_evidence.append({"action_and_return": event, "model_records": traces.get(eid, []),
                                       "validation_and_ledger": snapshots[eid], "r1": route_by_id[eid]})
            details.append({"mechanism": mechanism, "trigger_record": row, "events": event_evidence,
                            "task_extraction": traces[("task_constraints", row["question_id"])],
                            "task_validation": specs[trajectory], "final": finals.get(trajectory),
                            "final_extraction": traces[("final_candidate", trajectory)], "grounding": g})
            indices.append({"private_row": len(details), "mechanism": mechanism, "split": row["split"],
                            "reviewed_tool_events": len(event_evidence), "grounding": g["primary_blocker"],
                            "r1_routes": [record["r1"]["primary_route"] for record in event_evidence]})
    destination = protected / "real_cases.jsonl"
    write_jsonl(destination, details)
    write_jsonl(public / "real_cases.jsonl", indices)
    atomic_json(public / "case_evidence_manifest.json", {
        "source_replay": str(private), "protected_file": str(destination), "private_sha256": digest(destination),
        "rows": len(details), "row_numbering": "1-based",
        "selected": dict(Counter(r["mechanism"] for r in indices)),
        "available": {kind: stat_rows(rows) for kind, rows in case_groups.items()},
        "selection": "dev first, then calibration and audit; distinct trajectories, or questions for Q2",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cases-dir", type=Path)
    options = parser.parse_args()
    if any(options.private.resolve() == target.resolve() or options.private.resolve() in target.resolve().parents
           for target in (options.output, options.cases_dir) if target):
        raise SystemExit("supplemental report must use a new directory")
    summary = augment(options.private)
    atomic_json(options.output, summary)
    if options.cases_dir:
        case_evidence(options.private, options.cases_dir, summary)
