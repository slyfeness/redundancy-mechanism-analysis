"""Read sealed Phase 1.1 bundles and model receipts. Emit counts and event IDs only."""

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
from statistics import median
from unittest.mock import patch

from redundancy_judge import cli
from redundancy_judge.common import JudgeFailure, candidate_name, canonical, identity, read_json
from redundancy_judge.init_task_ledger import initial_ledger
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.summarize_trajectory import summarize_trajectory
from redundancy_judge.update_evidence_ledger import (
    _mention,
    _uncertainty_coordinates,
    merge_parallel_updates,
    support_key,
    unresolved_risks,
    update_evidence_ledger,
)


SPAN = "evidence quote does not match its character span"
UNCERTAIN = "evidence extraction uncertain"
INVALID = "invalid support coordinates or state"
REASONS = ("uncertain", "span_mismatch", "state_unknown_rejected", "invalid_coordinates", "other")
R1_GATES = ("no_usable_tool_return", "unresolved_target", "prior_not_supported",
            "global_risk", "local_risk", "other")
G_GATES = ("no_final", "final_candidate_extraction_failed", "task_uncertain",
           "global_risk", "local_risk", "other")
FUNNEL = ("candidate_events", "usable_tool_return", "usable_return_and_task", "target_unresolved",
          "unresolved_raw_candidate_missing", "unresolved_candidate_response_unavailable",
          "entered_verification", "r1_positive")
CODE = "bd32aa4cc4664d20d448480e0d04cc8ccb0f2e01"
LOCALIZATION_GATES = ("nonempty_update_list", "no_scope_object", "scope_candidate_not_previously_known",
                      "scope_constraint_invalid", "scope_constraint_text_not_unique_in_return",
                      "scope_candidate_not_unique_in_return", "scope_span_not_exact_full_return", "localized")


def populated(counter, keys):
    return {key: counter.get(key, 0) for key in keys}


def distribution(values, *, histogram=False):
    result = {"min": min(values), "median": median(values), "max": max(values)} if values else {
        "min": None, "median": None, "max": None}
    if histogram:
        result["histogram"] = dict(sorted(Counter(values).items()))
    return result


