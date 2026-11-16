"""Build independent human review queues and a calculation-only reward preview."""

from collections import Counter, defaultdict
import csv
from pathlib import Path

from .audit_judge import LABELS, audit_judge
from .build_grpo_inputs import build_grpo_inputs
from .cli import jsonl, reference_cost, write_jsonl
from .common import atomic_json, canonical, identity, read_json


PROTECTION_KINDS = ("first_evidence", "resolve_conflict", "independent_support",
                    "summary_to_fulltext", "restore_invisible_evidence", "tool_failure_retry")


def _review_labels(config):
    return ("R2b", "R2a") if config.get("phase1_mode") == "docid" else LABELS


def quick_rows(folder):
    judgments = jsonl(folder / "stage_judgments.jsonl")
    return [
        {**label, **{key: judgment[key] for key in (
            "event_id", "question_id", "trajectory_id", "split", "synthetic", "provenance")},
         "stage_id": judgment["stage_id"], "protections": judgment["protections"]}
        for judgment in judgments for label in judgment["labels"]
    ]


def export_review(folder, rows, config):
    if any(r["synthetic"] for r in rows):
        raise ValueError("human quality audit requires real annotation")
    seed = config.get("review_seed", 20261113)
    labels = _review_labels(config)
    strata = defaultdict(list)
    for row in rows:
        if row["split"] == "audit" and row["label"] in labels:
            strata[(row["label"], row["decision"])].append(row)
    samples = []
    for (label, decision), pool in sorted(strata.items()):
        count = min(100, len(pool))
        question_pools = defaultdict(list)
        for row in pool:
            question_pools[row["question_id"]].append(row)
        if len(question_pools) <= count:
            per_question = {qid: min(len(group), count // len(question_pools))
                            for qid, group in question_pools.items()}
            left = count - sum(per_question.values())
            for qid in sorted(question_pools, key=lambda key: identity([seed, label, decision, key])):
                n = min(left, len(question_pools[qid]) - per_question[qid])
                per_question[qid] += n
                left -= n
            for qid, group in sorted(question_pools.items()):
                n = per_question[qid]
                ranked = sorted(group, key=lambda r: identity([seed, label, decision, r["event_id"]]))
                samples.extend((row, "natural", n / len(group), None) for row in ranked[:n])
        else:
            ranked = sorted(pool, key=lambda r: identity([seed, label, decision, r["event_id"]]))
            samples.extend((row, "natural", count / len(pool), None) for row in ranked[:count])
    challenges = defaultdict(list)
    for row in rows:
        if row["split"] == "audit" and row["label"] in labels:
            for reason in row["protections"]:
                challenges[(row["label"], reason)].append(row)
    challenge_report = []
    for label in labels:
        selected = {}
        for reason in sorted(PROTECTION_KINDS, key=lambda reason: (len(challenges[label, reason]), reason)):
            pool = challenges[label, reason]
            sample = sorted(pool, key=lambda r: identity([seed, reason, r["event_id"]]))[:20]
            for row in sample:
                selected.setdefault(row["event_id"], (row, []))[1].append(reason)
            challenge_report.append({"label": label, "protection": reason, "pool": len(pool),
                                     "selected": len(sample), "target": 20})
        samples.extend((row, "protection", 1.0, reasons) for row, reasons in selected.values())
    manifest, blind = [], []
    for row, kind, probability, reason in samples:
        key = {field: row[field] for field in ("event_id", "question_id", "trajectory_id", "stage_id", "label")}
        key.update(sample_kind=kind, selection_probability=probability)
        blind.append(key)
        manifest.append({**key, "automatic_decision": row["decision"], "challenge_categories": reason})
    write_jsonl(folder / "audit_sampling_manifest.jsonl", manifest)
    atomic_json(folder / "protection_sampling.json", {"design": "purposeful challenge, unweighted",
                "category_pools": challenge_report})
    fields = ["event_id", "question_id", "trajectory_id", "stage_id", "label", "sample_kind", "selection_probability",
              "human_decision", "necessary", "reviewer_id", "independent", "source", "adjudication", "protection_reason"]
    with (folder / "human_review_template.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(blind)
    write_blind_packets(folder, blind)
    return len(blind)


def write_blind_packets(folder, blind):
    units = defaultdict(list)
    for row in blind:
        units[row["trajectory_id"]].append(row)

    def packets():
        for source in jsonl(folder / "input_index.jsonl"):
            trajectory_id = source["trajectory_id"]
            if trajectory_id not in units:
                continue
            raw = read_json(source["path"])
            events = {}
            for i, event in enumerate(raw["tool_events"]):
                identity_key = str(event.get("event_id", f"unknown:{i}"))
                key = identity_key if identity_key not in events else f"duplicate-event:{i}"
                events[key] = event
            for unit in units[trajectory_id]:
                event = events[unit["event_id"].removeprefix(trajectory_id + ":")]
                round_id = event["round_id"]
                current = next(item for item in raw["rounds"] if item["round_id"] == round_id)
                yield {**unit, "question": source["question"],
                       "actor_visible_prefix": current["actor_visible_messages"],
                       "current_strategy": current.get("reasoning_content"),
                       "current_content": current.get("content"),
                       "tool_calls": current.get("tool_calls"),
                       "observed_event": {key: event.get(key) for key in ("tool_name", "tool_call_id",
                           "exact_arguments", "exact_result", "dispatch_order", "return_order",
                           "dispatch_utc", "return_utc", "raw_mcp_response")}}

    write_jsonl(folder / "human_review_packets.jsonl", packets())


def execute(command, config):
    folder = Path(config["run_dir"])
    if command in ("export-review", "audit"):
        if read_json(folder / "run_manifest.json")["synthetic"]:
            raise ValueError("human quality audit requires real annotation")
        rows = quick_rows(folder)
        if command == "export-review":
            print(f"exported {export_review(folder, rows, config)} independent review units")
            return 0
        humans = jsonl(config["human_annotations"]) if config.get("human_annotations") else []
        legacy = jsonl(config["reviewed_legacy_links"]) if config.get("reviewed_legacy_links") else []
        write_jsonl(folder / "audit_annotations.jsonl", humans)
        planned_path = folder / "audit_sampling_manifest.jsonl"
        planned = jsonl(planned_path) if planned_path.is_file() else None
        report = audit_judge(rows, humans, legacy, config=config.get("thresholds"), planned_reviews=planned,
                             label_ids=_review_labels(config))
        atomic_json(folder / "acceptance.json", report)
        atomic_json(folder / "approved_labels.json", report["approved_labels"])
        print(report["status"])
        return 0

    summaries = jsonl(folder / "trajectory_summaries.jsonl")
    price_path = folder / "approved_labels.json"
    approvals = read_json(price_path) if price_path.is_file() else {}
    options = config["reward"]
    if config.get("cost_weighted"):
        reference = read_json(folder / "reference_cost.json")
        measured = reference_cost(stage for stage in jsonl(folder / "stages.jsonl") if stage["split"] == "dev")
        if reference != measured or reference is None:
            raise ValueError("development cost receipt differs from the frozen reference")
        options = {**options, "price_mode": "cost_weighted", "reference_cost": reference}
    preview = build_grpo_inputs(summaries, options, approved_labels=approvals)
    groups = preview.pop("groups")
    write_jsonl(folder / "reward_preview.jsonl", groups)
    preview.update(computed_groups=len(groups), computed_trajectories=sum(len(g["trajectories"]) for g in groups),
                   applied_event_debits=sum(event["debit"] > 0 for g in groups for t in g["trajectories"]
                                            for event in t["event_debits"]))
    pure = build_grpo_inputs(summaries, {**options, "w_g": 0, "prices": {"R1": 0, "R2b": 0, "R2a": 0}},
                             approved_labels={})
    pure_groups = pure.pop("groups")
    write_jsonl(folder / "outcome_only_preview.jsonl", pure_groups)
    preview["outcome_only_control"] = {"status": pure["status"], "assertions": pure["assertions"],
                                      "groups": len(pure_groups),
                                      "trajectories": sum(len(g["trajectories"]) for g in pure_groups)}
    atomic_json(folder / "reward_preview_summary.json", preview)
    print(canonical({key: preview[key] for key in ("status", "computed_groups", "computed_trajectories",
                                                   "applied_event_debits", "optimizer_steps")}))
    return 0
