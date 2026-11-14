"""Measure reversible Judge extraction encoding on archived native trajectories."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer

from ledger_grpo.browsecomp_adapter import adapt_trajectory
from ledger_grpo.client import _BASE, extraction_request
from ledger_grpo.pipeline import analyze_trajectory


def read(path):
    return json.loads(path.read_bytes())


def expand(payload):
    """Decode without relying on the original observations or text table."""
    by_id, evidence = {}, []
    for item in payload["evidence"]:
        record = item.copy()
        if "text_ref" in record:
            record["text"] = by_id[record.pop("text_ref")]["text"]
        by_id[record["evidence_id"]] = record
        evidence.append(record)
    turn = payload["turn"].copy()
    turn["observations"] = [{k: v for k, v in by_id[identity].items() if k != "turn_id"}
                            for identity in turn.pop("observation_refs")]
    return dict(payload, turn=turn, evidence=evidence)


class Capture:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.counts = Counter()
        self.system_tokens = {}

    def extract(self, payload):
        full_prompt, full = extraction_request(payload)
        compact_prompt, compact = extraction_request(payload, compact=True)
        if expand(compact) != full:
            raise ValueError("compacted prefix is not fully reversible")
        self.counts["extract_calls"] += 1
        self.counts["evidence_entries"] += len(full["evidence"])
        self.counts["text_aliases"] += sum("text_ref" in row for row in compact["evidence"])
        self.counts["duplicate_turn_observations"] += len(full["turn"]["observations"])
        for name, prompt, value in (("full", full_prompt, full), ("compact", compact_prompt, compact)):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False)
            system = _BASE+prompt
            if name not in self.system_tokens:
                self.system_tokens[name] = len(self.tokenizer.encode(system, add_special_tokens=False))
            estimate = len(self.tokenizer.encode(body, add_special_tokens=False))+self.system_tokens[name]
            self.counts[name+"_bytes"] += len(body.encode())+len(system.encode())
            self.counts[name+"_content_tokens"] += estimate
            self.counts[name+"_max_content_tokens"] = max(self.counts[name+"_max_content_tokens"], estimate)
        return {"facts": []}

    def check(self, kind, payload):
        return {"verdict": "uncertain", "evidence_refs": [], "rationale": "offline encoding audit"}


def combine(target, source):
    for key, value in source.items():
        if key.endswith("_max_content_tokens"):
            target[key] = max(target[key], value)
        else:
            target[key] += value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    rollout, scored = args.run/"train-P0", args.run/"scored"
    questions = {str(row["query_id"]): row["question"] for row in read(rollout/"sample_manifest.json")["selected"]}
    constraints = read(scored/"CONSTRAINTS.json")
    batch = scored/"NATIVE_BATCH.json"
    samples = read(batch)["trajectories"]
    if len(samples) != 32 or len({row["id"] for row in samples}) != 32:
        raise ValueError("expected the original frozen training batch")
    totals, by_task, rows = Counter(), defaultdict(Counter), []
    for native in samples:
        tid, qid = native["id"], str(native["query_id"])
        original = (rollout/"trajectories"/tid/"trajectory.json").read_bytes()
        trace, observed = adapt_trajectory(json.loads(original), questions[qid], constraints[qid],
                                           outcome=int(native["reward"]))
        if any(observed[key] != native[key] for key in ("id", "query_id", "segments", "terminal")):
            raise ValueError("audit is not bound to the original native trajectory")
        capture = Capture(tokenizer)
        report = analyze_trajectory(trace, judge=capture)
        if not report["qa"]["parse_ok"] or capture.counts["extract_calls"] != len(trace["turns"]):
            raise ValueError("did not verify every original extraction prefix")
        combine(totals, capture.counts)
        combine(by_task[qid], capture.counts)
        rows.append({"sample_id": tid, "task_id": qid, "trajectory_sha256": hashlib.sha256(original).hexdigest(),
                     **capture.counts})
    report = {"scope": "Same frozen training trajectories, offline extraction payloads, no model judgement.",
              "token_counter": "Qwen3.5-9B tokenizer, sum of user and system message contents; no template overhead",
              "ledger_replay": "Actual prefix observations with no new extracted semantic facts. Both encodings share one ledger.",
              "training_batch_sha256": hashlib.sha256(batch.read_bytes()).hexdigest(), "totals": totals,
              "by_task": by_task, "rows": rows}
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, ensure_ascii=False, allow_nan=False)
    print(json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
