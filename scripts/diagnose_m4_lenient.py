"""Replay the lenient Phase 1 bundles without network access and select private samples."""

import argparse
from collections import Counter
from hashlib import sha256
from pathlib import Path

from diagnose_m4_gating import (
    FUNNEL, G_GATES, R1_GATES, REASONS, ReadOnlyJudge, RiskOrigins, distribution, grounding_gate,
    non_invocation_gate, populated, private_sample_row, replay_bundle, support_set, usable_return, write_new,
)
from redundancy_judge import cli
from redundancy_judge.common import candidate_name, identity, read_json
from redundancy_judge.init_task_ledger import initial_ledger
from redundancy_judge.update_evidence_ledger import support_key


LAYOUT = {
    "supported": (30, ("correct", "partially_correct", "incorrect")),
    "final": (20, ("correct", "incorrect")),
    "r1": (15, ("established", "not_established")),
    "uncertain": (20, tuple("abcde")),
}
LOCATION_METHODS = ("exact", "normalized", "multi", "absent")
LOCATION_FAILURES = {"empty evidence quote", "evidence quote not found in source"}


class Sample:
    def __init__(self, kind):
        self.limit = LAYOUT[kind][0]
        self.rows = []

    def add(self, identifier, payload):
        rank = sha256(("20261116|" + identifier).encode()).hexdigest()
        if len(self.rows) == self.limit and rank >= self.rows[-1][0]:
            return
        self.rows.append((rank, identifier, payload))
        self.rows.sort(key=lambda row: (row[0], row[1]))
        del self.rows[self.limit:]

    def packet(self):
        return [{"id": identifier, **payload} for _, identifier, payload in self.rows]


def final_review(bundle, judge, samples, counts):
    finals = [row["final_text"] for row in bundle["stages"] if row["stage_type"] == "final"]
    if not finals:
        counts["without_final"] += 1
        return
    counts["with_final"] += 1
    final = bundle["final_candidate"]
    if final is not None:
        ref = final["source"]
        if finals[-1][ref["start"]:ref["end"]] != ref["quote"]:
            raise RuntimeError("final candidate lost its original source coordinates")
        samples["final"].add(bundle["input_index"]["trajectory_id"],
                             {"question": bundle["input_index"]["question"],
                              "final_text": finals[-1], "candidate": final})
        counts["success"] += 1
    elif judge.final_response is None:
        counts["model_failure"] += 1
    elif judge.final_response["quote"] is None:
        counts["null"] += 1
    elif any(row["event_id"] is None and row["reason"] in LOCATION_FAILURES
             for row in bundle["annotation_failures"]):
        counts["location_failed"] += 1
    else:
        counts["other_failure"] += 1


