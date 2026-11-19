
"""Orchestrate full M2 around the original v6.1 generation and v6 Judge."""

from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import sys

from context import Budget, Ranking, choose
from embed import dump
from prepare_full import SPLIT_SHA, digest, read, train_selection
from rules import cleanup, failed_slots, outcome_label, resolve

JUDGE_HASH = "8eb23007afa2dc25632569e89a66236a42e114246bb7fb995d6cd22b0fa532d0"
SOURCES = {
    "judge_v61/pipeline.py": "e8aeadc9c6fdd83839e3ce713ceb8c60b330c70a042bf39b68fbbcfd535e42d1",
    "judge_v61/run_v61.py": "12c71a15ad5a1e76929c311648bb4d278f50a17488f3f51826dac7ce89e7ad00",
    "judge_v6/judgement.py": "ef168f7cb7b96218a97547e2dfc8587b61c21aa593c69b71e7fc4680c973e1d4",
    "v6_prompts": "834a79a9d07bed62a43e04cfd0e65a63f120f72985b7e28ec846fbec917442c1",
}


def frozen(args):
    prompt_file = args.root / "judge-v6-192949/results/private_prompts.json"
    files = {key: (args.v61 if key.startswith("judge_v61") else args.v6) / key
             for key in SOURCES if key != "v6_prompts"}
    files["v6_prompts"] = prompt_file
    if {key: digest(path) for key, path in files.items()} != SOURCES:
        raise ValueError("v6.1 sources do not match the frozen hashes")
    sys.path[:0] = [str(args.v61 / "judge_v61"), str(args.v4 / "judge_v4")]
    import run_v61 as old
    import pipeline
    import prepare
    import pilot

    prompts = read(prompt_file)
    judge = old.JUDGE_PROMPT
    if prompts["judge"] != judge or sha256(judge.encode()).hexdigest() != JUDGE_HASH:
        raise ValueError("frozen Judge prompt changed")
    first = prompts["first"] + pipeline.SUBJECT_RULE
    repair = first + old.REPAIR_PROMPT + pipeline.REPAIR_RULE
    dump(args.out / "fingerprints.json", {**SOURCES, "judge_prompt": JUDGE_HASH,
         "first_prompt": sha256(first.encode()).hexdigest(), "repair_prompt": sha256(repair.encode()).hexdigest()})
    return old, pipeline, prepare, pilot, first, repair


def loading(args):
    receipt = read(args.prep / "PREP.json")
    questions_path, docs_path = (args.prep / name for name in ("questions.json", "documents.json"))
    if (receipt["heldout_decoded"] != 0 or receipt["split_sha256"] != SPLIT_SHA
            or receipt["question_sha256"] != digest(questions_path)
            or receipt["document_sha256"] != digest(docs_path)):
        raise ValueError("training input receipt mismatch")
    questions, docs = read(questions_path), read(docs_path)
    train, heldout, _ = train_selection(args.root)
    if questions.keys() != train or questions.keys() & heldout:
        raise ValueError("full run may only use the 664 training questions")
    return questions, docs, receipt


def emit(path, rows):
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def journal(path, jobs, run, *, workers=24):
    """Persist each finished request, including errors, before moving to the next phase."""
    path.mkdir(mode=0o700, exist_ok=True)
    result = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        requests = {}
        for key, job in jobs.items():
            target = path / f"{key}.json"
            if target.exists():
                result[key] = read(target)
            else:
                requests[pool.submit(run, key, job)] = key
        for future in as_completed(requests):
            key = requests[future]
            result[key] = future.result()
            dump(path / f"{key}.json", result[key])
            if len(result) % 20 == 0 or len(result) == len(jobs):
                print(json.dumps({"phase": path.name, "done": len(result), "total": len(jobs)}), flush=True)
    return {key: result[key] for key in jobs}


def truncation(qid, phase, before, after, blocks, assertion_id=None):
    return {"query_id": qid, "phase": phase, "assertion_id": assertion_id,
            "original_tokens": before, "kept_tokens": after, "block_ids": [b["id"] for b in blocks]}


def assertion_inputs(questions, documents):
    return {qid: {"query_id": qid, "question": q["question"], "reference_answers": q["answers"],
                  "evidence_documents": [{"docid": docid, "text": documents[docid]} for docid in q["evidence_docs"]]}
            for qid, q in questions.items()}


def retained_docs(docids, blocks):
    keep = {docid: [] for docid in docids}
    for block in blocks:
        keep[block["docid"]].append(block)
    return [{"docid": docid, "text": "\n\n".join(b["text"] for b in
             sorted(keep[docid], key=lambda b: int(b["id"].rsplit(":", 1)[1])))} for docid in docids]


