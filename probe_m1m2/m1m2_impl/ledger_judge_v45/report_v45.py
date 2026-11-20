"""Count-only v4.5 report with event identity and cancellation reasons."""

from collections import Counter, defaultdict

from probe_v45 import ACCEPTED, OUTCOMES, REJECTED, track_index
from rules_v45 import normalized

REASONS = {
    "capitalization": "引号内小写", "backfilled": "补抽退出错误计分", "eligibility_no": "资格复核否",
    "eligibility_invalid": "资格未决", "containment": "包含匹配转 correct", "correct": "匹配转 correct",
    "unattributed": "归属不足", "lost_recurrence": "不足两步", "lost_premise": "对应错误候选已取消",
}


def event_key(row):
    return row["trajectory_id"], row["event"], row["var"], normalized(row["wrong_name"])


def render(before, old_events, stages, events, checks, calls):
    items = [item for row in stages for item in row["items"]]
    by_step = {(row["trajectory_id"], row["stage_id"]): row for row in stages}
    old_map, new_map = ({event_key(row): row for row in values} for values in (old_events, events))
    changes = Counter()
    removed = {}
    for key, row in old_map.items():
        tag = row["event"]
        if key in new_map:
            changes[tag, "preserved"] += 1
            continue
        changes[tag, "cancelled"] += 1
        related = [item for step in (row["first_stage"], row["confirmation_stage"])
                   for item in by_step[row["trajectory_id"], step]["items"]
                   if normalized(item["v44_main_name"] or "") == key[3]]
        if tag == "F_corrected":
            reason = "lost_premise"
        elif any(item["main_name"] == "none" for item in related):
            reason = "capitalization"
        else:
            reasons = {item["decision_reason"] for item in related}
            reason = next((candidate for candidate in REASONS if candidate in reasons), "lost_recurrence")
            if reason == "lost_recurrence" and any(item["backfilled"] for item in related):
                reason = "backfilled"
        removed[key] = reason
    for key in new_map.keys() - old_map.keys():
        changes[key[1], "new"] += 1

    lowered = sum(item["v44_main_name"] not in (None, "none")
                  and item["v44_main_name"] != item["main_name"]
                  and item["judge_main_name"] is not None for item in items)
    tags = Counter(item["decision_reason"] for item in items)
    new_contains = sum(item["containment_match"] and item["v44_attribution"] != "correct" for item in items)
    check_counts = Counter(row["result"] for row in checks)
    idle = Counter(row["idle_type"] for row in stages)
    before_labels = {(row["trajectory_id"], row["stage_id"]): row["labels"] for track in before.values() for row in track}
    protection_delta = sum(row["labels"]["protected_new_hypothesis"] != before_labels[key]["protected_new_hypothesis"]
                           for key, row in by_step.items())
    lines = [
        "# 搜索词账本判定 v4.5",
        "- 状态 · 待人工验收。v4.4 冻结已撤销。",
        f"- 轨迹 {len(before)}｜Stage {len(stages)}｜Judge {sum(calls.values())}/100｜资格 {calls.get('eligibility', 0)}｜类别 {calls.get('type', 0)}｜别名 {calls.get('alias', 0)}",
        f"- 去引号豁免后换名或作废 {lowered}｜补抽不计错误 {tags['backfilled']}｜包含匹配命中 {tags['containment']}｜其中转 correct {new_contains}｜保护标签变化 {protection_delta}",
        f"- 资格复核对数 {len(checks)}｜yes {check_counts['yes']}｜no {check_counts['no']}｜无效 {check_counts[None]}｜no 转 aux 搜索词 {tags['eligibility_no']}",
        "- v4.4 → v4.5 事件（保留/新增/取消） " + "｜".join(
            f"{tag} {changes[tag, 'preserved'] + changes[tag, 'cancelled']}→{changes[tag, 'preserved'] + changes[tag, 'new']}"
            f"（{changes[tag, 'preserved']}/{changes[tag, 'new']}/{changes[tag, 'cancelled']}）"
            for tag in ("F_new", "F_corrected")),
        "- 取消原因 " + ("｜".join(f"{REASONS[reason]} {total}" for reason, total in sorted(
            Counter(removed.values()).items())) or "0"),
        f"- idle_type strict {idle['strict']}｜semantic {idle['semantic']}｜none {idle['none']}",
        "| 结果 | 轨迹 | 平均 strict | 平均 semantic | 平均 F_new | 平均未纠正 F_new |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    per_track = Counter((e["trajectory_id"], e["event"]) for e in events)
    groups = defaultdict(Counter)
    for tid, track in track_index(stages).items():
        group = groups[track[0]["outcome"]]
        group.update(n=1, F_new=per_track[tid, "F_new"], F_corrected=per_track[tid, "F_corrected"])
        group.update(row["idle_type"] for row in track)
    for outcome, label in OUTCOMES.items():
        g = groups[outcome]
        values = [g["strict"], g["semantic"], g["F_new"], g["F_new"] - g["F_corrected"]]
        lines.append(f"| {label} | {g['n']} | " + " | ".join(f"{value / g['n']:.3f}" for value in values) + " |")

    def label(row):
        return "+".join(tag for tag, active in row["labels"].items() if active) or "无标签"

    cases = {(event["trajectory_id"], event["stage_id"]): event_key(event)
             for event in old_events if event["event"] == "F_new"}
    if set(cases) != set(REJECTED) | set(ACCEPTED):
        raise ValueError("human review event inventory differs from v4.4")
    lines.append("- 6 个复核误判（步号 当前候选归属 / 当前 Stage 标签）")
    for tid, step in REJECTED:
        row = by_step[tid, step]
        key = cases[tid, step]
        attribution = "+".join(item["attribution"] for item in row["items"]
                               if normalized(item["v44_main_name"] or "") == key[3]) or "none"
        status = "保留" if key in new_map else f"取消（{REASONS[removed[key]]}）"
        lines.append(f"  - {tid}/{step} {attribution} / {label(row)} / {status}")
    row = by_step["408__rep7", 6]
    lines.append("- 408__rep7/6 " + "+".join(item["attribution"] for item in row["items"]) + " / " + label(row))
    retained = []
    for tid, step in ACCEPTED:
        key = cases[tid, step]
        status = f"保留@{new_map[key]['stage_id']}" if key in new_map else f"取消（{REASONS[removed[key]]}）"
        retained.append(f"{tid}/{step} {status}")
    lines.append("- 8 个已人工确认事件 " + "｜".join(retained))
    return "\n".join(lines) + "\n"
