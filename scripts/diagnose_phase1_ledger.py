"""Trace a frozen Phase 1 run with cached responses and no network I/O."""

import argparse
from collections import Counter, defaultdict, deque
from contextlib import ExitStack
from functools import wraps
from hashlib import file_digest, sha256
import importlib
from pathlib import Path
import re
import sys
import unicodedata
from unittest.mock import patch

from redundancy_judge import cli
from redundancy_judge.adapters.model import ModelJudge
from redundancy_judge.adapters.trace import NativeByteTokenizer
from redundancy_judge.common import JudgeFailure, atomic_json, candidate_name, exact_quote, identity, read_json
from redundancy_judge.review_workflow import execute
from redundancy_judge.update_evidence_ledger import support_key


BAD = {"annotation_error", "partial_annotation"}
QUOTE_ERROR = "evidence quote absent or ambiguous"


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def quote_analysis(source, quote, alternatives=()):
    if not isinstance(source, str) or not isinstance(quote, str) or not quote:
        return None, "unlinked", []
    hits = overlap_count(source, quote)
    if hits:
        return hits, "multiple" if hits > 1 else "one_other_validation", []
    flags = []
    space = lambda value: " ".join(value.split())
    if space(quote) in space(source):
        flags.append("whitespace")
    fold = lambda value: re.sub(r"[^\w]+", " ", unicodedata.normalize(
        "NFKC", re.sub(r"\\[nrt]", " ", value)).casefold()).strip()
    if fold(quote) and fold(quote) in fold(source) and not flags:
        flags.append("punctuation_character_or_escaping")
    chunks = [fold(x) for x in re.split(r"\.{2,}|…|\[\.\.\.\]", quote) if len(fold(x)) >= 8]
    if len(chunks) >= 2 and all(x in fold(source) for x in chunks):
        flags.append("noncontiguous_segments")
    if any(quote in value for value in alternatives if isinstance(value, str)):
        flags.append("exact_in_other_source")
    return hits, "zero", flags or ["unresolved_substitution_or_rewrite"]


def grounded_alias_links(links):
    """Require explicit same-entity wording in the quoted source."""
    out = []
    for row in links:
        left, right = row["final_candidate"], row["other_candidate"]
        pairs = "|".join(re.escape(a) + r"\s*(?:\(|,)?\s*(?:also known as|formerly known as|better known as|aka|née)\s+" +
                         re.escape(b) for a, b in ((left, right), (right, left)))
        for ref in row["evidence"]:
            if re.search(pairs, ref["quote"], re.I):
                out.append({**row, "identity_evidence": ref})
                break
    return out


def overlap_count(source, quote):
    if not quote:
        return 0
    n, cursor = 0, 0
    while (location := source.find(quote, cursor)) >= 0:
        n += 1
        cursor = location + 1
    return n


class OfflineJudge(ModelJudge):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, replay_only=True, **kwargs)
        self.calls = []
        self.context = {}

    def ask(self, kind, payload):
        receipt = {**self.context, "component": kind, "payload_sha256": identity(payload)}
        receipt["coordinates"] = dict(self.context)
        if kind == "evidence_update":
            receipt["source_sha256"] = sha256(payload["returned_text"].encode()).hexdigest()
        self.calls.append(receipt)

        def observe(frame, event, value):
            if frame.f_code is ModelJudge.ask.__code__:
                if event == "return":
                    path = frame.f_locals.get("path")
                    receipt.update(cache_key=frame.f_locals.get("key"),
                                   cache_hit=bool(path and path.is_file()))
                return observe
            return None

        previous = sys.gettrace()
        sys.settrace(observe)
        try:
            response = super().ask(kind, payload)
        except Exception as exc:
            receipt["error"] = str(exc)
            raise
        else:
            receipt["response"] = response
            return response
        finally:
            sys.settrace(previous)


def network_forbidden(*args, **kwargs):
    raise AssertionError("network attempts are forbidden in diagnosis")


