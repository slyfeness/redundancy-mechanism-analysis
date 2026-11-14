"""Compute supplemental event rollups from sealed diagnosis records."""

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re

from diagnose_phase1_ledger import digest, stat_rows
from redundancy_judge.cli import jsonl
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
                            "same_entity_evidence_sha256": __import__("hashlib").sha256(
                                evidence["quote"].encode()).hexdigest(),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    if options.private.resolve() in options.output.resolve().parents:
        raise SystemExit("supplemental report must use a new directory")
    atomic_json(options.output, augment(options.private))
