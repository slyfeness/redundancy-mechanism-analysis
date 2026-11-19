"""Run the private pilot and conditionally construct a new M2 ledger."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import mean, median

from ledger_grpo.client import LocalJudge
from ledger_grpo.ledgercredit.__main__ import load_frozen, rows, selection
from ledger_grpo.ledgercredit.conditions import freeze_digest
from ledger_grpo.ledgercredit.evidence_judge import request_once
from ledger_grpo.ledgercredit.judge_v3 import (
    ASSERTION_PROMPT, ASSERTION_VERSION, JUDGE_PROMPT, JUDGE_VERSION, VERSION,
    audit_rule_first, blocks, check_verdicts, freeze_question, gate, merge_verdicts,
    normalize_for_match, payload, sentences,
)
from ledger_grpo.ledgercredit.ledger import build_ledger, dry_run
from ledger_grpo.ledgercredit.validate import validate_ledger

V2 = "bcplus-round4-192109-v2"
MODEL = "gpt-oss-120b"
BUDGET = 80
CONTEXT = 131_072
WORKERS = 8
PILOT_COUNT = 10
TERM = re.compile(r"[^\W_]{3,}")


def emit(file, row):
    file.write(json.dumps(row, ensure_ascii=False) + "\n")
    file.flush()


def dump(path, row):
    with path.open("x", encoding="utf-8") as file:
        emit(file, row)


def read(path):
    return json.loads(path.read_bytes())


def training(root):
    labels, train = selection(root.parent / "round4_bcplus" / "selection")
    questions = {q["id"]: q for q in labels}
    if len(questions) != 50 or not questions.keys() <= train:
        raise ValueError("input outside the frozen training pilot")
    original = load_frozen(root / "m2-192109", questions.keys(), train, V2)
    if sum(len(q["conditions"]) for q in original.values()) != 210:
        raise ValueError("expected 210 v2 conditions")
    m2 = root / "supplement-m2-192129" / "trajectory_results.jsonl"
    outcomes = {r["trajectory_id"]: r for r in rows(m2)}
    if len(outcomes) != 399 or any(r["question_id"] not in questions for r in outcomes.values()):
        raise ValueError("expected 399 validated training trajectories")
    return questions, original, outcomes


def stage_rows(root, ids):
    grouped = defaultdict(list)
    for stage in rows(root / "supplement-m1-192125" / "stages.jsonl"):
        if stage["trajectory_id"] in ids:
            grouped[stage["trajectory_id"]].append(stage)
    if grouped.keys() != set(ids):
        raise ValueError("missing selected Stage records")
    return grouped


def condition_input(question, original, documents, tokenize):
    refs = {}
    for i, docid in enumerate(question["evidence_docs"], 1):
        for row in sentences(documents[docid], f"d{i}"):
            refs[row["id"]] = {**row, "docid": docid}
    parent_terms = [set(TERM.findall(c["text"].casefold())) for c in original["conditions"]]
    anchored = defaultdict(list)
    for c in original["conditions"]:
        for e in c["evidence"]:
            anchored[e["docid"]].append(normalize_for_match(e["quote"]))
    def build(keys):
        return {"question": question["question"], "answer_relation": original["answer_relation"],
                "parents": [{k: c[k] for k in ("id", "text", "support_rule")} for c in original["conditions"]],
                "source_sentences": [{"id": key, "text": refs[key]["text"]} for key in keys]}
    def length(keys):
        return tokenize(json.dumps(build(keys), ensure_ascii=False))
    keys = list(refs)
    if length(keys) <= 105_000:
        return build(keys), refs, len(keys)

    def rank(key):
        row = refs[key]
        ts = set(TERM.findall(row["text"].casefold()))
        target_match = max((len(ts & p) for p in parent_terms), default=0)
        return (any(q and q in normalize_for_match(row["text"]) for q in anchored[row["docid"]]),
                target_match, -row["index"])

    rated = sorted(keys, key=rank, reverse=True)
    order = {key: i for i, key in enumerate(keys)}
    left, right = 0, len(keys)
    while left + 1 < right:
        middle = (left + right) // 2
        prefix = sorted(rated[:middle], key=order.get)
        if length(prefix) <= 105_000:
            left = middle
        else:
            right = middle
    included = sorted(rated[:left], key=order.get)
    return build(included), {key: refs[key] for key in included}, len(keys)


def prepare(args):
    from transformers import AutoTokenizer

    qs, old, outcomes = training(args.root)
    legacy = read(args.legacy / "plan.json")
    tids = [r["trajectory_id"] for r in legacy["samples"]]
    if len(tids) != PILOT_COUNT or len(set(tids)) != PILOT_COUNT or not set(tids) <= outcomes.keys():
        raise ValueError("legacy sample IDs do not match training receipts")
    grouped = stage_rows(args.root, tids)
    number = sum(len(blocks(stages)) for stages in grouped.values())
    if len(qs) + number > BUDGET:
        raise ValueError("pilot exceeds hard cap")
    docs = read(args.root / "docs-192072" / "evidence_docs.json")
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True, model_max_length=1_000_000)
    args.out.mkdir(mode=0o700, exist_ok=False)
    with (args.out / "assertion_inputs.jsonl").open("x", encoding="utf-8") as file:
        for qid, q in qs.items():
            model_input, refs, all_sentences = condition_input(
                q, old[qid], docs, lambda text: len(tokenizer.encode(text, add_special_tokens=False)))
            emit(file, {"qid": qid, "payload": model_input, "sentence_index": refs,
                        "available": all_sentences})
    identity = {"prompt_version": ASSERTION_VERSION, "judge_prompt_version": JUDGE_VERSION,
                "assertion_prompt_sha256": sha256(ASSERTION_PROMPT.encode()).hexdigest(),
                "judge_prompt_sha256": sha256(JUDGE_PROMPT.encode()).hexdigest(),
                "old_conditions_sha256": sha256(
                    (args.root / "m2-192109" / "conditions.jsonl").read_bytes()).hexdigest(),
                "model_revision": "config-sha256:" + sha256((args.model_path / "config.json").read_bytes()).hexdigest(),
                "tids": tids, "assertion_requests": len(qs), "pilot_requests": number, "heldout_read": 0}
    dump(args.out / "plan.json", identity)
    print(json.dumps(identity), flush=True)


def call(url, prompt, body, max_tokens):
    try:
        parsed, raw, error = request_once(url, MODEL, prompt, body, max_tokens=max_tokens)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        parsed, raw, error = None, None, type(exc).__name__
    return parsed, raw, error


def check_service(url):
    client = LocalJudge(url, MODEL, cache_size=0)
    with client.opener.open(url.rstrip("/") + "/models", timeout=10) as response:
        models = json.load(response)["data"]
    if next(row["max_model_len"] for row in models if row["id"] == MODEL) != CONTEXT:
        raise ValueError("unexpected vLLM context")


def freeze_all(url, folder, inputs, original):
    proposed = list(rows(inputs / "assertion_inputs.jsonl"))
    if len(proposed) != 50 or {r["qid"] for r in proposed} != original.keys():
        raise ValueError("assertion inputs are not a complete single pass")

    def one(item):
        qid = item["qid"]
        index = item["sentence_index"]
        payload_ids = [r["id"] for r in item["payload"]["source_sentences"]]
        if payload_ids != list(index):
            raise ValueError("assertion citation table drift")
        parsed, raw, error = call(url, ASSERTION_PROMPT, item["payload"], 8192)
        row, audit = freeze_question(original[qid], index, parsed if not error else None)
        return row, {"question_id": qid, **audit, "raw": raw, "error": error,
                     "sent": len(index), "available": item["available"]}

    frozen, stats, reasons, per_question = {}, Counter(), Counter(), []
    with (folder / "conditions.jsonl").open("x", encoding="utf-8") as records, (
            folder / "assertion_receipts.jsonl").open("x", encoding="utf-8") as receipts, (
            ThreadPoolExecutor(max_workers=WORKERS)) as pool:
        for row, audit in pool.map(one, proposed):
            qid = row["question_id"]
            n = len(row["conditions"])
            frozen[qid] = row
            split = [p for p in audit["parents"] if p["atomic_check"] == "compound"]
            reasons.update(audit["rejected"])
            stats.update(calls=1, conditions=n, below_three=n < 3, errors=bool(audit["error"]),
                         restricted=audit["sent"] < audit["available"], split_parents=len(split),
                         split_proposed=sum(p["proposed"] for p in split),
                         split_retained=sum(p["accepted"] for p in split),
                         parents_without_child=sum(not p["accepted"] for p in audit["parents"]))
            per_question.append({"question_id": qid, "v2": len(original[qid]["conditions"]), "v3": n})
            emit(records, row)
            emit(receipts, audit)
            print(json.dumps({"assertion_done": stats["calls"], "error": audit["error"]}), flush=True)
    summary = dict(stats, rejected=sum(reasons.values()), rejected_by_reason=dict(reasons),
                   per_question=per_question,
                   frozen_sha256=sha256((folder / "conditions.jsonl").read_bytes()).hexdigest())
    dump(folder / "assertions.json", summary)
    return frozen


def read_v3(folder, original):
    frozen = {r["question_id"]: r for r in rows(folder / "conditions.jsonl")}
    if frozen.keys() != original.keys():
        raise ValueError("frozen v3 is incomplete")
    for qid, row in frozen.items():
        content = {k: v for k, v in row.items() if k != "content_sha256"}
        if (row["version"] != VERSION or row["v2_content_sha256"] != original[qid]["content_sha256"] or
                row["content_sha256"] != freeze_digest(content)):
            raise ValueError("frozen v3 identity mismatch")
    return frozen


def judge_all(url, output, grouped, conditions, outcomes, *, planned=None):
    chunked = {tid: blocks(stages) for tid, stages in grouped.items()}
    jobs = [(tid, number, block, conditions[outcomes[tid]["question_id"]])
            for tid, group in chunked.items() for number, block in enumerate(group, 1)]
    if planned is not None and len(jobs) != planned:
        raise ValueError("sample block plan disagrees with budget")

    def one(job):
        tid, number, block, spec = job
        claims = spec["conditions"]
        parsed, raw, error = call(url, JUDGE_PROMPT, payload(claims, block), 6144)
        checks, count = check_verdicts(claims, block, parsed if not error else None)
        return {"trajectory_id": tid, "question_id": spec["question_id"], "block": number,
                "conditions_sha256": spec["content_sha256"], "raw": raw, "error": error,
                "verdicts": checks, "counts": count}

    responses = defaultdict(list)
    totals = Counter()
    with (output / "judge_receipts.jsonl").open("x", encoding="utf-8") as receipts, (
            ThreadPoolExecutor(max_workers=WORKERS)) as pool:
        for result in pool.map(one, jobs):
            totals.update(calls=1, errors=bool(result["error"]))
            totals.update(result["counts"])
            responses[result["trajectory_id"]].append(result["verdicts"])
            emit(receipts, result)
            if totals["calls"] % 10 == 0 or totals["calls"] == len(jobs):
                print(json.dumps({"judge_done": totals["calls"], "total": len(jobs),
                                  "errors": totals["errors"]}), flush=True)
    result = {}
    for tid, chunks in chunked.items():
        qid = outcomes[tid]["question_id"]
        claims = conditions[qid]["conditions"]
        decisions, picks = merge_verdicts(claims, responses[tid])
        audits = {}
        for claim, decision in zip(claims, decisions, strict=True):
            cid = claim["id"]
            rule = audit_rule_first(claim, chunks)
            rule_unit = rule["unit_id"] if rule else None
            judge_unit = decision["first_supported"]
            comparison = ("both" if rule is not None and judge_unit is not None else "judge_only"
                          if judge_unit is not None else "rule_only" if rule is not None else "neither")
            totals[decision["status"]] += 1
            totals[comparison] += 1
            totals["same_first"] += comparison == "both" and rule_unit == judge_unit
            audits[cid] = {"comparison": comparison, "rule_unit": rule_unit,
                           "rule_passage_id": rule["id"] if rule else None, "verdict": picks.get(cid)}
        result[tid] = {"question_id": qid, "decisions": decisions, "audits": audits}
    with (output / "merged.jsonl").open("x", encoding="utf-8") as file:
        for tid, row in result.items():
            emit(file, {"trajectory_id": tid, **row})
    return result, totals


def run_pilot(args):
    qs, old, outcomes = training(args.root)
    plan = read(args.inputs / "plan.json")
    if plan["tids"] != [r["trajectory_id"] for r in read(args.legacy / "plan.json")["samples"]]:
        raise ValueError("wrong legacy sample")
    grouped = stage_rows(args.root, plan["tids"])
    count = sum(len(blocks(s)) for s in grouped.values())
    if count != plan["pilot_requests"] or len(qs) != plan["assertion_requests"] or count + len(qs) > BUDGET:
        raise ValueError("pilot admission failed")
    check_service(args.url)
    args.out.mkdir(mode=0o700, exist_ok=False)
    dump(args.out / "run_identity.json", {**plan, "model": MODEL, "max_context": CONTEXT})
    frozen = freeze_all(args.url, args.out, args.inputs, old)
    _, totals = judge_all(args.url, args.out, grouped, frozen, outcomes, planned=count)
    decision = gate(totals["valid_refs"], totals["attempted_refs"], totals["rule_only"])
    summary = dict(totals, gate=decision, trajectories=len(grouped),
                   rule_only=totals["rule_only"], valid_refs=totals["valid_refs"],
                   attempted_refs=totals["attempted_refs"])
    dump(args.out / "pilot_summary.json", summary)
    print(json.dumps({"pilot": summary}), flush=True)


def ledger_all(output, grouped, judged, conditions, qs, outcomes, outcome_rows):
    by_qid = defaultdict(list)
    for r in outcome_rows:
        if isinstance(r["correct"], bool):
            by_qid[r["question_id"]].append(r["correct"])
    rhos = {qid: mean(values) for qid, values in by_qid.items() if len(values) == 8}
    costs = [s["generated_tokens"] + sum(e["obs_tokens"] for e in s["tool_events"])
             for group in grouped.values() for s in group]
    scale = median(costs)
    distributions = defaultdict(Counter)
    groups = defaultdict(Counter)
    validation = Counter()
    with ExitStack() as stack:
        events, states, results = [stack.enter_context((output / name).open("x", encoding="utf-8"))
                                   for name in ("ledger_events.jsonl", "ledger_states.jsonl",
                                                "trajectory_results.jsonl")]
        for tid, stages in grouped.items():
            result = outcomes[tid]
            qid = result["question_id"]
            q = qs[qid]
            spec = conditions[qid]
            decisions = judged[tid]["decisions"]
            ledger = build_ledger(stages, spec["conditions"], decisions,
                                  evidence_docs=q["evidence_docs"], gold_docs=q["gold_docs"])
            # Only Judge verdicts above enter the ledger. Rule results are kept separately.
            utility = dry_run(ledger, rhos[qid], scale) if qid in rhos else []
            prepared = {row["unit_id"]: row for row in utility}
            c_new = sum(len(row["C_new"]) for row in ledger)
            docid = sum(len(row["C_new_docid"]) for row in ledger)
            if c_new != sum(row["status"] == "supported" for row in decisions):
                raise ValueError("rule or unverified evidence entered C_new")
            identity = {"trajectory_id": tid, "question_id": qid}
            ledger = [{**identity, **row, "dry_run": prepared.get(row["unit_id"])} for row in ledger]
            validation.update(validate_ledger(stages, ledger, expected_rho=rhos, cost_median=scale))
            for row in ledger:
                emit(states, row)
                emit(events, {k: row[k] for k in ("trajectory_id", "question_id", "unit_id", "C_new",
                                                 "C_new_docid", "z_pre", "z_pre_docid", "b_pre", "unit_cost",
                                                 "strict_repeat", "repeat_flags", "dry_run")})
            emit(results, {**result, "C_new": c_new, "C_new_docid": docid})
            outcome = "no_submission" if not result["submitted"] else "correct" if result["correct"] else "incorrect"
            for label in ("all", outcome, result["terminal_status"]):
                groups[label].update(n=1, C_new=c_new, DocID=docid)
                distributions[label][c_new] += 1
    return {"validation": dict(validation), "cost_median": scale, "groups": {
        k: dict(v, mean_C_new=v["C_new"] / v["n"], mean_DocID=v["DocID"] / v["n"])
        for k, v in groups.items()}, "distributions": {k: dict(v) for k, v in distributions.items()}}


def run_full(args):
    pilot = read(args.pilot / "pilot_summary.json")
    live_gate = gate(pilot["valid_refs"], pilot["attempted_refs"], pilot["rule_only"])
    if not live_gate["passed"] or live_gate != pilot["gate"]:
        raise ValueError("pilot did not meet both frozen gates")
    check_service(args.url)
    qs, old, outcomes = training(args.root)
    conditions = read_v3(args.pilot, old)
    grouped = stage_rows(args.root, outcomes)
    args.out.mkdir(mode=0o700, exist_ok=False)
    dump(args.out / "run_identity.json", {**read(args.pilot / "run_identity.json"), "trajectories": 399,
                                         "frozen_sha256": sha256((args.pilot / "conditions.jsonl").read_bytes()).hexdigest()})
    judged, totals = judge_all(args.url, args.out, grouped, conditions, outcomes)
    outcome_rows = rows(args.root / "supplement-m1-192125" / "trajectory_results.jsonl")
    # The supplementary outcome recheck is already frozen in the 399 M2 rows.
    outcome_rows = [outcomes.get(row["trajectory_id"], row) for row in outcome_rows]
    metrics = ledger_all(args.out, grouped, judged, conditions, qs, outcomes, outcome_rows)
    dump(args.out / "full_summary.json", dict(totals, trajectories=399, ledger=metrics))
    print(json.dumps({"full": dict(totals, trajectories=399, ledger=metrics)}), flush=True)


def main():
    command = ArgumentParser(description=__doc__)
    command.add_argument("mode", choices=("prepare", "pilot", "full"))
    for key in ("root", "inputs", "pilot", "legacy", "model-path", "out"):
        command.add_argument(f"--{key}", type=Path)
    command.add_argument("--url")
    args = command.parse_args()
    {"prepare": prepare, "pilot": run_pilot, "full": run_full}[args.mode](args)


if __name__ == "__main__":
    main()