def inspect_update(original, impacts):
    @wraps(original)
    def wrapped(task, before, stage, event, judge):
        buffered = []
        terminal_locals = {}

        def observe(frame, op, arg):
            if frame.f_code is original.__code__:
                if op == "return":
                    buffered.extend(frame.f_locals.get("updates", ()))
                    terminal_locals.update(frame.f_locals)
                return observe
            return None

        previous = sys.gettrace()
        sys.settrace(observe)
        try:
            after, delta = original(task, before, stage, event, judge)
        finally:
            sys.settrace(previous)
        response = terminal_locals.get("response", {})
        rows = response.get("updates", []) if isinstance(response, dict) else []
        independently_valid = []
        if delta["status"] == "annotation_error" and isinstance(rows, list) and not response.get("uncertain"):
            for index, item in enumerate(rows):
                if not isinstance(item, dict):
                    continue
                candidate = candidate_name(item.get("candidate"))
                cid, state = item.get("constraint_id"), item.get("state")
                if (not candidate or cid not in {c["constraint_id"] for c in task["constraints"]}
                        or state not in {"partially_supported", "supported", "conflicted", "refuted"}
                        or type(item.get("resolves_conflict", False)) is not bool):
                    continue
                try:
                    ref = exact_quote(event["return_text"], item)
                except JudgeFailure:
                    continue
                key = support_key(candidate, cid)
                independently_valid.append({"candidate": candidate, "constraint_id": cid,
                    "source_row": index, "state": state, "quote": ref["quote"],
                    "prior_state": before["support"].get(key, {}).get("state", "unknown"),
                    "frozen_after_state": after["support"].get(key, {}).get("state", "unknown")})
        if delta["status"] == "annotation_error" and (buffered or independently_valid):
            impacts.append({**judge.context, "error": delta["error"],
                            "cache_key": judge.calls[-1]["cache_key"] if hasattr(judge, "calls") else None,
                            "independently_valid_rows": independently_valid,
                            "buffered_valid_updates": [
                                {"candidate": candidate, "constraint_id": cid, "proposed_state": state,
                                 "prior_state": before["support"].get(key, {}).get("state", "unknown"),
                                 "frozen_after_state": after["support"].get(key, {}).get("state", "unknown"),
                                 "quote": ref["quote"], "reference": ref["reference"],
                                 "would_add_quote": ref["quote"] not in {
                                     old["quote"] for old in before["support"].get(key, {}).get("evidence", [])}}
                                for key, candidate, cid, state, ref, _ in buffered]})
        return after, delta
    return wrapped


def observe_quote(failures, judge, original):
    @wraps(original)
    def wrapped(source, item):
        try:
            return original(source, item)
        except Exception as exc:
            call = judge.calls[-1]
            failures.append({**call["coordinates"], "component": call["component"], "cache_key": call["cache_key"],
                             "reason": str(exc), "quote": item.get("quote"), "source_text": source,
                             "source_sha256": sha256(source.encode()).hexdigest(),
                             "constraint_id": item.get("constraint_id"), "candidate": item.get("candidate"),
                             "validator": "common.exact_quote", "source_length": len(source),
                             "coordinate": [item.get("start"), item.get("end")]})
            raise
    return wrapped


def quote_modules():
    modules = [importlib.import_module("redundancy_judge." + name)
               for name in ("init_task_ledger", "update_evidence_ledger")]
    return [cli, *modules]


def instrument(judge, quotes, impacts, observed):
    stack = ExitStack()
    for module in quote_modules():
        stack.enter_context(patch.object(module, "exact_quote", observe_quote(quotes, judge, module.exact_quote)))
    for function in ("resolve_action_target", "update_evidence_ledger", "judge_stage", "summarize_trajectory"):
        orig = getattr(cli, function)
        if function == "update_evidence_ledger":
            orig = inspect_update(orig, impacts)
        stack.enter_context(patch.object(cli, function, callback(function, orig, judge, observed)))
    stack.enter_context(patch("urllib.request.OpenerDirector.open", network_forbidden))
    return stack


def callback(function, original, judge, observed):
    @wraps(original)
    def wrapped(*args, **kwargs):
        if function == "summarize_trajectory":
            observed.update(final_ledger=args[2], candidate=kwargs["submitted_candidate"])
            return original(*args, **kwargs)
        stage = args[3] if function == "judge_stage" else args[2]
        event = stage["action"]["event_id"] if stage.get("action") else next(iter(stage["event_ids"]), None)
        if function == "update_evidence_ledger":
            event = args[3]["event_id"]
        if function == "judge_stage":
            event = args[4]["event_id"]
        judge.context.update(stage_id=stage["stage_id"], event_id=judge.context["trajectory_id"] + ":" + str(event))
        if function == "judge_stage":
            observed["gate_before"][judge.context["event_id"]] = args
        result = original(*args, **kwargs)
        if function == "judge_stage":
            # The next unscoped call is final_candidate, if any.
            judge.context.update(stage_id=None, event_id=None)
        return result
    return wrapped


def ordered_digest(paths):
    return {str(path): digest(path) if path.is_file() else None for path in sorted(paths)}


