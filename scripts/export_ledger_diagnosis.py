"""Project controlled ledger diagnosis files to disclosure-safe indices."""

import argparse
from pathlib import Path

from diagnose_phase1_ledger import digest
from redundancy_judge.cli import jsonl, write_jsonl
from redundancy_judge.common import atomic_json, read_json


FIELDS = {
    "quote_error_breakdown": ("split", "component", "failure_ordinal", "reason", "matches", "match_class",
                              "diagnostic_flags", "downstream_status", "effective_gain", "retained_updates"),
    "all_annotation_errors": ("split", "component", "reason", "failure_ordinal", "downstream_status"),
    "grounding_blockers": ("split", "result", "g", "has_final", "raw_termination_reason",
                           "candidate_missing_detail", "constraints_status", "constraints_uncertain",
                           "constraint_count", "valid_support_count", "has_later_final_candidate_evidence",
                           "primary_blocker", "blockers", "reward_exclusion_reason"),
    "r1_reason_reconciliation": ("split", "original_decision", "original_reason", "primary_route",
                                 "all_blockers", "delta_status", "delta_gain", "ledger_only_verification_gate",
                                 "called", "cache_hit", "r1_price_eligible", "chosen_price"),
    "batch_failure_impact": ("split", "error"),
    "real_cases": ("split", "case_kind", "match_class", "component", "reason", "grounding", "r1_route"),
}


def export(private, public):
    public.mkdir(parents=True, exist_ok=False)
    private_index = {}
    for name, fields in FIELDS.items():
        path = private / (name + ".jsonl")
        rows = jsonl(path)
        private_index[path.name] = {"sha256": digest(path), "rows": len(rows)}
        write_jsonl(public / path.name, ({"private_row": number, **{key: row[key] for key in fields if key in row}}
                                         for number, row in enumerate(rows, 1)))
    for name in ("summary", "r1_funnel", "replay_checks"):
        filename = name + ".json"
        (public / filename).write_bytes((private / filename).read_bytes())
    check = private / "input_manifest.json"
    manifest = read_json(check)
    for name in ("model_call_trace", "ledger_state_risks"):
        path = private / (name + ".jsonl")
        private_index[path.name] = {"sha256": digest(path)}
    for key in ("before", "after"):
        manifest.pop(key)
    atomic_json(public / "input_manifest.json", {**manifest, "protected_directory": str(private),
                "complete_private_input_manifest_sha256": digest(check), "private_results": private_index,
                "row_numbering": "1-based line number in the indicated controlled file"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", required=True, type=Path)
    parser.add_argument("--public", required=True, type=Path)
    opts = parser.parse_args()
    export(opts.private, opts.public)
