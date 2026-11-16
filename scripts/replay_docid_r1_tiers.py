"""Re-evaluate DocID M3/M6 using the original request cache and pre-event state."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from redundancy_judge.adapters.model import ModelJudge
from redundancy_judge.common import atomic_json, identity, read_json
from redundancy_judge.judge_stage import judge_stage
from redundancy_judge.resolve_action_target import resolve_action_target


class CachedJudge(ModelJudge):
    def __init__(self, config, folder, freeze):
        super().__init__(config["judge"], config["prompt_dir"], folder / "model_cache", freeze, replay_only=True)
        self.opener = self
        self.cache_reads = Counter()

    def open(self, *_args, **_kwargs):
        raise RuntimeError("Network access is forbidden during cached replay")

    def ask_m3(self, step, payload, shape, event_id):
        response = super().ask_m3(step, payload, shape, event_id)
        if step == "intent":
            receipt = read_json(self.cache.parent / "m3_call_receipts" / (identity([event_id, step]) + ".json"))
            # The second request embeds the first response with its original wire field order.
            envelope = json.loads(receipt["raw_response"])
            original = json.loads(envelope["choices"][0]["message"]["content"])
            if original != response:
                raise ValueError(f"cached M3 intent differs from its raw response: {event_id}")
            response = original
        self.cache_reads[step] += 1
        return response


def label(row, name):
    return next(item for item in row["labels"] if item["label"] == name)


def restore_request_order(before, target):
    passage_ids = target["provided_passage_ids"]
    if not passage_ids:
        return before
    passages = before.get("evidence_passages", {})
    if len(passage_ids) != len(passages) or set(passage_ids) != {"P" + docid for docid in passages}:
        raise ValueError("archived request passage membership differs from the frozen ledger")
    return {**before, "evidence_passages": {pid[1:]: passages[pid[1:]] for pid in passage_ids}}


def replay(config):
    root = Path(config["source"])
    original = read_json(root / "config.json")
    folder = Path(original["run_dir"])
    freeze = read_json(folder / "run_manifest.json")["freeze"]
    judge = CachedJudge(original, folder, freeze)
    assert original["phase1_mode"] == "docid" and original["r1_record_only"]
    assert judge.prompt_sha256 == freeze["prompt_sha256"]
    prior = Counter()
    updated = Counter()
    changed = []
    sentinel = []
    skipped_verifications = 0
    tiers = {"high": [], "normal": []}
    expected = {}
    for verdict, event_ids in config["human_verdicts"].items():
        for eid in event_ids:
            if eid in expected:
                raise ValueError("human verdicts contain duplicate event IDs")
            expected[eid] = verdict
    previous_positives = set()
    example_types = {}
    bundles = sorted((folder / "bundles").glob("*.json"))
    for path in bundles:
        bundle = read_json(path)
        source = bundle["input_index"]
        trajectory = Path(source["path"])
        source_bytes = trajectory.read_bytes()
        assert sha256(source_bytes).hexdigest() == source["sha256"]
        reasoning = {r["round_id"]: r.get("reasoning_content") for r in json.loads(source_bytes)["rounds"]}
        task = bundle["task_specs"]
        snapshots = {row["event_id"]: row for row in bundle["ledger_snapshots"] if row["event_id"] is not None}
        events = {f'{source["trajectory_id"]}:{row["event_id"]}': row for row in bundle["tool_events"]}
        stages = {row["stage_id"]: row for row in bundle["stages"]}
        old_targets = {row["event_id"]: row for row in bundle["action_targets"]}
        for old in bundle["stage_judgments"]:
            eid = old["event_id"]
            event, snapshot = events[eid], snapshots[eid]
            old_target = old_targets[eid]
            before = restore_request_order(snapshot["before"], old_target)
            stage = {**stages[old["stage_id"]],
                     "m3_event_id": f'{source["trajectory_id"]}:{event["recorded_event_id"]}',
                     "m3_reasoning": reasoning[event["round_id"]]}
            if stage["parallel_group_id"] and stage["parse_status"] == "ok":
                stage["action"] = {key: event[key] for key in ("tool_name", "arguments", "call_id", "event_id",
                                                              "environment", "deterministic", "dispatch_time")}
            target = resolve_action_target(task, before, stage, judge,
                                           threshold=original.get("threshold", .8))
            result = judge_stage(task, before, snapshot["after"], stage, event,
                                 target, snapshot["delta"], judge, r1_record_only=True)
            prior_r1, now_r1 = label(old, "R1"), label(result, "R1")
            prior[prior_r1["decision"]] += 1
            updated[now_r1["decision"]] += 1
            if prior_r1["decision"] == "positive":
                previous_positives.add(eid)
            assert not now_r1["reward_eligible"] and result["price_label"] != "R1"
            for fixed_label in ("R2a", "R2b"):
                assert label(old, fixed_label) == label(result, fixed_label), eid
            for key in ("protections", "price_label", "charge_token_spans"):
                assert old[key] == result[key], (eid, key)
            diagnostics = result["diagnostics"]
            assert old["diagnostics"]["result_label"] == diagnostics["result_label"], eid
            assert old["diagnostics"]["r2a_subtype"] == diagnostics["r2a_subtype"], eid
            if old_target["entity"] is not None and target["entity"] is None:
                assert target["skip_reason"] == "new_candidate", eid
                sentinel.append(eid)
                skipped_verifications += bool(old_target["provided_passage_ids"])
            else:
                assert all(target[key] == value for key, value in old_target.items()
                           if key not in ("event_id", "stage_id")), eid
            if prior_r1["decision"] != now_r1["decision"]:
                assert eid in sentinel and now_r1["decision"] == "abstain", eid
                changed.append({"event_id": eid, "before": prior_r1["decision"], "after": now_r1["decision"]})
            if diagnostics["r1_confidence"]:
                tiers[diagnostics["r1_confidence"]].append(eid)
            for kind, positive in (("R2b", label(old, "R2b")["decision"] == "positive"),
                                   (diagnostics["r2a_subtype"], label(old, "R2a")["decision"] == "positive")):
                if positive and kind not in example_types:
                    example_types[kind] = {"event_id": eid, "search_query": event["arguments"]["query"]}
    assert len(bundles) == 400 and sum(prior.values()) == sum(updated.values()) == 5114
    assert previous_positives == set(expected)
    assert judge.cache_reads["intent"] == 5114
    assert judge.cache_reads["verification"] == 1848 - skipped_verifications
    summary = {"source_job": 187767, "events": sum(prior.values()), "baseline": prior, "replay": updated,
               "string_null_events": sorted(sentinel),
               "positive_to_abstain_due_to_null": sorted(row["event_id"] for row in changed if row["before"] == "positive"),
               "other_decision_changes": sorted((row for row in changed if row["before"] != "positive"),
                                                key=lambda row: row["event_id"]),
               "tiers": {}, "cache_hits": judge.cache_reads, "new_model_requests": 0, "r1_priced_events": 0}
    for tier, ids in tiers.items():
        verdicts = Counter(expected[eid] for eid in ids)
        summary["tiers"][tier] = {"count": len(ids), "event_ids": sorted(ids),
                                 "human_verdicts": {name: verdicts[name] for name in ("true", "borderline", "false")}}
    return summary, example_types


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    summary, examples = replay(read_json(args.config))
    atomic_json(args.config.parent / "r1_tiers_summary.json", summary)
    atomic_json(args.config.parent / "examples.private.json", examples)
