"""Verify private Phase 1 outputs against original native recorder coordinates."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from redundancy_judge.adapters.trace import sha256 as raw_hash
from redundancy_judge.cli import jsonl
from redundancy_judge.common import atomic_json, identity


def demand(condition, message):
    if not condition:
        raise ValueError(message)


def dereference(record, pointer):
    for part in pointer.removeprefix("/").split("/"):
        record = record[int(part)] if isinstance(record, list) else record[part]
    return record


def collect(run):
    data = {}
    for path in sorted((run / "bundles").glob("*.json")):
        bundle = json.loads(path.read_bytes())
        tid = bundle["input_index"]["trajectory_id"]
        demand(tid not in data, "duplicate trajectory receipt")
        data[tid] = bundle
    return data


def check_bundle(bundle, validators, expected_provenance):
    index = bundle["input_index"]
    raw_bytes = Path(index["path"]).read_bytes()
    demand(raw_hash(raw_bytes) == index["sha256"], "source changed")
    demand(bundle["provenance"]["input_sha256"] == index["sha256"]
           and all(bundle["provenance"].get(k) == v for k, v in expected_provenance.items()),
           "frozen provenance mismatch")
    summary = bundle.get("trajectory_summaries")
    if summary is None:
        demand(bool(bundle["parse_failures"]), "missing trajectory and failure receipt")
        return Counter(rejected=1)
    raw = json.loads(raw_bytes)
    stages = bundle["stages"]
    events = bundle["tool_events"]
    demand(len(events) == len(raw["tool_events"]), "lost tool events")
    demand([stage["order"] for stage in stages] == list(range(1, len(stages) + 1)), "stage order")
    demand([rid for stage in stages for rid in stage["round_ids"]]
           == [row["round_id"] for row in raw["rounds"]], "round coverage or order")
    owned = [eid for stage in stages for eid in stage["event_ids"]]
    ids = {event["event_id"]: event for event in events}
    demand(len(ids) == len(events) and len(owned) == len(set(owned)), "duplicate tool-event ownership")
    if summary["recording_complete"]:
        demand(set(owned) == set(ids), "missing tool-event ownership")
    position = bundle["position_map"]["rounds"]
    native = 0
    for row in position:
        start, end = row["policy_token_span"]
        native_ids = dereference(raw, row["source_pointer"])
        demand(start == native and end - start == len(native_ids), "native token axis mismatch")
        native = end
    if summary["token_alignment_status"] == "verified":
        demand(native == sum(len(r["raw_response"]["choices"][0]["token_ids"]) for r in raw["rounds"])
               == summary["policy_token_count"], "native completion counts differ")
        demand([span for stage in stages for span in stage["policy_token_spans"]]
               == [row["policy_token_span"] for row in position if row["policy_token_span"][0] <
                   row["policy_token_span"][1]], "stage policy extents do not match native rounds")
    for schema, rows in (("StageRecord", stages), ("TaskSpec", [bundle["task_specs"]]),
                         ("ActionTarget", bundle["action_targets"]),
                         ("StageJudgment", bundle["stage_judgments"]),
                         ("TrajectoryAnnotation", [summary])):
        for row in rows:
            validators[schema].validate(row)
    evidence_checks = 0

    def quote(ref):
        text = dereference(raw, ref["reference"]["source_pointer"])
        demand(text[ref["start"]:ref["end"]] == ref["quote"]
               and identity(text) == ref["content_id"], "unbound evidence quotation")

    for constraint in bundle["task_specs"]["constraints"]:
        ref = constraint["source"]
        demand(index["question"][ref["start"]:ref["end"]] == ref["quote"], "unbound task quotation")
    for snap in bundle["ledger_snapshots"]:
        validators["LedgerSnapshot"].validate(snap["before"])
        validators["LedgerSnapshot"].validate(snap["after"])
        for ref in snap.get("delta", {}).get("evidence", ()):
            quote(ref)
            evidence_checks += 1

    stage_map = {row["stage_id"]: row for row in stages}
    for judgment in bundle["stage_judgments"]:
        stage = stage_map[judgment["stage_id"]]
        event = ids[judgment["event_id"].removeprefix(index["trajectory_id"] + ":")]
        for label in judgment["labels"]:
            if label["reward_eligible"]:
                demand(stage["stage_type"] == "tool" and not stage["parallel_group_id"]
                       and event["visible_next"] and label["known_at"] == event["return_time"],
                       "illegal reward candidate")
            if label["label"] == "R1":
                for ref in label["evidence"]:
                    quote(ref)
            if label["label"] == "R2b" and label["decision"] == "positive":
                demand(any(old in stage["visible_return_ids"]
                           and all(ids[old][k] == event[k] for k in (
                               "tool_name", "arguments", "environment", "return_text"))
                           for old in label["evidence"]), "repeat has no visible exact match")
        if judgment["price_label"]:
            demand(judgment["charge_token_spans"] == stage["charge_token_spans"] != [],
                   "pricing coordinates detached from verified call")
    counters = Counter(checked=1, raw_rounds=len(raw["rounds"]), tool_events=len(events), stages=len(stages),
                       verified_evidence_quotes=evidence_checks,
                       annotation_failures=len(bundle["annotation_failures"]),
                       parse_anomalies=len(bundle["parse_failures"]))
    return counters


def verify(run):
    schema_path = Path(__file__).resolve().parents[1] / "src/redundancy_judge/schemas/phase1.schema.json"
    schema = json.loads(schema_path.read_bytes())
    validators = {key: Draft202012Validator({**schema, "$ref": f"#/$defs/{key}"}) for key in schema["$defs"]}
    provenance = json.loads((run / "run_manifest.json").read_bytes())["freeze"]
    index = jsonl(run / "input_index.jsonl")
    bundles = collect(run)
    demand({row["trajectory_id"] for row in index} == set(bundles) and len(index) == len(bundles),
           "manifest coverage differs from sealed bundles")
    count = Counter()
    parse, annotation = Counter(), Counter()
    errors = []
    for tid, bundle in bundles.items():
        try:
            count.update(check_bundle(bundle, validators, provenance))
        except Exception as exc:
            errors.append({"trajectory_id": tid, "error_class": type(exc).__name__, "message": str(exc).splitlines()[0]})
        parse.update(row.get("code", row.get("state", "unknown")) for row in bundle["parse_failures"])
        annotation.update(row["reason"] for row in bundle.get("annotation_failures", ()))
    files = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(run.glob("*.jsonl"))}
    return {"status": "PASS" if not errors and not count["rejected"] else "FAIL",
            "counts": dict(count), "checked_inputs": len(index), "proof_failures": errors,
            "parse_codes": dict(parse), "annotation_reasons": dict(annotation),
            "private_output_sha256": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    opts = parser.parse_args()
    result = verify(opts.run)
    atomic_json(opts.receipt, result)
    print(json.dumps({k: v for k, v in result.items() if k != "private_output_sha256"},
                     ensure_ascii=False), flush=True)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
