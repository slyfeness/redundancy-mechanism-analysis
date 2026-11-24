"""Classify v8.1 mechanics and keep belief separate from evidence points."""
from chain_reader_v8 import validate_reader as validate_v8
from chain_extractor_v7 import candidate_equivalent


TIERS = {
    "严格重复": "冗余",
    "已够还查": "冗余",
    "重复核实": "冗余",
    "查没问的": "冗余",
    "同一缺口重试": "无进展",
    "无收获的探索": "无进展",
    "有进展": "有进展",
}


def validate_reader(reply, step, goal_counts):
    if not isinstance(reply, dict) or not isinstance(reply.get("subgoals"), list):
        return False
    if "established" not in reply:
        return False
    rows = []
    for goal in reply["subgoals"]:
        if not isinstance(goal, dict):
            return False
        rows.append({**goal, "result": "没结果" if goal.get("result") == "只是猜测" else goal.get("result")})
    return validate_v8({**reply, "answerable": reply["established"], "answer_reason": reply.get("established_reason"),
                        "subgoals": rows}, step, goal_counts)


def classify(stage, goals, evidence):
    step = stage["stage"]
    if stage["repeat_of"]:
        return "严格重复"
    if evidence is not None and step > evidence:
        return "已够还查"
    progress = stage["candidate_changed"] or any(
        g["answered_before"] is None and g["result"] in ("找到", "否定") for g in goals or ())
    if stage["new_docs"] > 0 and progress:
        return "有进展"
    if goals is None:
        return None
    if goals and all(g["answered_before"] is not None or g["needed"] == "不需要" or g["same_as"] is not None
                     for g in goals):
        if any(g["answered_before"] is not None for g in goals):
            return "重复核实"
        if any(g["needed"] == "不需要" for g in goals):
            return "查没问的"
        return "同一缺口重试"
    return "无收获的探索"


def belief_point(states, verdicts):
    timeline = []
    for row in states:
        candidate = row["candidate"]
        if candidate is None:
            correct = None
        else:
            correct = verdicts[candidate]
        timeline.append({**row, "correct": correct})
    idx = next((i for i, row in enumerate(timeline) if row["correct"]), None)
    first = timeline[idx] if idx is not None else None
    return {"states": timeline, "t_belief": None if first is None else first["stage"],
            "candidate": None if first is None else first["candidate"],
            "kept": None if first is None else all(row["correct"] is True and (
                candidate_equivalent(row["candidate"], first["candidate"]) or row["candidate"] == first["candidate"])
                for row in timeline[idx:])}


def probe_points(belief, evidence, last):
    if belief is None:
        return {last: ["末步对照"]}
    points = {}
    slots = [(belief - 1, "信念前一步"), (belief, "信念点"), (evidence, "证据点"), (last, "末步")]
    for step, label in slots:
        if step is not None and 0 <= step <= last:
            points.setdefault(step, []).append(label)
    return points


def result_class(value):
    return "没结果" if value in ("没结果", "只是猜测") else value


def derive(chain, replies, grades, belief, *, reference=False):
    results = {r["stage"]: r["result"] for r in replies}
    evidence = next((s["stage"] for s in chain["stages"] if grades.get(s["stage"]) is True), None)
    belief_at = belief["t_belief"]
    last = len(chain["stages"])
    stages = []
    conflicts = []
    for source in chain["stages"]:
        t = source["stage"]
        response = results[t]
        goals = None if response is None else sorted(response["subgoals"], key=lambda row: row["index"])
        category = classify(source, goals, evidence)
        flags = []
        if not source["new_docs"]:
            flags.append("零新文档")
        if source["reinstated"]:
            flags.append("改正")
        if source["group"] == "C" and belief_at is not None and t > belief_at and (evidence is None or t <= evidence):
            flags.append("信念后核实")
        if not reference and response and response["established"] and grades.get(t) is False:
            flags.append("认定错误答案")
        for prior in goals or []:
            idx = prior["index"]
            declared = source["subgoals"][idx - 1]
            if prior["answered_before"] is not None and any(
                candidate_equivalent(declared["object"], x) for x in source["excluded_before"]):
                if "追已排除" not in flags:
                    flags.append("追已排除")
            link = prior["same_as"]
            if link is not None and results.get(link["step"]):
                previous = next((v for v in results[link["step"]]["subgoals"] if v["index"] == link["subgoal"]), None)
                if previous and previous["result"] in ("找到", "否定") and (
                    prior["answered_before"] is None or prior["answered_before"] > link["step"]):
                    conflicts.append({"stage":t,"index":idx,"same_as":link})
        stages.append({"stage": t, "category": category, "tier": TIERS.get(category), "flags": flags,
                       "subgoals": goals, "established": None if response is None else response.get("established"),
                       "correct": grades.get(t)})
    trajectory_flag = None
    if belief_at is not None and chain["group"] in ("W", "N"):
        trajectory_flag = {"name": "有证据不交卷" if chain["group"] == "N" else "线索被丢",
                           "t_belief": belief_at, "t_evidence": evidence, "kept": belief["kept"],
                           "steps_after_belief": last - belief_at,
                           "steps_after_evidence": None if evidence is None else last - evidence}
    return {"stages": stages, "t_belief": belief_at, "t_evidence": evidence,
            "belief_kept": belief["kept"], "trajectory_flag": trajectory_flag, "consistency_conflicts": conflicts}
