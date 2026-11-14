"""Unblind a frozen set of independent result verdicts for paired analysis."""

import argparse
from collections import Counter
import json
from pathlib import Path

from export_blind_result_review import ARMS, PROTOCOL
from ledger_grpo.evaluation import paired_event_diagnostics
from regrade_pilot import read, sha


def _read_review(root):
    frozen = read(root / "FREEZE.json")
    packet_sha = sha(root / "PACKET.json")
    verdict_sha = sha(root / "BLIND_VERDICTS.json")
    if frozen["sha256"] != {"PACKET.json": packet_sha, "BLIND_VERDICTS.json": verdict_sha}:
        raise ValueError("review and packet must match the pre-unblinding freeze")
    packet, review, identity = (read(root / name) for name in ("PACKET.json", "BLIND_VERDICTS.json", "IDENTITIES.json"))
    cases = [row["id"] for group in packet["groups"] for row in group["cases"]]
    verdicts = review["verdicts"]
    if (not cases or len(set(cases)) != len(cases) or set(cases) != verdicts.keys()
            or set(cases) != identity["cases"].keys() or identity["packet_sha256"] != packet_sha
            or packet["protocol"] != PROTOCOL):
        raise ValueError("incomplete or mismatched independent review")
    numeric = {"equivalent": 1, "not_equivalent": 0, "uncertain": None}
    by_sample = {}
    for case, binding in identity["cases"].items():
        key = binding["arm"], binding["task_id"], binding["sample_id"]
        if key in by_sample or key[0] not in ARMS or key[0] not in identity["bindings"]:
            raise ValueError("invalid or duplicate review sample")
        by_sample[key] = (numeric[verdicts[case]], binding["archived_verdict"])
    metadata = {"reviewer": review["reviewer"], "review_method": review["method"],
                "frozen_sha256": frozen["sha256"], "identity_sha256": sha(root/"IDENTITIES.json"),
                "export_job": frozen["export_job"], "normal_submissions": len(cases)}
    return by_sample, identity, metadata


def load_reviewed_rows(root, evaluations, *, additions=()):
    by_sample, original, metadata = _read_review(root)
    bindings = original["bindings"].copy()
    reviews = [metadata]
    for path in additions:
        more, identities, receipt = _read_review(path)
        if any(identities[k] != original[k] for k in ("source_run", "judge_identity", "plan_sha256")):
            raise ValueError("additional blind review refers to a different experiment or grading protocol")
        if more.keys() & by_sample.keys() or identities["bindings"].keys() & bindings.keys():
            raise ValueError("additional blind review must cover distinct arms and samples")
        by_sample.update(more)
        bindings.update(identities["bindings"])
        reviews.append(receipt)
    if "targeted" not in bindings:
        raise ValueError("comparison requires a reviewed targeted arm")
    agreement = Counter()
    paired, summaries = {}, {}
    fixed_sample_ids = None
    for arm in ARMS:
        if arm not in bindings:
            continue
        path = evaluations / f"EVAL-{arm}.json"
        if sha(path) != bindings[arm]["original_eval_sha256"]:
            raise ValueError("evaluation is not the frozen source")
        rows = read(path)["rows"]
        sample_ids = {(row["task_id"], row["sample_id"]) for row in rows}
        if len(rows) != 128 or len(sample_ids) != 128:
            raise ValueError("expected all 128 fixed evaluation samples for each reviewed arm")
        if fixed_sample_ids is not None and sample_ids != fixed_sample_ids:
            raise ValueError("reviewed arms must have identical fixed evaluation samples")
        fixed_sample_ids = sample_ids
        converted, counts = [], Counter()
        for row in rows:
            if row["complete"]:
                score, archived = by_sample.pop((arm, row["task_id"], row["sample_id"]))
                if archived != row["outcome"]:
                    raise ValueError("archived outcome disagrees with frozen binding")
                if archived is not None:
                    agreement["uncertain" if score is None else f"archive_{int(archived)}_blind_{score}"] += 1
                counts["normal_submissions"] += 1
            else:
                if row["outcome"] != 0:
                    raise ValueError("expected a terminal failure outcome")
                score = 0
                counts["terminal_failures"] += 1
            counts["equivalent"] += int(score == 1)
            counts["uncertain"] += int(score is None)
            converted.append(dict(row, outcome=score))
        n = len(rows)
        summaries[arm] = {"samples": n, **counts, "evaluation_sha256": sha(path),
                          "diagnostic_accuracy": counts["equivalent"]/n if not counts["uncertain"] else None,
                          "diagnostic_accuracy_bounds": [counts["equivalent"]/n, (counts["equivalent"]+counts["uncertain"])/n]}
        paired[arm] = converted
    if by_sample:
        raise ValueError("review case is not bound to a normal frozen submission")
    return paired, summaries, agreement, reviews, metadata


def summarize(root, evaluations, *, additions=()):
    paired, summaries, agreement, reviews, metadata = load_reviewed_rows(root, evaluations, additions=additions)
    comparisons, operational_comparisons = {}, {}
    for arm in paired:
        if arm == "targeted":
            continue
        name = f"targeted_minus_{arm}"
        delta = paired_event_diagnostics(paired[arm], paired["targeted"], additional_metrics=("gen_tokens",))["delta"]
        comparisons[name] = delta["outcome"]
        operational_comparisons[name] = {key: delta[key] for key in ("gen_tokens", "tool_calls", "budget_exhausted")}
    return {**metadata, "normal_submissions": sum(review["normal_submissions"] for review in reviews),
            "planned_protocol": PROTOCOL, "review_batches": reviews,
            "arms": summaries, "agreement_on_successfully_graded_normal_submissions": dict(agreement),
            "paired_diagnostic_comparisons": comparisons, "paired_operational_comparisons": operational_comparisons,
            "scope": "Offline semantic review by one independent model. Original outcomes are unchanged."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--additional-review", type=Path, action="append", default=[])
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.review, args.evaluations, additions=args.additional_review)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
    print(json.dumps({"arms": result["arms"], "agreement": result["agreement_on_successfully_graded_normal_submissions"]}))


if __name__ == "__main__":
    main()