def integrity(manifest, config, index, cache_list):
    root = Path(config["run_dir"])
    inventory = Path(config["input_index"]).parent
    paths = [Path(row["path"]) for row in index]
    paths.extend(root / name for name in manifest["private_output_sha256"])
    required = {Path(row["path"]): row["sha256"] for row in index}
    required.update({root / name: sha for name, sha in manifest["private_output_sha256"].items()})
    old_manifest = inventory / "old_assets.json"
    old_receipts = read_json(old_manifest)
    for row in old_receipts:
        if row["status"] == "present":
            required[Path(row["path"])] = row["sha256"]
    required[Path(config["input_index"])] = manifest["freeze"]["input_index_sha256"]
    required[Path(config["tokenizer"])] = manifest["freeze"]["tokenizer_sha256"]
    required[cache_list] = manifest["replay_cache"]["manifest_sha256"]
    cache_entries = {}
    for line in cache_list.read_text().splitlines():
        checksum, name = line.split("  ", 1)
        if not re.fullmatch(r"model_cache/[0-9a-f]{2}/[0-9a-f]{64}\.json", name):
            raise ValueError("invalid cache manifest path")
        cache_entries[root / name] = checksum
    if len(cache_entries) != manifest["replay_cache"]["receipt_files"]:
        raise ValueError("cache inventory count mismatch")
    required.update(cache_entries)
    paths = set(paths) | set(required) | {old_manifest, root.parent / "config.json",
            root / "approved_labels.json", root / "reward_preview_summary.json", root / "reference_cost.json",
            root / "run_manifest.json"}
    paths.update(Path(config["prompt_dir"]).glob("*.md"))
    runtime_source = Path(cli.__file__).resolve().parent
    paths.update(runtime_source.rglob("*.py"))
    paths.update((runtime_source.parent.parent / "configs").glob("*.yaml"))
    measured = ordered_digest(paths)
    discrepancies = [str(path) for path, expected in required.items() if measured[str(path)] != expected]
    extra_cache = set((root / "model_cache").glob("*/*.json")) - set(cache_entries)
    return measured, discrepancies + sorted(map(str, extra_cache))


def stat_rows(rows):
    event_ids = {r["event_id"] for r in rows if r.get("event_id")}
    return {"events": len(rows), "unique_tool_events": len(event_ids),
            "trajectories": len({r["trajectory_id"] for r in rows}),
            "questions": len({r["question_id"] for r in rows})}


def coordinate_rollup(rows):
    return {**stat_rows(rows), "unique_cache_keys": len({r["cache_key"] for r in rows if r.get("cache_key")})}


def funnel_steps(rows):
    ordered = ["tool_and_return", "task", "target", "update", "prior_supported", "prior_visible",
               "verify_intent", "preverify_eligible", "called", "positive", "chargeable"]
    result = {"tool_events": stat_rows(rows)}
    for gate in ordered:
        rows = [row for row in rows if row["gates"][gate]]
        result[gate] = stat_rows(rows)
    return result


def grouped_stats(rows, fields):
    by_key = defaultdict(list)
    for row in rows:
        by_key[tuple(str(row.get(k)) for k in fields)].append(row)
    return [{"cells": list(key), **stat_rows(values)} for key, values in sorted(by_key.items())]


def failure_details(bundle, q_errors, calls):
    index = bundle["input_index"]
    snapshots = {row["event_id"]: row for row in bundle["ledger_snapshots"] if row["event_id"]}
    by_event = defaultdict(deque)
    for row in q_errors:
        by_event[(row["event_id"], row["reason"])].append(row)
    calls_by_key = {(row.get("event_id"), row["component"]): row for row in calls}
    notes = []
    for rank, row in enumerate(bundle["annotation_failures"], 1):
        eid, reason = row["event_id"], row["reason"]
        trace = by_event[eid, reason].popleft() if by_event[eid, reason] else None
        if trace:
            alternatives = [bundle["input_index"]["question"]]
            if eid and eid in snapshots:
                visible = set(snapshots[eid]["visible_before"])
                alternatives.extend(x["return_text"] for x in bundle["tool_events"] if x["event_id"] in visible)
            matches, match_class, flags = quote_analysis(trace["source_text"], trace["quote"], alternatives)
            trace = {**trace, "matches": matches, "match_class": match_class, "diagnostic_flags": flags}
        else:
            stage = snapshots.get(eid)
            kind = ("evidence_update" if stage and stage["delta"].get("error") == reason else
                    "action_target" if eid else
                    "task_constraints" if bundle["task_specs"].get("error") == reason else "final_candidate")
            trace = {"component": kind}
            if (call := calls_by_key.get((eid, kind))) is not None:
                trace["cache_key"] = call["cache_key"]
            if reason == QUOTE_ERROR:
                trace["match_class"] = "unlinked"
        if eid in snapshots:
            state = snapshots[eid]
            delta = state["delta"]
            trace.update(stage_id=state["stage_id"], downstream_status=delta["status"],
                         retained_updates=len(delta["evidence"]), effective_gain=delta["effective_gain"])
        if trace.get("component") == "evidence_update" and eid:
            raw_id = eid.removeprefix(index["trajectory_id"] + ":")
            raw = next(x for x in bundle["tool_events"] if x["event_id"] == raw_id)
            trace["source_reference"] = raw["return_ref"]
        elif trace.get("component") == "task_constraints":
            trace["source_reference"] = "input_index.question"
        elif trace.get("component") == "final_candidate":
            trace["source_reference"] = next((s["strategy_refs"] for s in bundle["stages"] if s["stage_type"] == "final"), None)
        notes.append({**{k: index[k] for k in ("trajectory_id", "question_id", "split")},
                      "failure_ordinal": rank, **row, **trace})
    if any(by_event.values()):
        raise ValueError("quote hook produced extra failures")
    return notes


