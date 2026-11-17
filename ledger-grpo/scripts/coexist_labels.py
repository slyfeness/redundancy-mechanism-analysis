"""Project the phase-one DocID ledger onto the original native training axis."""

import argparse
from base64 import b64decode
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from ledger_grpo.browsecomp_adapter import native_trajectory
from redundancy_judge.adapters.model import ModelJudge
from redundancy_judge.adapters.trace import NativeByteTokenizer, load_trajectory
from redundancy_judge.common import atomic_json, identity, read_json
from redundancy_judge.docid import bind_labels, evidence_labels, grounding_coverage
from redundancy_judge.init_task_ledger import initial_ledger, task_spec
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.parse_stages import parse_stages
from redundancy_judge.resolve_action_target import resolve_action_target
from redundancy_judge.update_evidence_ledger import merge_parallel_updates, update_evidence_ledger


_BUDGET = {"CONTEXT_LIMIT_STOP", "SAFETY_CEILING_STOP", "GENERATION_LENGTH_STOP"}
_ACTION_FIELDS = ("tool_name", "arguments", "call_id", "event_id", "environment", "deterministic", "dispatch_time")


@dataclass(frozen=True)
class EvidenceSnapshot:
    rows: dict
    sha256: str


def load_evidence_snapshot(path):
    payload = Path(path).read_bytes()
    return EvidenceSnapshot(evidence_labels(payload), sha256(payload).hexdigest())


def _official_decoder(card):
    canary = re.search(r'^CANARY = "([^"]+)"$', card, re.M)
    if canary is None:
        raise ValueError("official dataset card is missing its codec key")
    key = sha256(canary[1].encode()).digest()

    def decode(value):
        return bytes(byte ^ key[i % len(key)] for i, byte in enumerate(b64decode(value, validate=True))).decode()

    return decode


def _project_qrels(plan, source_rows, corpus_ids, decode):
    questions = {}
    for split in ("training", "evaluation"):
        expected = [str(qid) for qid in plan.get(split + "_ids", [])]
        rows = plan.get(split + "_rows", [])
        if expected != [str(row["query_id"]) for row in rows]:
            raise ValueError(f"frozen pilot {split} rows differ from the planned IDs")
        for row in rows:
            qid, question = str(row["query_id"]), row["question"]
            if qid in questions or sha256(question.encode()).hexdigest() != row["question_sha256"]:
                raise ValueError(f"frozen pilot question identity mismatch for {qid}")
            questions[qid] = question
    if not questions:
        raise ValueError("frozen pilot plan has no questions")

    def docid(value):
        identifier = value if value in corpus_ids else decode(value)
        if identifier not in corpus_ids:
            raise ValueError("official label DocID outside frozen corpus")
        return identifier

    matches = {}
    for row in source_rows:
        qid = str(row["query_id"])
        if qid not in questions:
            continue
        if qid in matches or (row["query"] != questions[qid] and decode(row["query"]) != questions[qid]):
            raise ValueError(f"official question identity mismatch for {qid}")
        matches[qid] = {"question_id": qid, **{
            name: sorted({docid(item["docid"]) for item in row[field] or []}, key=int)
            for name, field in (("evidence", "evidence_docs"), ("gold", "gold_docs"))}}
    missing = sorted(questions.keys() - matches.keys(), key=int)
    if missing:
        raise ValueError(f"official qrels are missing planned questions: {missing}")
    return [matches[qid] for qid in sorted(matches, key=int)]


def prepare_evidence_snapshot(snapshot_config, pilot_plan, output):
    """Build qrels from the frozen 187299 assets for planned 182406 questions."""
    import sys

    # The existing phase-one export owns Parquet iteration and file hashing.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        from freeze_docid_labels import ParquetFile, digest, rows
    finally:
        sys.path.pop(0)
    snapshot = read_json(snapshot_config)
    assets = Path(snapshot["dataset_assets"])
    card = assets / "questions/README.md"
    corpus = sorted((assets / "corpus/data").glob("*.parquet"))
    questions = sorted((assets / "questions/data").glob("*.parquet"))
    current = {p.relative_to(assets).as_posix(): digest(p) for p in (card, *corpus, *questions)}
    if current != snapshot["asset_snapshot_sha256"]:
        raise ValueError("DocID annotations/corpus differ from 187299")
    decode = _official_decoder(card.read_text(encoding="utf-8"))
    ids = set()
    for row in rows(corpus, ["docid"]):
        token = row["docid"]
        identifier = token if token.isascii() and token.isdecimal() else decode(token)
        if not identifier.isascii() or not identifier.isdecimal() or identifier in ids:
            raise ValueError("invalid or duplicate corpus DocID")
        ids.add(identifier)
    schema = ParquetFile(questions[0]).schema
    fields = [schema.column(i).path for i in range(len(schema))]
    columns = ["query_id", "query"] + [field for field in fields if field.split(".")[0] in {
        "evidence_docs", "gold_docs"} and field.endswith(".docid")]
    normalized = _project_qrels(read_json(pilot_plan), rows(questions, columns), ids, decode)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in normalized)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
    return {"questions": len(normalized), "sha256": sha256(encoded.encode()).hexdigest(),
            "source_assets_job": 187299, "source_plan_job": 182406}