def tool_reviews(bundle, judge, samples, aggregate):
    tid = bundle["input_index"]["trajectory_id"]
    task = bundle["task_specs"]
    constraints = {row["constraint_id"]: row for row in task["constraints"]}
    stages = {row["stage_id"]: row for row in bundle["stages"]}
    events = {f"{tid}:{row['event_id']}": row for row in bundle["tool_events"]}
    targets = {row["event_id"]: row for row in bundle["action_targets"]}
    snapshots = {row["event_id"]: row for row in bundle["ledger_snapshots"] if row["event_id"]}
    judgments = {row["event_id"]: row for row in bundle["stage_judgments"]}
    if not (events.keys() == targets.keys() == snapshots.keys() == judgments.keys()):
        raise RuntimeError(f"tool records do not reconcile for {tid}")
    used_candidates = set()
    invoked_count = 0
    funnel, gates = aggregate["funnel"], aggregate["r1_gates"]
    for eid, decision in judgments.items():
        event, target, snap = events[eid], targets[eid], snapshots[eid]
        stage = stages[decision["stage_id"]]
        delta = snap["delta"]
        invoked = decision["diagnostics"]["r1_funnel"]["outcome"] != "not_invoked"
        invoked_count += invoked
        funnel["candidate_events"] += 1
        funnel["entered_verification"] += invoked
        funnel["r1_positive"] += any(label["label"] == "R1" and label["decision"] == "positive"
                                     for label in decision["labels"])
        if usable_return(stage, event):
            funnel["usable_tool_return"] += 1
            if not task["uncertain"] and constraints:
                funnel["usable_return_and_task"] += 1
                if target["state"] != "resolved":
                    raw_present = judge.target.get(event["event_id"])
                    funnel["target_unresolved"] += 1
                    funnel["unresolved_raw_candidate_missing"] += raw_present is False
                    funnel["unresolved_candidate_response_unavailable"] += raw_present is None
        if not invoked:
            gate = non_invocation_gate(snap["before"], stage, event, target, decision)
            if gate in {"global_risk", "local_risk"}:
                gate = ("local_risk" if decision["diagnostics"]["r1_funnel"]["reason"] == "unresolved_evidence_risk"
                        else "other")
            gates[gate] += 1
        else:
            fact = snap["before"]["support"][support_key(target["candidate"], target["constraint_id"])]
            samples["r1"].add(eid, {
                "prior_fact": fact, "target": target, "constraint": constraints[target["constraint_id"]],
                "arguments": event["arguments"], "strategy": stage.get("strategy_text"),
                "visible_return_ids": stage["visible_return_ids"], "return_text": event["return_text"],
                "prior_returns": [events[f'{tid}:{ref["event_id"]}']["return_text"] for ref in fact["evidence"]],
            })
        aggregate["locations"].update(delta["quote_locations"])
        aggregate["unknown_dropped"] += delta["unknown_dropped"]
        used_candidates.update(delta["new_candidates"])
        if delta["uncertain"]:
            receipt = judge.evidence[event["event_id"]]
            samples["uncertain"].add(eid, private_sample_row(bundle, snap, event, receipt))
            aggregate["uncertain"] += 1
        for i, ref in enumerate(delta["evidence"], 1):
            if ref["state"] == "supported":
                fact = snap["after"]["support"][ref["support_key"]]
                samples["supported"].add(f"{eid}:{i}", {
                    "candidate": fact["candidate"], "constraint": constraints[fact["constraint_id"]],
                    "quote": ref, "return_text": event["return_text"],
                })
                aggregate["supported_rows_accepted"] += 1
    if invoked_count != judge.r1_calls:
        raise RuntimeError(f"R1 receipts do not reconcile for {tid}")
    aggregate["new_candidates"] += len(used_candidates)


