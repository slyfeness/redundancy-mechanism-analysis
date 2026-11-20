"""Replay v4.2 labels with document novelty from the recorded actor inputs."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

FLAGS = Path(__file__).resolve().parent.parent / "fpremise_probe"
if FLAGS.is_dir():
    sys.path.append(str(FLAGS))
from flags import name_key

CASES = {
    "408__rep2": range(3, 9), "408__rep6": range(4, 7), "408__rep8": range(3, 7),
    "790__rep1": range(5, 10), "515__rep4": range(8, 10), "391__rep2": range(11, 12),
}
TAGS = ("semantic_repeat", "stale_return", "strict_repeat")
OUTCOMES = {"correct": "答对", "incorrect": "答错", "no_submission": "未交卷"}


def rows(path):
    with path.open(encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def stage_docids(stage):
    """Count the ID once even if it appears in several fed returns of this Stage."""
    ids = set()
    for event in stage["tool_events"]:
        # Same visibility field and historical fallback as M1 event_fed.
        fed = event.get("fed_to_model", event.get("visible_to_actor"))
        if fed is not True or event["status"] != "ok":
            continue
        ids.update(str(hit["docid"]) for hit in event["returned_docids"])
        if event["opened_docid"] is not None:
            ids.add(str(event["opened_docid"]))
    return ids


def alias_pairs(records):
    return {frozenset(name_key(name) for name in record["names"].values())
            for record in records if record["result"] == "yes"}


def apply(stages, documents, aliases):
    earlier_docs, last_stage, result = set(), {}, []
    for row, docids in zip(stages, documents, strict=True):
        sid, items = row["stage_id"], row["items"]
        if sid != len(result) + 1:
            raise ValueError("non-contiguous frozen Stage IDs")
        names = {name_key(item["main_name"]) for item in items or []
                 if item["main_name"] != "none"
                 and item["status"] not in {"non_proper_name", "name_type_unresolved"}}
        fresh, seen = docids - earlier_docs, docids & earlier_docs
        labels = dict(row["labels"])
        eligible = bool(seen) and not fresh and not row["C_new"] and not labels.get("strict_repeat")
        distances = []
        if eligible:
            for name in sorted(names):
                previous = [step for known, step in last_stage.items()
                            if name == known or frozenset((name, known)) in aliases]
                if previous:
                    distances.append(sid - max(previous))
        labels["semantic_repeat"] = bool(distances)
        labels["stale_return"] = eligible and bool(items) and all(item["main_name"] == "none" for item in items)
        result.append({**row, "labels": labels, "new_docids": len(fresh), "seen_docids": len(seen),
                       "semantic_repeat_distances": distances})
        earlier_docs.update(docids)
        last_stage.update(dict.fromkeys(names, sid))
    return result


def track_index(records):
    index = defaultdict(list)
    for row in records:
        index[row["trajectory_id"]].append(row)
    return index


def load_documents(source, expected):
    index = {}
    for row in rows(source):
        key = row["trajectory_id"], row["unit_id"]
        if key[0] not in expected:
            continue
        if key in index:
            raise ValueError("duplicate M1 Stage")
        index[key] = stage_docids(row)
    keys = {(tid, stage["stage_id"]) for tid, stages in expected.items() for stage in stages}
    if index.keys() != keys:
        raise ValueError("frozen Stage coverage differs from M1")
    return index


def report(before, after):
    transition, totals, groups = Counter(), Counter(), defaultdict(Counter)
    tracks = track_index(after)
    for old, row in zip(before, after, strict=True):
        transition[old["labels"].get("semantic_repeat", False), row["labels"]["semantic_repeat"]] += 1
        totals.update(k for k, active in row["labels"].items() if active)
    for track in tracks.values():
        outcome = track[0]["outcome"]
        groups[outcome].update(n=1)
        groups[outcome].update(tag for row in track for tag in TAGS if row["labels"].get(tag))

    lines = [
        "# 搜索词账本判定 v4.3",
        f"- [已验证] 轨迹 {len(tracks)}｜Stage {len(after)}｜新增 Judge 调用 0",
        f"- [已验证] semantic_repeat {totals['semantic_repeat']}｜stale_return {totals['stale_return']}"
        f"｜strict_repeat {totals['strict_repeat']}｜F_new {totals['F_new']}｜F_corrected {totals['F_corrected']}",
        f"- [已验证] v4.2 semantic_repeat {transition[True, True] + transition[True, False]}"
        f"｜保留 {transition[True, True]}｜新增 {transition[False, True]}｜取消 {transition[True, False]}",
        "| 结果 | 轨迹 | 平均 semantic_repeat | 平均 stale_return | 平均 strict_repeat |",
        "|---|---:|---:|---:|---:|",
    ]
    for outcome, title in OUTCOMES.items():
        counts = groups[outcome]
        averages = " | ".join(f"{counts[tag] / counts['n']:.3f}" for tag in TAGS)
        lines.append(f"| {title} | {counts['n']} | {averages} |")
    lines.extend(["", "各步格式为 步号 标签 / new_docids。"])
    for tid, steps in CASES.items():
        indexed = {row["stage_id"]: row for row in tracks[tid]}
        values = []
        for step in steps:
            row = indexed[step]
            tags = "+".join(k for k, value in row["labels"].items() if value) or "无标签"
            values.append(f"{step} {tags}/{row['new_docids']}")
        lines.append(f"- [已验证] {tid}｜" + "｜".join(values))
    return "\n".join(lines) + "\n"


def main():
    parser = ArgumentParser(description=__doc__)
    for key in ("frozen", "m1_stages", "out"):
        parser.add_argument(key, type=Path)
    args = parser.parse_args()
    before = list(rows(args.frozen / "stages.jsonl"))
    expected = track_index(before)
    if len(before) != 430 or len(expected) != 40:
        raise ValueError("unexpected frozen sample size")
    index = load_documents(args.m1_stages, expected)
    aliases = alias_pairs(rows(args.frozen / "alias_checks.jsonl"))
    after = [row for tid, track in expected.items()
             for row in apply(track, (index[tid, old["stage_id"]] for old in track), aliases)]
    if [(r["trajectory_id"], r["stage_id"]) for r in before] != [(r["trajectory_id"], r["stage_id"]) for r in after]:
        raise ValueError("frozen Stage order changed")
    summary = report(before, after)
    args.out.mkdir(mode=0o700)
    with (args.out / "stages.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for row in after:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.out / "REPORT.md").write_text(summary, encoding="utf-8", newline="\n")
    print(json.dumps({"judge_calls": 0, "stage_rows": len(after),
                      "stages_sha256": sha256((args.out / "stages.jsonl").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
