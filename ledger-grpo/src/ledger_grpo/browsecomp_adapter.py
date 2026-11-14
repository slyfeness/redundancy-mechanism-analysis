"""BrowseComp native recorder adapter; no gold text enters process judging.

One native model call is one turn, including parallel tool calls. This is a
coarse call-level span, not an attribution to an individual parallel search.
"""
import hashlib
import json
import re
import unicodedata

from .schema import validate_trajectory


CONSTRAINT_PROMPT = """Extract independently verifiable requirements from the supplied task only.
Return {"clauses":["exact contiguous substring of task", ...]}.
Include the requested answer type and every factual/temporal/relational qualification.
Preserve negations and numerical bounds. Do not solve the task, invent requirements,
use background knowledge, or read any answer. Each clause must occur verbatim in task.
The clauses are an uncalibrated task projection, not verified semantic ground truth.
"""


def extract_constraints(question, judge):
    result = judge._request(CONSTRAINT_PROMPT, {"task": question})
    clauses = result.get("clauses")
    if (not isinstance(clauses, list) or not clauses or len(clauses) > 32
            or any(not isinstance(c, str) or not c.strip() or c not in question for c in clauses)
            or len(set(clauses)) != len(clauses)):
        raise ValueError("task constraint extraction failed its exact-quote contract")
    return [{"cid": f"c{i+1}", "text": clause, "required": True, "kind": "evidence"}
            for i, clause in enumerate(clauses)]


def canonical_candidate(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).strip(" *`\"'")


def submitted_candidate(content):
    # Only parse the actor's explicit answer line. No evaluator or gold fields.
    matches = re.findall(r"(?im)^\s*(?:\*\*)?Exact Answer\s*:(?:\*\*)?\s*(.+)$", content)
    return canonical_candidate(matches[-1]) if matches else None


def native_trajectory(raw, *, reward):
    task = raw["metadata"]["task"]
    segments = []
    for turn in raw["rounds"]:
        if not turn.get("response_received"):
            continue
        tokens = turn["token_accounting"]
        completion = tokens["completion_token_ids"]
        if not tokens["exact_prompt_token_ids_equal"] or completion is None:
            raise ValueError("native token identities are unavailable")
        if not completion:
            continue
        probs = turn["raw_response"]["choices"][0]["logprobs"]["content"]
        if len(probs) != len(completion):
            raise ValueError("native sampling probabilities do not cover actions")
        segments.append({"prompt_ids": tokens["prompt_token_ids"], "completion_ids": completion,
                         "vllm_logprobs": [item["logprob"] for item in probs]})
    return {"id": task["run_id"], "query_id": str(task["query_id"]),
            "terminal": raw["metadata"]["terminal_status"], "reward": reward, "segments": segments}


def _observations(event):
    """Use returned JSON content, not privileged corpus or supporting-document data."""
    try:
        returned = json.loads(event["exact_result"])
    except (TypeError, ValueError):
        returned = None
    eid = str(event["event_id"])
    if isinstance(returned, list) and all(isinstance(d, dict) and {"docid", "snippet"} <= d.keys() for d in returned):
        records = []
        for index, doc in enumerate(returned):
            if not isinstance(doc["snippet"], str):
                raise ValueError("document snippet must be visible text")
            docid, text = str(doc["docid"]), doc["snippet"]
            records.append({"evidence_id": f"e{eid}-d{index}", "document_id": docid,
                            "source_id": "browsecomp-corpus", "text": text,
                            "version": hashlib.sha256(text.encode()).hexdigest(), "representation": "snippet"})
        return records
    # Unknown/error tool results have no asserted provenance and cannot establish
    # independent corroboration or qualify as a known-source repeat.
    return [{"evidence_id": f"e{eid}-unparsed", "document_id": f"unknown:{eid}",
             "source_id": "", "text": str(event.get("exact_result", "")), "representation": "snippet"}]


