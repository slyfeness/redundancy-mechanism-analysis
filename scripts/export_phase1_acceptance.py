"""Export privacy-minimized engineering evidence from a frozen Phase 1 run."""

import argparse
from collections import Counter
from hashlib import sha256
from pathlib import Path
import re

from redundancy_judge.cli import jsonl, write_jsonl
from redundancy_judge.common import atomic_json, canonical, read_json


NOTE = """The cluster files listed in run_manifest.json live in its restricted Phase 1
run directory under the Zhurong bulk storage project. Access requires separate
approval from the project data steward. The inventory describes the immutable
historical BrowseComp-Plus source and its independent outcome ledger.
Verify SHA-256 before using the input index, private JSONL or replay cache.
The review CSV in this release is a field template. The restricted run holds
the event-coordinate CSV and blind prefix packets without automatic decisions,
reference answers or future responses.
"""


def safe_error(reason):
    known = {
        "evidence quote absent or ambiguous", "evidence quote does not match its character span",
        "duplicate candidate/constraint update", "invalid support coordinates or state",
        "missing task constraints", "missing task uncertainty", "duplicate constraint",
        "evidence extraction uncertain", "invalid action target", "invalid evidence update",
        "invalid R1 verification", "judge generation did not finish", "replay cache entry is missing",
        "invalid conflict resolution field", "empty evidence quote",
    }
    if reason in known:
        return reason
    if re.fullmatch(r"judge transport or JSON failure \([A-Za-z]+\)", reason):
        return reason
    return "other_private_error"


def export(run, inventory, verification, target, test_report, jobs):
    outputs = run / "real"
    target.mkdir(parents=True, exist_ok=False)
    freeze = read_json(outputs / "run_manifest.json")["freeze"]
    metrics = read_json(outputs / "metrics.json")
    quality = read_json(outputs / "acceptance.json")
    reward = read_json(outputs / "reward_preview_summary.json")
    proof = read_json(verification / "mechanical.json")
    replay = read_json(verification / "replay_verification.json")
    account = Path(jobs).read_text(encoding="utf-8")
    source = read_json(inventory / "inventory.json")
    receipt = {"code_commit": freeze["code_commit"], "freeze": freeze,
               "private_output_directory": str(outputs), "inventory_directory": str(inventory),
               "private_output_sha256": proof["private_output_sha256"],
               "replay_verification_sha256": sha256((verification / "replay_verification.json").read_bytes()).hexdigest(),
               "cost_reference": read_json(outputs / "reference_cost.json"),
               "model_weights": "config/tokenizer/index byte hashes, shard sizes/mtimes and upstream metadata",
               "synthetic": False}
    for row in quality["labels"].values():
        if row["review_plan"]:
            row["review_plan"]["outstanding"] = len(row["review_plan"]["outstanding"])
        row["failure_cases"] = [{"decision": item["decision"], "human_decision": item["human_decision"]}
                                for item in row["failure_cases"]]
    for key in ("disagreements", "unresolved_reviews"):
        if quality[key]:
            raise ValueError("manual review identity requires explicit release projection")
    exclusions = Counter(reason for row in reward.pop("excluded") for reason in (
        *row["group_reasons"], *row["row_reasons"].values()))
    reward["excluded_reason_counts"] = dict(exclusions)
    proof["proof_failures"] = dict(Counter(r["error_class"] for r in proof.pop("proof_failures")))
    reasons = Counter()
    for key, value in proof["annotation_reasons"].items():
        reasons[safe_error(key)] += value
    proof["annotation_reasons"] = dict(reasons)
    acceptance = {"status": quality["status"], "judge": quality,
                  "engineering": {"status": "PASS" if proof["status"] == replay["status"] == "PASS"
                                  and all(reward["assertions"].values()) else "FAIL",
                                  "native_proof": proof, "replay": replay}}
    challenges = read_json(outputs / "protection_sampling.json")
    metrics["protection_sampling"] = challenges
    for name, data in (("inventory", source), ("run_manifest", receipt), ("metrics", metrics),
                       ("acceptance", acceptance), ("approved_labels", quality["approved_labels"]),
                       ("reward_preview_summary", reward)):
        atomic_json(target / f"{name}.json", data)
    review_manifest = jsonl(outputs / "audit_sampling_manifest.jsonl")
    write_jsonl(target / "audit_sampling_manifest.jsonl", (
        {"unit": num, **{k: row[k] for k in (
            "label", "sample_kind", "selection_probability", "automatic_decision", "challenge_categories"
        )}} for num, row in enumerate(review_manifest, 1)))
    with (outputs / "human_review_template.csv").open(encoding="utf-8") as stream:
        (target / "human_review_template.csv").write_text(stream.readline(), encoding="utf-8", newline="\n")
    errors = [{"kind": "annotation", "reason": reason, "events": count}
              for reason, count in proof["annotation_reasons"].items()]
    errors.extend({"kind": "parser", "reason": reason, "events": count}
                  for reason, count in proof["parse_codes"].items())
    examples = {}
    for row in jsonl(outputs / "stage_judgments.jsonl"):
        for label in row["labels"]:
            name, decision = label["label"], label["decision"]
            key = (name, decision, label["abstention_reason"])
            if key in examples:
                continue
            examples[key] = {"kind": "anonymized_observation", "split": row["split"], "label": name,
                             "decision": decision, "reason": label["abstention_reason"],
                             "protections": row["protections"], "evidence_count": len(label["evidence"]),
                             "price_candidate": row["price_label"],
                             "charge_token_count": sum(b - a for a, b in row["charge_token_spans"]),
                             "exact_match_count": len(row["diagnostics"]["exact_repeat_ids"]),
                             "effective_gain": row["diagnostics"]["effective_gain"],
                             "known_after_return": label["decision_time"] == "after_return"}
    errors.extend(examples.values())
    write_jsonl(target / "failure_cases.jsonl", errors)
    (target / "data_access.md").write_text(NOTE, encoding="utf-8", newline="\n")
    (target / "execution.log").write_text(account, encoding="utf-8", newline="\n")
    (target / "test_results.xml").write_bytes(test_report.read_bytes())
    print(canonical({"status": acceptance["status"], "review_units": len(review_manifest),
                     "engineering": acceptance["engineering"]["status"], "target": str(target)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "inventory", "verification", "target", "test-report", "jobs"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    export(args.run, args.inventory, args.verification, args.target, args.test_report, args.jobs)


if __name__ == "__main__":
    main()
