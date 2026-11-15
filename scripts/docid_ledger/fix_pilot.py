"""Compare two stricter DocID support schemes and replay only changed target inputs."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from check import file_sha, read_json, write_new
from snippet_pilot import LocalJudge, account, classify, object_schema, task_payload


VERDICT_SCHEMA = object_schema(reason={"type": "string"}, verdict={"type": "string", "enum": ["yes", "no"]})


def verdict_ids(reply, valid):
    if (not isinstance(reply, dict) or set(reply) != {"reason", "verdict"}
            or not isinstance(reply["reason"], str) or reply["verdict"] not in {"yes", "no"} or len(valid) != 1):
        raise ValueError("invalid verification receipt")
    return sorted(valid) if reply["verdict"] == "yes" else []


def compare_pairs(predicted, gold, calls):
    correct = len(predicted & gold)
    return {"calls": calls, "labeled_pairs": len(predicted), "correct_pairs": correct,
            "precision": correct / len(predicted) if predicted else None,
            "relative_recall": correct / len(gold) if gold else None, "gold_pairs": len(gold)}


def choose_scheme(schemes):
    defined = {name: row for name, row in schemes.items()
               if row["precision"] is not None and row["relative_recall"] is not None}
    if not defined:
        raise ValueError("no scheme with measurable precision and relative recall")
    best_precision = max(row["precision"] for row in defined.values())
    eligible = [name for name, row in defined.items() if best_precision - row["precision"] <= .03 + 1e-12]
    return max(eligible, key=lambda name: (defined[name]["relative_recall"], defined[name]["precision"],
                                          -defined[name].get("calls", 0)))


def gates(metrics, same_yes, same_n, semantic_yes, semantic_n):
    precision = metrics["precision"]
    recall = metrics["relative_recall"]
    same_rate = same_yes / same_n if same_n else None
    semantic_rate = semantic_yes / semantic_n if semantic_n else None
    support = precision is not None and recall is not None and precision >= .90 and recall >= .85
    same = same_rate is not None and same_rate >= .85
    semantic = semantic_rate is not None and semantic_rate >= .80
    return {"precision_threshold": .90, "recall_threshold": .85, "same_threshold": .85,
            "semantic_threshold": .80, "same_rate": same_rate, "semantic_rate": semantic_rate,
            "support_passed": int(support), "same_passed": int(same), "semantic_passed": int(semantic),
            "use_intersection": int(not semantic), "run_full": int(support and same)}


def plan_targets(old_events, current_events, old_targets):
    reused, changed, now_ineligible = {}, [], 0
    for event in current_events:
        eid = event["id"]
        before = set(old_events[eid]["confirmed"])
        after = set(event["confirmed"])
        if not after:
            now_ineligible += bool(before)
            continue
        if before == after:
            reused[eid] = old_targets[eid]
        else:
            changed.append(event)
    return reused, changed, now_ineligible


def prompt_files():
    root = Path(__file__).parent
    return {"supports": root / "p2_prompt.md", "verdict": root / "verify_prompt.md",
            "targets": root / "targets_prompt.md"}


def label(packet, old, config, out):
    started = perf_counter()
    paths = prompt_files()
    prompts = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    cfg = {**config, "prompt_sha256": {name: file_sha(path) for name, path in paths.items()
                                      if name in {"supports", "verdict"}}}
    cache = out / "model_cache"
    cache.mkdir(mode=0o700)
    judge = LocalJudge(cfg, cache, prompts)
    passages, tasks, original = packet["passages"], packet["tasks"], old["supports"]
    if len(passages) != 36 or original.keys() != passages.keys():
        raise ValueError("B1 requires the sealed 36-passage pilot")
    begin = perf_counter()

    def support_job(pid):
        passage = passages[pid]
        task = tasks[passage["query_id"]]
        payload = {**task_payload(task), "reference_answer": task["answer"],
                   "search_result_passage": passage["passage"]}
        return pid, judge.ask("supports", pid, task, payload)

    with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        p2 = dict(pool.map(support_job, sorted(passages)))
    p2_seconds = perf_counter() - begin
    begin = perf_counter()
    pair_ids = [(pid, cid) for pid, ids in sorted(original.items()) for cid in ids or ()]

    def verify_job(pair):
        pid, cid = pair
        passage = passages[pid]
        task = tasks[passage["query_id"]]
        constraint = next(row for row in task["constraints"] if row["constraint_id"] == cid)
        payload = {"question": task["question"], "reference_answer": task["answer"],
                   "constraint": {"constraint_id": cid, "text": constraint["text"]},
                   "search_result_passage": passage["passage"]}
        value = judge.ask("verdict", f"{pid}:{cid}", {"constraints": [constraint]}, payload,
                          schema=VERDICT_SCHEMA, validate=verdict_ids)
        return pid, cid, value

    with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        verification = list(pool.map(verify_job, pair_ids))
    v = {pid: [] for pid in passages}
    decisions = {}
    for pid, cid, value in verification:
        decisions[f"{pid}:{cid}"] = None if value is None else int(bool(value))
        if value:
            v[pid].extend(value)
    if len(list(cache.glob("*.json"))) != len(p2) + len(pair_ids):
        raise RuntimeError("B1 cache receipts do not reconcile")
    write_new(out / "labels.private.json", {"original": original, "P2": p2, "V": v, "verification": decisions})
    cost = {
        "original_reused_calls": len(original), "P2_calls": len(p2), "V_verification_calls": len(pair_ids),
        "P2_failures": sum(value is None for value in p2.values()),
        "V_verification_failures": sum(value is None for value in decisions.values()),
        "P2_seconds": round(p2_seconds, 3), "V_seconds": round(perf_counter() - begin, 3),
        "total_seconds": round(perf_counter() - started, 3), "retries": 0,
    }
    write_new(out / "cost.json", cost)
    endpoint = urlsplit(cfg.pop("endpoint"))
    cfg.update(loopback_host=endpoint.hostname, loopback_port=endpoint.port)
    write_new(out / "config.json", cfg)
    print("B1_done", len(p2), len(pair_ids), flush=True)


def tracked_events(packet, labels):
    tracks, lookup = {}, {}
    support = {pid: None if ids is None else set(ids) for pid, ids in labels.items()}
    for record in packet["tracks"]:
        tid, qid = record["trajectory_id"], record["query_id"]
        keywords = {row["constraint_id"]: row["keywords"] for row in packet["tasks"][qid]["constraints"]}
        tracks[tid] = account(record["events"], support, keywords)
        lookup.update((event["id"], qid) for event in tracks[tid]["events"])
    return tracks, lookup


def signal_report(tracks, targets, intersection):
    names = ("r1_a", "r1_b_keyword", "r1_b_semantic", "r1_b_final", "search_exact_repeat", "search_jaccard_repeat")
    signals = {name: set() for name in names}
    counts = Counter()
    events = [row for track in tracks.values() for row in track["events"]]
    for row in events:
        eid = row["id"]
        if row["query_repeat"]:
            signals[row["query_repeat"]].add(eid)
        if row["a"]:
            signals["r1_a"].add(eid)
            counts[row["a"]] += 1
        counts["incomplete_evidence"] += row["a_incomplete"]
        if eid not in targets:
            continue
        semantic, _ = classify(set(row["confirmed"]), targets[eid], row["keyword"])
        keyword = row["keyword"] == "r1"
        if keyword:
            signals["r1_b_keyword"].add(eid)
        if semantic:
            signals["r1_b_semantic"].add(eid)
            if keyword or not intersection:
                signals["r1_b_final"].add(eid)
        if row["keyword"] == "pending":
            counts["pending"] += 1
            counts["pending_r1"] += semantic is True
            counts["pending_not_r1"] += semantic is False
            counts["pending_unresolved"] += semantic is None
        if semantic is not None:
            name = {(True, True): "both", (True, False): "keyword_only",
                    (False, True): "semantic_only", (False, False): "neither"}[keyword, semantic]
            counts[name] += 1
    return {
        "trajectories": len(tracks), "searches": len(events), "visible_searches": sum(row["visible"] for row in events),
        "first_confirmation_round": {tid: trace["first"] for tid, trace in tracks.items()},
        "trajectories_with_confirmation": sum(bool(trace["first"]) for trace in tracks.values()),
        "r1_a_breakdown": {name: counts[name] for name in ("same", "different", "mixed", "incomplete_evidence")},
        "signal_counts": {name: len(values) for name, values in signals.items()},
        "signal_overlap": {f"{a}__{b}": len(signals[a] & signals[b]) for a, b in combinations(signals, 2)},
        "r1_b_contingency": {name: counts[name] for name in ("both", "keyword_only", "semantic_only", "neither")},
        "r1_b_pending": {name: counts[name] for name in ("pending", "pending_r1", "pending_not_r1", "pending_unresolved")},
    }


def recompute(packet, old, labels, selection, config, out):
    tracks, lookup = tracked_events(packet, labels[selection["selected_scheme"]])
    old_events = {row["id"]: row for track in old["tracks"].values() for row in track["events"]}
    current = [row for track in tracks.values() for row in track["events"]]
    targets, changed, ineligible = plan_targets(old_events, current, old["targets"])
    reused = len(targets)
    begin = perf_counter()
    if changed:
        if config is None:
            raise RuntimeError("changed target sets require the explicit loopback model")
        cache = out / "model_cache"
        cache.mkdir(mode=0o700)
        judge = LocalJudge(config, cache, {"targets": prompt_files()["targets"].read_text(encoding="utf-8")})

        def job(row):
            eid = row["id"]
            task = packet["tasks"][lookup[eid]]
            payload = {**task_payload(task), "constraints_established_earlier": row["confirmed"],
                       "current_search_query": row["query"]}
            return eid, judge.ask("targets", eid, task, payload)

        with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
            targets.update(pool.map(job, changed))
        if len(list(cache.glob("*.json"))) != len(changed):
            raise RuntimeError("B4 cache receipts do not reconcile")
    result = signal_report(tracks, targets, selection["gates"]["use_intersection"])
    result.update(comparison=selection["comparison"], selected_scheme=selection["selected_scheme"],
                  human_evaluation=selection["human_evaluation"], passage_support=selection["passage_support"],
                  gates=selection["gates"], query_ids=packet["query_ids"], cost={
                      **selection["b1_cost"], "target_reused": reused, "target_calls": len(changed),
                      "target_failures": sum(targets[event["id"]] is None for event in changed),
                      "target_now_ineligible": ineligible, "target_seconds": round(perf_counter() - begin, 3),
                      "mean_new_calls_per_trajectory": (
                          selection["b1_cost"]["P2_calls"] + selection["b1_cost"]["V_verification_calls"]
                          + len(changed)) / len(tracks),
                  })
    write_new(out / "fix_pilot.json", result)
    print("B4_done", reused, len(changed), ineligible, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["label", "recompute"], required=True)
    for name in ("packet", "old", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("config", "labels", "selection"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    config = read_json(args.config) if args.config else None
    packet, old = read_json(args.packet), read_json(args.old)
    if args.mode == "label":
        label(packet, old, config, args.output)
    else:
        recompute(packet, old, read_json(args.labels), read_json(args.selection), config, args.output)


if __name__ == "__main__":
    main()
