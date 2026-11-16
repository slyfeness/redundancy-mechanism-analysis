"""Run the two-question M3 exam on the 532 frozen v1 search events."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from run_exam import ExamJudge, NoRedirect, digest, dump, make_trials, read, records, save

PROMPTS = {"intent": "m3v2_intent.md", "verification": "m3v2_verification.md"}
KNOWN = ("289__rep1:4", "289__rep2:4", "289__rep3:4", "289__rep4:3")


def schema(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def skip_second(intent, passage_ids):
    if intent is None:
        return "first_call_failed"
    if intent["entity"] is None:
        return "new_candidate"
    if not passage_ids:
        return "no_prior_passages"
    return None


def verify_r1(already_stated, ids, allowed):
    contradiction = (already_stated and (not ids or not set(ids) <= allowed)) or (not already_stated and bool(ids))
    return already_stated and not contradiction, contradiction


def parse_answer(step, content):
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("response_schema")
    if step == "intent":
        valid = (value.keys() == {"seeking", "entity", "attribute"}
                 and isinstance(value["seeking"], str) and isinstance(value["attribute"], str)
                 and (value["entity"] is None or isinstance(value["entity"], str)))
    else:
        valid = (value.keys() == {"reason", "already_stated", "passage_ids"}
                 and isinstance(value["reason"], str) and type(value["already_stated"]) is bool
                 and isinstance(value["passage_ids"], list)
                 and all(isinstance(pid, str) for pid in value["passage_ids"]))
    if not valid:
        raise ValueError("response_schema")
    return value


def run_event(trial, call):
    query = trial["query"]
    prior = [{key: row[key] for key in ("id", "text")} for row in trial["passages"]]
    ids = [row["id"] for row in prior]
    first = call("intent", {"agent_reasoning_before_search": trial["reasoning"][-1500:],
                           "current_search_query": query}, schema({
        "seeking": {"type": "string"}, "entity": {"type": ["string", "null"]}, "attribute": {"type": "string"},
    }))
    intent = first["parsed"]
    skip = skip_second(intent, ids)
    second = None
    r1 = conflict = False
    if skip is None:
        payload = {"seeking": intent["seeking"], "entity": intent["entity"], "attribute": intent["attribute"],
                   "current_search_query": query, "previously_seen_passages": prior}
        second = call("verification", payload, schema({
            "reason": {"type": "string"}, "already_stated": {"type": "boolean"},
            "passage_ids": {"type": "array", "items": {"type": "string", "enum": ids}},
        }))
        if second["parsed"] is not None:
            answer = second["parsed"]
            r1, conflict = verify_r1(answer["already_stated"], answer["passage_ids"], set(ids))
    return {"event_id": trial["event_id"], "prior_passage_ids": ids,
            "provided_passage_ids": ids if second is not None else [],
            "first": first, "second": second, "skip_reason": skip, "new_r1": r1, "format_conflict": conflict}


class TwoStepJudge(ExamJudge):
    def __init__(self, config, prompts):
        # Reuse v1's parameter and numeric-loopback validation.
        super().__init__(config, prompt=None)
        self.prompts = prompts

    def call(self, step, payload, shape):
        config = self.config
        request = {
            "model": config["model"], "temperature": config["temperature"],
            "reasoning_effort": config["reasoning_effort"], "max_tokens": config["max_tokens"],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "m3v2_" + step, "strict": True, "schema": shape}},
            "messages": [{"role": "system", "content": self.prompts[step]},
                         {"role": "user", "content": dump(payload)}],
        }
        start = perf_counter()
        raw = parsed = status = finish = failure = usage = None
        try:
            req = Request(self.endpoint, data=dump(request).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(req, timeout=config["timeout_seconds"]) as response:
                status = response.status
                raw = response.read().decode("utf-8")
            envelope = json.loads(raw)
            if envelope["model"] != config["model"]:
                raise ValueError("unexpected_model")
            choice = envelope["choices"][0]
            finish = choice["finish_reason"]
            usage = envelope.get("usage")
            if finish != "stop":
                raise ValueError("non_stop")
            parsed = parse_answer(step, choice["message"]["content"])
        except HTTPError as exc:
            status, failure = exc.code, "http_error"
            with exc:
                try:
                    raw = exc.read().decode("utf-8")
                except (OSError, UnicodeError):
                    raw = None
        except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            failure = str(exc) if type(exc) is ValueError and str(exc) in {
                "unexpected_model", "non_stop", "response_schema"} else type(exc).__name__
        end = perf_counter()
        return {"request": request, "raw_response": raw, "parsed": parsed, "failure": failure, "http_status": status,
                "finish_reason": finish, "usage": usage, "seconds": end-start, "_started": start, "_finished": end}


def load_exam(review, manifest_file, v1):
    manifest = read(manifest_file)
    summary = read(v1 / "m3_exam_summary.json")
    config = read(v1 / "config.json")
    if summary["job_id"] != 187355 or config["source_manifest_sha256"] != digest(manifest_file):
        raise ValueError("v1 is not bound to the frozen review manifest")
    for name in ("questions.jsonl", "passages.jsonl", "searches.jsonl"):
        if digest(review / name) != manifest["files"][name]["sha256"] or (
                digest(review / name) != config["inputs"][name]):
            raise ValueError(f"frozen exam input differs: {name}")
    questions = {r["query_id"]: r["question"] for r in records(review / "questions.jsonl")}
    searches = records(review / "searches.jsonl")
    passages = {(r["query_id"], r["docid"]): r for r in records(review / "passages.jsonl")}
    by_track = {r["trajectory_id"]: r["trajectory_id"].split("__rep", 1)[0] for r in searches}
    trials = [trial for trial in make_trials(searches, by_track, questions, passages) if trial["variant"] == "A"]
    old = [row for row in records(v1 / "m3_exam_calls.jsonl") if row["variant"] == "A"]
    if len(trials) != len(old) or len(trials) != 532 or len({r["event_id"] for r in trials}) != 532:
        raise ValueError("exam population is not the 532 v1 searches")
    for trial, prior in zip(trials, old, strict=True):
        actual = json.loads(prior["request"]["messages"][1]["content"])["previously_seen_passages"]
        expected = [{k: p[k] for k in ("id", "text")} for p in trial["passages"]]
        if trial["event_id"] != prior["event_id"] or actual != expected:
            raise ValueError("prior passage list differs from the archived A request")
    baseline = set(summary["new_r1_event_ids"]["A"])
    if baseline != {row["event_id"] for row in old if row["new_r1"]}:
        raise ValueError("v1 A labels do not match receipts")
    return trials, baseline, manifest["query_ids"]


def timing(calls):
    return {
        "sum_request_seconds": round(sum(row["seconds"] for row in calls), 3),
        "elapsed_seconds": round(max(row["_finished"] for row in calls) - min(row["_started"] for row in calls), 3)
        if calls else 0,
    }


def summary(rows, baseline, qids, job_id, run_seconds):
    first = [row["first"] for row in rows]
    second = [row["second"] for row in rows if row["second"] is not None]
    valid = [row["parsed"] for row in first if row["parsed"] is not None]
    nulls = sum(row["entity"] is None for row in valid)
    counts = Counter(row["skip_reason"] for row in rows)
    r1 = {row["event_id"] for row in rows if row["new_r1"]}
    comparison = {
        "both_r1": [], "v1_only": [], "v2_only": [], "neither_r1": [],
    }
    names = {(True, True): "both_r1", (True, False): "v1_only",
             (False, True): "v2_only", (False, False): "neither_r1"}
    for row in rows:
        eid = row["event_id"]
        comparison[names[eid in baseline, eid in r1]].append(eid)
    return {
        "job_id": job_id, "query_ids": qids, "searches": len(rows), "model_calls": len(first)+len(second),
        "retry_count": 0, "elapsed_seconds": round(run_seconds, 3),
        "first": {"calls": len(first), "valid": len(valid), "entity_null": nulls,
                  "entity_null_ratio": nulls / len(valid) if valid else None,
                  "failures": sum(bool(row["failure"]) for row in first), **timing(first)},
        "second": {"calls": len(second), "already_stated_true": sum(
            row["parsed"] is not None and row["parsed"]["already_stated"] for row in second),
            "new_r1": len(r1), "format_conflicts": sum(row["format_conflict"] for row in rows),
            "failures": sum(bool(row["failure"]) for row in second), **timing(second)},
        "skipped_second": {key: counts[key] for key in ("new_candidate", "no_prior_passages", "first_call_failed")},
        "first_failed_event_ids": [row["event_id"] for row in rows if row["first"]["failure"]],
        "second_failed_event_ids": [row["event_id"] for row in rows if row["second"] and row["second"]["failure"]],
        "new_r1_event_ids": [row["event_id"] for row in rows if row["new_r1"]],
        "v1_A_comparison": {name: {"count": len(ids), "event_ids": ids} for name, ids in comparison.items()},
        "question_289": {eid: int(eid in r1) for eid in KNOWN},
    }


def run_exam(args, prefix="m3v2", prompts=PROMPTS, compare=None, extra_config=None):
    trials, baseline, qids = load_exam(args.review, args.manifest, args.v1)
    root = Path(__file__).parent
    prompt_paths = {key: root / file for key, file in prompts.items()}
    config = read(args.runtime)
    judge = TwoStepJudge(config, {key: path.read_text(encoding="utf8") for key, path in prompt_paths.items()})
    rows = []
    print("inputs_verified", len(trials), flush=True)
    begin = perf_counter()
    with (args.output / f"{prefix}_calls.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
            for i, row in enumerate(pool.map(lambda trial: run_event(trial, judge.call), trials), 1):
                light = row.copy()
                for step in ("first", "second"):
                    if row[step] is not None:
                        data = row[step]
                        row[step] = {k: v for k, v in data.items() if not k.startswith("_")}
                        light[step] = {k: v for k, v in data.items() if k not in ("request", "raw_response")}
                stream.write(dump(row) + "\n")
                rows.append(light)
                if not i % 50:
                    stream.flush()
                    print("events_finished", i, flush=True)
    report = summary(rows, baseline, qids, config["job_id"], perf_counter()-begin)
    if compare is not None:
        report.update(compare(report))
    save(args.output / f"{prefix}_summary.json", report)
    save(args.output / "config.json", {**config,
         "prompt_sha256": {k: digest(path) for k, path in prompt_paths.items()},
         "review_manifest_sha256": digest(args.manifest),
         "v1_A_summary_sha256": digest(args.v1 / "m3_exam_summary.json"),
         "v1_calls_sha256": digest(args.v1 / "m3_exam_calls.jsonl"),
         "context_selection": "each passage list sequence was compared with the archived 187355 A request",
         "q1_reasoning_tail_characters": 1500, "timing": "questions run sequentially per event and overlap across events",
         **(extra_config or {})})
    print("exam_complete", len(rows), report["model_calls"], report["first"]["failures"],
          report["second"]["failures"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("review", "manifest", "v1", "runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    run_exam(parser.parse_args())


if __name__ == "__main__":
    main()
