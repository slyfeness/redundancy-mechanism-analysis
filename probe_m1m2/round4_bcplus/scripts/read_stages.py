"""Extract Stage costs and rule flags from private actor records."""
import hashlib
import json

from native_stages import stage_costs
from rules import REPEAT_FLAGS, classify, normalize_query
from signals import add_progress


def parse_hits(value):
    if isinstance(value, dict):
        value = value.get("results", value.get("result"))
    if isinstance(value, list) and value and all(
        isinstance(row, dict) and row.get("type") == "text" and "text" in row for row in value
    ):
        parts = [json.loads(row["text"]) for row in value]
        return parse_hits(parts[0]) if len(parts) == 1 and isinstance(parts[0], list) else parse_hits(parts)
    if not isinstance(value, list) or any(not isinstance(row, dict) or "docid" not in row for row in value):
        raise ValueError("Expected structured search hits")
    ids = [str(row["docid"]) for row in value]
    if not all(identifier.isascii() and identifier.isdecimal() for identifier in ids):
        raise ValueError("Invalid corpus DocID")
    return ids


def outcome_record(task, folder, verdict_path, markers, evidence, gold, retry_path=None):
    row = {"trajectory_id": task["run_id"], "question_id": task["query_id"],
           "repetition_id": task["repetition_id"], "seed": task["seed"], "submitted": None,
           "correct": None, "termination_reason": "missing", "actor_calls": None, "tool_calls": None,
           "generated_tokens": None, "return_tokens": None, "unknown_return_stages": None,
           "terminal_unfed_stages": None, "unallocated_policy_tokens": None,
           "c_new_any": None, "c_new_open": None, "stage_accounting": "missing", "judge_source": None,
           "judge_first_failed": False, "judge_retry": 0, "trailing_open_rounds": 0}
    if not (folder / "TERMINAL.json").is_file():
        return row, []
    terminal = json.loads((folder / "TERMINAL.json").read_bytes())
    trace_data = (folder / "trajectory.json").read_bytes()
    assert hashlib.sha256(trace_data).hexdigest() == terminal["trajectory"]["sha256"]
    trace = json.loads(trace_data)
    assert trace["metadata"]["task"] == task
    status = terminal["status"]
    rounds = [r for r in trace["rounds"] if r["response_received"]]
    event_rows = sorted(trace["tool_events"], key=lambda e: (e["dispatch_utc"], e["dispatch_order"]))
    assert len(trace["rounds"]) == terminal["actor_calls"] <= 20
    assert len(event_rows) == terminal["search_calls"]
    row.update(submitted=status == "MODEL_FINAL_STOP", termination_reason=status,
               actor_calls=len(trace["rounds"]), tool_calls=len(event_rows),
               generated_tokens=sum(len(r["token_accounting"]["completion_token_ids"]) for r in rounds))
    if verdict_path.is_file():
        original_verdict = verdict_path.read_bytes()
        verdict = json.loads(original_verdict)
        assert (verdict["seed"], verdict["run_id"], verdict["status"]) == (task["seed"], task["run_id"], status)
        assert verdict["generated_tokens"] == row["generated_tokens"]
        row["judge_first_failed"] = verdict["judge"] == "gpt-oss-120b" and verdict["correct"] is None
        if retry_path is not None and retry_path.is_file():
            retry = json.loads(retry_path.read_bytes())
            assert row["judge_first_failed"] and retry["judge_retry"] in {1, 2}
            assert retry["prior_receipt_sha256"] == hashlib.sha256(original_verdict).hexdigest()
            assert (retry["seed"], retry["run_id"], retry["status"]) == (task["seed"], task["run_id"], status)
            row["judge_retry"] = retry["judge_retry"]
            verdict = retry
        row.update(correct=verdict["correct"], judge_source=verdict["judge"] or "terminal_rule")
    try:
        costs = stage_costs(trace, markers)
    except (ValueError, KeyError) as error:
        # Retain outcome signal and report the failure, even if Stage alignment is unavailable.
        row["stage_accounting"] = "unresolved_" + type(error).__name__
        return row, []
    assert costs["total_generated_tokens"] == row["generated_tokens"]
    response_rounds = {r["round_id"]: i for i, r in enumerate(rounds)}
    stages = []
    for event in event_rows:
        rid = event["round_id"]
        index = response_rounds[rid]
        parallel = len(rounds[index]["tool_calls"]) > 1
        stage_id = f"R{rid}:T{event['tool_ordinal']}" if parallel else f"R{rid}"
        try:
            args = json.loads(event["exact_arguments"])
        except (TypeError, ValueError):
            args = None
        raw = event["exact_result"]
        tool = event["tool_name"].rsplit("-", 1)[-1]
        if tool not in {"search", "open"} or not isinstance(args, dict):
            tool = "unknown"
            args = {}
        docids, docid, body_hash = [], None, f"unavailable:{event['event_id']}"
        query = args.get("query", "")
        valid = False
        try:
            value = json.loads(raw)
            mcp = event.get("raw_mcp_response")
            if isinstance(mcp, dict) and mcp.get("isError"):
                raise ValueError("Tool error")
            if tool == "search":
                docids = parse_hits(value)
                valid = isinstance(query, str) and bool(normalize_query(query))
            elif tool == "open" and isinstance(value, dict) and isinstance(value.get("text"), str):
                docid = str(args["docid"])
                docids = [docid]
                body_hash = hashlib.sha256(value["text"].encode()).hexdigest()
                valid = True
        except (ValueError, TypeError, KeyError):
            pass
        item = {"event_key": f"{task['run_id']}:{stage_id}", "trajectory_id": task["run_id"],
                "question_id": task["query_id"], "stage_id": stage_id, "round": rid, "tool": tool,
                "query": query, "docids": docids if valid else [], "docid": docid, "start": args.get("start", 0),
                "body_sha256": body_hash, "return_parsed": valid, "raw": raw,
                "b_before": (20 - index) / 20, **costs["stages"][stage_id]}
        visible = index + 1 < len(rounds)
        item["observation_visible"] = visible
        item["terminal_unfed"] = not visible
        if not visible:
            # No next received model prompt includes this completed tool return.
            item["obs_tokens"] = 0
        flags, matches = classify(item, stages)
        if not valid and tool == "search":
            flags = [flag for flag in flags if flag not in {"S_empty", "S_allseen"}]
        match_ids = set(matches.get("S_exact", ())) | set(matches.get("O_exact", ()))
        exact = [prior for prior in stages if prior["stage_id"] in match_ids and prior["return_parsed"]
                 and valid and prior["raw"] == raw]
        item.update(flags=flags, repeat_union=bool(set(flags) & REPEAT_FLAGS), strict_repeat=bool(exact),
                    strict_match_stage_id=exact[-1]["stage_id"] if exact else None,
                    strict_same_round_only=bool(exact) and all(prior["round"] == rid for prior in exact))
        stages.append(item)
    progress = add_progress(stages, evidence, gold)
    missing_costs = sum(stage["obs_tokens"] is None for stage in stages)
    row.update(return_tokens=sum(stage["obs_tokens"] for stage in stages) if not missing_costs else None,
               unknown_return_stages=missing_costs, terminal_unfed_stages=sum(s["terminal_unfed"] for s in stages),
               unallocated_policy_tokens=row["generated_tokens"] - sum(s["generated_tokens"] for s in stages),
               trailing_open_rounds=len(costs["trailing_open_rounds"]),
               c_new_any=progress["any"], c_new_open=progress["open"],
               stage_accounting="complete" if not missing_costs else "unresolved_return_tokens")
    assert row["unallocated_policy_tokens"] >= 0
    return row, stages
