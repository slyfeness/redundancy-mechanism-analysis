"""Undo the v4.5 eligibility gate using committed private artifacts only."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent.parent
for folder in ("ledger_judge_v44", "ledger_judge_v45"):
    sys.path.append(str(BASE / folder))

from probe_v45 import ACCEPTED, OUTCOMES, REJECTED
from rules_v44 import AliasEvidence, normalized, settle

FILES = ("stages", "stage_signals", "events", "audit_sample")
EVENT_TAGS = ("wrong_candidate", "F_new", "F_corrected")
GATE = {"eligible": "wrong_candidate", "eligibility_no": "aux", "eligibility_invalid": "eligibility_unresolved"}


def key(row):
    return row["trajectory_id"], row["stage_id"]


def committed(repo, path):
    blob = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{path}"])
    return [json.loads(line) for line in blob.splitlines()]


def update_item(item):
    reason = item["decision_reason"]
    if reason not in GATE:
        if "eligibility_check" in item:
            raise ValueError("unexpected eligibility receipt")
        return item
    if (item["attribution"] != GATE[reason] or not item.get("eligibility_check")
            or item["backfilled"] or not item["var"]):
        raise ValueError("cannot restore ambiguous pre-gate attribution")
    return {k: value for k, value in item.items() if k != "eligibility_check"} | {
        "attribution": "wrong_candidate", "decision_reason": "wrong_candidate"}


def sample_row(sample, row):
    index = sample["query_index"] - 1
    if index < 0 or (sample["query"], sample["judge_raw"]) != (row["searches"][index], row["judge_raw"]):
        raise ValueError("baseline sample is detached from its original query")
    return {**row["items"][index], **{k: sample[k] for k in
            ("trajectory_id", "stage_id", "query_index", "query", "judge_raw")}, "labels": row["labels"]}


def replay(previous, original_signals, original_sample, references):
    tracks = defaultdict(list)
    parts = {}
    for old in previous:
        updated = {**old, "items": [update_item(item) for item in old["items"]]}
        tracks[old["trajectory_id"]].append(updated)
        parts[key(old)] = updated
    if len(parts) != len(previous):
        raise ValueError("duplicate v4.5 Stage")
    events = []
    for tid, units in tracks.items():
        # The fold owns the event lifecycle. The v4.5 repeat and protection fields
        # are retained from the input because names and retrieval do not change.
        folded, track_events = settle(units, AliasEvidence([]), references[tid.split("__", 1)[0]])
        events.extend(track_events)
        for item in folded:
            updated = parts[key(item)]
            updated["labels"] = {**updated["labels"], **{field: item["labels"][field] for field in EVENT_TAGS}}
    stages = [parts[key(old)] for old in previous]
    signals = []
    for row, old in zip(stages, original_signals, strict=True):
        if key(row) != key(old) or row["C_new"] != old["C_new"]:
            raise ValueError("v4.5 Stage and signal mismatch")
        signals.append({**old, **{field: int(row["labels"][field]) for field in ("F_new", "F_corrected")}})
    sample = [sample_row(row, parts[key(row)]) for row in original_sample]
    return stages, signals, events, sample


def event_key(row):
    return row["trajectory_id"], row["var"], normalized(row["wrong_name"])


def event_label(row):
    return f"{row['trajectory_id']}/{row['stage_id']} ({row['var']})"


def report(previous, old_events, stages, events):
    before, after = ({event_key(row): row for row in event_list if row["event"] == "F_new"}
                     for event_list in (old_events, events))
    tracked = {key(row): event_key(row) for row in before.values()}
    if set(tracked) != set(ACCEPTED) | set(REJECTED):
        raise ValueError("v4.4 human review inventory changed")
    stage_idx = {key(row): row for row in stages}
    tracked_vars = Counter((row["trajectory_id"], row["event"]) for row in events)
    track_outcomes = {row["trajectory_id"]: row["outcome"] for row in stages}
    group_rows = defaultdict(Counter)
    for tid, outcome in track_outcomes.items():
        group_rows[outcome].update(n=1, F_new=tracked_vars[tid, "F_new"], F_corrected=tracked_vars[tid, "F_corrected"])
    for row in stages:
        group_rows[row["outcome"]][row["idle_type"]] += 1

    idle = Counter(row["idle_type"] for row in stages)
    statuses = Counter(row["event"] for row in events)
    restored = sum(item["decision_reason"] != other["decision_reason"]
                   and item["attribution"] != other["attribution"]
                   for old, new in zip(previous, stages, strict=True)
                   for item, other in zip(old["items"], new["items"], strict=True))
    lines = [
        "# 搜索词账本判定 v4.6",
        "- 状态 · 待人工验收。",
        f"- 轨迹 {len(track_outcomes)}｜Stage {len(stages)}｜Judge 调用 0｜恢复资格复核前归属 {restored} 条",
        f"- F_new {statuses['F_new']}｜F_corrected {statuses['F_corrected']}｜idle_type strict {idle['strict']}｜semantic {idle['semantic']}｜none {idle['none']}",
        "| 结果 | 轨迹 | 平均 strict | 平均 semantic | 平均 F_new | 平均未纠正 F_new |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for outcome, title in OUTCOMES.items():
        group = group_rows[outcome]
        means = (group["strict"], group["semantic"], group["F_new"], group["F_new"] - group["F_corrected"])
        lines.append(f"| {title} | {group['n']} | " + " | ".join(f"{value / group['n']:.3f}" for value in means) + " |")

    lines.append("")
    lines.append("与 v4.4 比较")
    for label, changes, records in (
        ("保留", before.keys() & after.keys(), after),
        ("取消", before.keys() - after.keys(), before),
        ("新增", after.keys() - before.keys(), after),
    ):
        locations = [event_label(records[item]) for item in sorted(changes)]
        lines.append(f"- {label} {len(locations)}" + ("｜" + "｜".join(locations) if locations else ""))

    for title, locations in (("8 个已人工确认事件", ACCEPTED), ("6 个已人工确认误判", REJECTED)):
        lines.append(f"- {title}（候选归属 / Stage 标签）")
        for location in locations:
            identity = tracked[location]
            row = stage_idx[location]
            attrs = "+".join(item["attribution"] for item in row["items"]
                             if normalized(item["v44_main_name"] or "") == identity[2]) or "none"
            active = "+".join(tag for tag, enabled in row["labels"].items() if enabled) or "无标签"
            event = before[identity]
            lines.append(f"  - {event_label(event)} {attrs} / {active}")
    return "\n".join(lines) + "\n"


def build(repo):
    previous, signals, sample = (committed(repo, f"ledger_judge_v45/{name}.jsonl")
                                 for name in ("stages", "stage_signals", "audit_sample"))
    original_events = committed(repo, "ledger_judge_v44/events.jsonl")
    refs = {row["question_id"]: {ent["var"]: (ent["canonical_name"], ent["final_type"])
                                  for ent in row["entities"]}
            for row in committed(repo, "ledger_judge_v42/entity_types_v41.jsonl")}
    for event in original_events:
        qid = event["trajectory_id"].split("__", 1)[0]
        if refs[qid][event["var"]][0] != event["correct_name"]:
            raise ValueError("historical reference name differs from v4.4")
    if len(previous) != 430 or len(sample) != 70 or len({row["trajectory_id"] for row in previous}) != 40:
        raise ValueError("unexpected v4.5 sample scope")
    rebuilt = replay(previous, signals, sample, refs)
    return rebuilt, report(previous, original_events, rebuilt[0], rebuilt[2])


def main():
    parser = ArgumentParser(description=__doc__)
    for arg in ("private_repo", "output", "report"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    artifacts, summary = build(args.private_repo)
    args.output.mkdir()
    for name, records in zip(FILES, artifacts, strict=True):
        with (args.output / f"{name}.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    args.report.write_text(summary, encoding="utf-8", newline="\n")
    print(json.dumps({"stages": len(artifacts[0]), "events": len(artifacts[2]), "sample": len(artifacts[3]), "judge_calls": 0}))


if __name__ == "__main__":
    main()