def ground(bundle, observed, calls, failures, reward_rows):
    row, spec = bundle["trajectory_summaries"], bundle["task_specs"]
    ledger = observed["final_ledger"]
    candidate = candidate_name(observed["candidate"])
    final = [stage for stage in bundle["stages"] if stage["stage_type"] == "final"]
    blockers = []
    if not final:
        blockers.append("no_final_stage")
    elif not candidate:
        blockers.append("final_candidate_quote_failure" if any(
            x["component"] == "final_candidate" for x in failures) else "final_candidate_not_extracted")
    if spec["status"] != "ok":
        blockers.append("task_constraint_validation_failed")
    elif spec["uncertain"] or not spec["constraints"]:
        blockers.append("task_constraints_uncertain_or_empty")
    errors = [a for a in ledger["attempts"] if a["status"] in BAD]
    if errors:
        blockers.append("historical_evidence_error")
    states = {}
    for item in spec["constraints"]:
        cid = item["constraint_id"]
        states[cid] = ledger["support"].get(support_key(candidate, cid), {"state": "unknown", "evidence": []})
    evidence_after_error = False
    if errors:
        flags = {a["event_id"] for a in errors}
        first = next(i for i, a in enumerate(ledger["attempts"]) if a["event_id"] in flags)
        later = {a["event_id"] for a in ledger["attempts"][first + 1:]}
        evidence_after_error = any(ref["event_id"] in later for value in states.values() for ref in value["evidence"])
    relevant_failures = []
    for failure in failures:
        if failure["component"] != "evidence_update":
            continue
        cand = candidate_name(failure.get("candidate"))
        related = "relevant" if candidate and cand == candidate else "unknown"
        relevant_failures.append({"event_id": failure["event_id"], "failure_ordinal": failure["failure_ordinal"],
                                  "relation": related, "candidate": failure.get("candidate"),
                                  "constraint_id": failure.get("constraint_id")})
    supported = [cid for cid, value in states.items() if value["state"] == "supported"]
    if supported != row["supported_constraints"] or bool(blockers) != (row["g"] is None):
        raise ValueError("grounding reconstruction differs from frozen summary")
    terminal = calls.get("final_candidate")
    candidate_missing_reason = None
    if final and not candidate:
        candidate_missing_reason = ("cached_response_error" if terminal and terminal.get("error") else
                                    "null_candidate_quote" if terminal and not terminal.get("response", {}).get("quote") else
                                    "candidate_quote_validation")
    related_candidates = []
    if candidate:
        for fact in ledger["support"].values():
            other = fact["candidate"]
            if other == candidate:
                continue
            if any(candidate in unicodedata.normalize("NFKC", ref["quote"]).casefold()
                   and other in unicodedata.normalize("NFKC", ref["quote"]).casefold()
                   for ref in fact["evidence"]):
                related_candidates.append({"other_candidate": other, "constraint_id": fact["constraint_id"],
                                           "state": fact["state"], "evidence": fact["evidence"],
                                           "final_candidate": candidate,
                                           "status": "co_mentioned_alias_unverified"})
    return {**{k: row[k] for k in ("trajectory_id", "question_id", "split", "result", "g",
                                 "raw_termination_reason", "grounding_issue")},
            "has_final": bool(final), "candidate": observed["candidate"],
            "candidate_missing_detail": candidate_missing_reason,
            "final_cache_key": terminal["cache_key"] if terminal else None,
            "constraints_status": spec["status"], "constraints_uncertain": spec["uncertain"],
            "constraint_count": len(states), "constraint_states": states,
            "historical_errors": [{k: a[k] for k in ("event_id", "stage_id", "status")} for a in errors],
            "evidence_errors_relation": relevant_failures, "valid_support_count": len(supported),
            "possible_candidate_name_links": related_candidates,
            "explicit_alias_links": grounded_alias_links(related_candidates),
            "has_later_final_candidate_evidence": evidence_after_error,
            "primary_blocker": blockers[0] if blockers else "valid", "blockers": blockers,
            "reward_exclusion_reason": reward_rows.get(row["trajectory_id"])}


