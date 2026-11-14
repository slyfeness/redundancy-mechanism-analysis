"""Validation for the normalized, task-independent trajectory contract."""
from copy import deepcopy
import hashlib
import json


# Unknown metadata is discarded at every level before an actor-visible object
# reaches a provider. The top-level privileged payload is stored separately.
TRAJECTORY_FIELDS = frozenset({
    "traj_id", "task_id", "task", "constraints", "turns", "outcome",
    "submitted_candidate", "complete", "response_mask", "budget_tokens", "privileged",
    "termination_reason", "recording_complete",
})
CONSTRAINT_FIELDS = frozenset({"cid", "text", "required", "kind", "artifact_id"})
TURN_FIELDS = frozenset({"turn_id", "token_start", "token_end", "action", "observations", "conclusion", "artifact"})
ACTION_FIELDS = frozenset({
    "kind", "query", "target_id", "fact_id", "candidate_id", "method", "decision_key",
    "independent_trial", "retry_justification",
})
OBSERVATION_FIELDS = frozenset({"evidence_id", "document_id", "source_id", "text", "version", "representation"})
ARTIFACT_FIELDS = frozenset({"artifact_id", "version", "operation", "passed"})


def _known_fields(value, allowed, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return {key: deepcopy(item) for key, item in value.items() if key in allowed}


def document_key(observation):
    digest = hashlib.sha256(observation["text"].encode("utf-8")).hexdigest()
    return json.dumps([observation.get("source_id", ""), observation["document_id"],
                       observation.get("version", ""), observation.get("representation", "fulltext"),
                       digest], ensure_ascii=False)


def validate_trajectory(raw):
    if not isinstance(raw, dict):
        raise ValueError("trajectory must be an object")
    trace = _known_fields(raw, TRAJECTORY_FIELDS, "trajectory")
    if trace.get("privileged") is not None and not isinstance(trace["privileged"], dict):
        raise ValueError("privileged must be a separate object or null")
    for name in ("traj_id", "task_id", "task"):
        if not isinstance(trace.get(name), str) or not trace[name].strip():
            raise ValueError(f"{name} must be a nonempty string")
    if type(trace.get("outcome")) is not int or trace["outcome"] not in (0, 1):
        raise ValueError("outcome must be an independently verified integer 0 or 1")
    mask = trace.get("response_mask")
    if not isinstance(mask, list) or not mask or any(type(v) not in (int, bool) or v not in (0, 1) for v in mask):
        raise ValueError("response_mask must contain only 0/1 and include the complete response axis")
    constraints = trace.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        raise ValueError("provide task constraints explicitly; no gold-derived requirements are inferred")
    ids = set()
    for index, raw_constraint in enumerate(constraints):
        c = _known_fields(raw_constraint, CONSTRAINT_FIELDS, "constraint")
        constraints[index] = c
        if not isinstance(c, dict) or not isinstance(c.get("cid"), str) or not c["cid"] or c["cid"] in ids:
            raise ValueError("constraint IDs must be unique nonempty strings")
        if not isinstance(c.get("text"), str) or not c["text"]:
            raise ValueError("constraint text is required")
        c.setdefault("required", True)
        c.setdefault("kind", "evidence")
        if type(c["required"]) is not bool or c["kind"] not in ("evidence", "artifact"):
            raise ValueError("invalid constraint required/kind")
        if "artifact_id" in c and (not isinstance(c["artifact_id"], str) or not c["artifact_id"]):
            raise ValueError("constraint artifact_id must be a nonempty string")
        if c["kind"] == "artifact" and not c.get("artifact_id"):
            raise ValueError("artifact constraints require artifact_id")
        ids.add(c["cid"])
    turns = trace.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("turns must be a nonempty list")
    evidence_ids, last_id, end = set(), -1, 0
    covered = [False] * len(mask)
    for turn_index, raw_turn in enumerate(turns):
        turn = _known_fields(raw_turn, TURN_FIELDS, "turn")
        turns[turn_index] = turn
        tid = turn.get("turn_id")
        start, stop = turn.get("token_start"), turn.get("token_end")
        if type(tid) is not int or tid <= last_id:
            raise ValueError("turn_id must increase strictly (IDs need not be contiguous)")
        if type(start) is not int or type(stop) is not int or not end <= start < stop <= len(mask):
            raise ValueError("turn token ranges must be ordered, disjoint, half-open and in bounds")
        if not any(mask[start:stop]):
            raise ValueError("each turn must contain at least one policy token")
        covered[start:stop] = [True] * (stop - start)
        last_id, end = tid, stop
        action = _known_fields(turn.get("action"), ACTION_FIELDS, "action")
        turn["action"] = action
        if not isinstance(action.get("kind"), str) or action["kind"] not in {"search", "read", "test", "write", "decision", "submit", "other"}:
            raise ValueError("invalid normalized action kind")
        for key in ("target_id", "fact_id", "candidate_id"):
            if key in action and action[key] is not None and (not isinstance(action[key], str) or not action[key]):
                raise ValueError(f"action.{key} must be a nonempty string or null")
        if action.get("target_id") is not None and action["target_id"] not in ids:
            raise ValueError("action target_id must refer to a task constraint")
        for key in ("query", "method", "decision_key", "retry_justification"):
            if key in action and not isinstance(action[key], str):
                raise ValueError(f"action.{key} must be a string")
        if "independent_trial" in action and type(action["independent_trial"]) is not bool:
            raise ValueError("action.independent_trial must be a boolean")
        observations = turn.setdefault("observations", [])
        if not isinstance(observations, list):
            raise ValueError("observations must be a list")
        for observation_index, raw_observation in enumerate(observations):
            if isinstance(raw_observation, dict) and raw_observation.get("privileged", False):
                raise ValueError("privileged evidence belongs outside actor-visible observations")
            obs = _known_fields(raw_observation, OBSERVATION_FIELDS, "observation")
            observations[observation_index] = obs
            for key in ("evidence_id", "document_id", "text"):
                if not isinstance(obs.get(key), str) or (key != "text" and not obs[key]):
                    raise ValueError(f"observation.{key} must be a string")
            if obs["evidence_id"] in evidence_ids:
                raise ValueError("evidence_id must be unique across the trajectory")
            obs.setdefault("source_id", "")
            obs.setdefault("version", "")
            obs.setdefault("representation", "fulltext")
            if any(not isinstance(obs[key], str) for key in ("source_id", "version", "representation")):
                raise ValueError("observation provenance fields must be strings")
            if obs["representation"] not in {"fulltext", "snippet"}:
                raise ValueError("observation representation must be fulltext or snippet")
            evidence_ids.add(obs["evidence_id"])
        turn.setdefault("conclusion", "")
        if not isinstance(turn["conclusion"], str):
            raise ValueError("turn.conclusion must be a string")
        artifact = turn.get("artifact")
        if artifact is not None:
            artifact = _known_fields(artifact, ARTIFACT_FIELDS, "artifact")
            turn["artifact"] = artifact
            if not isinstance(artifact, dict) or artifact.get("operation") not in ("write", "test", "submit"):
                raise ValueError("artifact operation must be write, test or submit")
            if not all(isinstance(artifact.get(k), str) and artifact[k] for k in ("artifact_id", "version")):
                raise ValueError("artifact identity and content version are required")
            if artifact["operation"] == "test" and type(artifact.get("passed")) is not bool:
                raise ValueError("artifact test requires a real boolean passed result")
            if "passed" in artifact and type(artifact["passed"]) is not bool:
                raise ValueError("artifact.passed must be a boolean")
        else:
            turn.pop("artifact", None)
    if any(m and not c for m, c in zip(mask, covered)):
        raise ValueError("all policy tokens must be mapped to a turn")
    trace.setdefault("complete", True)
    if type(trace["complete"]) is not bool:
        raise ValueError("complete must be a boolean")
    if "recording_complete" in trace and type(trace["recording_complete"]) is not bool:
        raise ValueError("recording_complete must be a boolean")
    if "termination_reason" in trace:
        if trace["termination_reason"] not in {"normal", "budget_exhausted", "tool_error", "format_error", "unknown"}:
            raise ValueError("invalid termination_reason")
        if trace["complete"] and trace["termination_reason"] != "normal":
            raise ValueError("normal completion conflicts with termination_reason")
        if trace["termination_reason"] == "budget_exhausted" and (trace["complete"] or trace["outcome"] != 0):
            raise ValueError("budget exhaustion must remain incomplete with outcome zero")
    trace.setdefault("submitted_candidate", None)
    if trace["submitted_candidate"] is not None and (not isinstance(trace["submitted_candidate"], str) or not trace["submitted_candidate"]):
        raise ValueError("submitted_candidate must be a nonempty string or null")
    last_submit = next((turn for turn in reversed(turns) if turn["action"]["kind"] == "submit"), None)
    actual_candidate = last_submit["action"].get("candidate_id") if last_submit else None
    if actual_candidate:
        if trace["submitted_candidate"] is not None and trace["submitted_candidate"] != actual_candidate:
            raise ValueError("submitted_candidate disagrees with the last actual submit action")
        # This is final scoring metadata; actor_view deliberately excludes it.
        trace["submitted_candidate"] = actual_candidate
    budget = trace.get("budget_tokens")
    if budget is not None and (type(budget) is not int or budget <= 0):
        raise ValueError("budget_tokens must be a positive integer")
    return trace


def actor_view(trace):
    """Whitelist, rather than redact, the information visible to the R judge."""
    visible = {key: deepcopy(trace[key]) for key in ("traj_id", "task_id", "task")}
    visible["constraints"] = [_known_fields(c, CONSTRAINT_FIELDS, "constraint") for c in trace["constraints"]]
    return visible