def _independent_result(result):
    if result is None or isinstance(result, dict):
        return result
    if type(result) in (float, int) and result in (0, 1):
        return {"label": "C" if result == 1 else "W", "source": "native_batch_verifier"}
    raise ValueError("expected an independent verifier result or an unresolved outcome")


def _round_coordinates(trace, parsed, layout):
    """Map the phase-one action-only intervals to the merged native mask."""
    training = iter(layout["turns"])
    mapping = {}
    for item in parsed["position_map"]["rounds"]:
        start, stop = item["policy_token_span"]
        if start == stop:
            continue
        native = next(training, None)
        if native is None or stop - start != native["token_end"] - native["token_start"]:
            raise ValueError("phase-one and native action lengths differ")
        mapping[item["round_id"]] = (start, stop, native["token_start"])
    if next(training, None) is not None or parsed["policy_token_count"] != sum(layout["response_mask"]):
        raise ValueError(f"unverified native action identity for {trace['trajectory_id']}")
    return mapping


def _termination(trace, parsed):
    stop = trace["termination_reason"]
    if stop == "MODEL_FINAL_STOP" and parsed["stages"] and parsed["stages"][-1]["stage_type"] == "final":
        return "normal", parsed["recording_complete"]
    if stop not in _BUDGET:
        return "unknown", False
    blocking = {"orphan_tool_event", "round_order_unverified", "call_event_mismatch",
                "return_not_reinjected_at_termination"}
    complete = (bool(trace["rounds"])
                and all(round_["response_received"] is True or
                        (round_.get("request_sent") is False and round_.get("guard_intercepted") is True)
                        for round_ in trace["rounds"])
                and not any(event["errors"] for event in parsed["tool_events"])
                and not any(row["code"] in blocking for row in parsed["anomalies"]))
    return "budget_exhausted", complete


def _score_event(stage, event, judgment, event_id, mapping, mask):
    spans = stage["charge_token_spans"]
    returned = event["return_tokens"]
    if not spans or type(returned) is not int:
        return None
    ((start, stop),) = spans
    round_id = event["round_id"]
    left, right, offset = mapping[round_id]
    if not left <= start < stop <= right:
        raise ValueError("call envelope is outside its original round")
    native_span = [start - left + offset, stop - left + offset]
    if not all(mask[slice(*native_span)]):
        raise ValueError("call envelope overlaps native observation tokens")
    return {"event_id": event_id, "turn_id": round_id, "known_at": round_id,
            "event_tokens": native_span, "label": judgment["price_label"],
            "event_cost": {"generated_tokens": stop - start, "returned_tokens": returned, "tool_calls": 1}}


def _read_trace(path, result, evidence, tokenizer, environment, question):
    if not isinstance(evidence, EvidenceSnapshot):
        raise ValueError("expected a frozen evidence-label snapshot")
    trace = load_trajectory(path, result=_independent_result(result), question=question, environment=environment)
    if tokenizer.revision != trace["tokenizer_revision"]:
        raise ValueError("native tokenizer revision differs from recorder")
    return trace, parse_stages(trace, {"tokenizer": tokenizer, "phase1_mode": "docid"})