def r1_row(args, judgment, call):
    task, before, _, stage, event, target, delta = args[:7]
    label = next(row for row in judgment["labels"] if row["label"] == "R1")
    fact = before["support"].get(support_key(target["candidate"], target["constraint_id"]), {})
    visible = set(stage["visible_return_ids"])
    direct = any(ref["event_id"] in visible for ref in fact.get("evidence", []))
    contents = {row["content_id"] for row in before["attempts"] if row["event_id"] in visible}
    seen = direct or any(ref["content_id"] in contents for ref in fact.get("evidence", []))
    reasons = []
    for condition, reason in (
        (stage["parse_status"] != "ok", "protocol"),
        (not event["visible_next"] or event["return_text"] is None or bool(event["error"]), "return_unavailable"),
        (task["uncertain"] or not task["constraints"], "task_unavailable"),
        (target["state"] != "resolved", "target_unresolved"),
        (delta["status"] != "ok", "ledger_update_" + delta["status"]),
        (fact.get("state") != "supported", "prior_fact_not_supported"),
        (not seen, "prior_fact_not_visible"),
        (target["intent"] != "verify", "different_intent"),
        (bool(judgment["protections"]), "protected"),
        (not stage["charge_token_spans"], "no_charge_span"),
    ):
        if condition:
            reasons.append(reason)
    check = judgment["diagnostics"]["r1_check"]
    if call:
        route = ("verification_error" if check is None else
                 "verification_low_confidence" if label["decision"] == "abstain" else
                 "verification_positive" if label["decision"] == "positive" else "verification_rejected")
    else:
        route = next((item for item in reasons if item != "no_charge_span"), "unexplained_no_call")
    if not call and route == "unexplained_no_call":
        raise ValueError("unexplained no-call gate")
    ledger_only = (event["visible_next"] and isinstance(event["return_text"], str) and not event["error"]
                   and target["state"] == "resolved" and delta["status"] in BAD
                   and fact.get("state") == "supported" and seen and target["intent"] == "verify"
                   and not judgment["protections"])
    return {**{k: judgment[k] for k in ("event_id", "stage_id", "question_id", "split")},
            "trajectory_id": stage["stage_id"].rsplit(":S", 1)[0],
            "original_decision": label["decision"], "original_reason": label["abstention_reason"],
            "primary_route": route, "all_blockers": reasons, "delta_status": delta["status"],
            "delta_gain": delta["effective_gain"], "ledger_only_verification_gate": ledger_only,
            "called": bool(call), "cache_hit": bool(call and call["cache_hit"]),
            "cache_key": call["cache_key"] if call else None, "verification": check,
            "r1_price_eligible": label["reward_eligible"], "chosen_price": judgment["price_label"],
            "gates": {"tool_and_return": stage["parse_status"] == "ok" and "return_unavailable" not in reasons,
                      "task": "task_unavailable" not in reasons, "target": target["state"] == "resolved",
                      "update": delta["status"] == "ok", "prior_supported": fact.get("state") == "supported",
                      "prior_visible": seen, "verify_intent": target["intent"] == "verify",
                      "preverify_eligible": bool(call), "called": bool(call),
                      "positive": label["decision"] == "positive", "chargeable": label["reward_eligible"]}}


def case_state(bundle, observed):
    findings = []
    for snap in bundle["ledger_snapshots"]:
        before, after = snap["before"], snap["after"]
        if after["candidate_gaps"] and not after["open_gaps"] and all(after["candidate_gaps"].values()):
            findings.append(("distributed_open_gaps", snap))
        if snap.get("delta", {}).get("conflicts") or snap.get("delta", {}).get("resolved_conflicts"):
            findings.append(("conflict_transition", snap))
        if snap.get("delta", {}).get("status") == "partial_annotation" and snap["delta"]["evidence"]:
            findings.append(("partial_update_preserved", snap))
    return [{"kind": key, "event_id": snap["event_id"], "stage_id": snap["stage_id"],
             "question_id": bundle["input_index"]["question_id"], "trajectory_id": bundle["input_index"]["trajectory_id"],
             "split": bundle["input_index"]["split"], "before": snap["before"], "after": snap["after"],
             "delta": snap.get("delta")} for key, snap in findings]


