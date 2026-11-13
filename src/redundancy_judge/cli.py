"""Inspect, annotate and audit frozen Phase 1 data."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import sys

import yaml

from .adapters.model import ModelJudge, SyntheticJudge
from .adapters.trace import NativeByteTokenizer, load_trajectory
from .common import JudgeFailure, atomic_json, canonical, exact_quote, identity, read_json
from .init_task_ledger import init_task_ledger
from .judge_stage import judge_stage
from .parse_stages import parse_stages
from .resolve_action_target import resolve_action_target
from .summarize_trajectory import summarize_trajectory
from .update_evidence_ledger import merge_parallel_updates, update_evidence_ledger

SCHEMA_VERSION = "phase1.v1"
BUDGET = {"CONTEXT_LIMIT_STOP", "GENERATION_LENGTH_STOP", "SAFETY_CEILING_STOP"}
PRIVATE_ARTIFACTS = ("input_index", "stages", "legacy_stage_mapping", "task_specs", "ledger_snapshots",
                 "action_targets", "stage_judgments", "trajectory_summaries",
                 "parse_failures", "annotation_failures", "tool_events", "position_map")


def config_file(path):
    path = Path(path).resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    return config


def jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path, rows):
    temp = path.with_suffix(".jsonl.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(canonical(row) + "\n")
    temp.replace(path)


def freeze_config(config):
    judge_config = {k: config["judge"][k] for k in ("model", "version", "timeout", "max_tokens")
                    if k in config["judge"]}
    tokenizer_sha = sha256(Path(config["tokenizer"]).read_bytes()).hexdigest() if config.get("tokenizer") else None
    legacy_shas = [sha256(Path(path).read_bytes()).hexdigest() for path in config.get("legacy_stages") or []]
    return {"schema_version": SCHEMA_VERSION, "code_commit": config["code_commit"],
            "model_version": judge_config["version"], "tokenizer_version": config.get("tokenizer_revision"),
            "config_sha256": identity([judge_config, config.get("threshold", 0.8), tokenizer_sha,
                                       config.get("pilot_seed"), config.get("mode"),
                                       config.get("reward"), config.get("cost_weighted"), legacy_shas]),
            "tokenizer_sha256": tokenizer_sha}


def load_legacy(config):
    blocks = defaultdict(list)
    for path in config.get("legacy_stages") or []:
        for row in jsonl(path):
            blocks[row["rollout_id"]].append(row)
    return blocks


def group_tasks(index, split, limit, seed):
    groups = defaultdict(list)
    for row in index:
        if split == "all" or row["split"] == split:
            groups[row["question_id"]].append(row)
    limit = limit or len(groups)
    ordered = sorted(groups, key=lambda qid: identity([seed, qid]))
    return [sorted(groups[qid], key=lambda row: row["trajectory_id"]) for qid in ordered[:limit]]


def annotate_one(row, task, initial, judge, tokenizer, legacy, freeze, config):
    result = row.get("result")
    trace = load_trajectory(row["path"], question=row["question"],
        result={"label": result, "source": row["result_source"]} if result in {"C", "W", "N"} else None,
        environment={"id": row["environment"], "deterministic_tools": row["deterministic_tools"]},
        synthetic=judge.synthetic)
    if trace["input_sha256"] != row["sha256"] or trace["trajectory_id"] != row["trajectory_id"]:
        raise ValueError("input index does not match the raw trajectory identity")
    if trace["termination_reason"] != row["termination_reason"] or trace["question_id"] != row["question_id"]:
        raise ValueError("source result does not match the raw trajectory")
    provenance = {**freeze, "input_sha256": trace["input_sha256"], "actor_model": trace["model"],
                  "actor_revision": trace["model_revision"]}
    parsed = parse_stages(trace, {"tokenizer": tokenizer}, legacy)
    events = {event["event_id"]: event for event in parsed["tool_events"]}
    judgments, states, targets, annotation_errors = [], [], {}, []
    ledger = initial
    stages = parsed["stages"]
    for stage in stages:
        if stage["stage_type"] != "tool":
            continue
        before = ledger
        branches, current_targets = [], {}
        for event_id in stage["event_ids"]:
            event = events[event_id]
            action_stage = stage
            if stage["parallel_group_id"] and stage["parse_status"] == "ok":
                action = {key: event[key] for key in ("tool_name", "arguments", "call_id", "event_id",
                                                     "environment", "deterministic", "dispatch_time")}
                action_stage = {**stage, "action": action}
            target = resolve_action_target(task, before, action_stage, judge, threshold=config.get("threshold", 0.8))
            after, delta = update_evidence_ledger(task, before, action_stage, event, judge)
            judgment = judge_stage(task, before, after, action_stage, event, target, delta, judge,
                                   threshold=config.get("threshold", 0.8), previous_targets=targets)
            unique_event = f"{row['trajectory_id']}:{event_id}"
            judgment.update(event_id=unique_event, question_id=row["question_id"], split=row["split"],
                            synthetic=judge.synthetic, provenance=provenance)
            states.append({"stage_id": stage["stage_id"], "event_id": unique_event,
                           "before": before, "after": after, "delta": delta,
                           "visible_before": action_stage["visible_return_ids"],
                           "observation_verified_in_next_prompt": event["visible_next"]})
            judgments.append(judgment)
            for error in [target.get("error"), delta.get("error"), *judgment["errors"]]:
                if error:
                    annotation_errors.append({"event_id": unique_event, "reason": error})
            branches.append((after, delta))
            current_targets[event_id] = {"stage_id": stage["stage_id"], "event_id": unique_event, **target}
        if branches:
            ledger = merge_parallel_updates(task, before, branches) if stage["parallel_group_id"] else branches[0][0]
            if stage["parallel_group_id"]:
                states.append({"stage_id": stage["stage_id"], "event_id": None,
                               "kind": "parallel_merge", "before": before, "after": ledger})
        targets.update(current_targets)
    candidate = None
    finals = [s["final_text"] for s in stages if s["stage_type"] == "final"]
    if finals:
        try:
            response = judge.ask("final_candidate", {"question": trace["question"], "final_text": finals[-1]})
            if response.get("quote"):
                candidate = exact_quote(finals[-1], response)["quote"]
        except (JudgeFailure, AttributeError, TypeError) as exc:
            annotation_errors.append({"event_id": None, "reason": str(exc)})
    if task["status"] != "ok":
        annotation_errors.append({"event_id": None, "reason": task["error"]})
    termination = row["termination_reason"]
    viable = termination in {"MODEL_FINAL_STOP", "EMPTY_MODEL_STOP"} or termination in BUDGET
    info = {k: row[k] for k in ("question_id", "trajectory_id", "split", "result", "result_source")}
    info.update(provenance=provenance, synthetic=judge.synthetic, raw_termination_reason=termination,
                termination_reason="normal" if termination == "MODEL_FINAL_STOP" else
                "budget_exhausted" if termination in BUDGET else
                "empty_final" if termination == "EMPTY_MODEL_STOP" else termination,
                Y=row.get("Y"),
                recording_complete=viable and parsed["recording_complete"],
                anomalies=parsed["anomalies"],
                thought_lengths=[{"round_id": r.get("round_id"),
                                  "source_chars": len(r.get("reasoning_content") or ""),
                                  "serving_reported_reasoning_tokens": r.get("reasoning_tokens"),
                                  "serving_reported_input_tokens": r.get("prompt_tokens")}
                                 for r in trace["rounds"]],
                **{k: parsed[k] for k in ("token_alignment_status", "policy_token_spans", "policy_token_count")})
    return {"input_index": row, "provenance": provenance, "task_specs": task,
            "stages": stages, "tool_events": parsed["tool_events"], "position_map": parsed["position_map"],
            "legacy_stage_mapping": [{"stage_id": s["stage_id"], "mapping": s["legacy_mapping"],
                                      "status": s["legacy_mapping_status"]} for s in stages],
            "ledger_snapshots": states, "action_targets": list(targets.values()),
            "stage_judgments": judgments, "trajectory_summaries": summarize_trajectory(
                info, task, ledger, stages, judgments, submitted_candidate=candidate),
            "parse_failures": parsed["anomalies"], "annotation_failures": annotation_errors}


def consolidate(output, bundles, selected, freeze):
    split_counts = {}
    for split in sorted({row["split"] for row in selected}):
        count = Counter()
        for bundle in bundles:
            if bundle["input_index"]["split"] != split:
                continue
            summary = bundle.get("trajectory_summaries")
            count.update(trajectories=1, failed=int(summary is None),
                         stages=len(bundle.get("stages", [])),
                         annotation_errors=len(bundle.get("annotation_failures", [])),
                         parse_anomalies=len(bundle.get("parse_failures", [])))
            if summary:
                count.update(summary["counts"])
                count.update(token_verified=int(summary["token_alignment_status"] == "verified"),
                             parallel_groups=sum(bool(s["parallel_group_id"]) for s in bundle["stages"]),
                             tool_events=len(bundle["tool_events"]), prunable_events=len(summary["events"]),
                             tool_stages=summary["tool_stage_count"],
                             normal_finals=sum(s["stage_type"] == "final" for s in bundle["stages"]),
                             partial_stages=sum(s["stage_type"] == "partial" for s in bundle["stages"]),
                             failed_annotation_trajectories=bool(bundle["annotation_failures"]),
                             fully_recorded=summary["recording_complete"],
                             valid_grounding=int(summary["grounding_status"] == "valid"))
        count["label_abstentions"] = sum(v for key, v in count.items() if key.endswith(":abstain"))
        count["questions"] = len({r["question_id"] for r in selected if r["split"] == split})
        split_counts[split] = dict(count)
    for name in PRIVATE_ARTIFACTS:
        def projected():
            for bundle in bundles:
                value = bundle.get(name)
                if value is None:
                    continue
                for item in value if isinstance(value, list) else [value]:
                    yield {**item, "trajectory_id": bundle["input_index"]["trajectory_id"],
                           "question_id": bundle["input_index"]["question_id"],
                           "split": bundle["input_index"]["split"], "provenance": bundle["provenance"]}
        write_jsonl(output / f"{name}.jsonl", projected())
    atomic_json(output / "metrics.json", {"splits": split_counts, "input_count": len(selected),
                "annotation_count": sum(bool(bundle.get("trajectory_summaries")) for bundle in bundles),
                "receipt_count": len(bundles), "freeze": freeze})


def reference_cost(stages):
    costs = []
    for stage in stages:
        cost = stage["cost"]
        if stage["stage_type"] == "tool" and not stage["parallel_group_id"] and all(
            type(cost.get(key)) is int for key in ("policy_tokens", "return_tokens")
        ):
            costs.append((stage["stage_id"], cost["policy_tokens"] + cost["return_tokens"]))
    if costs and median(value for _, value in costs) > 0:
        ordered = sorted(costs)
        return {"median": median(value for _, value in ordered), "split": "dev",
                "sample_size": len(ordered), "sample_sha256": identity(ordered)}
    return None


def annotate(config, args):
    if args.limit_questions is not None and (args.split != "dev" or args.limit_questions < 1):
        raise ValueError("only a positive development question limit is supported")
    index = jsonl(config["input_index"])
    if not index:
        raise ValueError("BLOCKED_DATA: empty input index")
    if any(row["split"] not in {"dev", "calibration", "audit"} for row in index):
        raise ValueError("input index contains an unknown split")
    if config.get("mode") not in {"real", "synthetic"}:
        raise ValueError("set mode to real or synthetic explicitly")
    freeze = freeze_config(config)
    output = Path(config["output_dir"])
    synthetic = config.get("mode") == "synthetic"
    output = output / ("synthetic" if synthetic else "real")
    config = dict(config)
    tokenizer = (NativeByteTokenizer(config["tokenizer"], config["tokenizer_revision"])
                 if config.get("tokenizer") else None)
    legacy = load_legacy(config)
    groups = group_tasks(index, args.split, args.limit_questions, config.get("pilot_seed", 20261113))
    selected = [row for group in groups for row in group]
    expected_index_sha = sha256(Path(config["input_index"]).read_bytes()).hexdigest()
    manifest_file = output / "run_manifest.json"
    if manifest_file.exists() and not args.resume:
        raise ValueError("output exists; use --resume with the same frozen identities")
    output.mkdir(parents=True, exist_ok=True)
    model_cache = output / "model_cache"
    real = not synthetic
    def make_judge():
        return ModelJudge(config["judge"], config["prompt_dir"], model_cache, freeze,
                          replay_only=args.replay_only) if real else SyntheticJudge()
    freeze.update(prompt_sha256=make_judge().prompt_sha256, input_index_sha256=expected_index_sha)
    manifest = {"freeze": freeze, "synthetic": synthetic}
    if manifest_file.exists() and read_json(manifest_file) != manifest:
        raise ValueError("output was created by another frozen configuration")
    atomic_json(manifest_file, manifest)
    if real and not args.replay_only:
        probe = make_judge()
        try:
            spec, _ = init_task_ledger("Which city hosted the 2012 Summer Olympics?", probe)
            if spec["status"] != "ok" or not spec["constraints"]:
                raise JudgeFailure("model probe returned no constraints")
        except JudgeFailure as exc:
            raise ValueError(f"BLOCKED_MODEL: {exc}") from exc

    def process(group):
        judge = make_judge()
        task, initial = init_task_ledger(group[0]["question"], judge)
        bundles = []
        for row in group:
            digest = identity([freeze, row["sha256"], row["trajectory_id"]])
            receipt = output / "bundles" / (digest + ".json")
            bundle = read_json(receipt) if receipt.is_file() and args.resume else None
            if bundle is None or bundle.get("annotation_failures") or not bundle.get("trajectory_summaries"):
                try:
                    bundle = annotate_one(row, task, initial, judge, tokenizer, legacy[row["trajectory_id"]],
                                          freeze, config)
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    bundle = {"input_index": row, "provenance": dict(freeze, input_sha256=row["sha256"]),
                              "parse_failures": [{"reason": str(exc), "state": "TRACE_REJECTED"}]}
                atomic_json(receipt, bundle)
            bundles.append(bundle)
        print("question", group[0]["question_id"], "trajectories", len(bundles), flush=True)
        return bundles

    with ThreadPoolExecutor(max_workers=config.get("workers", 4)) as pool:
        if args.split == "all":
            bundles = []
            for split in ("dev", "calibration", "audit"):
                subset = [group for group in groups if group[0]["split"] == split]
                partition = [bundle for group in pool.map(process, subset) for bundle in group]
                if split == "dev":
                    reference = reference_cost(stage for bundle in partition for stage in bundle.get("stages", []))
                    if reference is None and config.get("cost_weighted"):
                        raise ValueError("cost weighting requires measured development events")
                    reference_path = output / "reference_cost.json"
                    if reference_path.exists() and read_json(reference_path) != reference:
                        raise ValueError("development cost reference changed after freeze")
                    atomic_json(reference_path, reference)
                bundles.extend(partition)
        else:
            bundles = [bundle for group in pool.map(process, groups) for bundle in group]
    consolidate(output, bundles, selected, freeze)
    print(canonical(read_json(output / "metrics.json")), flush=True)
    return 0


def inspect(config):
    path = Path(config["input_index"])
    if not path.is_file():
        print("BLOCKED_DATA: input index missing", file=sys.stderr)
        return 2
    rows = jsonl(path)
    if rows and config.get("mode") == "real":
        try:
            ModelJudge(config["judge"], config["prompt_dir"], Path(config["output_dir"]) / "real" / "model_cache",
                       freeze_config(config)).check_service()
        except (JudgeFailure, OSError, KeyError, TypeError, ValueError) as exc:
            print(f"BLOCKED_MODEL: {exc}", file=sys.stderr)
            return 2
    print(canonical({"status": "READY" if rows else "BLOCKED_DATA", "input_count": len(rows),
                     "questions": len({row["question_id"] for row in rows}),
                     "freeze": freeze_config(config)}))
    return 0 if rows else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "annotate", "export-review", "audit", "reward-preview"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--split", choices=("all", "dev", "calibration", "audit"), default="all")
    parser.add_argument("--limit-questions", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--replay-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = config_file(args.config)
        if args.command == "annotate":
            return annotate(config, args)
        if args.command == "inspect":
            return inspect(config)
        from .review_workflow import execute
        return execute(args.command, config)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"{args.command} error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