def write_new(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def unique_span(text, quote):
    if not isinstance(quote, str) or not quote:
        return None
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        return None
    return start, start + len(quote)


def select_sample(events):
    return sorted(events, key=lambda eid: sha256(f"20261115|{eid}".encode()).hexdigest())[:30]


def sample_receipt(selected, labels):
    if set(labels) != set(selected) or any(label not in "abcde" or len(label) != 1
                                          for label in labels.values()):
        raise ValueError("manual labels must cover exactly the selected events")
    groups = {letter: [eid for eid in selected if labels[eid] == letter] for letter in "abcde"}
    return {letter: {"count": len(ids), "event_ids": ids} for letter, ids in groups.items()}


class ObservedEvidence:
    """Serve a previously observed M4 response or its cached failure."""

    protocol_version = cli.JUDGE_PROTOCOL_VERSION

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.span_failures = []
        self.served = False

    def ask(self, kind, _payload):
        if kind != "evidence_update":
            raise RuntimeError("diagnostic can only serve the recorded evidence response")
        self.served = True
        if self.error is not None:
            raise JudgeFailure(self.error)
        return self.response


class ReadOnlyJudge(cli.ModelJudge):
    def __init__(self, config, cache, freeze):
        super().__init__(config["judge"], config["prompt_dir"], cache, freeze, replay_only=True)
        self.opener = None
        self.clear()

    def clear(self):
        self.event_id = None
        self.target = {}
        self.evidence = {}
        self.r1_calls = 0
        self.final_response = None

    def ask(self, kind, payload):
        if kind == "r1_verification":
            self.r1_calls += 1
        try:
            result = super().ask(kind, payload)
        except JudgeFailure as exc:
            if str(exc) in {"replay cache entry is missing", "cache identity mismatch"}:
                raise RuntimeError("sealed cache missing or invalid during diagnosis") from None
            if kind == "evidence_update":
                self.evidence[self.event_id] = ObservedEvidence(error=str(exc))
            raise
        if kind == "evidence_update":
            self.evidence[self.event_id] = ObservedEvidence(result)
        if kind == "action_target":
            self.target[self.event_id] = bool(candidate_name(result.get("candidate")))
        if kind == "final_candidate":
            self.final_response = result
        return result


def replay_bundle(bundle, row, judge, tokenizer, legacy, freeze, config):
    """Rebuild the production cache keys and verify the entire archived bundle."""
    judge.clear()
    ledger_module = import_module("redundancy_judge.update_evidence_ledger")
    original_quote = ledger_module.exact_quote

    def target_at_event(task, before, stage, client, **kwargs):
        action = stage.get("action") or {}
        judge.event_id = action.get("event_id") or stage["event_ids"][0]
        return original_target(task, before, stage, client, **kwargs)

    def observed_quote(text, raw_row):
        try:
            return original_quote(text, raw_row)
        except JudgeFailure as exc:
            if str(exc) == SPAN:
                receipt = judge.evidence[judge.event_id]
                receipt.span_failures.append(next(
                    i for i, item in enumerate(receipt.response["updates"]) if item is raw_row))
            raise

    original_target = cli.resolve_action_target
    with patch.object(cli, "resolve_action_target", target_at_event), patch.object(
            ledger_module, "exact_quote", observed_quote):
        replayed = cli.annotate_one(row, bundle["task_specs"], initial_ledger(bundle["task_specs"]),
                                    judge, tokenizer, legacy, freeze, config)
    if canonical(replayed) != canonical(bundle):
        raise RuntimeError(f"cache replay differs from bundle for {row['trajectory_id']}")


def risk_records(ledger, scope):
    risks = ledger["unresolved_evidence_risk"]
    if scope == "global":
        return risks["global"]
    return [record for rows in risks["by_support"].values() for record in rows]


class RiskOrigins:
    def __init__(self, bundle, evidence):
        self.raw_unknown = Counter()
        self.raw_other_invalid = Counter()
        self.valid = {row["constraint_id"] for row in bundle["task_specs"]["constraints"]}
        for eid, receipt in evidence.items():
            body = receipt.response
            if not body or body["uncertain"]:
                continue
            for row in body["updates"]:
                if not isinstance(row, dict):
                    continue
                candidate, cid, state = candidate_name(row.get("candidate")), row.get("constraint_id"), row.get("state")
                cid = cid if isinstance(cid, str) else None
                if state == "unknown":
                    self.raw_unknown[eid, candidate, cid] += 1
                elif not isinstance(state, str):
                    self.raw_other_invalid[eid, candidate, cid] += 1

    def count(self, ledger, scope):
        unknown = self.raw_unknown.copy()
        counts = Counter()
        for record in risk_records(ledger, scope):
            reason = record["reason"]
            if reason == UNCERTAIN:
                counts["uncertain"] += 1
            elif reason == SPAN:
                counts["span_mismatch"] += 1
            elif reason == INVALID:
                key = (record["event_id"], record["candidate"], record["constraint_id"])
                collapsed = record["state"] == "unknown"
                if collapsed and unknown[key]:
                    if self.raw_other_invalid[key]:
                        raise RuntimeError("literal unknown and coercion share one archived risk identity")
                    counts["state_unknown_rejected"] += 1
                    unknown[key] -= 1
                elif not record["candidate"] or record["constraint_id"] not in self.valid:
                    counts["invalid_coordinates"] += 1
                else:
                    counts["other"] += 1
            else:
                counts["other"] += 1
        return counts


def usable_return(stage, event):
    return (stage["parse_status"] == "ok" and bool(event["visible_next"])
            and isinstance(event.get("return_text"), str) and not event.get("error"))


def non_invocation_gate(before, stage, event, target, judgment):
    if not usable_return(stage, event):
        return "no_usable_tool_return"
    if target["state"] != "resolved":
        return "unresolved_target"
    if before["support"].get(support_key(target["candidate"], target["constraint_id"]), {}).get("state") != "supported":
        return "prior_not_supported"
    reason = judgment["risk_guard_reason"]
    if reason == "global_unresolved_evidence":
        return "global_risk"
    if judgment["risk_guard_refs"]:
        return "local_risk"
    return "other"


def without_global(ledger, keys=None):
    local = ledger["unresolved_evidence_risk"]["by_support"]
    return {**ledger, "unresolved_evidence_risk": {"global": [], "by_support": local if keys is None else {
        key: local[key] for key in keys if key in local}}}


class VerificationReached(Exception):
    pass


class VerificationProbe:
    def ask(self, kind, _payload):
        if kind != "r1_verification":
            raise RuntimeError("unexpected request in R1 gate probe")
        raise VerificationReached


def verification_without_global(task, before, after, stage, event, target, delta, *, threshold):
    key = support_key(target["candidate"], target["constraint_id"])
    try:
        judge_stage(task, without_global(before, [key]), without_global(after, [key]),
                    stage, event, target, delta, VerificationProbe(), threshold=threshold)
    except VerificationReached:
        return True
    return False


def submitted_candidate(bundle):
    return candidate_name((bundle["final_candidate"] or {}).get("candidate"))


def grounding_gate(bundle, ledger):
    if bundle["trajectory_summaries"]["g"] is not None:
        return "valid"
    if not any(stage["stage_type"] == "final" for stage in bundle["stages"]):
        return "no_final"
    candidate = submitted_candidate(bundle)
    if not candidate:
        return "final_candidate_extraction_failed"
    task = bundle["task_specs"]
    if task["uncertain"] or not task["constraints"]:
        return "task_uncertain"
    if risk_records(ledger, "global"):
        return "global_risk"
    if unresolved_risks(ledger, candidate=candidate,
                        constraint_ids=[row["constraint_id"] for row in task["constraints"]]):
        return "local_risk"
    return "other"


def grounding_without_global(bundle, ledger):
    if not any(stage["stage_type"] == "final" for stage in bundle["stages"]):
        return None
    result = summarize_trajectory({}, bundle["task_specs"], without_global(ledger), [], [],
                                  submitted_candidate=submitted_candidate(bundle))
    return result["g"]


def replay_repairs(bundle, evidence):
    """Apply B/C to observed M4 replies in order, including frozen parallel merges."""
    task = bundle["task_specs"]
    events = {event["event_id"]: event for event in bundle["tool_events"]}
    tid = bundle["input_index"]["trajectory_id"]
    snapshots = {row["event_id"]: row for row in bundle["ledger_snapshots"] if row["event_id"]}
    ledger = initial_ledger(task)
    counts = Counter()
    for stage in bundle["stages"]:
        if stage["stage_type"] != "tool":
            continue
        branches = []
        for eid in stage["event_ids"]:
            event = events[eid]
            event_stage = stage
            if stage["parallel_group_id"] and stage["parse_status"] == "ok":
                event_stage = {**stage, "action": {key: event[key] for key in (
                    "tool_name", "arguments", "call_id", "event_id", "environment", "deterministic", "dispatch_time")}}
            observed = evidence.get(eid)
            fixed = {}
            if observed is None:
                client = ObservedEvidence(error="diagnostic has no original evidence response")
            else:
                response = deepcopy(observed.response)
                if response and not response["uncertain"]:
                    for i in observed.span_failures:
                        row = response["updates"][i]
                        if span := unique_span(event["return_text"], row["quote"]):
                            row["start"], row["end"] = span
                            fixed[support_key(candidate_name(row["candidate"]), row["constraint_id"])] = span
                    response["updates"] = [row for row in response["updates"]
                                           if not isinstance(row, dict) or row.get("state") != "unknown"]
                client = ObservedEvidence(response, observed.error)
            # Keep the observed call schedule fixed so repairing one response
            # cannot suppress another response that the original run saw.
            prefix = ledger
            if observed is not None:
                content_id = identity(event["return_text"])
                prefix = {**ledger, "attempts": [
                    {**attempt, "status": "diagnostic_observed"}
                    if attempt["content_id"] == content_id and attempt["status"] == "ok" else attempt
                    for attempt in ledger["attempts"]
                ]}
            after, delta = update_evidence_ledger(task, prefix, event_stage, event, client)
            if client.served != (observed is not None):
                raise RuntimeError("counterfactual evidence call schedule differs from the original")
            after["attempts"] = ledger["attempts"] + after["attempts"][len(ledger["attempts"]):]
            original_rejected = snapshots[f"{tid}:{eid}"]["delta"]["rejected_evidence"]
            if sum(record["reason"] == SPAN for record in original_rejected) != len(
                    observed.span_failures if observed else []):
                raise RuntimeError("recorded span failures do not match the original rejected rows")
            counts["span_rows_originally_rejected"] += len(observed.span_failures) if observed else 0
            counts["span_rows_with_unique_literal"] += len(fixed)
            counts["span_rows_accepted"] += sum(
                fixed.get(ref["support_key"]) == (ref["start"], ref["end"]) for ref in delta["evidence"])
            branches.append((after, delta))
        if branches:
            ledger = merge_parallel_updates(task, ledger, branches) if stage["parallel_group_id"] else branches[0][0]
    return ledger, counts


def support_set(ledger):
    return {key for key, fact in ledger["support"].items() if fact["state"] == "supported"}


def localization_details(task, before, text, response):
    normalized = candidate_name(text) or ""
    known = {fact["candidate"] for fact in before["support"].values()}
    mentioned = {row["constraint_id"] for row in task["constraints"]
                 if _mention(normalized, candidate_name(row.get("text")))}
    scope = response.get("uncertainty_scope")
    if response["updates"]:
        gate = "nonempty_update_list"
    elif not isinstance(scope, dict):
        gate = "no_scope_object"
    else:
        candidate, cid = candidate_name(scope.get("candidate")), scope.get("constraint_id")
        if candidate not in known:
            gate = "scope_candidate_not_previously_known"
        elif not isinstance(cid, str) or cid not in {row["constraint_id"] for row in task["constraints"]}:
            gate = "scope_constraint_invalid"
        elif mentioned != {cid}:
            gate = "scope_constraint_text_not_unique_in_return"
        elif not _mention(normalized, candidate) or any(_mention(normalized, other) for other in known - {candidate}):
            gate = "scope_candidate_not_unique_in_return"
        else:
            gate = "localized" if _uncertainty_coordinates(text, scope, task, before)[0] else (
                "scope_span_not_exact_full_return")
    return gate, not known, not mentioned


def private_sample_row(bundle, snapshot, event, receipt):
    return {
        "event_id": snapshot["event_id"],
        "constraints": bundle["task_specs"]["constraints"],
        "known_facts": [{"candidate": row["candidate"], "constraint_id": row["constraint_id"], "state": row["state"]}
                        for row in snapshot["before"]["support"].values()],
        "tool_name": event.get("tool_name"),
        "arguments": event.get("arguments"),
        "error": event.get("error"),
        "visible_next": event["visible_next"],
        "return_text": event.get("return_text"),
        "evidence_response": receipt.response,
    }


def summarize_bundle(bundle, judge, counts, selected, sample, *, counterfactual, threshold):
    tid = bundle["input_index"]["trajectory_id"]
    task = bundle["task_specs"]
    stages = {stage["stage_id"]: stage for stage in bundle["stages"]}
    snapshots = {row["event_id"]: row for row in bundle["ledger_snapshots"] if row["event_id"]}
    events = {f"{tid}:{event['event_id']}": event for event in bundle["tool_events"]}
    targets = {row["event_id"]: row for row in bundle["action_targets"]}
    judgments = {row["event_id"]: row for row in bundle["stage_judgments"]}
    if not (events.keys() == targets.keys() == judgments.keys() == snapshots.keys()):
        raise RuntimeError(f"bundle event IDs do not reconcile for {tid}")
    entered = 0
    for eid, decision in judgments.items():
        event, target, snap = events[eid], targets[eid], snapshots[eid]
        stage = stages[decision["stage_id"]]
        if stage["parallel_group_id"] and stage["parse_status"] == "ok":
            stage = {**stage, "action": snap["after"]["attempts"][-1]["action"]}
        invoked = decision["diagnostics"]["r1_funnel"]["outcome"] != "not_invoked"
        entered += invoked
        counts["funnel"]["candidate_events"] += 1
        counts["funnel"]["entered_verification"] += invoked
        counts["funnel"]["r1_positive"] += any(
            row["label"] == "R1" and row["decision"] == "positive" for row in decision["labels"])
        if usable_return(stage, event):
            counts["funnel"]["usable_tool_return"] += 1
            if not task["uncertain"] and task["constraints"]:
                counts["funnel"]["usable_return_and_task"] += 1
                if target["state"] != "resolved":
                    raw = judge.target.get(event["event_id"])
                    counts["funnel"]["target_unresolved"] += 1
                    counts["funnel"]["unresolved_raw_candidate_missing"] += raw is False
                    counts["funnel"]["unresolved_candidate_response_unavailable"] += raw is None
        if not invoked:
            gate = non_invocation_gate(snap["before"], stage, event, target, decision)
            counts["r1"][gate] += 1
            if counterfactual and gate == "global_risk":
                counts["a_r1"] += verification_without_global(
                    task, snap["before"], snap["after"], stage, event, target, snap["delta"], threshold=threshold)
        if snap["delta"].get("error") == UNCERTAIN:
            receipt = judge.evidence[event["event_id"]]
            gate, no_known, no_exact = localization_details(
                task, snap["before"], event["return_text"], receipt.response)
            counts["localization"][gate] += 1
            counts["localization"]["no_prior_candidate"] += no_known
            counts["localization"]["no_exact_normalized_constraint_mention"] += no_exact
        if eid in selected:
            sample[eid] = private_sample_row(bundle, snap, event, judge.evidence[event["event_id"]])
    if entered != judge.r1_calls:
        raise RuntimeError(f"R1 cache calls do not reconcile for {tid}")
    ledger = bundle["ledger_snapshots"][-1]["after"] if bundle["ledger_snapshots"] else initial_ledger(task)
    sources = RiskOrigins(bundle, judge.evidence)
    global_counts, local_counts = sources.count(ledger, "global"), sources.count(ledger, "support")
    counts["global"].update(global_counts)
    counts["local"].update(local_counts)
    counts["global_per_trajectory"].append(sum(global_counts.values()))
    if global_counts["state_unknown_rejected"] or local_counts["state_unknown_rejected"]:
        counts["b_trajectories"] += 1
    g_gate = grounding_gate(bundle, ledger)
    counts["g"][g_gate] += 1
    if g_gate == "final_candidate_extraction_failed":
        final_annotation_failed = (sum(row["event_id"] is None for row in bundle["annotation_failures"])
                                   > (task["status"] != "ok"))
        if judge.final_response is None:
            counts["final_failure"]["cached_model_failure"] += 1
        elif final_annotation_failed:
            counts["final_failure"]["candidate_or_anchor_validation_failed"] += 1
        elif not judge.final_response.get("quote"):
            counts["final_failure"]["null_candidate_in_model_response"] += 1
        else:
            counts["final_failure"]["other"] += 1
    final_or_task_spans = sum(
        row["event_id"] is None and row["reason"] == SPAN for row in bundle["annotation_failures"])
    task_span = task.get("error") == SPAN
    counts["span_source"]["task_constraints"] += task_span
    counts["span_source"]["final_candidate"] += final_or_task_spans - task_span
    counts["span_source"]["evidence_update"] += sum(
        row["event_id"] is not None and row["reason"] == SPAN for row in bundle["annotation_failures"])
    if counterfactual:
        if (g_value := grounding_without_global(bundle, ledger)) is not None:
            counts["a_g"].append(g_value)
        original_support = support_set(ledger)
        repaired, repair_counts = replay_repairs(bundle, judge.evidence)
        repaired_support = support_set(repaired)
        counts["c"].update(repair_counts)
        counts["c"].update(new_supported_facts=len(repaired_support - original_support),
                           lost_supported_facts=len(original_support - repaired_support),
                           trajectories_with_support_original=bool(original_support),
                           trajectories_with_support_c=bool(repaired_support))


def postprocess(run, *, counterfactual):
    config = cli.config_file(run / "config.json")
    real = run / "real"
    if Path(config["output_dir"]).resolve() != run.resolve():
        raise RuntimeError("diagnostic run path does not match the archived configuration")
    manifest = read_json(real / "run_manifest.json")
    freeze = manifest["freeze"]
    if manifest["synthetic"] or freeze["code_commit"] != CODE or config["code_commit"] != CODE:
        raise RuntimeError("diagnosis requires the frozen real Phase 1.1 source")
    index_path = Path(config["input_index"])
    if sha256(index_path.read_bytes()).hexdigest() != freeze["input_index_sha256"]:
        raise RuntimeError("input index identity differs from the archived manifest")
    if any(freeze[key] != value for key, value in cli.freeze_config(config).items()):
        raise RuntimeError("config or input dependency identity differs from the archived manifest")
    judge = ReadOnlyJudge(config, real / "model_cache", freeze)
    if judge.prompt_sha256 != freeze["prompt_sha256"]:
        raise RuntimeError("prompt identity differs from the archived manifest")
    tokenizer = cli.NativeByteTokenizer(config["tokenizer"], config["tokenizer_revision"]) if config.get("tokenizer") else None
    legacy = cli.load_legacy(config)
    index = cli.jsonl(index_path)
    if len(index) != 400 or len({row["question_id"] for row in index}) != 100:
        raise RuntimeError("expected the sealed 100-question, 400-trajectory inventory")
    uncertain_ids = {row["event_id"] for row in cli.jsonl(real / "annotation_failures.jsonl")
                     if row["reason"] == UNCERTAIN}
    ordered_sample = select_sample(uncertain_ids) if counterfactual else []
    selected, sample = set(ordered_sample), {}
    counts = {key: Counter() for key in (
        "r1", "g", "global", "local", "funnel", "c", "localization", "final_failure", "span_source")}
    counts.update(a_g=[], global_per_trajectory=[], a_r1=0, b_trajectories=0)
    for row in index:
        tid = row["trajectory_id"]
        filename = identity([freeze, row["sha256"], tid]) + ".json"
        bundle = read_json(real / "bundles" / filename)
        replay_bundle(bundle, row, judge, tokenizer, legacy[tid], freeze, config)
        summarize_bundle(bundle, judge, counts, selected, sample, counterfactual=counterfactual,
                         threshold=config.get("threshold", 0.8))
    if set(sample) != selected or counts["global"]["uncertain"] + counts["local"]["uncertain"] != len(uncertain_ids):
        raise RuntimeError("uncertainty source or sample does not reconcile")
    localization = counts["localization"]
    if (sum(localization[key] for key in LOCALIZATION_GATES) != len(uncertain_ids)
            or localization["localized"] != counts["local"]["uncertain"]):
        raise RuntimeError("uncertainty localization does not reconcile with ledger risk")
    g, r1, funnel = counts["g"], counts["r1"], counts["funnel"]
    if sum(r1.values()) + funnel["entered_verification"] != funnel["candidate_events"] or sum(g.values()) != len(index):
        raise RuntimeError("R1 or g reasons do not reconcile with the population")
    report = {
        "trajectories": len(index),
        "bundles_matched_by_cache_replay": len(index),
        "new_model_requests": 0,
        "risk": {
            "global_records": sum(counts["global"].values()),
            "local_records": sum(counts["local"].values()),
            "trajectories_with_global_risk": sum(value > 0 for value in counts["global_per_trajectory"]),
            "global_risks_per_trajectory": distribution(counts["global_per_trajectory"]),
            "global_by_source": populated(counts["global"], REASONS),
            "local_by_source": populated(counts["local"], REASONS),
            "span_mismatch_annotations_by_component": dict(counts["span_source"]),
            "uncertainty_localization": {
                "first_gate": populated(localization, LOCALIZATION_GATES),
                "no_prior_candidate": localization["no_prior_candidate"],
                "no_exact_normalized_constraint_mention": localization["no_exact_normalized_constraint_mention"],
            },
        },
        "r1": {"not_invoked": sum(r1.values()), "not_invoked_by_gate": populated(r1, R1_GATES),
               "funnel": populated(funnel, FUNNEL)},
        "g": {"valid": g["valid"], "empty": len(index) - g["valid"], "empty_by_gate": populated(g, G_GATES),
              "final_candidate_failures": populated(counts["final_failure"], (
                  "cached_model_failure", "candidate_or_anchor_validation_failed",
                  "null_candidate_in_model_response", "other"))},
    }
    if counterfactual:
        report["counterfactual"] = {
            "A": {"additional_r1_verification_entries": counts["a_r1"],
                  "g_valid_trajectories": len(counts["a_g"]), "g": distribution(counts["a_g"], histogram=True)},
            "B": {"global_risks_removed": counts["global"]["state_unknown_rejected"],
                  "local_risks_removed": counts["local"]["state_unknown_rejected"],
                  "affected_trajectories": counts["b_trajectories"]},
            "C": populated(counts["c"], (
                "span_rows_originally_rejected", "span_rows_with_unique_literal", "span_rows_accepted",
                "new_supported_facts", "lost_supported_facts",
                "trajectories_with_support_original", "trajectories_with_support_c")),
        }
    return report, [sample[eid] for eid in ordered_sample]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    analyze = subcommands.add_parser("analyze")
    analyze.add_argument("--run", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--private-sample", type=Path, help="enable A/B/C and write a private review packet")
    finalize = subcommands.add_parser("finalize-sample")
    for key in ("aggregate", "private-sample", "labels", "output"):
        finalize.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "analyze":
        run = args.run.resolve()
        outputs = [path.resolve() for path in (args.output, args.private_sample) if path]
        if any(path == run or run in path.parents or path.exists() for path in outputs):
            parser.error("output must be a new file outside the sealed run directory")
        report, sample = postprocess(run, counterfactual=args.private_sample is not None)
        if args.private_sample:
            write_new(args.private_sample, sample)
        write_new(args.output, report)
    else:
        report = read_json(args.aggregate)
        selected = [row["event_id"] for row in read_json(args.private_sample)]
        report["uncertainty_sample"] = sample_receipt(selected, read_json(args.labels))
        write_new(args.output, report)


if __name__ == "__main__":
    main()
