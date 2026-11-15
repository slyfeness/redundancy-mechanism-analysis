"""Run the two local semantic tasks once and account for support by trajectory round."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from itertools import combinations, groupby
import json
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from check import file_sha, read_json, write_new
from ledger import keyword_decision, normalized, search_repeat
from snippet import select_ids


def object_schema(**fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def support_schema(ids):
    row = object_schema(reason={"type": "string"}, constraint_id={"type": "string", "enum": ids})
    return object_schema(supports={"type": "array", "items": row})


def target_schema(ids):
    return object_schema(reason={"type": "string"},
                         targets={"type": "array", "items": {"type": "string", "enum": ids}})


def account(events, support, keywords):
    first, seen, queries, tagged = {}, set(), [], []
    for round_id, batch in groupby(sorted(events, key=lambda event: event["round"]), key=lambda event: event["round"]):
        prior = set(first)
        incoming, newly_seen, new_queries = set(), set(), []
        for event in batch:
            ids = event["passages"] if event["visible"] else []
            active = [pid for pid in ids if support[pid]]
            claims = set().union(*(support[pid] for pid in active))
            incomplete = any(support[pid] is None for pid in ids)
            a_type = None
            if claims and claims <= prior and not incomplete:
                repeated = sum(pid in seen for pid in active)
                a_type = "same" if repeated == len(active) else "different" if repeated == 0 else "mixed"
            tagged.append({
                **event, "confirmed": sorted(prior), "a": a_type, "a_incomplete": incomplete,
                "keyword": keyword_decision(event["query"], keywords, prior) if prior else None,
                "query_repeat": search_repeat(event["query"], queries),
            })
            incoming.update(claims)
            newly_seen.update(ids)
            new_queries.append(event["query"])
        for cid in sorted(incoming):
            first.setdefault(cid, round_id)
        seen.update(newly_seen)
        queries.extend(new_queries)
    return {"first": first, "events": tagged}


def classify(confirmed, targets, keyword):
    semantic = None if targets is None else bool(targets) and set(targets) <= confirmed
    return semantic, keyword == "r1" or (keyword == "pending" and semantic is True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_response(kind, value, valid):
    if kind == "supports":
        if not isinstance(value, dict) or set(value) != {"supports"} or not isinstance(value["supports"], list):
            raise ValueError("invalid supports response")
        rows = value["supports"]
        if any(not isinstance(row, dict) or set(row) != {"reason", "constraint_id"}
               or not isinstance(row["reason"], str) or row["constraint_id"] not in valid for row in rows):
            raise ValueError("invalid supports row")
        selected = [row["constraint_id"] for row in rows]
    else:
        if (not isinstance(value, dict) or set(value) != {"reason", "targets"}
                or not isinstance(value["reason"], str) or not isinstance(value["targets"], list)
                or any(cid not in valid for cid in value["targets"])):
            raise ValueError("invalid targets response")
        selected = value["targets"]
    return sorted(set(selected))


class LocalJudge:
    def __init__(self, config, cache, prompts):
        url = config["endpoint"]
        parts = urlsplit(url)
        if (parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.username or parts.password
                or not parts.port or parts.path != "/v1" or parts.query or parts.fragment):
            raise ValueError("model endpoint must be numeric loopback HTTP")
        self.url = url + "/chat/completions"
        self.model = config["model"]
        self.timeout = config["timeout_seconds"]
        self.max_tokens = config["max_tokens"]
        self.prompts = prompts
        self.cache = cache

    def ask(self, kind, identifier, task, payload, *, schema=None, validate=None):
        ids = [row["constraint_id"] for row in task["constraints"]]
        shape = schema if schema is not None else support_schema(ids) if kind == "supports" else target_schema(ids)
        request = {"model": self.model, "temperature": 0, "reasoning_effort": "medium",
                   "max_tokens": self.max_tokens,
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": kind, "strict": True, "schema": shape}},
                   "messages": [{"role": "system", "content": self.prompts[kind]},
                                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
        filename = self.cache / (sha256((kind + "|" + identifier).encode()).hexdigest() + ".json")
        raw, code, finish, selected, failure = None, None, None, None, None
        # Acquire an exclusive receipt before dispatch. Each ID is attempted at most once.
        with filename.open("x", encoding="utf-8") as out:
            try:
                opener = build_opener(ProxyHandler({}), NoRedirect())
                req = Request(self.url, data=json.dumps(request, ensure_ascii=False).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
                with opener.open(req, timeout=self.timeout) as response:
                    code = response.status
                    raw = response.read(4_000_001).decode("utf-8")
                if len(raw) > 4_000_000:
                    raise ValueError("model reply exceeds size bound")
                envelope = json.loads(raw)
                if envelope.get("model") != self.model:
                    raise ValueError("unexpected local model")
                choice = envelope["choices"][0]
                finish = choice["finish_reason"]
                if finish != "stop":
                    raise ValueError("model reply did not finish")
                content = json.loads(choice["message"]["content"])
                selected = (validate(content, set(ids)) if validate is not None
                            else validate_response(kind, content, set(ids)))
            except (OSError, ValueError, TypeError, IndexError, KeyError) as exc:
                code = getattr(exc, "code", code)
                failure = type(exc).__name__
            json.dump({"kind": kind, "id": identifier, "response": raw, "http_status": code,
                       "finish_reason": finish, "failure": failure, "selected": selected}, out, ensure_ascii=False)
            out.write("\n")
        return selected


def task_payload(task):
    return {"question": task["question"],
            "constraints": [{"constraint_id": row["constraint_id"], "text": row["text"]}
                            for row in task["constraints"]]}


def run_pilot(packet, snippet, config, output, prompts):
    tasks, passages = packet["tasks"], packet["passages"]
    if len(packet["query_ids"]) != 10 or len(packet["tracks"]) != 40 or len(passages) != snippet[
            "unique_evidence_passages_10_queries"]:
        raise ValueError("pilot input counts differ from the CPU receipt")
    cache = output / "model_cache"
    cache.mkdir(mode=0o700)
    judge = LocalJudge(config, cache, prompts)
    start = perf_counter()

    def passage_job(item):
        pid, passage = item
        task = tasks[passage["query_id"]]
        data = {**task_payload(task), "reference_answer": task["answer"], "search_result_passage": passage["passage"]}
        value = judge.ask("supports", pid, task, data)
        return pid, None if value is None else set(value)

    with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
        supports = dict(pool.map(passage_job, sorted(passages.items())))
    support_seconds = perf_counter() - start
    write_new(output / "passage_support.private.json",
              {pid: None if cids is None else sorted(cids) for pid, cids in supports.items()})
    tracks = {}
    event_qids = {}
    for trace in packet["tracks"]:
        qid, tid = trace["query_id"], trace["trajectory_id"]
        keywords = {row["constraint_id"]: row["keywords"] for row in tasks[qid]["constraints"]}
        tracks[tid] = account(trace["events"], supports, keywords)
        event_qids.update((event["id"], qid) for event in tracks[tid]["events"])
    events = {event["id"]: event for trace in tracks.values() for event in trace["events"]}
    if len(events) != sum(len(trace["events"]) for trace in tracks.values()):
        raise ValueError("duplicate frozen pilot event ID")
    eligible = [event for event in events.values() if event["confirmed"]]
    target_start = perf_counter()

    def target_job(event):
        eid = event["id"]
        task = tasks[event_qids[eid]]
        data = {**task_payload(task), "constraints_established_earlier": event["confirmed"],
                "current_search_query": event["query"]}
        return eid, judge.ask("targets", eid, task, data)

    with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
        targets = dict(pool.map(target_job, eligible))
    target_seconds = perf_counter() - target_start
    counts = Counter()
    signals = {key: set() for key in ("r1_a", "r1_b_keyword", "r1_b_semantic", "r1_b_final",
                                      "search_exact_repeat", "search_jaccard_repeat")}
    for eid, event in events.items():
        if event["query_repeat"]:
            signals[event["query_repeat"]].add(eid)
        if event["a"]:
            signals["r1_a"].add(eid)
            counts[event["a"]] += 1
        counts["incomplete_evidence"] += event["a_incomplete"]
        if eid not in targets:
            continue
        keyword = event["keyword"]
        semantic, final = classify(set(event["confirmed"]), targets[eid], keyword)
        if keyword == "r1":
            signals["r1_b_keyword"].add(eid)
        if semantic:
            signals["r1_b_semantic"].add(eid)
        if final:
            signals["r1_b_final"].add(eid)
        if keyword == "pending":
            counts["pending"] += 1
            counts["pending_r1"] += semantic is True
            counts["pending_not_r1"] += semantic is False
            counts["pending_unresolved"] += semantic is None
        if semantic is not None:
            case = {(True, True): "both", (True, False): "keyword_only",
                     (False, True): "semantic_only", (False, False): "neither"}[keyword == "r1", semantic]
            counts[case] += 1
    pair_ids = {f"{pid}:{cid}": {"passage_id": pid, "constraint_id": cid}
                for pid, values in supports.items() for cid in values or ()}
    sampled = {
        "a": {key: pair_ids[key] for key in select_ids(pair_ids, 30)},
        "b": {pid: {"passage_id": pid} for pid in select_ids(passages, 10)},
        "c": {eid: {"event_id": eid} for eid in select_ids(signals["r1_a"], 20)},
        "d": {eid: {"event_id": eid} for eid in select_ids(signals["r1_b_final"], 20)},
        "e": {eid: {"event_id": eid} for eid in select_ids(signals["search_exact_repeat"], 20)},
    }
    # Sort by the published hash ranking again during manual review because JSON maps sort their keys.
    review = {"samples": sampled, "tracks": tracks, "query_id_by_event": event_qids,
              "targets": targets, "supports": {pid: None if value is None else sorted(value)
                                              for pid, value in supports.items()}}
    successful = sum(value is not None for value in supports.values())
    overlap = {f"{left}__{right}": len(signals[left] & signals[right])
               for left, right in combinations(signals, 2)}
    report = {
        "query_ids": packet["query_ids"], "trajectories": len(tracks), "searches": len(events),
        "visible_searches": sum(row["visible"] for row in events.values()),
        "passage_support": {
            "unique_passages": len(passages), "unique_query_document_pairs": len(
                {(row["query_id"], row["docid"]) for row in passages.values()}),
            "labeled_passages": successful, "passages_with_any_support": sum(bool(value) for value in supports.values()),
            "support_pairs": len(pair_ids), "mean_support_per_labeled_passage": len(pair_ids) / successful if successful else None,
        },
        "first_confirmation_round": {tid: trace["first"] for tid, trace in tracks.items()},
        "trajectories_with_confirmation": sum(bool(trace["first"]) for trace in tracks.values()),
        "r1_a_breakdown": {key: counts[key] for key in ("same", "different", "mixed", "incomplete_evidence")},
        "signal_counts": {key: len(value) for key, value in signals.items()},
        "signal_overlap": overlap,
        "r1_b_contingency": {key: counts[key] for key in ("both", "keyword_only", "semantic_only", "neither")},
        "r1_b_pending": {key: counts[key] for key in ("pending", "pending_r1", "pending_not_r1", "pending_unresolved")},
        "cost": {
            "support_calls": len(supports), "target_calls": len(targets),
            "support_failures": len(supports) - successful, "target_failures": sum(v is None for v in targets.values()),
            "support_seconds": round(support_seconds, 3), "target_seconds": round(target_seconds, 3),
            "total_seconds": round(perf_counter() - start, 3), "retries": 0,
            "mean_calls_per_trajectory": (len(supports) + len(targets)) / len(tracks),
            "estimated_support_calls_100_queries": snippet["unique_evidence_passages_100_queries"],
        },
    }
    if sum(report["r1_b_contingency"].values()) + report["cost"]["target_failures"] != len(targets):
        raise RuntimeError("semantic/keyword table does not reconcile")
    if len(list(cache.glob("*.json"))) != len(supports) + len(targets):
        raise RuntimeError("local model receipts do not reconcile")
    return report, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "output", "config"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    config = read_json(args.config)
    path = Path(__file__).parent
    prompt_paths = {kind: path / f"{kind}_prompt.md" for kind in ("supports", "targets")}
    prompts = {kind: file.read_text(encoding="utf-8") for kind, file in prompt_paths.items()}
    config["prompt_sha256"] = {kind: file_sha(file) for kind, file in prompt_paths.items()}
    config["snippet_check_sha256"] = file_sha(args.prepared / "snippet_check.json")
    packet = read_json(args.prepared / "inputs.private.json")
    snippet = read_json(args.prepared / "snippet_check.json")
    report, review = run_pilot(packet, snippet, config, args.output, prompts)
    write_new(args.output / "docid_pilot.json", report)
    write_new(args.output / "review.private.json", review)
    endpoint = urlsplit(config.pop("endpoint"))
    config.update(loopback_host=endpoint.hostname, loopback_port=endpoint.port)
    write_new(args.output / "config.json", config)
    print("completed model receipts", report["cost"]["support_calls"], report["cost"]["target_calls"], flush=True)


if __name__ == "__main__":
    main()
