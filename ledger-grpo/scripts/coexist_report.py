"""Summarize measured device peaks and throughput without discarding raw telemetry."""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from pathlib import Path
import re
from statistics import mean
import sys

from redundancy_judge.cli import jsonl
from redundancy_judge.common import atomic_json, read_json


def telemetry(path):
    rows = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for fields in csv.reader(stream, skipinitialspace=True):
            try:
                ts = datetime.strptime(fields[0], "%Y/%m/%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
                rows.append((ts.timestamp(), fields[1], int(fields[2]), int(fields[4]), int(fields[5])))
            except (IndexError, ValueError):
                continue
    return rows


def select(samples, start, end):
    return [row for row in samples if start <= row[0] <= end]


def peak(samples):
    result = defaultdict(int)
    for _, device, memory, _, _ in samples:
        result[device] = max(result[device], memory)
    return dict(result)


def gpu_use(samples):
    by_device = defaultdict(list)
    for _, device, _, util, _ in samples:
        by_device[device].append(util)
    return {device: {"samples": len(values), "mean_gpu_util_pct": mean(values)}
            for device, values in by_device.items()}


def signatures(folder):
    counts = Counter()
    matchers = {"oom": re.compile(r"out of memory|outofmemoryerror", re.I),
                "kv_pressure": re.compile(r"less than desired gpu memory utilization|"
                         r"to serve at least one request|kv cache.*not enough|no available memory for the cache", re.I),
                "nccl_error": re.compile(r"nccl.*(?:error|failure|timeout|warn).*", re.I)}
    for path in folder.rglob("*.log"):
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                counts.update(name for name, rexp in matchers.items() if rexp.search(line))
    return {name + "_log_line_count": counts[name] for name in matchers}


def summarize(root, baseline):
    cfg = read_json(root / "config.json")
    reference_path = baseline / "train-P0"
    rollout = read_json(reference_path/"ROLLOUT_RESULT.json")
    trajectories = read_json(reference_path/"TRAJECTORY_METRICS.json")
    reference = {"job": 182516, "generation_seconds": rollout["generation_seconds"], "trajectories": len(trajectories),
                 "generated_tokens": sum(rec["generated_tokens"] for rec in trajectories)}
    reference["generation_tokens_per_second"] = reference["generated_tokens"] / reference["generation_seconds"]
    samples = telemetry(root/"gpu-samples.csv")
    stages = jsonl(root/"phases.jsonl")
    layouts = {}
    for name in ("A","B","C"):
        attempts = sorted(root.glob(name+"-[12]/result.json"))
        if not attempts:
            continue
        rows = [read_json(path) for path in attempts]
        run, chosen = attempts[-1].parent, rows[-1]
        relevant = [phase for phase in stages if phase.get("layout") == name]
        stats = signatures(run)
        if relevant:
            stats["peak_gpu_mib"] = peak(select(samples, relevant[0]["started_epoch"], relevant[-1]["ended_epoch"]))
        for batch in chosen["batches"]:
            archive = batch.get("generation_archive")
            tail_samples = telemetry(Path(archive).parents[1] / "gpu-samples.csv") if archive else samples
            batch["tail_gpu_utilization"] = (None if batch["tail_start_epoch"] is None else
                                             gpu_use(select(tail_samples, batch["tail_start_epoch"], batch["tail_end_epoch"])))
            batch["generation_change_pct"] = 100 * (batch["generation_tokens_per_second"] /
                                                      reference["generation_tokens_per_second"] - 1)
        rank = [read_json(path) for path in sorted((run/"isolated-update").glob("MEMORY-rank*.json"))]
        fsdp = {"rank_receipts": rank, "matches_peak_check": None,
                "historic_comparison": {"job": 181915, "max_allocated_bytes": 81041387520, "max_reserved_bytes": 83078676480}}
        if rank:
            fsdp["comparable_peak_no_increase_vs_historic"] = (
                max(x["peak_allocated_bytes"] for x in rank) <= 81041387520
                and max(x["peak_reserved_bytes"] for x in rank) <= 83078676480)
            fsdp["matches_peak_check"] = fsdp["comparable_peak_no_increase_vs_historic"]
        ready = len(chosen["batches"]) == 3 and chosen.get("status") == "completed" and not stats["oom_log_line_count"]
        consistent = chosen.get("consistency", {}).get("pure", {}).get("ok") is True
        approved = ready and consistent and fsdp["matches_peak_check"] is True and bool((chosen.get("update") or {}).get("step_complete"))
        layouts[name] = {"attempts": rows, "peak_and_errors": stats, "fsdp": fsdp,
                         "three_batches_no_oom": ready, "code_label_exact": consistent,
                         "passes_comparison_gates": approved}
    rank = sorted((row["attempts"][-1]["batches"][-1]["step_seconds_including_update"], name)
                  for name,row in layouts.items() if row["passes_comparison_gates"]
                  and row["attempts"][-1]["batches"][-1]["step_seconds_including_update"] is not None)
    return {"baseline": reference, "layouts": layouts, "recommended_layout": rank[0][1] if rank else None,
            "limits": {"context_actor": 65536, "context_judge": 131072, "max_judge_sequences": 16,
                       "pressure_batches_per_layout": 3, "trajectories_per_batch": 128,
                       "fsdp_comparison": "historical per-rank peak bound; live input shapes differ",
                       "price_label": "R2b", "outcome_verifier": cfg["outcome_verifier"]}}


if __name__ == "__main__":
    root, baseline = map(Path, sys.argv[1:])
    atomic_json(root/"coexist-summary.json", summarize(root, baseline))