def call_result(driver, url, prompt, body, max_tokens):
    parsed, raw, error = driver.call(url, prompt, body, max_tokens)
    return {"parsed": parsed if not error else None, "raw": raw, "error": error}


def generate(args, questions, documents, old, driver, first, repair, budget, ranks):
    inputs = assertion_inputs(questions, documents)
    vectors = ranks.queries("first")

    def reduce(qid, phase, prompt, body):
        original = budget.size(prompt, body)
        if original + 8192 + 512 <= driver.CONTEXT:
            return body, None
        docids = questions[qid]["evidence_docs"]
        order = ranks.rank(docids, vectors[qid])

        def selected(blocks):
            return {**body, "evidence_documents": retained_docs(docids, blocks)}

        tokens, blocks = choose(order, lambda blocks: budget.size(prompt, selected(blocks)), document_ids=docids)
        return selected(blocks), truncation(qid, phase, original, tokens, blocks)

    def request(qid, body):
        selected, cut = reduce(qid, "assertion", first, body)
        return {**call_result(driver, args.url, first, selected, 8192), "cut": cut}

    first_rows = journal(args.out / "assertions", inputs, request)
    original = {qid: row["parsed"] for qid, row in first_rows.items()}
    marks, jobs = old.repair_targets(inputs, original)

    def fix(qid, body):
        selected, cut = reduce(qid, "repair", repair, body)
        attempts = [call_result(driver, args.url, repair, selected, 8192)]
        if not old.usable_repair(attempts[-1]["parsed"]):
            attempts.append(call_result(driver, args.url, repair, selected, 8192))
        return {"attempts": attempts, "cut": cut}

    repairs = journal(args.out / "repairs", jobs, fix)
    rejected, cleaned, records = [], [], {}
    for qid, row in first_rows.items():
        checked = marks[qid]
        _, _, conditions = old.initial_parts(row["parsed"])
        if checked["record"]:
            rejected.append(old.event(qid, "mark_record", None, checked["record"], row["parsed"] or row["raw"]))
        for slot, issues in checked["claims"].items():
            rejected.append(old.event(qid, "mark", slot, issues, conditions[slot]))
        attempts = repairs.get(qid, {}).get("attempts", [])
        repair_response = attempts[-1]["parsed"] if attempts else None
        if len(attempts) > 1:
            rejected.append(old.event(qid, "repair_retry", None, ["repair_response_unusable"],
                                      attempts[0]["raw"], attempts[-1]["raw"]))
        record, changes = old.reconcile(qid, inputs[qid]["question"], row["parsed"], checked, repair_response,
                                        exhausted=qid in jobs and not old.usable_repair(repair_response))
        record, audit = cleanup(qid, record, questions[qid]["answers"])
        records[qid] = record
        rejected.extend(changes)
        cleaned.extend(audit)
    cuts = [v["cut"] for rows in (first_rows, repairs) for v in rows.values() if v["cut"]]
    dump(args.out / "records.json", records)
    dump(args.out / "assertion_cuts.json", cuts)
    emit(args.out / "rejected.jsonl", rejected)
    emit(args.out / "cleanup.jsonl", cleaned)
    dump(args.out / "generation_counts.json", {"assertion_calls": len(first_rows),
         "repair_calls": sum(len(row["attempts"]) for row in repairs.values()),
         "assertion_errors": sum(bool(row["error"]) for row in first_rows.values()),
         "cleanup": dict(Counter(row["reason"] for row in cleaned)),
         "initial_or_repair_flagged": dict(Counter(row["phase"] for row in rejected))})


def gold_plan(args, questions, documents, records, pipeline, prepare, v4, old, budget):
    queries, oversize = [], {}
    for qid, question in questions.items():
        passages = prepare.passages(v4, documents, question)
        record = records[qid]
        size = budget.size(old.JUDGE_PROMPT, pipeline.build_payload(record, passages))
        if size + 6144 + 512 <= CONTEXT_LIMIT:
            continue
        oversize[qid] = size
        names = {entity["var"]: entity["name"] for entity in record["entities"]}
        for index, claim in enumerate(record["conditions"]):
            queries.append({"id": f"{qid}-{index}", "text": f'{names[claim["subject"]]} {claim["claim"]}'})
    dump(args.out / "gold_oversize.json", oversize)
    dump(args.out / "gold_queries.json", queries)
    print(json.dumps({"phase": "gold_plan", "overflow_questions": len(oversize), "overflow_claim_queries": len(queries)}),
          flush=True)


