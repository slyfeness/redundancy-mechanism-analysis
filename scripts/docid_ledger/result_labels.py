"""Label each frozen search by observed result and optional local intent comparison."""

from collections import Counter
from itertools import groupby
from re import findall
from statistics import median

from ledger import normalized

MAIN = ("no_return", "repeat_query", "no_new_information", "effective", "repeat_evidence", "ineffective")
FINAL = (*MAIN, "definite_redundancy", "soft_redundancy", "rephrased_success")
FLAGS = ("new_gold", "same_round_repeat", "result_overlap", "query_similarity")
WEAK = {"no_new_information", "repeat_evidence"}


def jaccard(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def annotate(events, evidence, gold):
    """Commit visible documents and search queries only after each complete round."""
    previous, output, seen, prior_queries = [], [], set(), set()
    events = sorted(events, key=lambda row: row["round"])
    for _, batch in groupby(events, key=lambda row: row["round"]):
        group = list(batch)
        queries = [normalized(row["query"]) for row in group]
        group_count = Counter(queries)
        pending = []
        for row, query in zip(group, queries):
            docs = set(row["docs"]) if row["visible"] else set()
            words = set(findall(r"\w+", query))
            new = docs - seen
            if not row["visible"]:
                main = "no_return"
            elif query in prior_queries:
                main = "repeat_query"
            elif not new:
                main = "no_new_information"
            elif new & evidence:
                main = "effective"
            elif docs & evidence:
                main = "repeat_evidence"
            else:
                main = "ineffective"
            ranked = [(jaccard(docs, past_docs), jaccard(words, past_words), eid)
                      for past_docs, past_words, eid in previous]
            # Stable sorting keeps earlier events first when both scores tie.
            ranked.sort(key=lambda item: (-item[0], -item[1]))
            overlap = ranked[0] if ranked and ranked[0][0] >= .6 else None
            flags = {"new_gold": bool(new & gold), "same_round_repeat": group_count[query] > 1,
                     "result_overlap": overlap is not None,
                     "query_similarity": any(score >= .8 for _, score, _ in ranked)}
            eligible = main in WEAK or (main == "effective" and
                                       (flags["result_overlap"] or flags["query_similarity"]))
            output.append({
                **row, "main": main, "flags": flags, "new_docs": sorted(new),
                "overlap_event_id": overlap[2] if overlap else None,
                "overlap_jaccard": overlap[0] if overlap else None,
                "eligible": eligible, "candidates": [eid for _, _, eid in ranked[:3]] if eligible else [],
                "after_first_gold": bool(seen & gold),
                "after_all_evidence": bool(evidence) and evidence <= seen,
            })
            pending.append((docs, words, row["id"]))
        previous.extend(pending)
        seen.update(doc for docs, _, _ in pending for doc in docs)
        prior_queries.update(queries)
    return output


def combine(row, answers):
    main = row["main"]
    if main == "repeat_query":
        return "definite_redundancy"
    if main in WEAK:
        same = row["flags"]["result_overlap"] if answers is None else bool(answers[row["id"]])
        return "definite_redundancy" if same else "soft_redundancy"
    if main == "effective" and answers is not None and answers.get(row["id"]):
        return "rephrased_success"
    return main


def distribution(values):
    return ({"min": min(values), "median": median(values), "max": max(values)}
            if values else {"min": None, "median": None, "max": None})


def summarize(counts, labels, total):
    return {key: {"count": counts[key], "share": counts[key] / total if total else None}
            for key in labels}


def outcome_groups(tracks):
    known = {track["outcome"] for track in tracks}
    if known <= {"correct", "wrong", "no_final"}:
        return ("correct", "wrong", "no_final"), False
    if known <= {"correct", "wrong", "no_final", "final_unscored"}:
        return ("has_final", "no_final"), True
    raise ValueError("unexpected trajectory outcome")


def report(tracks, answers):
    sources = {"main": MAIN, "flags": FLAGS, "final": FINAL}
    counters = {name: Counter() for name in sources}
    involved = {name: Counter() for name in sources}
    sections = {name: Counter() for name in ("after_first_gold", "after_all_evidence", "early", "middle", "late")}
    outcome_names, fallback = outcome_groups(tracks)
    outcome = {key: [] for key in outcome_names}
    rows_by_id, sequences, repeat_with_new = {}, [], []
    totals = Counter()
    pair_table = Counter()
    codebook = {key: {label: i + 1 for i, label in enumerate(labels)} for key, labels in sources.items()}
    for track in tracks:
        events = track["events"]
        local = {name: Counter() for name in sources}
        sequence = []
        n = len(events)
        returned = sum(row["visible"] for row in events)
        for i, row in enumerate(events):
            final = combine(row, answers)
            local["main"][row["main"]] += 1
            local["final"][final] += 1
            active_flags = [key for key in FLAGS if row["flags"][key]]
            local["flags"].update(active_flags)
            for key in ("after_first_gold", "after_all_evidence"):
                if row[key]:
                    sections[key][final] += 1
            third = ("early", "middle", "late")[min(i * 3 // n, 2)]
            sections[third][final] += 1
            if row["main"] == "repeat_query" and row["new_docs"]:
                repeat_with_new.append(row["id"])
            if answers is not None and row["id"] in answers:
                pair_table[bool(row["flags"]["result_overlap"]), bool(answers[row["id"]])] += 1
            sequence.append({
                "round": row["round"], "event_id": row["id"],
                "main": codebook["main"][row["main"]],
                "flags": [codebook["flags"][key] for key in active_flags],
                "overlap_event_id": row["overlap_event_id"], "overlap_jaccard": row["overlap_jaccard"],
                "final": codebook["final"][final],
            })
        totals.update(searches=n, returned=returned)
        strict = local["final"]["definite_redundancy"]
        broad = strict + local["final"]["soft_redundancy"]
        counts = {key: {label: local[key][label] for label in labels} for key, labels in sources.items()}
        item = {"searches": n, "returned": returned, **counts,
                "strict_ratio": strict / returned if returned else None,
                "broad_ratio": broad / returned if returned else None}
        tid, status = track["id"], track["outcome"]
        rows_by_id[tid] = item
        group = "has_final" if fallback and status != "no_final" else status
        outcome[group].append(item)
        sequences.append({"trajectory_id": tid, "question_id": track["qid"], "events": sequence})
        for key in sources:
            counters[key].update(local[key])
            involved[key].update(label for label, count in local[key].items() if count)
    ratio_keys = ("strict_ratio", "broad_ratio")

    def ratios(items):
        return {key: distribution([row[key] for row in items if row[key] is not None]) for key in ratio_keys}

    def group_summary(items):
        searches = sum(row["searches"] for row in items)
        counts = Counter()
        for row in items:
            counts.update(row["final"])
        return {"trajectories": len(items), "searches": searches, "final": summarize(counts, FINAL, searches),
                "ratios": ratios(items)}

    result = {
        "codebook": codebook, "approximate": int(answers is None),
        "overall": {**totals, "trajectories": len(tracks), **{
            name: {key: {**summary, "trajectories": involved[name][key]}
                   for key, summary in summarize(counters[name], labels, totals["searches"]).items()}
            for name, labels in sources.items()
        }},
        "per_trajectory": rows_by_id,
        "trajectory_distributions": {
            **{name: {key: distribution([row[name][key] for row in rows_by_id.values()]) for key in labels}
               for name, labels in sources.items()},
            **ratios(rows_by_id.values()),
        },
        "timing": {key: {"searches": sum(counts.values()), "final": summarize(counts, FINAL, sum(counts.values()))}
                   for key, counts in sections.items()},
        "outcomes": {key: group_summary(items) for key, items in outcome.items()},
        "outcome_grouping_fallback": int(fallback),
        "consistency": None if answers is None else {
            f"overlap_{int(overlap)}_same_{int(same)}": pair_table[overlap, same]
            for overlap in (False, True) for same in (False, True)
        },
        "exact_repeat_with_new_docs": {"count": len(repeat_with_new), "example_event_ids": repeat_with_new[:3]},
    }
    return result, sequences
