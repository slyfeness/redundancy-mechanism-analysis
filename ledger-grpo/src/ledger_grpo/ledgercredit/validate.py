"""Verify every native Stage ID against the unchanged training entry point."""

import math

import torch

from ..hf_native import native_turn_layout, prepare_native_records
from .stages import event_fed, observed_texts


def validate_stages(parsed):
    native = parsed["native"]
    layout = native_turn_layout(native)
    mask = layout["response_mask"]
    spans = parsed["stage_ids"]
    units = {stage["unit_id"]: stage for stage in parsed["stages"]}
    if len(units) != len(parsed["stages"]):
        raise ValueError("duplicate unit ID")
    if len(spans) != len(layout["spans"]):
        raise ValueError("native span count mismatch")
    if sum(stage["generated_tokens"] for stage in units.values()) != sum(mask):
        raise ValueError("generated token totals disagree")
    for stage in units.values():
        left, right = stage["gen_token_range"]
        ranges = sorted(stage["think_range"] + stage["call_range"] + stage["answer_range"])
        cursor = left
        for start, stop in ranges:
            if start != cursor or stop <= start or stop > right:
                raise ValueError("generated regions overlap or leave a gap")
            cursor = stop
        if cursor != right or right - left != stage["generated_tokens"]:
            raise ValueError("generated subregions disagree")
        if stage["span_id"] is None:
            if stage["generated_tokens"] != 0:
                raise ValueError("missing native span")
        else:
            ids = spans[stage["span_id"]]["stage_ids"]
            if ids[left:right] != [stage["unit_id"]] * (right-left):
                raise ValueError("unit-to-native Stage ID mismatch")
        if len(stage["call_range"]) != len(stage["tool_events"]):
            raise ValueError("shared tool stage lost a child event")
        for event in stage["tool_events"]:
            if (type(event.get("fed_to_model")) is not bool or event_fed(event) !=
                    (event["obs_tokens_source"] == "next_prompt")):
                raise ValueError("tool result visibility does not match the native prompt receipt")
    for row, span in zip(spans, layout["spans"], strict=True):
        ids = row["stage_ids"]
        if len(ids) != len(span["completion_ids"]):
            raise ValueError("stage_ids length disagrees with native span")
        active = [i for i, value in enumerate(ids) if value != -1]
        if active != span["action_offsets"] or any(ids[i] not in units for i in active):
            raise ValueError("stage_ids includes an observation or loses a model token")
    if not mask:
        return {"native_action_tokens": 0, "spans": 0}
    # Zero placeholders only exercise layout. They are never used as rewards
    # or advantages, and no model or optimizer is instantiated.
    score = {"advantages": torch.zeros((1, len(mask))),
             "effective_response_mask": torch.tensor([mask]),
             "valid_rows": torch.tensor([True]),
             "process_inputs": [{"traj_id": native["id"], "task_id": native["query_id"],
                                 "response_mask": mask}]}
    records = prepare_native_records([native], score)["records"]
    if len(records) != len(spans):
        raise ValueError("HF training record span count mismatch")
    for row, record in zip(spans, records, strict=True):
        if ([i for i, value in enumerate(row["stage_ids"]) if value != -1] != record["action_offsets"]
                or not bool(record["action_mask"].all())):
            raise ValueError("HF training positions disagree with stage_ids")
    return {"native_action_tokens": sum(mask), "spans": len(spans)}


def validate_ledger(stages, ledger_rows, *, expected_rho, cost_median):
    """Check serialized states and utility against the original Stage table."""
    previous_id, previous_state = None, None
    passed, missing, repeats = 0, 0, 0
    for stage, row in zip(stages, ledger_rows, strict=True):
        identity = row["trajectory_id"], row["question_id"], row["unit_id"]
        if identity != (stage["trajectory_id"], stage["question_id"], stage["unit_id"]):
            raise ValueError("Stage and ledger identities disagree")
        tid, qid, unit = identity
        before, after = row["L_pre"], row["L_post"]
        if tid == previous_id:
            if before != previous_state:
                raise ValueError("ledger snapshots are not continuous")
        elif (before["evidence"] or before["attempts"] or before["visibility"] or
              any(value["status"] != "unknown" for value in before["conditions"].values())):
            raise ValueError("initial ledger includes future information")
        used = before["execution"]["used_calls"]
        if before["visibility"] != list(range(1, unit)) or used != unit - 1:
            raise ValueError("ledger visibility or call sequence disagrees")
        supported = {key for key, value in before["conditions"].items() if value["status"] == "supported"}
        post = {key for key, value in after["conditions"].items() if value["status"] == "supported"}
        if len(set(row["C_new"])) != len(row["C_new"]) or post != supported | set(row["C_new"]) or (
                supported & set(row["C_new"])):
            raise ValueError("support regressed or was credited more than once")
        if any(after["conditions"][claim]["first_supported"] != unit for claim in row["C_new"]):
            raise ValueError("new support has the wrong first unit")
        if row["C_new"] and not any(observed_texts(event) for event in stage["tool_events"]):
            raise ValueError("a Stage without visible source text was credited")
        attempts = row["E_t"]["attempts"]
        for event, attempt in zip(stage["tool_events"], attempts, strict=True):
            if (event["event_id"] != attempt["event_id"] or attempt["fed_to_model"] is not event_fed(event) or
                    (not event_fed(event) and (attempt["repeat_flags"] or attempt["strict_repeat"] or
                                               attempt["new_docids"] or attempt["seen_hash"]))):
                raise ValueError("unfed return influences evidence or repetition accounting")
        cost = stage["generated_tokens"] + sum(event["obs_tokens"] for event in stage["tool_events"])
        unfed = sum(event["obs_tokens"] for event in stage["tool_events"] if not event_fed(event))
        doc_count = row["evidence_doc_count"]
        doc_seen = sum(doc["evidence_doc"] or doc["answer_doc"] for doc in before["evidence"].values())
        if (row["unit_cost"] != cost or row["b_pre"] != (20 - used) / 20 or
                row["unfed_return_tokens"] != unfed or
                row["z_pre_docid"] != (doc_seen / doc_count if doc_count else 0.0) or
                row["z_pre"] != len(supported) / max(1, len(before["conditions"]))):
            raise ValueError("Stage costs or pre-state ratios disagree")
        strict = any(attempt["strict_repeat"] for attempt in row["E_t"]["attempts"])
        if row["strict_repeat"] is not strict:
            raise ValueError("Stage repeat is not derived from its events")
        utility, rho = row["dry_run"], expected_rho.get(qid)
        if utility is None:
            if rho is not None:
                raise ValueError("utility omitted for a verified outcome group")
            missing += 1
        else:
            c = min(2.0, cost / max(1, cost_median))
            idle = c if strict else 0.0
            if (rho is None or utility["rho_x"] != rho or utility["c"] != c or utility["idle"] != idle
                    or not math.isclose(utility["u"], len(row["C_new"]) - 0.2 * rho * idle)):
                raise ValueError("utility disagrees with its independently checked inputs")
        passed += 1
        repeats += strict
        previous_id, previous_state = tid, after
    return {"validated_units": passed, "dry_run_missing": missing, "strict_repeat_units": repeats}
