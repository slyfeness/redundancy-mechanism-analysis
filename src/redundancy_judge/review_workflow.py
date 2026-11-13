"""Build independent human review queues and a calculation-only reward preview."""

from collections import Counter, defaultdict
import csv
from pathlib import Path
from statistics import median

from .audit_judge import audit_judge
from .build_grpo_inputs import build_grpo_inputs
from .cli import jsonl, write_jsonl
from .common import atomic_json, canonical, identity, read_json


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
    strata = defaultdict(list)
    for row in rows:
        if row["split"] == "audit" and row["label"] in ("R1", "R2b"):
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
        if row["split"] == "audit" and row["label"] in ("R1", "R2b"):
            for reason in row["protections"]:
                challenges[(row["label"], reason)].append(row)
    seen = set()
    for (label, reason), pool in sorted(challenges.items()):
        for row in sorted(pool, key=lambda r: identity([seed, reason, r["event_id"]]))[:20]:
            key = (label, row["event_id"])
            if key not in seen:
                seen.add(key)
                samples.append((row, "protection", 1.0, reason))
    manifest, blind = [], []
    for row, kind, probability, reason in samples:
        key = {field: row[field] for field in ("event_id", "question_id", "trajectory_id", "stage_id", "label")}
        key.update(sample_kind=kind, selection_probability=probability)
        blind.append(key)
        manifest.append({**key, "automatic_decision": row["decision"], "automatic_protection": reason})
    write_jsonl(folder / "audit_sampling_manifest.jsonl", manifest)
    fields = ["event_id", "question_id", "trajectory_id", "stage_id", "label", "sample_kind", "selection_probability",
              "human_decision", "necessary", "reviewer_id", "independent", "source", "adjudication", "protection_reason"]
    with (folder / "human_review_template.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(blind)
    return len(blind)


def execute(command, config):
    folder = Path(config["run_dir"])
    if command in ("export-review", "audit"):
        rows = quick_rows(folder)
        if command == "export-review":
            print(f"exported {export_review(folder, rows, config)} independent review units")
            return 0
        humans = jsonl(config["human_annotations"]) if config.get("human_annotations") else []
        legacy = jsonl(config["reviewed_legacy_links"]) if config.get("reviewed_legacy_links") else []
        write_jsonl(folder / "audit_annotations.jsonl", humans)
        planned_path = folder / "audit_sampling_manifest.jsonl"
        planned = jsonl(planned_path) if planned_path.is_file() else None
        report = audit_judge(rows, humans, legacy, config=config.get("thresholds"), planned_reviews=planned)
        atomic_json(folder / "acceptance.json", report)
        atomic_json(folder / "approved_labels.json", report["approved_labels"])
        print(report["status"])
        return 0

    summaries = jsonl(folder / "trajectory_summaries.jsonl")
    price_path = folder / "approved_labels.json"
    approvals = read_json(price_path) if price_path.is_file() else {}
    options = config["reward"]
    valid_costs = []
    for stage in jsonl(folder / "stages.jsonl"):
        cost = stage["cost"]
        if stage["split"] == "dev" and stage["stage_type"] == "tool" and all(
            type(cost.get(k)) is int for k in ("policy_tokens", "return_tokens")):
            valid_costs.append((stage["stage_id"], cost["policy_tokens"] + cost["return_tokens"]))
    if valid_costs:
        reference = {"median": median(v for _, v in valid_costs), "split": "dev",
                     "sample_sha256": identity(valid_costs)}
        atomic_json(folder / "reference_cost.json", reference)
        if config.get("cost_weighted"):
            options = {**options, "price_mode": "cost_weighted", "reference_cost": reference}
    preview = build_grpo_inputs(summaries, options, approved_labels=approvals)
    groups = preview.pop("groups")
    write_jsonl(folder / "reward_preview.jsonl", groups)
    preview.update(computed_groups=len(groups), computed_trajectories=sum(len(g["trajectories"]) for g in groups),
                   applied_event_debits=sum(event["debit"] > 0 for g in groups for t in g["trajectories"]
                                            for event in t["event_debits"]))
    atomic_json(folder / "reward_preview_summary.json", preview)
    print(canonical({key: preview[key] for key in ("status", "computed_groups", "computed_trajectories",
                                                   "applied_event_debits", "optimizer_steps")}))
    return 0