def diagnose(args):
    config = cli.config_file(args.config)
    original = Path(config["run_dir"]).resolve(strict=True)
    output = args.output.resolve()
    if output == original or original in output.parents or output.exists():
        raise ValueError("output must be a fresh directory outside the frozen run")
    manifest = read_json(args.manifest)
    index = cli.jsonl(config["input_index"])
    before, changed = integrity(manifest, config, index, args.cache_manifest)
    if changed:
        raise ValueError(f"frozen input digest mismatches: {len(changed)}")
    output.mkdir(parents=True)
    freeze = cli.freeze_config(config)
    judge = OfflineJudge(config["judge"], config["prompt_dir"], original / "model_cache", freeze)
    freeze.update(prompt_sha256=judge.prompt_sha256, input_index_sha256=digest(Path(config["input_index"])))
    if freeze != manifest["freeze"] or read_json(original / "run_manifest.json")["freeze"] != freeze:
        raise ValueError("freeze identity mismatch")
    tokenizer = NativeByteTokenizer(config["tokenizer"], config["tokenizer_revision"])
    old_failures = cli.jsonl(original / "annotation_failures.jsonl")
    rewards = read_json(original / "reward_preview_summary.json")["excluded"]
    reward_rows = {tid: reason for item in rewards for tid, reason in item["row_reasons"].items()}
    groups = cli.group_tasks(index, "all", None, config["pilot_seed"])
    groups = [g for split in ("dev", "calibration", "audit") for g in groups if g[0]["split"] == split]
    bundles, quotes, impacts, reconciled, grounding, funnel, case_candidates = [], [], [], [], [], [], []
    observed = {}
    legacy = cli.load_legacy(config)
    case_refs = defaultdict(list)
    with instrument(judge, quotes, impacts, observed):
        for group in groups:
            qid = group[0]["question_id"]
            judge.context = {"question_id": qid, "split": group[0]["split"], "trajectory_id": None,
                             "event_id": None, "stage_id": None}
            q_start = len(quotes)
            task, initial = cli.init_task_ledger(group[0]["question"], judge)
            task_quotes = quotes[q_start:]
            task_call = judge.calls[-1]
            for row in group:
                tid = row["trajectory_id"]
                judge.context.update(trajectory_id=tid, stage_id=None, event_id=None)
                observed.clear()
                observed["gate_before"] = {}
                start, call_start = len(quotes), len(judge.calls)
                bundle = cli.annotate_one(row, task, initial, judge, tokenizer, legacy[tid], freeze, config)
                bundles.append(bundle)
                calls = judge.calls[call_start:]
                by_event = {(r["event_id"], r["component"]): r for r in calls}
                actual_quotes = [{**item, "trajectory_id": tid} for item in task_quotes] + quotes[start:]
                notes = failure_details(bundle, actual_quotes, [task_call, *calls])
                reconciled.extend(notes)
                grounding.append(ground(bundle, observed, {r["component"]: r for r in calls}, notes, reward_rows))
                for judgment in bundle["stage_judgments"]:
                    eid = judgment["event_id"]
                    funnel.append(r1_row(observed["gate_before"][eid], judgment, by_event.get((eid, "r1_verification"))))
                case_candidates.extend(case_state(bundle, observed))
                if row["split"] == "dev":
                    for note in notes:
                        key = (note["component"], note["reason"], note.get("match_class", "other"))
                        if len(case_refs[key]) < 5:
                            case_refs[key].append(note)
            print("replayed question", qid, flush=True)
    if any(not call["cache_hit"] for call in judge.calls):
        raise ValueError("BLOCKED_DATA: cache miss during replay")
    replay = output / "replay"
    replay.mkdir()
    cli.consolidate(replay, bundles, [row for group in groups for row in group], freeze)
    atomic_json(replay / "run_manifest.json", {"freeze": freeze, "synthetic": False})
    reference = cli.reference_cost(s for b in bundles if b["input_index"]["split"] == "dev" for s in b["stages"])
    atomic_json(replay / "reference_cost.json", reference)
    for command in ("export-review", "audit", "reward-preview"):
        execute(command, {**config, "run_dir": str(replay)})
    compared = {path.name: digest(path) == digest(original / path.name)
                for path in replay.iterdir() if (original / path.name).is_file()}
    if not all(compared.values()):
        raise ValueError(f"non-identical frozen outputs: {[key for key, val in compared.items() if not val]}")
    old = Counter((row["trajectory_id"], row["event_id"], row["reason"]) for row in old_failures)
    now = Counter((row["trajectory_id"], row["event_id"], row["reason"]) for row in reconciled)
    disagreements = {"missing": list((old-now).items()), "extra": list((now-old).items())}
    atomic_json(output / "reconciliation_differences.json", disagreements)
    if old != now:
        raise ValueError("original annotation records and replay traces disagree")
    output_files(args, manifest, config, output, before, index, compared, reconciled, grounding,
                 funnel, impacts, case_candidates, case_refs, judge.calls)


