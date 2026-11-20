"""Build causal prefix snapshots from the exact previous sample and M2 ledger."""

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

from embed import dump
from prepare_full import SPLIT_SHA, read
from ledger_grpo.ledgercredit.stages import event_fed, search_records

THOUGHT_LIMIT = 1500


def rows(path):
    with path.open(encoding="utf-8") as source:
        yield from (json.loads(line) for line in source)


def tail(text, tokenizer, limit=THOUGHT_LIMIT):
    raw = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)
    if len(raw["input_ids"]) <= limit:
        return text, len(raw["input_ids"])
    for start, _ in raw["offset_mapping"][-limit:]:
        part = text[start:]
        size = len(tokenizer.encode(part, add_special_tokens=False))
        if size <= limit:
            return part, size
    raise ValueError("failed to recover the verbatim reasoning suffix")


def returned(event):
    if not event_fed(event) or event["status"] != "ok":
        return []
    hits = search_records(json.loads(event["return_text"]))
    return [{"docid": str(row["docid"]), "title": row["title"] if isinstance(row.get("title"), str)
             and row["title"].strip() else None} for row in hits]


def snapshot(stage, l_pre, claims, queries, repeats):
    confirmed = []
    for index, row in enumerate(claims, 1):
        record = l_pre["conditions"][row["id"]]
        if record["status"] == "supported":
            unit = record["first_supported"]
            if type(unit) is not int or not 1 <= unit < stage:
                raise ValueError("condition credit in snapshot is not strictly earlier")
            confirmed.append({"id": f"C{index}", "stage_id": unit, "role": row["subject"], "claim": row["claim"]})
    if any(e["stage_id"] >= stage for e in queries + repeats):
        raise ValueError("search or repetition in snapshot is not strictly earlier")
    return {"conditions": confirmed, "searches": list(queries), "strict_repeats": list(repeats)}


def assemble(args, budget, prompt, max_output):
    from transformers import AutoTokenizer

    records = read(args.fixed / "records.json")
    labels = read(args.prep / "questions.json")
    split = read(args.prep / "PREP.json")
    prior = read(args.previous / "plan.json")
    receipt = read(args.previous / "selection_counts.json")
    if (len(prior) != 40 or len({r["question_id"] for r in prior.values()}) != 10
            or receipt["heldout_decoded"] != 0 or split["split_sha256"] != SPLIT_SHA
            or split["heldout_decoded"] != 0 or len(labels) != 664):
        raise ValueError("previous probe scope or training receipt changed")
    selected = set(prior)
    tokenizer = AutoTokenizer.from_pretrained(args.actor, local_files_only=True, model_max_length=200_000)
    staged, ledger = defaultdict(list), defaultdict(dict)
    for stage in rows(args.root / "supplement-m1-192125/stages.jsonl"):
        if stage["trajectory_id"] in selected:
            staged[stage["trajectory_id"]].append(stage)
    for row in rows(args.fixed / "ledger_states.jsonl"):
        if row["trajectory_id"] in selected:
            ledger[row["trajectory_id"]][row["unit_id"]] = row
    refs = {r["trajectory_id"]: r for r in rows(args.root / "supplement-m1-192125/rollouts_ref.jsonl")
            if r["trajectory_id"] in selected}
    if refs.keys() != selected or staged.keys() != selected or ledger.keys() != selected:
        raise ValueError("missing native trace or M2 ledger for sealed probe")
    plan, metrics = {}, Counter()
    for tid, sample in prior.items():
        qid = sample["question_id"]
        record = records[qid]
        if qid not in split["round4_ids"] or len(record["conditions"]) < 2:
            raise ValueError("sealed sample contains a non-usable or out-of-scope question")
        entities = [{k: e[k] for k in ("var", "name", "role")} for e in record["entities"]]
        if entities != sample["entities"] or labels[qid]["question"] != sample["problem"]:
            raise ValueError("frozen question or entity table changed")
        blob = Path(refs[tid]["path"]).read_bytes()
        if sha256(blob).hexdigest() != refs[tid]["sha256"]:
            raise ValueError("original trajectory changed")
        trace = json.loads(blob)
        units = sorted(staged[tid], key=lambda e: e["unit_id"])
        if len(units) != len(trace["rounds"]) or len(units) != len(ledger[tid]):
            raise ValueError("Stage boundaries disagree with native trace")
        previous_search, previous_strict, frames, stats = [], [], [], {}
        for index, (unit, native) in enumerate(zip(units, trace["rounds"], strict=True), 1):
            if unit["unit_id"] != index or unit["question_id"] != qid:
                raise ValueError("non-contiguous or misassigned Stage")
            current = ledger[tid][index]
            prior_credit = current["L_pre"]
            if prior_credit["visibility"] != list(range(1, index)):
                raise ValueError("pre-Stage ledger includes future observations")
            history = snapshot(index, prior_credit, record["conditions"], previous_search, previous_strict)
            raw = native.get("raw_response") or {}
            choices = raw.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            thinking = message.get("reasoning") or message.get("reasoning_content") or ""
            thought, tokens = tail(thinking, tokenizer)
            assert thinking.endswith(thought) and tokens <= THOUGHT_LIMIT
            searches, ids = [], []
            for event in unit["tool_events"]:
                if event["tool"] != "search":
                    continue
                raw_args = event["args_raw"]
                query = (json.loads(raw_args) if isinstance(raw_args, str) else raw_args)["query"]
                expected = sample["queries"][len(previous_search)]
                if expected != {"id": len(previous_search) + 1, "text": query}:
                    raise ValueError("native search record differs from the sealed probe")
                sid = f"S{expected['id']}"
                hits = returned(event)
                searches.append(query)
                ids.append(sid)
                previous_search.append({"id": sid, "stage_id": index, "query": query, "returns": hits})
                metrics.update(hits=len(hits), known_titles=sum(h["title"] is not None for h in hits))
            if current["strict_repeat"]:
                previous_strict.append({"id": f"R{index}", "stage_id": index, "search_ids": ids})
            frames.append({"stage_id": index, "pre": history, "thought_tail": thought, "searches": searches})
            stats[str(index)] = {"C_new": current["C_new"], "program_strict_repeat": current["strict_repeat"]}
            metrics.update(stages=1, searches=len(searches), stages_with_thought=bool(thought),
                           cap_hits=tokens == THOUGHT_LIMIT)
        if len(previous_search) != len(sample["queries"]):
            raise ValueError("some previously sealed search calls are missing")
        payload = {"question": labels[qid]["question"], "entities": entities, "stages": frames}
        tokens = budget.size(prompt, payload)
        if tokens + max_output + 512 > 131_072:
            raise ValueError("trajectory input exceeds the single-call context")
        metrics["max_input_tokens"] = max(tokens, metrics["max_input_tokens"])
        plan[tid] = {"payload": payload, "metrics": stats, "outcome": sample["outcome"], "question_id": qid}
    if (metrics["stages"], metrics["searches"]) != (430, 464):
        raise ValueError("stage or query totals differ from the previous probe")
    dump(args.out / "plan.json", plan)
    metrics.update(trajectories=len(plan), heldout_decoded=0, psi=0)
    dump(args.out / "prep_counts.json", dict(metrics))
    print(json.dumps({"phase": "prepare", **metrics}), flush=True)
