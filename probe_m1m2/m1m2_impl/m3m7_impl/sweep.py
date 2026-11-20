"""Audit round4 strict-repeat labels and sweep M3–M7 without changing either rule."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256
from math import fsum, isfinite, isinf, isnan
from pathlib import Path
from statistics import fmean, median

from ledger_grpo.ledgercredit.ledger import repeat_flags
from ledger_grpo.ledgercredit.m3m7 import Config, assign, tool_signature
from ledger_grpo.ledgercredit.stages import event_fed
from prepare import METRICS, TYPES, emit, group_by_track, key, read, rows, write


LAMBDAS = (.5, 1., 2.)
KAPPAS = (0., .3, .6, 1.)
GROUPS = dict(zip(TYPES, ("全对", "有对有错", "全错"), strict=True))
REASONS = {
    "current_unfed": "本次返回未投喂",
    "same_unit_parallel": "并行单元内的前序子调用",
    "comparison": "查询或返回比较口径",
    "non_ok": "调用状态非 ok",
    "mixed_reasons": "多个因素",
    "other": "其他",
}


def candidate_pair(current, prior, same_unit):
    event, signature = current
    previous, previous_signature = prior
    if event["tool"] != previous["tool"]:
        return None
    legacy_compare = repeat_flags(event, [previous], set())[1]
    new_compare = signature is not None and signature == previous_signature
    current_fed, previous_fed = event_fed(event), event_fed(previous)
    old = legacy_compare and current_fed and previous_fed and event["status"] == previous["status"] == "ok"
    new = new_compare and previous_fed and not same_unit
    if not old and not new:
        return None
    reasons = []
    if old and not new:
        if same_unit:
            reasons.append("same_unit_parallel")
        if not new_compare:
            reasons.append("comparison")
    if new and not old:
        if not current_fed:
            reasons.append("current_unfed")
        if event["status"] != "ok" or previous["status"] != "ok":
            reasons.append("non_ok")
        # M2 records parsed query/offset fields only on successful calls.
        if not legacy_compare and event["status"] == previous["status"] == "ok":
            reasons.append("comparison")
    return {"m2": old, "n3": new, "same_unit": same_unit, "reasons": reasons,
            "raw_signature_equal": new_compare, "m2_signature_equal": legacy_compare,
            "return_equal": event["return_text"] == previous["return_text"],
            "current_fed": current_fed, "prior_fed": previous_fed,
            "current_status": event["status"], "prior_status": previous["status"]}


def audit_repeats(stages, states, scored):
    details, counts = [], Counter()
    inputs = {key(row): row for row in scored}
    seen = set()
    for group in group_by_track(stages.values()).values():
        history = []
        for stage in group:
            label = key(stage)
            signal, frozen = inputs[label], states[label]
            seen.add(label)
            events = [(event, tool_signature(event)) for event in stage["tool_events"]]
            old_children, new_children, witnesses = [], [], []
            for index, current in enumerate(events):
                old_match = new_match = False
                for pos, child, prior in history:
                    pair = candidate_pair(current, prior, pos == stage["unit_id"])
                    if pair is None:
                        continue
                    old_match |= pair["m2"]
                    new_match |= pair["n3"]
                    witnesses.append({"child": index, "prior_unit_id": pos, "prior_child": child, **pair})
                if old_match:
                    old_children.append(index)
                if new_match:
                    new_children.append(index)
                history.append((stage["unit_id"], index, current))
            attempts = frozen["E_t"]["attempts"]
            if [x[0]["event_id"] for x in events] != [x["event_id"] for x in attempts]:
                raise ValueError("frozen M2 attempt ordering differs from source")
            if old_children != [i for i, a in enumerate(attempts) if a["strict_repeat"]]:
                raise ValueError("M2 child flags did not replay exactly")
            if new_children != signal["strict_repeat_children"] or bool(old_children) != bool(frozen["strict_repeat"]):
                raise ValueError("stage flags did not replay exactly")
            m2, n3 = bool(old_children), bool(new_children)
            if (m2, n3) != (bool(signal["strict_repeat"]), bool(signal["I_N"])):
                raise ValueError("repeat stage input flags diverged")
            counts["units"] += 1
            counts["old_strict"] += m2
            counts["new_strict"] += n3
            if len(events) > 1:
                counts["parallel"] += 1
                counts["n3_partial_parallel"] += 0 < len(new_children) < len(events)
                counts["m2_partial_parallel"] += 0 < len(old_children) < len(events)
            if m2 != n3:
                reasons = sorted({reason for pair in witnesses for reason in pair["reasons"]})
                reason = reasons[0] if len(reasons) == 1 else "mixed_reasons" if reasons else "other"
                counts[reason] += 1
                counts["m2_only" if m2 else "n3_only"] += 1
                details.append({"trajectory_id": label[0], "unit_id": label[1], "reason": reason,
                                "reason_factors": reasons, "m2": m2, "n3": n3,
                                "parallel": len(events) > 1, "child_count": len(events),
                                "m2_children": old_children, "n3_children": new_children, "matches": witnesses})
    if seen != inputs.keys() or seen != states.keys():
        raise ValueError("repeat audit did not cover the original eligible units")
    return dict(counts), sorted(details, key=key)


def aggregate(values):
    return {"n": len(values), "mean": fmean(values) if values else None,
            "median": median(values) if values else None, "nonnegative": sum(v >= 0 for v in values)}


def evaluate(values, receipts):
    gaps = {name: {"repeat": [], "progress": []} for name in TYPES}
    conservation, sign_flips, nan, inf, overlap = [], 0, 0, 0, 0
    for tid, track in group_by_track(values).items():
        aout, rho = receipts[tid]["A_out"], receipts[tid]["rho"]
        category = "all_correct" if rho == 1 else "all_wrong" if rho == 0 else "mixed"
        gen = sum(row["n_gen"] for row in track)
        if gen:
            conservation.append(abs(fsum(row["n_gen"] * row["A_re"] for row in track) / gen - aout))
        sign_flips += sum(aout != 0 and row["A_re"] * aout <= 0 for row in track)
        nan += sum(isnan(row[metric]) for row in track for metric in METRICS)
        inf += sum(isinf(row[metric]) for row in track for metric in METRICS)
        stages = [row for row in track if row["unit_type"] == "stage"]
        baseline = [row["A"] for row in stages if not row["I_N"] and not row["C_new"]]
        repeat = [row["A"] for row in stages if row["I_N"]]
        progress = [row["A"] for row in stages if row["C_new"] > 0]
        overlap += sum(row["I_N"] and row["C_new"] > 0 for row in stages)
        for name, actions in (("repeat", repeat), ("progress", progress)):
            if baseline and actions:
                gaps[category][name].append(fmean(actions) - fmean(baseline))
    return {"metrics": {category: {name: aggregate(vals) for name, vals in comps.items()}
                        for category, comps in gaps.items()},
            "conservation_max": max(conservation, default=0.), "sign_flips": sign_flips,
            "nan": nan, "inf": inf, "progress_repeat_overlap": overlap}


def indexed(path, covered):
    result = {}
    for row in rows(path):
        label = key(row)
        if label in covered:
            if label in result:
                raise ValueError("source has repeated unit keys")
            result[label] = row
    return result


def render(counts, sweep):
    def digits(value):
        return "—" if value is None else f"{value:.8g}"

    lines = [
        "# M3–M7 重复口径核对与参数扫描",
        "",
        f"- round4 可用题 {counts['questions']}｜轨迹 {counts['trajectories']}｜单元 {counts['units']}｜测试题读取 0。",
        f"- 旧严格重复 {counts['old_strict']}｜新严格 N3 {counts['new_strict']}｜差异 {counts['different']}｜"
        f"仅旧 {counts.get('m2_only', 0)}｜仅新 {counts.get('n3_only', 0)}。",
        f"- 并行单元 {counts.get('parallel', 0)}｜仅部分调用重复，"
        f"新 N3 {counts.get('n3_partial_parallel', 0)}、旧 M2 {counts.get('m2_partial_parallel', 0)}。",
        f"- 同时严格重复且有进展的工具 Stage {sweep[0]['progress_repeat_overlap']}。",
        "",
        "| 原因 | 仅旧 | 仅新 | 合计 |",
        "|---|---:|---:|---:|",
    ]
    for reason, name in REASONS.items():
        old = counts["by_reason"].get(reason, {}).get("m2_only", 0)
        new = counts["by_reason"].get(reason, {}).get("n3_only", 0)
        lines.append(f"| {name} | {old} | {new} | {old + new} |")
    lines += ["",
              "| λ | κ | 第一路守恒最大误差 | 第一路符号翻转 | NaN | Inf |",
              "|---:|---:|---:|---:|---:|---:|"]
    for s in sweep:
        lines.append(f"| {s['lambda']:g} | {s['kappa']:g} | {digits(s['conservation_max'])} | "
                     f"{s['sign_flips']} | {s['nan']} | {s['inf']} |")
    lines += ["", "差距均在轨迹内以工具 Stage 等权计算。基线为非重复且 C_new=0 的工具 Stage。"
              "两项差距分别纳入同时有基线和对应比较步的轨迹，组内再按轨迹等权汇总。",
              "", "| λ | κ | 组类 | 重复 n | 差距均值 | 中位数 | ≥0 | 有进展 n | 差距均值 | 中位数 | ≥0 |",
              "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in sweep:
        for code, group in GROUPS.items():
            parts = [f"{s['lambda']:g}", f"{s['kappa']:g}", group]
            for kind in ("repeat", "progress"):
                stat = s["metrics"][code][kind]
                n, ge = stat["n"], stat["nonnegative"]
                parts.extend((str(n), digits(stat["mean"]), digits(stat["median"]),
                              f"{100 * ge / n:.2f}% ({ge}/{n})" if n else "—"))
            lines.append("| " + " | ".join(parts) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = ArgumentParser(description=__doc__)
    for arg in ("root", "offline", "config", "out"):
        parser.add_argument("--" + arg, required=True, type=Path)
    a = parser.parse_args()
    frozen = read(a.offline / "COUNTS.json")
    if frozen["test_read"] != 0:
        raise ValueError("source receipt did not exclude held-out questions")
    scored = list(rows(a.offline / "scored_signals.jsonl"))
    covered = {key(row) for row in scored}
    questions = {row["query_id"] for row in scored}
    trajectories = {row["trajectory_id"] for row in scored}
    if (len(covered), len(scored), len(questions), len(trajectories)) != (3850, 3850, 44, 351):
        raise ValueError("unexpected original M3–M7 eligible population")
    states = indexed(a.root / "m2-v61-fix-192990/ledger_states.jsonl", covered)
    stages = indexed(a.root / "supplement-m1-192125/stages.jsonl", covered)
    counts, details = audit_repeats(stages, states, scored)
    if len(details) != frozen["strict_changed_vs_frozen_m2"] or counts["new_strict"] != frozen["strict_units"]:
        raise ValueError("difference count does not match frozen receipt")
    by_reason = defaultdict(Counter)
    for row in details:
        by_reason[row["reason"]]["m2_only" if row["m2"] else "n3_only"] += 1
    counts.update(different=len(details), questions=len(questions), trajectories=len(trajectories), by_reason=by_reason)

    config = Config.read(a.config)
    sweep = []
    for strength in LAMBDAS:
        for kappa in KAPPAS:
            values, receipts = assign(scored, replace(config, lambda_idle=strength, kappa=kappa))
            if (strength, kappa) == (.5, 0.) and any(
                new[field] != old[field] for new, old in zip(values, scored, strict=True) for field in METRICS
            ):
                raise ValueError("default does not reproduce accepted unit scores")
            result = evaluate(values, receipts)
            if result["sign_flips"] or result["nan"] or result["inf"] or not isfinite(result["conservation_max"]) \
                    or result["conservation_max"] >= 1e-9:
                raise ValueError("parameter sweep failed numerical acceptance")
            if kappa and any(result["metrics"][group] != sweep[-1]["metrics"][group]
                             for group in ("all_correct", "mixed")):
                raise ValueError("kappa changed a non-all-wrong group")
            sweep.append({"lambda": strength, "kappa": kappa, **result})

    a.out.mkdir(mode=0o700)
    emit(a.out / "repeat_differences.jsonl", details)
    sample = {reason: [{"trajectory_id": r["trajectory_id"], "unit_id": r["unit_id"]}
                       for r in [item for item in details if item["reason"] == reason][:3]] for reason in REASONS}
    write(a.out / "difference_samples.json", sample)
    write(a.out / "COUNTS.json", {"repeats": counts, "sweep": sweep})
    (a.out / "REPORT_sweep.md").write_text(render(counts, sweep), encoding="utf-8", newline="\n")
    paths = {"sweep.py": Path(__file__), **{name: a.out / name for name in
             ("repeat_differences.jsonl", "difference_samples.json", "REPORT_sweep.md", "COUNTS.json")}}
    receipt = {"units": len(scored), "differences": len(details), "configurations": len(sweep), "test_read": 0,
               "sha256": {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}}
    write(a.out / "RECEIPT.json", receipt)
    print(receipt)


if __name__ == "__main__":
    main()
