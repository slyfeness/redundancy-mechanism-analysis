"""Run the frozen M3 intent exam once per event and passage-selection variant."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from itertools import groupby
import json
from math import log1p
from pathlib import Path
import re
from time import perf_counter
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CATEGORIES = ("already_seen", "new_information", "new_candidate")
VARIANTS = ("A", "B")
LABELS = ("repeat_query", "no_new_information", "repeat_evidence", "effective", "ineffective", "no_return")


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def read(path):
    return json.loads(path.read_bytes())


def records(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def digest(path):
    with path.open("rb") as stream:
        return sha256(stream.read()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def terms(text):
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def choose_passages(seen, query):
    if not seen:
        return {variant: [] for variant in VARIANTS}
    query_terms = sorted(set(terms(query)))
    vectors = {docid: Counter(terms(row["passage"])) for docid, row in seen.items()}
    lengths = {docid: sum(vector.values()) for docid, vector in vectors.items()}
    n = len(seen)
    mean_length = sum(lengths.values()) / n or 1.0
    document_frequency = {word: sum(word in vector for vector in vectors.values()) for word in query_terms}
    scores = {}
    k1, b = 1.2, .75
    for docid, vector in vectors.items():
        normalization = k1 * (1 - b + b * lengths[docid] / mean_length)
        scores[docid] = sum(
            log1p((n - document_frequency[word] + .5) / (document_frequency[word] + .5))
            * vector[word] * (k1 + 1) / (vector[word] + normalization)
            for word in query_terms if vector[word]
        )
    rows = {docid: {"id": "P" + docid, "is_evidence": row["is_evidence"],
                    "bm25_score": scores[docid], "text": row["passage"]}
            for docid, row in seen.items()}
    ranked = sorted(seen, key=lambda docid: (-scores[docid], int(docid)))
    return {"A": [row for row in rows.values() if row["is_evidence"]],
            "B": [rows[docid] for docid in ranked[:5]]}


def make_trials(searches, trajectories, questions, passages):
    trials = []
    ordered = sorted(searches, key=lambda row: (row["trajectory_id"], row["round"], row["parallel_index"]))
    for tid, track in groupby(ordered, key=lambda row: row["trajectory_id"]):
        qid = trajectories[tid]
        seen = {}
        for _, batch in groupby(track, key=lambda row: row["round"]):
            current = list(batch)
            for row in current:
                reason = row["reasoning"] or ""
                choices = choose_passages(seen, row["query"] + "\n" + reason[-500:])
                for variant, chosen in choices.items():
                    trials.append({"event_id": row["event_id"], "variant": variant, "passages": chosen,
                                   "question": questions[qid], "reasoning": reason[-2000:], "query": row["query"]})
            # Parallel sibling calls share exactly the same preceding visibility state.
            for row in current:
                if row["visible"]:
                    for docid in row["returned_docids"]:
                        passage = passages[qid, docid]
                        if not isinstance(passage["passage"], str):
                            raise ValueError(f"visible document lacks source passage: {qid}:{docid}")
                        seen.setdefault(docid, passage)
    return trials


def passage_schema(passage_ids):
    items = {"type": "string", "enum": passage_ids} if passage_ids else {"type": "string"}
    array = {"type": "array", "items": items}
    if not passage_ids:
        array["maxItems"] = 0
    fields = {"seeking": {"type": "string"}, "reason": {"type": "string"},
              "category": {"type": "string", "enum": list(CATEGORIES)}, "passage_ids": array}
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def judge_labels(category, ids, allowed):
    seen = category == "already_seen"
    conflict = (seen and (not ids or not set(ids) <= allowed)) or (not seen and bool(ids))
    return seen and not conflict, conflict


def parse_content(content):
    value = json.loads(content)
    if (not isinstance(value, dict) or value.keys() != {"seeking", "reason", "category", "passage_ids"}
            or not isinstance(value["seeking"], str) or not isinstance(value["reason"], str)
            or value["category"] not in CATEGORIES or not isinstance(value["passage_ids"], list)
            or any(not isinstance(item, str) for item in value["passage_ids"])):
        raise ValueError("response_schema")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ExamJudge:
    def __init__(self, config, prompt):
        if (config["workers"], config["reasoning_effort"], config["temperature"], config["retry_limit"]) != (
                16, "medium", 0, 0):
            raise ValueError("incorrect exam runtime parameters")
        parts = urlsplit(config["endpoint"])
        if (parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port
                or parts.username or parts.password or parts.path != "/v1" or parts.query or parts.fragment):
            raise ValueError("model service endpoint must be numeric loopback")
        self.endpoint = config["endpoint"] + "/chat/completions"
        self.prompt = prompt
        self.config = config

    def call(self, trial):
        supplied = trial["passages"]
        allowed = [row["id"] for row in supplied]
        body = {"question": trial["question"], "agent_reasoning_before_search": trial["reasoning"],
                "current_search_query": trial["query"],
                "previously_seen_passages": [{key: row[key] for key in ("id", "text")} for row in supplied]}
        user = dump(body)
        config = self.config
        request = {"model": config["model"], "temperature": config["temperature"],
                   "reasoning_effort": config["reasoning_effort"], "max_tokens": config["max_tokens"],
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": "m3_exam", "strict": True, "schema": passage_schema(allowed)}},
                   "messages": [{"role": "system", "content": self.prompt}, {"role": "user", "content": user}]}
        started = perf_counter()
        raw = parsed = status = finish = failure = usage = None
        r1 = conflict = False
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
            parsed = parse_content(choice["message"]["content"])
            r1, conflict = judge_labels(parsed["category"], parsed["passage_ids"], set(allowed))
        except HTTPError as exc:
            status = exc.code
            failure = "http_error"
            with exc:
                try:
                    raw = exc.read().decode("utf-8")
                except (OSError, UnicodeError):
                    raw = None
        except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            failure = str(exc) if type(exc) is ValueError and str(exc) in {
                "response_schema", "unexpected_model", "non_stop"} else type(exc).__name__
        finished = perf_counter()
        return {"event_id": trial["event_id"], "variant": trial["variant"],
                "passages": [{k: row[k] for k in ("id", "is_evidence", "bm25_score")} for row in supplied],
                "passage_characters": sum(len(row["text"]) for row in supplied),
                "request_characters": len(self.prompt) + len(user),
                "request": request, "raw_response": raw, "parsed": parsed,
                "new_r1": r1, "format_conflict": conflict, "http_status": status, "finish_reason": finish,
                "failure": failure, "usage": usage, "seconds": finished - started,
                "_started": started, "_finished": finished}


def load_inputs(review, manifest_path, old_path):
    manifest = read(manifest_path)
    bound = {name: review / name for name in ("questions.jsonl", "passages.jsonl", "searches.jsonl")}
    bound["model_calls/187221_action_target.jsonl"] = old_path
    for name, path in bound.items():
        if digest(path) != manifest["files"][name]["sha256"]:
            raise ValueError(f"exam input hash mismatch: {name}")
    questions = {row["query_id"]: row["question"] for row in records(bound["questions.jsonl"])}
    passages = {(r["query_id"], r["docid"]): r for r in records(bound["passages.jsonl"])}
    searches = records(bound["searches.jsonl"])
    events = {row["event_id"] for row in searches}
    trajectories = {row["trajectory_id"]: row["trajectory_id"].split("__rep", 1)[0] for row in searches}
    old = {row["event_id"]: {"raw": (row["parsed_response"] or {}).get("intent") or "missing",
                             "recorded": row["code_use"].get("intent") or "missing"}
           for row in records(old_path)}
    if (len(searches) != 532 or len(events) != 532 or not len(trajectories) <= manifest["trajectories"] == 40
            or old.keys() != events
            or questions.keys() != set(trajectories.values()) or questions.keys() != set(manifest["query_ids"])
            or sum(row["visible"] for row in searches) != manifest["visible_searches"]):
        raise ValueError("exam input population or archived action-target IDs differ")
    return searches, old, make_trials(searches, trajectories, questions, passages), manifest["query_ids"]


def summarize(rows, searches, old, wall_seconds):
    search_labels = {r["event_id"]: r["main_label"] for r in searches}
    by_variant = {variant: {r["event_id"]: r for r in rows if r["variant"] == variant} for variant in VARIANTS}
    agreement = Counter()
    category_table = {c: dict.fromkeys(CATEGORIES, 0) for c in CATEGORIES}
    for eid in search_labels:
        a, b = (by_variant[v].get(eid) for v in VARIANTS)
        if not (a and b and a["parsed"] and b["parsed"]):
            continue
        category_table[a["parsed"]["category"]][b["parsed"]["category"]] += 1
        agreement[a["new_r1"], b["new_r1"]] += 1
    report = {}
    cross_raw, cross_recorded, by_label, event_ids = {}, {}, {}, {}
    for variant, lookup in by_variant.items():
        current = list(lookup.values())
        counts = Counter(r["parsed"]["category"] for r in current if r["parsed"])
        failures = Counter(r["failure"] for r in current if r["failure"])
        r1 = [r["event_id"] for r in current if r["new_r1"]]
        labels = Counter(search_labels[eid] for eid in r1)
        by_label[variant] = {label: labels[label] for label in LABELS}
        event_ids[variant] = r1
        report[variant] = {"calls": len(current), "categories": {c: counts[c] for c in CATEGORIES},
                           "new_r1": len(r1), "format_conflicts": sum(r["format_conflict"] for r in current),
                           "failures": sum(failures.values()), "failure_types": dict(failures),
                           "mean_input_characters": sum(r["request_characters"] for r in current) / len(current),
                           "mean_passage_characters": sum(r["passage_characters"] for r in current) / len(current),
                           "sum_request_seconds": round(sum(r["seconds"] for r in current), 3),
                           "elapsed_seconds": round(max(r.get("_finished", r["seconds"]) for r in current)
                                                    - min(r.get("_started", 0) for r in current), 3)}
        for field, dest in (("raw", cross_raw), ("recorded", cross_recorded)):
            table = {}
            for r in current:
                intent = old[r["event_id"]][field]
                col = r["parsed"]["category"] if r["parsed"] else "failed"
                table.setdefault(intent, dict.fromkeys((*CATEGORIES, "failed"), 0))[col] += 1
            dest[variant] = table
    return {"searches": len(searches), "trajectories_with_searches": len({r["trajectory_id"] for r in searches}),
            "calls": len(rows), "retry_count": 0, "elapsed_seconds": round(wall_seconds, 3),
            "variants": report, "category_agreement_A_rows_B_columns": category_table,
            "new_r1_agreement": {"paired_valid": sum(agreement.values()),
                                 "paired_missing": len(searches) - sum(agreement.values()),
                                 "both_true": agreement[True, True], "A_only": agreement[True, False],
                                 "B_only": agreement[False, True], "both_false": agreement[False, False]},
            "old_action_target_intent_vs_category": cross_raw, "old_recorded_intent_vs_category": cross_recorded,
            "new_r1_by_result_main_label": by_label, "new_r1_event_ids": event_ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("review", "manifest", "old-target", "runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    searches, archived_targets, trials, qids = load_inputs(args.review, args.manifest, args.old_target)
    if len(trials) != 1064:
        raise ValueError("expected one exam call per search and variant")
    prompt = Path(__file__).with_name("m3_exam_prompt.md")
    config = read(args.runtime)
    judge = ExamJudge(config, prompt.read_text(encoding="utf-8"))
    calls = []
    print("inputs_verified", len(searches), len(trials), flush=True)
    start = perf_counter()
    with (args.output / "m3_exam_calls.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
            for i, row in enumerate(pool.map(judge.call, trials), 1):
                stream.write(dump({key: val for key, val in row.items() if not key.startswith("_")}) + "\n")
                calls.append({key: val for key, val in row.items() if key not in ("request", "raw_response", "passages")})
                if not i % 100:
                    stream.flush()
                    print("calls_finished", i, flush=True)
    summary = summarize(calls, searches, archived_targets, perf_counter() - start)
    summary["query_ids"] = qids
    summary["job_id"] = config["job_id"]
    save(args.output / "m3_exam_summary.json", summary)
    save(args.output / "config.json", {**config, "prompt_sha256": digest(prompt),
         "source_manifest_sha256": digest(args.manifest),
         "inputs": {**{name: digest(args.review / name) for name in ("questions.jsonl", "passages.jsonl", "searches.jsonl")},
                    "187221_action_target.jsonl": digest(args.old_target)},
         "bm25": {"k1": 1.2, "b": .75, "limit_B": 5, "corpus": "all previous visible distinct docids per trajectory",
                  "tokens": "Unicode word tokens after NFKC and casefold", "tiebreak": "ascending numeric DocID"},
         "input_length_unit": "characters in system plus serialized user messages",
         "result_main_label_for_R2b": "repeat_query",
         "timing": "per-variant wall time spans first dispatch to last response; variants overlap"})
    print("exam_complete", len(calls), sum(s["failures"] for s in summary["variants"].values()), flush=True)


if __name__ == "__main__":
    main()