def _docid_labels(trace, parsed, tokenizer, evidence):
    trajectory_id, qid = trace["trajectory_id"], trace["question_id"]
    task = bind_labels(task_spec(trace["question"], trace["question_sha256"]), evidence.rows.get(qid))
    ledger = initial_ledger(task)
    reasoning = {row["round_id"]: row.get("reasoning_content") for row in trace["rounds"]}
    events = {row["event_id"]: row for row in parsed["tool_events"]}
    causal_events, m3_inputs = [], []
    for stage in parsed["stages"]:
        if stage["stage_type"] != "tool":
            continue
        before = ledger
        branches = []
        for short_id in stage["event_ids"]:
            event = events[short_id]
            event_id = f"{trajectory_id}:{short_id}"
            m3_event_id = f"{trajectory_id}:{event['recorded_event_id']}"
            action_stage = {**stage, "m3_event_id": m3_event_id,
                            "m3_reasoning": reasoning[event["round_id"]]}
            if stage["parallel_group_id"] and stage["parse_status"] == "ok":
                action_stage["action"] = {key: event[key] for key in _ACTION_FIELDS}
            after, delta = update_evidence_ledger(task, before, action_stage, event, None)
            target = {"intent": "explore", "skip_reason": "m3_disabled"}
            judgment = judge_stage(task, before, after, action_stage, event, target, delta, None)
            r2b = next(row for row in judgment["labels"] if row["label"] == "R2b")
            causal_events.append({"event_id": event_id, "m3_event_id": m3_event_id, "round_id": event["round_id"],
                                  "r2b": r2b, "result_label": judgment["diagnostics"]["result_label"],
                                  "protections": judgment["protections"],
                                  "docids_before": before["documents"], "docids_returned": event["document_ids"],
                                  "docids_after": after["documents"], "new_evidence": delta["new_evidence"],
                                  "evidence_passages_before_sha256": identity(before.get("evidence_passages", {})),
                                  "evidence_passages_after_sha256": identity(after.get("evidence_passages", {})),
                                  "ledger_delta": delta,
                                  "visible_before": action_stage["visible_return_ids"],
                                  "visible_next": event["visible_next"]})
            m3_inputs.append((action_stage, event, before, after, delta, judgment))
            branches.append((after, delta))
        if branches:
            ledger = merge_parallel_updates(task, before, branches) if stage["parallel_group_id"] else branches[0][0]
    g, grounding_issue = grounding_coverage(task, ledger)
    causal = {"trajectory_id": trajectory_id, "question_id": qid, "source_trajectory_sha256": trace["input_sha256"],
              "evidence_labels_sha256": evidence.sha256, "tokenizer_sha256": tokenizer.sha256,
              "task_result": trace["result"], "grounding": g, "grounding_issue": grounding_issue,
              "documents": ledger["documents"], "events": causal_events, "anomalies": parsed["anomalies"]}
    return {"causal": causal, "_m3_inputs": (task, m3_inputs)}


def label_trajectory(path, result, evidence, tokenizer, *, environment, question=None):
    """Return score-event input and a receipt on the same original recorder bytes."""
    from ledger_grpo.hf_native import native_turn_layout

    trace, parsed = _read_trace(path, result, evidence, tokenizer, environment, question)
    trajectory_id, qid = trace["trajectory_id"], trace["question_id"]
    result = trace["result"]
    no_final = 0 if trace["termination_reason"] in _BUDGET | {"EMPTY_MODEL_STOP"} else None
    outcome = {"C": 1, "W": 0, "N": no_final}[result["label"]] if result is not None else None
    native = native_trajectory(
        {"metadata": {"task": {"run_id": trajectory_id, "query_id": qid},
                      "terminal_status": trace["termination_reason"]}, "rounds": trace["rounds"]},
        reward=outcome)
    layout = native_turn_layout(native)
    mask = layout["response_mask"]
    mapping = _round_coordinates(trace, parsed, layout)
    labeled = _docid_labels(trace, parsed, tokenizer, evidence)
    score_events = []
    for causal, (stage, event, _, _, _, judgment) in zip(
            labeled["causal"]["events"], labeled["_m3_inputs"][1], strict=True):
        measured = _score_event(stage, event, judgment, causal["event_id"], mapping, mask)
        causal["native_event"] = measured
        if measured is not None:
            score_events.append(measured)
    stop, complete = _termination(trace, parsed)
    row = {"traj_id": trajectory_id, "task_id": qid, "outcome": outcome,
           "recording_complete": complete, "termination_reason": stop, "grounding": labeled["causal"]["grounding"],
           "response_mask": mask, "events": score_events}
    return {**labeled, "score_row": row, "native": native}


def replay_historical_trajectory(path, result, evidence, tokenizer, *, environment, question=None):
    """Replay the historical DocID code from native IDs without assuming training logprobs."""
    trace, parsed = _read_trace(path, result, evidence, tokenizer, environment, question)
    return _docid_labels(trace, parsed, tokenizer, evidence)