def judge(args, old, pipeline, driver, record, passages):
    payload = pipeline.build_payload(record, passages)
    attempts, sets = [], []
    for _ in range(2):
        response = call_result(driver, args.url, old.JUDGE_PROMPT, payload, 6144)
        raw = response["parsed"]
        decisions = old.check_verdicts(record["conditions"], passages, raw)
        sets.append(decisions)
        attempts.append({**response, "invalid_slots": sorted(failed_slots(decisions))})
        empty_parse_failure = (not record["conditions"] and
                               (not isinstance(raw, dict) or not isinstance(raw.get("verdicts"), list)))
        if not attempts[-1]["invalid_slots"] and not empty_parse_failure:
            break
    merged = resolve(sets[0], sets[1] if len(sets) > 1 else [])
    return merged, attempts


def block_passages(v4, question, blocks):
    by_label = {key: set(question[key + "_docs"]) for key in ("gold", "evidence")}
    result = []
    for index, block in enumerate(blocks, 1):
        pid, docid = f"g{index}", block["docid"]
        result.append({"id": pid, "unit_id": index, "docid": docid, "text": block["text"],
                       "labels": [label for label, ids in by_label.items() if docid in ids],
                       "sentences": v4.sentences(block["text"], pid)})
    return result


def judge_gold(args, questions, documents, records, old, pipeline, prepare, v4, budget, ranks):
    oversized = read(args.out / "gold_oversize.json")
    vectors = ranks.queries("gold", args.out / "gold_embed") if read(args.out / "gold_queries.json") else {}
    work = {f"{qid}-full": (qid, None) for qid in questions if qid not in oversized}
    work.update({f"{qid}-{index}": (qid, index) for qid in oversized
                 for index, _ in enumerate(records[qid]["conditions"])})
    work.update({f"{qid}-empty": (qid, None) for qid in oversized if not records[qid]["conditions"]})

    def assess(key, job):
        qid, index = job
        record, question = records[qid], questions[qid]
        cut = None
        if qid not in oversized:
            passages = prepare.passages(v4, documents, question)
        elif index is None:
            passages = []
            tokens = budget.size(old.JUDGE_PROMPT, pipeline.build_payload(record, []))
            cut = truncation(qid, "gold", oversized[qid], tokens, [])
        else:
            claim = record["conditions"][index]
            record = {**record, "conditions": [claim]}
            docids = list(dict.fromkeys(question["gold_docs"] + question["evidence_docs"]))
            blocks = ranks.rank(docids, vectors[key])

            def size(chosen):
                return budget.size(old.JUDGE_PROMPT, pipeline.build_payload(record, block_passages(v4, question, chosen)))

            tokens, keep = choose(blocks, size)
            passages = block_passages(v4, question, keep)
            original = budget.size(old.JUDGE_PROMPT, pipeline.build_payload(
                record, prepare.passages(v4, documents, question)))
            cut = truncation(qid, "gold", original, tokens, keep, claim["id"])
        decisions, attempts = judge(args, old, pipeline, v4.previous_driver, record, passages)
        verdicts = [{"query_id": qid, "assertion_id": row["id"], "status": outcome_label(row),
                     "reason": row["reason"], "not_supported_by_gold": row["status"] not in ("supported", "partial"),
                     "citations": old.sources_for_judge(row, passages, gold=True)} for row in decisions]
        return {"attempts": attempts, "verdicts": verdicts, "cut": cut}

    return journal(args.out / "gold", work, assess)


CONTEXT_LIMIT = 131_072


def main():
    parser = ArgumentParser()
    parser.add_argument("phase", choices=("generate", "plan", "settle"))
    for name in ("root", "prep", "embedding", "v4", "v6", "v61", "out", "model"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--url")
    args = parser.parse_args()
    old, pipeline, prepare, v4, first, repair = frozen(args)
    questions, docs, receipt = loading(args)
    budget, ranks = Budget(args.model), Ranking(args.embedding)
    if args.phase == "generate":
        v4.previous_driver.check_service(args.url)
        generate(args, questions, docs, old, v4.previous_driver, first, repair, budget, ranks)
    else:
        records = read(args.out / "records.json")
        if args.phase == "plan":
            gold_plan(args, questions, docs, records, pipeline, prepare, v4, old, budget)
        else:
            v4.previous_driver.check_service(args.url)
            from settlement import settle
            gold = judge_gold(args, questions, docs, records, old, pipeline, prepare, v4, budget, ranks)
            settle(args, questions, records, receipt, gold, old, pipeline, v4)


if __name__ == "__main__":
    main()
