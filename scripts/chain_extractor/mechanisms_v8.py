"""Deterministically derive reader mechanisms without condition-state inputs."""
from collections import Counter
from chain_extractor_v7 import candidate_equivalent
from chain_reader_v8 import useful_labels


COMPARE_FIELDS=("same_as","needed","answered_before","result")
MECHANISMS=("重复核实","追已排除","查没问的","同一缺口重试","有进展","已够还查","改正","严格重复","零新文档")


def derive_run(chain, replies, grades):
    """Grades map step numbers to the human-reviewed pass/fail outcome."""
    by_step={r["stage"]:r["result"] for r in replies}
    sufficient=next((s["stage"] for s in chain["stages"] if grades.get(s["stage"]) is True),None)
    steps=[]
    violations=[]
    for source in chain["stages"]:
        time=source["stage"]
        reply=by_step[time]
        subgoals=None
        compared=None if reply is None else reply["subgoals"]
        if source["subgoals"] is not None and compared is not None:
            ordered=sorted(compared,key=lambda x:x["index"])
            subgoals=[]
            for declared, judgement in zip(source["subgoals"],ordered,strict=True):
                flags=[]
                checked=judgement["answered_before"]
                same=judgement["same_as"]
                if checked is not None:
                    flags.append("重复核实")
                    if any(candidate_equivalent(declared["object"],x) for x in source["excluded_before"]):
                        flags.append("追已排除")
                if judgement["needed"]=="不需要":
                    flags.append("查没问的")
                if same is not None and checked is None:
                    flags.append("同一缺口重试")
                if same is not None:
                    prior=by_step[same["step"]]
                    if prior is not None:
                        answer=next((g for g in prior["subgoals"] if g["index"]==same["subgoal"]),None)
                        if answer is not None and answer["result"] in ("找到","否定") and (checked is None or checked>same["step"]):
                            violations.append({"step":time,"index":judgement["index"],"same_as":same,
                                               "answered_before":checked,"prior_result":answer["result"]})
                subgoals.append({**judgement,"flags":flags})
        after=sufficient is not None and time>sufficient
        makes_progress=bool(source["candidate_changed"] or subgoals and any(r["answered_before"] is None and
                            r["result"] in ("找到","否定") for r in subgoals))
        strict=bool(source["repeat_of"])
        flags={flag for judgement in subgoals or [] for flag in judgement["flags"]}
        flags.update(name for name,active in (("有进展",makes_progress),("已够还查",after),("改正",source["reinstated"]),
                                               ("严格重复",strict),("零新文档",source["new_docs"]==0)) if active)
        steps.append({"stage":time,"category":useful_labels(strict=strict,after=after,progress=makes_progress,goals=subgoals),
                      "flags":sorted(flags),"subgoals":subgoals,"answerable":None if reply is None else reply["answerable"],
                      "grade":grades.get(time)})
    return {"steps":steps,"t_star":sufficient,
            "evidence_no_submit":({"t_star":sufficient,"following_steps":len(steps)-sufficient}
                                  if chain["group"]=="N" and sufficient is not None else None),
            "lost_evidence":chain["group"]=="W" and sufficient is not None,"consistency_violations":violations}


def compare_steps(first, second, compare_subgoals):
    result={k:[0,0] for k in ("category",*COMPARE_FIELDS)}
    disagreements={k:[] for k in result}
    for left,right in zip(first["steps"],second["steps"],strict=True):
        assert left["stage"]==right["stage"]
        t=left["stage"]
        ca,cb=left["category"],right["category"]
        result["category"][1]+=1
        if ca is not None and ca==cb:
            result["category"][0]+=1
        else:
            disagreements["category"].append((t,None))
        if not compare_subgoals:
            continue
        a={g["index"]:g for g in (left["subgoals"] or [])}
        b={g["index"]:g for g in (right["subgoals"] or [])}
        for i in sorted(a.keys()|b.keys()):
            for field in COMPARE_FIELDS:
                result[field][1]+=1
                if i in a and i in b and a[i][field]==b[i][field]:
                    result[field][0]+=1
                else:
                    disagreements[field].append((t,i))
    return result,disagreements


def step_sets(case, flag):
    return {row["stage"] for row in case["steps"] if flag in row["flags"]}