class _M3Receipts:
    """Keep original intent wire order when replaying a cached verification."""

    def __init__(self, judge):
        self.judge = judge

    def ask_m3(self, step, payload, shape, event_id):
        response = self.judge.ask_m3(step, payload, shape, event_id)
        path = self.judge.cache.parent / "m3_call_receipts" / (identity([event_id, step]) + ".json")
        if step == "intent" and path.is_file():
            receipt = read_json(path)
            original = json.loads(json.loads(receipt["raw_response"])["choices"][0]["message"]["content"])
            if original != response:
                raise ValueError(f"M3 receipt does not match the parsed intent for {event_id}")
            return original
        return response


def record_m3(labels, judge, *, policy_snapshot_sha256, output):
    """Run the original M3 v3 request protocol and write record-only R1 receipts."""
    if not isinstance(judge, ModelJudge) or judge.freeze.get("policy_snapshot_sha256") != policy_snapshot_sha256:
        raise ValueError("M3 requires a ModelJudge bound to the actor policy snapshot")
    task, inputs = labels["_m3_inputs"]
    causal = labels["causal"]
    binding = {key: causal[key] for key in ("trajectory_id", "source_trajectory_sha256",
                                            "evidence_labels_sha256", "tokenizer_sha256")}
    binding.update(policy_snapshot_sha256=policy_snapshot_sha256, judge_model=judge.name,
                   judge_prompt_sha256=judge.prompt_sha256, judge_freeze_sha256=identity(judge.freeze))
    output = Path(output)
    if output.exists():
        receipt = read_json(output)
        if any(receipt.get(key) != value for key, value in binding.items()):
            raise ValueError("existing R1 receipt uses different frozen inputs")
        return receipt
    m3 = _M3Receipts(judge)
    records = []
    for stage, event, before, after, delta, original in inputs:
        target = resolve_action_target(task, before, stage, m3)
        judgment = judge_stage(task, before, after, stage, event, target, delta, m3, r1_record_only=True)
        r1 = next(label for label in judgment["labels"] if label["label"] == "R1")
        if (r1["reward_eligible"] or judgment["price_label"] != original["price_label"]
                or judgment["labels"][0] != original["labels"][0]
                or judgment["diagnostics"]["result_label"] != original["diagnostics"]["result_label"]):
            raise ValueError("record-only M3 altered an active DocID scoring decision")
        records.append({"event_id": stage["m3_event_id"], "round_id": event["round_id"], "r1": r1,
                        "target": target, "r1_confidence": judgment["diagnostics"]["r1_confidence"],
                        "prior_passage_ids": ["P" + docid for docid in before.get("evidence_passages", {})]})
    receipt = {**binding, "events": records}
    atomic_json(output, receipt)
    return receipt


def _jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        yield from (json.loads(line) for line in stream if line.strip())


def _index(rows, key):
    result = {}
    for row in rows:
        identity = row[key]
        if identity in result:
            raise ValueError(f"duplicate frozen {key}: {identity}")
        result[identity] = row
    return result


def _compare_code_labels(labeled, reference_results, reference_r2b, reference_g):
    causal = labeled["causal"]
    actual = _index(causal["events"], "event_id")
    differences = []

    def compare(check, key, expected, observed):
        if expected != observed:
            differences.append({"check": check, "id": key, "expected": expected, "observed": observed})

    compare("event_ids_187333", causal["trajectory_id"], sorted(reference_results), sorted(actual))
    compare("event_ids_187767", causal["trajectory_id"], sorted(reference_r2b), sorted(actual))
    for eid, event in actual.items():
        compare("result_label_187333", eid, reference_results.get(eid), event["result_label"])
        if eid in reference_results:
            compare("R2b_187333", eid, reference_results[eid] == "repeat_query", event["r2b"]["decision"] == "positive")
        compare("R2b_187767", eid, reference_r2b.get(eid), event["r2b"])
    compare("g_187767", causal["trajectory_id"], reference_g, causal["grounding"])
    return differences


def _frozen_event_state(row):
    before, after = row["before"], row["after"]
    return {"docids_before": before["documents"], "docids_after": after["documents"],
            "evidence_passages_before_sha256": identity(before.get("evidence_passages", {})),
            "evidence_passages_after_sha256": identity(after.get("evidence_passages", {})),
            "ledger_delta": row["delta"], "visible_before": row["visible_before"],
            "visible_next": row["observation_verified_in_next_prompt"]}