def run_diagnosis(run, expected_code):
    config = cli.config_file(run / "config.json")
    real = run / "real"
    manifest = read_json(real / "run_manifest.json")
    freeze = manifest["freeze"]
    index_path = Path(config["input_index"])
    index = cli.jsonl(index_path)
    if (config["mode"] != "real" or manifest["synthetic"] or expected_code != freeze["code_commit"]
            or Path(config["output_dir"]).resolve() != run.resolve() or len(index) != 400
            or len({row["question_id"] for row in index}) != 100
            or sha256(index_path.read_bytes()).hexdigest() != freeze["input_index_sha256"]
            or any(freeze[key] != value for key, value in cli.freeze_config(config).items())):
        raise RuntimeError("run inventory or frozen identity differs")
    judge = ReadOnlyJudge(config, real / "model_cache", freeze)
    if judge.prompt_sha256 != freeze["prompt_sha256"] or judge.protocol_version != cli.JUDGE_PROTOCOL_VERSION:
        raise RuntimeError("unexpected prompt or Judge protocol")
    tokenizer = cli.NativeByteTokenizer(config["tokenizer"], config["tokenizer_revision"]) if config.get("tokenizer") else None
    legacy = cli.load_legacy(config)
    counts = {k: Counter() for k in ("funnel", "r1_gates", "g_gates", "global", "local", "locations", "final")}
    counts.update(unknown_dropped=0, uncertain=0, new_candidates=0, supported_rows_accepted=0)
    samples = {kind: Sample(kind) for kind in LAYOUT}
    global_per_trajectory, facts, g_values = [], [], []
    g_with_global = 0
    for row in index:
        tid = row["trajectory_id"]
        bundle = read_json(real / "bundles" / (identity([freeze, row["sha256"], tid]) + ".json"))
        replay_bundle(bundle, row, judge, tokenizer, legacy[tid], freeze, config)
        tool_reviews(bundle, judge, samples, counts)
        final_review(bundle, judge, samples, counts["final"])
        snapshots = bundle["ledger_snapshots"]
        ledger = snapshots[-1]["after"] if snapshots else initial_ledger(bundle["task_specs"])
        origins = RiskOrigins(bundle, judge.evidence)
        global_risks, local_risks = origins.count(ledger, "global"), origins.count(ledger, "support")
        counts["global"].update(global_risks)
        counts["local"].update(local_risks)
        summary = bundle["trajectory_summaries"]
        global_count = sum(global_risks.values())
        if global_count != summary["global_risk_count"]:
            raise RuntimeError(f"global risk count differs for {tid}")
        global_per_trajectory.append(global_count)
        facts.append(len(support_set(ledger)))
        gate = grounding_gate(bundle, ledger)
        if gate == "global_risk":
            gate = "local_risk" if summary["grounding_issue"] == "unresolved_evidence_risk" else "other"
        counts["g_gates"][gate] += 1
        if summary["g"] is not None:
            g_values.append(summary["g"])
            g_with_global += global_count > 0
    r1, g, funnel, final = (counts[key] for key in ("r1_gates", "g_gates", "funnel", "final"))
    if (sum(r1.values()) + funnel["entered_verification"] != funnel["candidate_events"]
            or sum(g.values()) != len(index) or counts["global"]["uncertain"] != counts["uncertain"]
            or final["with_final"] != sum(final[k] for k in ("success", "null", "location_failed",
                                                            "other_failure", "model_failure"))):
        raise RuntimeError("diagnostic counts do not reconcile")
    return {
        "trajectories": len(index), "bundles_matched_by_cache_replay": len(index), "new_model_requests": 0,
        "risk": {
            "global_records": sum(counts["global"].values()), "local_records": sum(counts["local"].values()),
            "trajectories_with_global_risk": sum(count > 0 for count in global_per_trajectory),
            "global_risks_per_trajectory": distribution(global_per_trajectory),
            "global_by_source": populated(counts["global"], REASONS), "local_by_source": populated(counts["local"], REASONS),
        },
        "r1": {"not_invoked": sum(r1.values()), "not_invoked_by_gate": populated(r1, R1_GATES),
               "funnel": populated(funnel, FUNNEL)},
        "g": {"valid": g["valid"], "empty": len(index) - g["valid"], "empty_by_gate": populated(g, G_GATES),
              "distribution": distribution(g_values, histogram=True), "valid_with_global_risk": g_with_global},
        "evidence": {
            "uncertain": counts["uncertain"], "unknown_dropped": counts["unknown_dropped"],
            "quote_locations": populated(counts["locations"], LOCATION_METHODS),
            "new_candidates": counts["new_candidates"], "supported_rows_accepted": counts["supported_rows_accepted"],
            "supported_facts": sum(facts), "trajectories_with_supported_fact": sum(value > 0 for value in facts),
            "supported_facts_per_trajectory": distribution(facts),
        },
        "final": populated(final, ("with_final", "without_final", "success", "null", "location_failed",
                                   "model_failure", "other_failure")),
    }, {kind: sample.packet() for kind, sample in samples.items()}


def spot_receipt(packet, labels):
    if set(packet) != set(labels) or set(packet) != set(LAYOUT):
        raise ValueError("sample groups do not reconcile")
    result = {}
    for kind, rows in packet.items():
        ordered_ids = [row["id"] for row in rows]
        classes = LAYOUT[kind][1]
        assignments = labels[kind]
        if set(ordered_ids) != set(assignments) or any(label not in classes for label in assignments.values()):
            raise ValueError(f"manual labels must match all selected IDs for {kind}")
        buckets = {label: [eid for eid in ordered_ids if assignments[eid] == label] for label in classes}
        result[kind] = {"sample_size": len(ordered_ids), "labels": {
            label: {"count": len(ids), "ids": ids} for label, ids in buckets.items()}}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    diagnose = commands.add_parser("diagnose")
    for name in ("run", "output", "private-packet"):
        diagnose.add_argument("--" + name, type=Path, required=True)
    diagnose.add_argument("--code-commit", required=True)
    spot = commands.add_parser("spot")
    for name in ("private-packet", "labels", "output"):
        spot.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "spot":
        write_new(args.output, spot_receipt(read_json(args.private_packet), read_json(args.labels)))
    else:
        run = args.run.resolve()
        targets = [path.resolve() for path in (args.output, args.private_packet)]
        if any(path == run or run in path.parents or path.exists() for path in targets):
            parser.error("reports must be new files outside the sealed run directory")
        diagnostics, packet = run_diagnosis(run, args.code_commit)
        write_new(args.private_packet, packet)
        write_new(args.output, diagnostics)


if __name__ == "__main__":
    main()
