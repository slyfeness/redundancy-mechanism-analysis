"""Estimate the R2a 0.02 counterfactual without writing GRPO inputs."""

import argparse
from collections import Counter, defaultdict
import math
from pathlib import Path
from statistics import median

from redundancy_judge.build_grpo_inputs import _positions
from redundancy_judge.cli import jsonl
from redundancy_judge.common import atomic_json, read_json


def distribution(values):
    values = list(values)
    return {"min": min(values), "median": median(values), "max": max(values),
            "mean": math.fsum(values) / len(values)} if values else dict.fromkeys(("min", "median", "max", "mean"))


def whatif(groups, judgments, cap):
    candidates = defaultdict(list)
    for row in judgments:
        spans = row["diagnostics"].get("r2a_whatif_token_spans", [])
        if spans:
            candidates[row["trajectory_id"]].append((row["event_id"], spans))
    values, counts = {}, Counter()
    for group in groups:
        counts["groups_with_no_correct"] += not any(row["Y"] for row in group["trajectories"])
        for row in group["trajectories"]:
            tid = row["trajectory_id"]
            masks = row["policy_mask"]
            taken = set()
            for event in row["event_debits"]:
                taken.update(_positions(event["charge_token_spans"], len(masks)))
            added = 0
            for eid, spans in candidates[tid]:
                try:
                    proposed = _positions(spans, len(masks))
                except ValueError:
                    counts["invalid_r2a_positions"] += 1
                    continue
                if not proposed or any(not masks[pos] for pos in proposed) or proposed & taken:
                    counts["unpriceable_r2a_positions"] += 1
                    continue
                taken.update(proposed)
                added += 1
            old = math.fsum(event["debit"] for event in row["event_debits"])
            base = math.fsum(event["base_price"] for event in row["event_debits"]) + .02 * added
            paid = min(cap, base) if row["peer_gate"] and not row["budget_process_disabled"] else 0
            counts["cap_triggers"] += base > cap
            counts["r2a_valid_candidates"] += added
            counts["r2a_exempt_no_peer"] += added if not row["peer_gate"] else 0
            values[tid] = {"R": row["R"], "old_debit": old, "whatif_debit": paid,
                           "change": paid-old, "r2a_candidates": added}
    return {"r2a_price": .02, "trajectory_count": len(values), "optimizer_steps": 0, "counts": counts,
            "old_debit": distribution(v["old_debit"] for v in values.values()),
            "whatif_debit": distribution(v["whatif_debit"] for v in values.values()),
            "debit_change": distribution(v["change"] for v in values.values()),
            "per_trajectory": values}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    cap = read_json(args.run / "config.json")["reward"].get("trajectory_price_cap", .5)
    atomic_json(args.run / "r2a_whatif.json", whatif(jsonl(args.run / "provisional_reward_dryrun.jsonl"),
        jsonl(args.run / "real/stage_judgments.jsonl"), cap))