def _compare_ledger_event(actual, expected):
    return [{"check": f"DocID_187767.{key}", "id": actual["event_id"],
             "expected": value, "observed": actual[key]}
            for key, value in expected.items() if actual[key] != value]


def validate_frozen_labels(phase1, result_sequences, tokenizer, evidence, *, trajectory_ids=None):
    """Compare fresh pure labels on original files to jobs 187333 and 187767."""
    phase1, result_sequences = Path(phase1), Path(result_sequences)
    index = _index(_jsonl(phase1 / "input_index.jsonl"), "trajectory_id")
    selected = set(index) if trajectory_ids is None else set(trajectory_ids)
    if not selected or selected - index.keys():
        raise ValueError("selected frozen trajectories must exist in the historical input index")
    ref_summary = _index(_jsonl(phase1 / "trajectory_summaries.jsonl"), "trajectory_id")
    ref_results = _index(_jsonl(result_sequences), "trajectory_id")
    codebook = read_json(result_sequences.with_name("result_labels.json"))["codebook"]["main"]
    by_code = {code: name for name, code in codebook.items()}
    judgments = {}
    for row in _index(_jsonl(phase1 / "stage_judgments.jsonl"), "event_id").values():
        tid, _ = row["event_id"].rsplit(":", 1)
        if tid in selected:
            judgments.setdefault(tid, {})[row["event_id"]] = next(x for x in row["labels"] if x["label"] == "R2b")
    ledger_states = _index(
        ({"event_id": row["event_id"], **_frozen_event_state(row)}
         for row in _jsonl(phase1 / "ledger_snapshots.jsonl")
         if row["event_id"] is not None and row["trajectory_id"] in selected), "event_id")
    expected_event_ids = {eid for rows in judgments.values() for eid in rows}
    if ledger_states.keys() != expected_event_ids:
        raise ValueError("frozen ledger snapshots and historical judgments have different event IDs")
    differences = []
    events = 0
    for tid in sorted(selected):
        source = index[tid]
        independent = {"label": source["result"], "source": source["result_source"],
                       "trajectory_id": tid} if source.get("Y") is not None else None
        labeled = replay_historical_trajectory(
            source["path"], independent, evidence, tokenizer, question=source["question"],
            environment={"id": source["environment"], "deterministic_tools": source["deterministic_tools"]})
        causal = labeled["causal"]
        if (causal["source_trajectory_sha256"] != source["sha256"] or causal["trajectory_id"] != tid
                or causal["question_id"] != source["question_id"]):
            raise ValueError(f"original recorder differs from frozen historical identity for {tid}")
        reference = _index(ref_results[tid]["events"], "event_id")
        results = {eid: by_code[row["main"]] for eid, row in reference.items()}
        differences.extend(_compare_code_labels(labeled, results, judgments.get(tid, {}), ref_summary[tid]["g"]))
        for row in causal["events"]:
            state = ledger_states.get(row["event_id"])
            if state is not None:
                differences.extend(_compare_ledger_event(row, state))
        events += len(causal["events"])
    return {"ok": not differences, "trajectories": len(selected), "events": events, "mismatches": differences,
            "evidence_labels_sha256": evidence.sha256, "tokenizer_sha256": tokenizer.sha256,
            "ledger_snapshots_compared": len(ledger_states),
            "reference_jobs": {"R2b": [187333, 187767], "result_label": 187333, "g": 187767, "DocID": 187767}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-evidence")
    for name in ("snapshot_config", "pilot_plan", "output"):
        prepare.add_argument(name, type=Path)
    validate = sub.add_parser("validate-frozen")
    for name in ("phase1", "result_sequences", "tokenizer", "evidence", "output"):
        validate.add_argument(name, type=Path)
    validate.add_argument("--tokenizer-revision", required=True)
    validate.add_argument("--trajectory-id", action="append")
    args = parser.parse_args(argv)
    if args.command == "prepare-evidence":
        print(json.dumps(prepare_evidence_snapshot(args.snapshot_config, args.pilot_plan, args.output)))
        return
    result = validate_frozen_labels(args.phase1, args.result_sequences,
                                    NativeByteTokenizer(args.tokenizer, args.tokenizer_revision),
                                    load_evidence_snapshot(args.evidence), trajectory_ids=args.trajectory_id)
    atomic_json(args.output, result)
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