def output_files(args, manifest, config, output, before, index, compared, failures, grounding,
                 funnel, impacts, cases, case_refs, calls):
    quotes = [row for row in failures if row["reason"] == QUOTE_ERROR]
    discounts = [row for row in grounding if row["reward_exclusion_reason"] == "unverified_grounding"]
    valid = [row for row in grounding if row["g"] is not None]
    low_false = [r for r in funnel if r["original_reason"] == "low_verification_confidence" and not r["called"]]
    abstained = [r for r in funnel if r["original_decision"] == "abstain"]
    ledger_gate = [r for r in abstained if r["primary_route"].startswith("ledger_update_")]
    scope = {"all": grounding, "with_final": [r for r in grounding if r["has_final"]],
             "correct": [r for r in grounding if r["result"] == "C"]}
    scope.update({split: [r for r in grounding if r["split"] == split] for split in ("dev", "calibration", "audit")})
    cache_metrics = {kind: {"logical_calls": len(group), "unique_keys": len({r["cache_key"] for r in group}),
                            "hits": sum(r["cache_hit"] for r in group),
                            "events": len({r["event_id"] for r in group if r["event_id"]}),
                            "trajectories": len({r["trajectory_id"] for r in group if r["trajectory_id"]}),
                            "questions": len({r["question_id"] for r in group})}
                     for kind in sorted({x["component"] for x in calls})
                     for group in [[r for r in calls if r["component"] == kind]]}
    quote_stats = grouped_stats(quotes, ["component", "match_class"])
    blocked_target = [r for r in funnel if "task_unavailable" in r["all_blockers"]]
    only_candidate = [r for r in grounding if r["has_final"] and not r["candidate"]]
    alias_links = [r for r in grounding if r["explicit_alias_links"]]
    summary = {"status": "REAL_REPLAY_CONFIRMED", "failures": len(failures), "quotes": len(quotes),
               "quote_classes": quote_stats, "quote_flags": dict(Counter(
                   flag for row in quotes for flag in row.get("diagnostic_flags", ()))),
               "all_errors": grouped_stats(failures, ["component", "reason"]),
               "component_quotes": {kind: coordinate_rollup([r for r in quotes if r["component"] == kind])
                                    for kind in ("task_constraints", "evidence_update", "final_candidate")},
               "q2_blocked_target": stat_rows(blocked_target),
               "missing_candidate": dict(Counter(r["candidate_missing_detail"] for r in only_candidate)),
               "explicit_alias_trajectories": len(alias_links),
               "alias_co_mentions": sum(bool(r["possible_candidate_name_links"]) for r in grounding),
               "grounding": {name: {"n": len(rows),
                   "primary": dict(Counter(row["primary_blocker"] for row in rows)),
                   "coexisting": dict(Counter(k for row in rows for k in row["blockers"]))}
                   for name, rows in scope.items()},
               "reward_unverified_grounding": {"n": len(discounts),
                   "primary": dict(Counter(row["primary_blocker"] for row in discounts)),
                   "coexisting": dict(Counter(k for row in discounts for k in row["blockers"]))},
               "final_supported_with_failed_history": len([r for r in grounding if r["valid_support_count"] and
                            "historical_evidence_error" in r["blockers"]]),
               "later_evidence_history_still_blocks": len([r for r in grounding if r["has_later_final_candidate_evidence"]]),
               "g_valid": len(valid), "r1_events": len(funnel), "r1_abstentions": len(abstained),
               "r1_ledger_primary_abstentions": stat_rows(ledger_gate),
               "r1_ledger_only_verification_gate": stat_rows([r for r in funnel if r["ledger_only_verification_gate"]]),
               "r1_mislabeled_low_confidence": stat_rows(low_false),
               "batch_failures": stat_rows(impacts),
               "batch_buffered_legal_updates": sum(len(r["buffered_valid_updates"]) for r in impacts),
               "batch_independently_valid_rows": sum(len(r["independently_valid_rows"]) for r in impacts),
               "ledger_cases": grouped_stats(cases, ["split", "kind"]),
               "cache": cache_metrics, "cache_entries": manifest["replay_cache"]["receipt_files"],
               "used_cache_keys": len({row["cache_key"] for row in calls}),
               "new_model_requests": 0, "new_generations": 0, "new_deletion_runs": 0, "optimizer_steps": 0}
    if (len(failures), len(quotes), len(grounding), len(discounts), len(valid)) != (923, 810, 400, 109, 9):
        raise ValueError("frozen receipt count mismatch")
    for name, rows in (("quote_error_breakdown", quotes), ("all_annotation_errors", failures),
                       ("grounding_blockers", grounding), ("r1_reason_reconciliation", funnel),
                       ("batch_failure_impact", impacts), ("model_call_trace", calls), ("ledger_state_risks", cases)):
        cli.write_jsonl(output / f"{name}.jsonl", rows)
    r1 = {"cumulative": {"all": funnel_steps(funnel), **{
          split: funnel_steps([r for r in funnel if r["split"] == split])
          for split in ("dev", "calibration", "audit")}},
          "by_route": grouped_stats(funnel, ["split", "primary_route"]),
          "by_decision": grouped_stats(funnel, ["split", "original_decision"]),
          "called": grouped_stats([r for r in funnel if r["called"]], ["split", "primary_route"]),
          "blockers": grouped_stats([dict(r, blocker=b) for r in funnel for b in r["all_blockers"]],
                                    ["split", "blocker"])}
    atomic_json(output / "r1_funnel.json", r1)
    call_index = {row["cache_key"]: row for row in calls}
    ground_index = {row["trajectory_id"]: row for row in grounding}
    funnel_index = {row["event_id"]: row for row in funnel}
    snapshot_index = {row["event_id"]: row for b in bundles for row in b["ledger_snapshots"] if row["event_id"]}
    events = {b["input_index"]["trajectory_id"] + ":" + row["event_id"]: row
              for b in bundles for row in b["tool_events"]}
    def example(row, kind):
        event_id = row.get("event_id")
        return {**row, "case_kind": kind, "cached": call_index.get(row.get("cache_key")),
                "event": events.get(event_id), "snapshot": snapshot_index.get(event_id),
                "grounding": ground_index[row["trajectory_id"]]["primary_blocker"],
                "r1_route": funnel_index.get(event_id, {}).get("primary_route")}

    examples = [example(row, "annotation_failure") for rows in case_refs.values() for row in rows]
    for kind, candidates in (
        ("R1_reason_mismatch", low_false), ("U1_batch_rejection", impacts),
        ("G1_retained_support_failed_history", [r for r in grounding if r["valid_support_count"] and
                                             "historical_evidence_error" in r["blockers"]]),
        ("G2_later_support_failed_history", [r for r in grounding if r["has_later_final_candidate_evidence"]]),
        ("S1_distributed_gaps", [r for r in cases if r["kind"] == "distributed_open_gaps"]),
        ("GUARD_conflict_transition", [r for r in cases if r["kind"] == "conflict_transition"]),
        ("S2_name_link_candidate", [r for r in grounding if r["possible_candidate_name_links"]]),
    ):
        picked = set()
        for row in candidates:
            if row["split"] != "dev" or row["trajectory_id"] in picked:
                continue
            picked.add(row["trajectory_id"])
            examples.append(example(row, kind))
            if len(picked) == 5:
                break
    cli.write_jsonl(output / "real_cases.jsonl", examples)
    after, changed = integrity(manifest, config, index, args.cache_manifest)
    if changed or before != after:
        raise ValueError("frozen input changed during investigation")
    atomic_json(output / "input_manifest.json", {"freeze": manifest["freeze"], "input_count": len(index),
                "checked_files": len(before), "cache_manifest_sha256": digest(args.cache_manifest),
                "before": before, "after": after, "unchanged": True})
    atomic_json(output / "replay_checks.json", {"byte_identical": compared, "byte_identical_count": len(compared),
                "annotation_error_counter_equal": True, "source_hashes_equal": True, "new_network_requests": 0,
                "seven_deterministic_reconciliation_gates": [
                    "raw_sha256", "cache_sha256", "frozen_phase1_product_sha256", "immutable_before_after",
                    "replayed_output_sha256", "frozen_config_identity", "failure_record_multiset"]})
    atomic_json(output / "summary.json", summary)
    print(cli.canonical(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--cache-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--replay-only", required=True, action="store_true")
    try:
        diagnose(parser.parse_args())
    except (OSError, KeyError, ValueError) as exc:
        print(f"Diagnosis stopped: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