def _recorded_search_response(event):
    result = event.get("raw_mcp_response")
    if not isinstance(result, dict) or result.get("isError") is not False:
        return False
    content = result.get("content")
    return (isinstance(event.get("exact_result"), str) and isinstance(content, list) and bool(content)
            and all(isinstance(block, dict) and block.get("type") == "text"
                    and isinstance(block.get("text"), str) for block in content))


def adapt_trajectory(raw, question, constraints, *, outcome):
    from .hf_native import native_turn_layout
    if type(outcome) is not int or outcome not in (0, 1):
        raise ValueError("outcome must come from a resolved independent verifier")
    expected_question = raw["metadata"]["task"].get("question_sha256")
    if expected_question is not None and hashlib.sha256(question.encode()).hexdigest() != expected_question:
        raise ValueError("question does not match the native task identity")
    native = native_trajectory(raw, reward=outcome)
    layout = native_turn_layout(native)
    observed = [r for r in raw["rounds"] if r.get("response_received")
                and r["token_accounting"]["completion_token_ids"]]
    if len(observed) != len(layout["turns"]):
        raise ValueError("round/native call count mismatch")
    events = {}
    for event in raw["tool_events"]:
        events.setdefault(event["round_id"], []).append(event)
    if not set(events) <= {row["round_id"] for row in observed}:
        raise ValueError("tool events have no corresponding native model call")
    turns = []
    final_candidate = None
    normal = native["terminal"] == "MODEL_FINAL_STOP"
    budget = native["terminal"] in {"CONTEXT_LIMIT_STOP", "SAFETY_CEILING_STOP", "GENERATION_LENGTH_STOP"}
    # Only fully recorded calls and successfully returned tools permit the
    # explicitly enabled budget-failure outcome path. Unknown/error stops do not.
    recording_complete = (all(r.get("response_received") is True or
                              (r.get("request_sent") is False and r.get("guard_intercepted") is True)
                              for r in raw["rounds"])
                          and all(_recorded_search_response(e) for e in raw["tool_events"]))
    for index, (row, position) in enumerate(zip(observed, layout["turns"], strict=True)):
        associated = sorted(events.get(row["round_id"], []), key=lambda e: e["tool_ordinal"])
        calls = row.get("tool_calls") or []
        call_ids = [c["id"] for c in calls]
        event_calls = [e["tool_call_id"] for e in associated]
        ordinals = [e["tool_ordinal"] for e in associated]
        if (len(set(call_ids)) != len(call_ids) or len(set(event_calls)) != len(event_calls)
                or len(set(ordinals)) != len(ordinals) or len(call_ids) != len(event_calls)
                or set(call_ids) != set(event_calls)):
            raise ValueError("native call and observed tool event identity mismatch")
        content = row.get("content") or ""
        action = {"kind": "decision"}
        if associated:
            queries, methods = [], []
            for event in associated:
                args = json.loads(event["exact_arguments"])
                methods.append(event["tool_name"])
                queries.append(args)
            # Order matters: changing the set/order is not an exact repeat.
            action = {"kind": "search" if all("search" in m.lower() for m in methods) else "other",
                      "query": json.dumps(queries, sort_keys=True, ensure_ascii=False),
                      "method": "+".join(methods)}
        elif normal and index == len(observed)-1:
            action = {"kind": "submit"}
            final_candidate = submitted_candidate(content)
            if final_candidate:
                action["candidate_id"] = final_candidate
        turns.append({"turn_id": row["round_id"], "token_start": position["token_start"],
                      "token_end": position["token_end"], "action": action,
                      "observations": [o for e in associated for o in _observations(e)],
                      "conclusion": content})
    result = {"traj_id": native["id"], "task_id": native["query_id"], "task": question,
              "constraints": constraints, "turns": turns, "outcome": outcome,
              "complete": normal, "submitted_candidate": final_candidate,
              "termination_reason": "normal" if normal else "budget_exhausted" if budget else "unknown",
              "recording_complete": recording_complete,
              "response_mask": layout["response_mask"], "budget_tokens": 20 * 10000}
    return validate_trajectory(result), native
