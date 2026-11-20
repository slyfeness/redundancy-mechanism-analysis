"""Run the three round4 offline controls and prepare one bound native smoke batch."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256
import json
from math import fsum, isfinite
from pathlib import Path
from statistics import fmean

from ledger_grpo.ledgercredit.m3m7 import Config, assign, exact_repeats, map_scores
from ledger_grpo.ledgercredit.stages import search_records
from ledger_grpo.native_capture import native_chat_segment

VARIANTS = {"v1": {}, "kappa_0_3": {"kappa": .3}, "beta_c_0": {"beta_c": 0.}}
METRICS = ("u", "A_out", "A_re", "A_st", "A")
LEVELS = (0, .05, .25, .5, .75, .95, 1.)
TYPES = ("all_correct", "mixed", "all_wrong")


def rows(path):
    with path.open(encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def emit(path, records):
    with path.open("x", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def key(row):
    return row["trajectory_id"], row["unit_id"]


def sealed_trace(reference):
    data = Path(reference["path"]).read_bytes()
    if sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError("round4 raw trace differs from sealed M1")
    return json.loads(data)


def group_by_track(records):
    data = defaultdict(list)
    for row in records:
        data[row["trajectory_id"]].append(row)
    return data


def diagnostics(stages, signals, raw, d):
    exact = exact_repeats([unit["tool_events"] for unit in stages])
    seen = set()
    for unit, signal, children, turn in zip(stages, signals, exact, raw["rounds"], strict=True):
        if key(unit) != key(signal) or unit["generated_tokens"] != signal["n_gen"]:
            raise ValueError("M1 stage and corrected M2 signals disagree")
        if sum(event["obs_tokens"] for event in unit["tool_events"]) != signal["n_ret"]:
            raise ValueError("tool cost differs from the verified signal table")
        choices = (turn.get("raw_response") or {}).get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        text = message.get("reasoning") or message.get("reasoning_content") or ""
        reasoning = (" ".join(text.split()).casefold(), signal["z_pre"])
        repeated = (reasoning in seen) if reasoning[0] else None
        if reasoning[0]:
            seen.add(reasoning)
        labels = d.get(key(signal))
        available = labels is not None and not labels["invalid"]
        yield {**signal, "I_N": int(bool(children)), "strict_repeat_children": children,
               "N2_exact_reasoning_repeat": repeated,
               "D": {field: labels.get(field, False) for field in
                     ("wrong_candidate", "F_new", "F_corrected")} if available else None,
               "F_new": 0, "F_corrected": 0}


def quantiles(data):
    values = sorted(data)
    if not values:
        return []
    result = []
    for q in LEVELS:
        offset = q * (len(values) - 1)
        base = int(offset)
        result.append(values[base] + (offset - base) * (values[min(base + 1, len(values) - 1)] - values[base]))
    return result


def summarize(scored, receipts):
    groups = defaultdict(list)
    for row in receipts.values():
        groups[row["query_id"]].append(row["rho"])
    qids = {qid: "all_correct" if values[0] == 1 else "all_wrong" if values[0] == 0 else "mixed"
            for qid, values in groups.items()}
    output = {}
    conservation, flips, nonfinite = [], 0, 0
    for track in group_by_track(scored).values():
        aout = track[0]["A_out"]
        n = sum(row["n_gen"] for row in track)
        if n:
            conservation.append(abs(fsum(row["A_re"] * row["n_gen"] for row in track) / n - aout))
        flips += sum(aout != 0 and row["A_re"] * aout <= 0 for row in track)
        nonfinite += sum(not isfinite(row[field]) for row in track for field in METRICS)
    for kind in TYPES:
        subset = [row for row in scored if qids[row["query_id"]] == kind]
        stage = [row for row in subset if row["unit_type"] == "stage"]
        repeat = [row["A"] for row in stage if row["I_N"]]
        no_gain = [row["A"] for row in stage if not row["I_N"] and not row["C_new"]]
        output[kind] = {
            "groups": sum(kind == value for value in qids.values()), "units": len(subset),
            "no_peer": sum(not r["peers"] for r in subset),
            "equal_peer": sum(bool(r["peers"]) and r["A_st"] == 0 for r in subset),
            "quantiles": {field: quantiles(row[field] for row in subset) for field in METRICS},
            "repeat": {"n": len(repeat), "mean_A": fmean(repeat) if repeat else None},
            "nonrepeat_no_progress": {"n": len(no_gain), "mean_A": fmean(no_gain) if no_gain else None},
        }
    return {"conservation_max": max(conservation, default=0), "sign_flips": flips,
            "nonfinite": nonfinite, "groups": output}


def choose_smoke(signals, config):
    groups = defaultdict(lambda: defaultdict(list))
    for row in signals:
        groups[row["query_id"]][row["trajectory_id"]].append(row)
    complete = [group for group in groups.values() if len(group) == config.G and
                0 < sum(track[0]["R"] for track in group.values()) < len(group)]
    if not complete:
        raise ValueError("no fully scored mixed round4 group")
    winner = min(complete, key=lambda group: (
        max(sum(r["n_gen"] + r["n_ret"] for r in track) for track in group.values()),
        sum(sum(r["n_gen"] + r["n_ret"] for r in track) for track in group.values())))
    return set(winner)


def smoke_batch(out, tids, records, config, references):
    import torch
    trajectories = []
    for tid in sorted(tids):
        raw = sealed_trace(references[tid])
        policy = [native_chat_segment(turn["raw_response"]) for turn in raw["rounds"]
                  if turn["response_received"] and turn["token_accounting"]["completion_token_ids"]]
        qid = next(row["query_id"] for row in records if row["trajectory_id"] == tid)
        trajectories.append({"id": tid, "query_id": qid, "segments": policy})
    native = out / "native-batch.json"
    write(native, {"trajectories": trajectories})
    score = map_scores(trajectories, [row for row in records if row["trajectory_id"] in tids],
                       config, input_binding={"native_batch_sha256": digest(native)})
    if int(score["effective_response_mask"].sum()) != sum(row["n_gen"] for row in records if row["trajectory_id"] in tids):
        raise ValueError("M7 action token count changed")
    torch.save(score, out / "scores.pt")


def requested_ids(event):
    if event["status"] != "ok":
        return []
    if event["tool"] == "search":
        data = search_records(json.loads(event["return_text"]))
        return [str(r["docid"]) for r in data]
    return [str(event["opened_docid"])] if event["opened_docid"] is not None else []


def document_prefixes(corpus, requested):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    found = {}
    domain = pa.array(sorted(requested), type=pa.string())
    for path in sorted(corpus.rglob("*.parquet")):
        for batch in pq.ParquetFile(path).iter_batches(columns=["docid", "text"], batch_size=2048):
            keep = pc.is_in(pc.cast(batch.column(0), pa.string()), value_set=domain)
            for row in batch.filter(keep).to_pylist():
                found[str(row["docid"])] = row["text"][:300]
    if set(found) != requested:
        raise ValueError("a sampled return could not bind to the local corpus")
    return found


def private_examples(scored, receipts, stages, records, corpus):
    tracks = group_by_track(scored)

    def streak(track):
        length = longest = 0
        for r in track:
            length = length + 1 if r["I_N"] else 0
            longest = max(longest, length)
        return longest

    winner = next(tid for tid, track in tracks.items() if track[0]["R"] and any(r["C_new"] for r in track))
    loser = next(tid for tid, track in tracks.items() if not track[0]["R"] and track[0]["submitted"]
                 and any(r["C_new"] for r in track))
    loop = max((tid for tid, track in tracks.items() if not track[0]["submitted"]),
               key=lambda tid: (streak(tracks[tid]), tid))
    if streak(tracks[loop]) < 2:
        raise ValueError("missing continuous repeat example")
    prefixes = document_prefixes(corpus, {docid for tid in (winner, loser, loop) for stage in stages[tid]
                                          for event in stage["tool_events"] for docid in requested_ids(event)})
    output = []
    for case, tid in (("correct", winner), ("incorrect", loser), ("loop", loop)):
        qid = tracks[tid][0]["query_id"]
        claims = {claim["id"]: claim["claim"] for claim in records[qid]["conditions"]}
        steps = []
        for signal, stage in zip(tracks[tid], stages[tid], strict=True):
            entry = {field: signal[field] for field in
                     ("unit_id", "unit_type", "C_new", "c", "I_N", "u", "A_re", "A_st", "A")}
            calls = []
            for event in stage["tool_events"]:
                args = event["args_raw"]
                args = json.loads(args) if isinstance(args, str) else args
                calls.append({"query": args.get("query"), "tool": event["tool"],
                              "returned": [{"docid": docid, "prefix_300": prefixes[docid]}
                                           for docid in requested_ids(event)]})
            entry.update(calls=calls, assertions=[{"id": cid, "text": claims[cid]} for cid in signal["assertion_ids"]])
            steps.append(entry)
        output.append({**receipts[tid], "case": case, "repeat_streak": streak(tracks[tid]), "units": steps})
    return output


def main():
    parser = ArgumentParser(description=__doc__)
    for name in ("root", "signals", "config", "corpus", "diagnostics", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    a = parser.parse_args()
    cfg = Config.read(a.config)
    prep = read(a.root / "m2-v61-full-prep-192982/PREP.json")
    records = read(a.root / "m2-v61-fix-192990/records.json")
    unusable = {qid for qid, record in records.items() if len(record["conditions"]) < cfg.minimum_assertions}
    source = list(rows(a.signals))
    if (prep["heldout_decoded"] or len(records) != 664 or len(unusable) != 54
            or len({r["trajectory_id"] for r in source}) != 399
            or {r["query_id"] for r in source} != set(prep["round4_ids"])):
        raise ValueError("frozen round4 training selection mismatch")
    eligible = group_by_track(r for r in source if r["query_id"] not in unusable)
    stages = group_by_track(r for r in rows(a.root / "supplement-m1-192125/stages.jsonl") if r["trajectory_id"] in eligible)
    refs = {r["trajectory_id"]: r for r in rows(a.root / "supplement-m1-192125/rollouts_ref.jsonl")
            if r["trajectory_id"] in eligible}
    d = {(r["trajectory_id"], r["stage_id"]): r["labels"] for r in rows(a.diagnostics)}
    prepared = []
    for tid, units in eligible.items():
        prepared.extend(diagnostics(stages[tid], units, sealed_trace(refs[tid]), d))
    a.out.mkdir(mode=0o700)
    summaries = {}
    for name, options in VARIANTS.items():
        scored, receipts = assign(prepared, replace(cfg, **options))
        summaries[name] = summarize(scored, receipts)
        variant = summaries[name]
        if variant["conservation_max"] >= 1e-9 or variant["sign_flips"] or variant["nonfinite"]:
            raise ValueError("offline formula acceptance failed")
        if name == "v1":
            main_rows, main_receipts = scored, receipts
    tids = choose_smoke(prepared, cfg)
    smoke_batch(a.out, tids, main_rows, cfg, refs)
    print(json.dumps({"phase": "smoke_ready", "trajectories": len(tids)}), flush=True)
    examples = private_examples(main_rows, main_receipts, stages, records, a.corpus)
    emit(a.out / "examples.jsonl", examples)
    emit(a.out / "scored_signals.jsonl", main_rows)
    counts = {"input_trajectories": 399, "trajectories": len(eligible), "units": len(prepared),
              "questions": len({r["query_id"] for r in prepared}), "incomplete_groups": len({
                  r["query_id"] for r in prepared if r["group_size"] != cfg.G}),
              "test_read": 0, "excluded_questions_round4": len({r["query_id"] for r in source if r["query_id"] in unusable}),
              "excluded_questions_all": len(unusable), "excluded_zero_all": sum(not val["conditions"] for val in records.values()),
              "strict_units": sum(r["I_N"] for r in prepared),
              "strict_changed_vs_frozen_m2": sum(r["I_N"] != r["strict_repeat"] for r in prepared),
              "D_covered": sum(r["D"] is not None for r in prepared),
              "N2_covered": sum(r["N2_exact_reasoning_repeat"] is not None for r in prepared),
              "N2_exact": sum(r["N2_exact_reasoning_repeat"] is True for r in prepared),
              "formula": summaries, "examples": len(examples)}
    write(a.out / "COUNTS.json", counts)
    print(json.dumps({key: value for key, value in counts.items() if key != "formula"}), flush=True)


if __name__ == "__main__":
    main()
