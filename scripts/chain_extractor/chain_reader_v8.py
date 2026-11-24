"""Closed-question reader for v7 chain prefixes and validated A1 subgoals."""
import re

EVENT_ORDER=("严格重复","已够还查","有进展","重复核实","查没问的","同一缺口重试","无收获的探索")


def _int(value):
    return type(value) is int


def _text(value):
    return isinstance(value,str) and bool(value.strip())


def _ids(values, allowed):
    return isinstance(values,list) and all(isinstance(key,str) and key in allowed for key in values)


def validate_subgoals(value, queries, allowed):
    if not isinstance(value,dict) or not isinstance(value.get("subgoals"),list):
        return False
    if value.get("plan_match") not in ("一致","不一致","思考没说") or not _ids(value.get("plan_ids"),allowed):
        return False
    if not isinstance(value.get("plan_note"),str):
        return False
    seen=set()
    for goal in value["subgoals"]:
        if not isinstance(goal,dict):
            return False
        index=goal.get("query_index")
        if (not _int(index) or not 1<=index<=queries or not _text(goal.get("object")) or
                not _text(goal.get("attribute")) or not _ids(goal.get("ids"),allowed)):
            return False
        seen.add(index)
    return seen==set(range(1,queries+1))


def validate_reader(value, step, goal_counts):
    if not isinstance(value,dict) or not isinstance(value.get("subgoals"),list):
        return False
    expected=set(range(1,goal_counts[step]+1))
    seen=set()
    for goal in value["subgoals"]:
        if not isinstance(goal,dict):
            return False
        index=goal.get("index")
        if not _int(index) or index not in expected or index in seen:
            return False
        seen.add(index)
        same=goal.get("same_as")
        if same is not None:
            if not isinstance(same,dict):
                return False
            s,g=same.get("step"),same.get("subgoal")
            if not _int(s) or not _int(g) or not 0<s<step or not 1<=g<=goal_counts.get(s,0):
                return False
        prior=goal.get("answered_before")
        if prior is not None and (not _int(prior) or not 0<=prior<step):
            return False
        if not {"index","same_as","needed","answered_before","result","reason"} <= goal.keys():
            return False
        if goal.get("needed") not in ("需要","不需要") or goal.get("result") not in ("找到","否定","没结果"):
            return False
        if not _text(goal.get("reason")):
            return False
    if seen!=expected or type(value.get("answerable")) is not bool or not _text(value.get("answer_reason")):
        return False
    basis=value.get("basis_steps")
    if not isinstance(basis,list) or any(not _int(k) or not 0<=k<=step for k in basis):
        return False
    return (bool(basis) and _text(value.get("answer"))) if value["answerable"] else (
        "answer" in value and value["answer"] is None)


def useful_labels(*, strict, after, progress, goals):
    if strict:
        return EVENT_ORDER[0]
    if after:
        return EVENT_ORDER[1]
    if progress or goals is not None and any(x["answered_before"] is None and x["result"] in ("找到","否定") for x in goals):
        return EVENT_ORDER[2]
    if goals is None:
        return None
    if any(x["answered_before"] is not None for x in goals):
        return EVENT_ORDER[3]
    if any(x["needed"]=="不需要" for x in goals):
        return EVENT_ORDER[4]
    if any(x["same_as"] is not None and x["answered_before"] is None for x in goals):
        return EVENT_ORDER[5]
    return EVENT_ORDER[6]


def one_line(value):
    return re.sub(r"\s+"," ",value).strip() if isinstance(value,str) else ""
