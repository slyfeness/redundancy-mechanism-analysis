"""Export DocID comparison and provisional-only M9 dry-run summaries."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import math
from pathlib import Path

from redundancy_judge.build_grpo_inputs import build_grpo_inputs, freeze_identity
from redundancy_judge.cli import jsonl, write_jsonl
from redundancy_judge.common import atomic_json, read_json
from r2a_price_whatif import distribution


def decisions(row):
    return {label["label"]: label for label in row["labels"]}


def compare(judgments, reference):
    ref = {row["event_id"]: row for row in reference}
    actual = {row["event_id"]: row for row in judgments}
    if len(ref) != len(reference) or len(actual) != len(judgments):
        raise ValueError("duplicate event ID")
    out = {"reference_job": 187333, "reference_events": len(ref), "observed_events": len(actual),
           "missing_event_ids": sorted(ref.keys() - actual.keys()), "extra_event_ids": sorted(actual.keys() - ref.keys())}
    shared = ref.keys() & actual.keys()
    out["result_label_mismatches"] = [
        {"event_id": eid, "expected": ref[eid]["main"], "actual": actual[eid]["diagnostics"]["result_label"]}
        for eid in sorted(shared) if ref[eid]["main"] != actual[eid]["diagnostics"]["result_label"]]
    for name, expected in (("R2b", {"repeat_query"}), ("R2a", {"no_new_information", "repeat_evidence"})):
        counts = Counter()
        mismatches = []
        for eid in sorted(shared):
            row = actual[eid]
            predicted = decisions(row)[name]
            bench = ref[eid]["main"] in expected
            observed = predicted["decision"] == "positive"
            counts[f"reference_{int(bench)}_actual_{int(observed)}"] += 1
            if bench != observed:
                reason = row["protections"] or [predicted["abstention_reason"] or
                          ("selected_R2b" if decisions(row)["R2b"]["decision"] == "positive"
                           else "label_precondition_difference")]
                mismatches.append({"event_id": eid, "reference": int(bench), "positive": int(observed), "reason": reason})
        out[name] = {"table": {f"reference_{i}_actual_{j}": counts[f"reference_{i}_actual_{j}"]
                               for i in (0, 1) for j in (0, 1)}, "mismatches": mismatches,
                     "reason_counts": Counter(reason for row in mismatches for reason in row["reason"])}
    out["result_labels_match"] = int(not (out["result_label_mismatches"] or out["missing_event_ids"] or out["extra_event_ids"]))
    return out


def dryrun(run, config, summaries, spot_file):
    spot = read_json(spot_file)
    categories = spot["categories"]
    repeat = categories["repeat_query"]["checks"]["same_query_without_gain"]
    weak = [categories[group]["checks"]["no_useful_gain"] for group in ("definite_nonexact", "soft")]
    if not (repeat["yes"] == 10 and repeat["no"] == 0 and all(c["yes"] == 20 and c["no"] == 0 for c in weak)):
        raise ValueError("frozen 187333 audit does not satisfy the requested provisional evidence")
    identity = freeze_identity(read_json(run / "real/run_manifest.json")["freeze"])
    approvals = {label: {"status": "PASS", "provenance": identity, "synthetic": False,
                         "provisional": True, "source_job": 187333, "reviewed_count": count}
                 for label, count in (("R2b", 10), ("R2a", 40))}
    atomic_json(run / "provisional_labels.private.json", approvals)
    options = {**config["reward"], "enable_optimizer_step": False}
    if config.get("cost_weighted"):
        options.update(price_mode="cost_weighted", reference_cost=read_json(run / "real/reference_cost.json"))
    result = build_grpo_inputs(summaries, options, approved_labels=approvals)
    groups = result["groups"]
    if result["formal_training_usable"] or result["optimizer_steps"]:
        raise RuntimeError("dry run made training usable")
    flat = [row for group in groups for row in group["trajectories"]]
    private = [{**g, "trajectories": [{k: v for k, v in r.items() if k != "token_advantages"}
                                     for r in g["trajectories"]]} for g in groups]
    write_jsonl(run / "provisional_reward_dryrun.jsonl", private)
    by_tid = {}
    for row in flat:
        event_cost = {event["event_id"]: event["debit"] for event in row["event_debits"]}
        by_tid[row["trajectory_id"]] = {"R": row["R"], "g": row["g"],
                                       "debit": math.fsum(event_cost.values()), "event_debits": event_cost}
    reasons = Counter(reason for g in result["excluded"] for reason in
                      [*g["group_reasons"], *set(g["row_reasons"].values())])
    atomic_json(run / "grpo_dryrun_summary.json", {
        "provisional": 1, "optimizer_steps": 0, "assertions": {key: int(val) for key, val in result["assertions"].items()},
        "computed_groups": len(groups), "excluded_groups": len(result["excluded"]), "excluded_group_reasons": reasons,
        "excluded": result["excluded"], "trajectories": len(flat),
        "R": distribution(row["R"] for row in flat),
        "event_debit": distribution(e["debit"] for row in flat for e in row["event_debits"]),
        "trajectory_debit": distribution(row["debit"] for row in by_tid.values()),
        "cap_triggers": sum(row["scale"] < 1 for row in flat),
        "groups_with_no_correct": sum(not any(r["Y"] for r in g["trajectories"]) for g in groups),
        "exempt_events_no_correct_in_group": sum(len(r["event_debits"]) for g in groups
            if not any(r["Y"] for r in g["trajectories"]) for r in g["trajectories"]),
        "r1_priced_events": sum(e["label"] == "R1" for r in flat for e in r["event_debits"]),
        "per_trajectory": by_tid,
    })


def export(run, trial_labels, spot):
    config = read_json(run / "config.json")
    phase = run / "real"
    judgments = jsonl(phase / "stage_judgments.jsonl")
    summaries = jsonl(phase / "trajectory_summaries.jsonl")
    with_final = {"has_final": [], "no_final": []}
    for row in summaries:
        if row["g"] is not None:
            with_final["has_final" if row["raw_termination_reason"] == "MODEL_FINAL_STOP" else "no_final"].append(row["g"])
    model = [read_json(p) for p in (phase / "model_cache").glob("*/*.json")]
    m3 = [read_json(p) for p in (phase / "m3_call_receipts").glob("*.json")]
    counts = Counter(f"{label['label']}:{label['decision']}" for row in judgments for label in row["labels"])
    atomic_json(run / "docid_phase1_summary.json", {
        "trajectories": len(summaries), "events": len(judgments),
        "labels": {name: {decision: counts[f"{name}:{decision}"] for decision in ("positive", "negative", "abstain")}
                   for name in ("R2b", "R2a", "R1")},
        "R2a_subtypes": Counter(row["diagnostics"]["r2a_subtype"] for row in judgments if row["diagnostics"]["r2a_subtype"]),
        "protections": Counter(p for row in judgments for p in row["protections"]),
        "g": distribution(v for values in with_final.values() for v in values),
        "g_valid": sum(map(len, with_final.values())), "g_by_final": {key: {"count": len(val), **distribution(val)}
                                                                    for key, val in with_final.items()},
        "model_calls": {"M3": len(m3), "M5": len(model), "M4": 0, "legacy_R1_verification": 0,
                        "M3_failures": sum(bool(r["failure"]) for r in m3),
                        "M5_failures": sum("failure" in r for r in model),
                        "M5_sum_request_seconds": round(sum(r.get("seconds", 0) for r in model), 3)},
    })
    r = Path(trial_labels)
    labels = jsonl(r)
    codebook = read_json(r.with_name("result_labels.json"))["codebook"]["main"]
    by_code = {code: name for name, code in codebook.items()}
    reference = [{**row, "main": by_code[row["main"]]} for t in labels for row in t["events"]]
    atomic_json(run / "consistency_vs_187333.json", compare(judgments, reference))
    dryrun(run, config, summaries, spot)
    return m3, judgments


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "trial_labels", "spot"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    export(args.run, args.trial_labels, args.spot)
