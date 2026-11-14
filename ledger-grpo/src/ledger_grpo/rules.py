"""Conservative rule evaluation over an actor-visible ledger."""

from dataclasses import dataclass
import math
import re
import unicodedata

from .schema import document_key


@dataclass(frozen=True)
class RuleConfig:
    query_similarity_threshold: float = 1.0
    new_document_epsilon: float = 0.0
    saturation_count: int | None = None
    enable_artifact_d4: bool = False
    r2_local_check: bool = False

    def __post_init__(self):
        if type(self.enable_artifact_d4) is not bool:
            raise ValueError('enable_artifact_d4 must be boolean')
        if type(self.r2_local_check) is not bool:
            raise ValueError('r2_local_check must be boolean')
        for name in ("query_similarity_threshold", "new_document_epsilon"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if self.saturation_count is not None and (
            isinstance(self.saturation_count, bool)
            or not isinstance(self.saturation_count, int)
            or self.saturation_count < 2
        ):
            raise ValueError("saturation_count must be None or an integer >= 2")


_TOOL_KINDS = {"search", "read", "test", "write"}


def _normal_query(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _similar_query(left, right, threshold):
    left, right = _normal_query(left), _normal_query(right)
    if not left or not right:
        return False
    if threshold == 1.0:
        return left == right
    a, b = set(re.findall(r"\w+", left)), set(re.findall(r"\w+", right))
    return bool(a and b) and len(a & b) / len(a | b) >= threshold


def _observation_index(trajectory, through):
    return {
        observation["evidence_id"]: (turn["turn_id"], observation)
        for turn in trajectory.get("turns", [])
        if turn["turn_id"] <= through
        for observation in turn.get("observations", [])
        if observation.get("evidence_id")
    }


def _fact_refs(fact):
    return list(dict.fromkeys(
        list(fact.get("evidence_refs", []))
        + [e["evidence_id"] for e in fact.get("evidence", []) if e.get("evidence_id")]
    ))


def _span(trajectory, turn, label, target, rule_ids, refs, rationale, *, eligible=False, abstain=False):
    return {
        "sid": f"{trajectory['traj_id']}:{turn['turn_id']}:{label}:{target}",
        "turns": [turn["turn_id"]], "label": label, "target": target,
        "confidence": 0.0 if abstain else 1.0, "abstain": abstain,
        "rule_ids": rule_ids, "evidence_refs": list(dict.fromkeys(refs)),
        "rationale": rationale, "reward_eligible": eligible and not abstain,
    }


def _current_attempt(after, turn_id):
    return next((a for a in reversed(after.get("attempts", [])) if a.get("turn") == turn_id), None)


def _fulltext_upgrade(trajectory, turn):
    previous = [obs for t in trajectory.get("turns", []) if t["turn_id"] < turn["turn_id"] for obs in t.get("observations", [])]
    for observation in turn.get("observations", []):
        if observation.get("representation") != "fulltext":
            continue
        matching = [obs for obs in previous if (obs.get("source_id"), obs.get("document_id")) == (observation.get("source_id"), observation.get("document_id"))]
        if matching and not any(obs.get("representation") == "fulltext" for obs in matching):
            return True
    return False


def _no_new_information(trajectory, turn, before, after, config):
    action = turn.get("action", {})
    if action.get("independent_trial") or action.get("retry_justification"):
        return False
    attempt = _current_attempt(after, turn["turn_id"])
    observations = turn.get("observations", [])
    if not attempt or attempt.get("gain") is not False or not observations:
        return False
    if any(not obs.get("source_id") or not obs.get("document_id") for obs in observations):
        return False
    keys = set(attempt.get("document_keys", []))
    if not keys or len(keys - set(before.get("seen_documents", []))) / len(keys) > config.new_document_epsilon:
        return False
    if before.get("revision") != after.get("revision"):
        return False
    # An equivalent source returned under a fresh evidence ID is a provenance
    # refresh, not new information. Compare content and lineage, not reference IDs.
    index = _observation_index(trajectory, turn["turn_id"])
    def facts_signature(ledger):
        signatures = []
        for fact in ledger.get("facts", []):
            evidence = []
            for citation in fact.get("evidence", []):
                ref = citation.get("evidence_id")
                if ref not in index:
                    return None
                evidence.append((document_key(index[ref][1]), citation.get("quote", "")))
            signatures.append((fact.get("fid"), fact.get("cid"), fact.get("candidate_id"),
                               fact.get("statement"), fact.get("state"), tuple(sorted(set(evidence)))))
        return sorted(signatures)
    previous_facts, current_facts = facts_signature(before), facts_signature(after)
    if previous_facts is None or current_facts is None or previous_facts != current_facts:
        return False
    return not _fulltext_upgrade(trajectory, turn)


def _candidate_facts(ledger, candidate_id, cid):
    return [fact for fact in ledger.get("facts", []) if fact.get("cid") == cid and fact.get("candidate_id") == candidate_id]


def _constraint_supported(ledger, constraint, candidate_id):
    if constraint.get("kind") == "artifact":
        artifact = ledger.get("artifacts", {}).get(constraint.get("artifact_id"), {})
        version = artifact.get("submitted_version")
        return bool(
            version
            and version == artifact.get("last_verified_version")
            and version == artifact.get("last_tested_version")
            and artifact.get("last_test_passed") is True
            and (not artifact.get("current_version") or version == artifact["current_version"])
        )
    facts = _candidate_facts(ledger, candidate_id, constraint["cid"])
    if not candidate_id or any(fact.get("state") == "refuted" for fact in facts):
        return False
    return any(
        fact.get("state") == "supported"
        and _fact_refs(fact)
        and fact.get("independent_sources", 1) > 0
        for fact in facts
    )


def _r1(trajectory, turn, before, after, judge):
    action = turn.get("action", {})
    fid = action.get("fact_id")
    facts = [f for f in before.get("facts", []) if f.get("fid") == fid] if fid else []
    results = []
    index = _observation_index(trajectory, turn["turn_id"])
    current_refs = {obs["evidence_id"] for obs in turn.get("observations", []) if obs.get("evidence_id")}
    for fact in facts:
        refs = _fact_refs(fact)
        first = fact.get("first_supported_turn")
        if fact.get("state") != "supported" or first is None or first >= turn["turn_id"] or not refs or fact.get("independent_sources", 1) <= 0:
            continue
        if any(ref not in index or index[ref][0] >= turn["turn_id"] or not index[ref][1].get("source_id") for ref in refs):
            continue
        related = _candidate_facts(after, fact.get("candidate_id"), fact.get("cid"))
        if any(f.get("state") == "refuted" for f in related):
            continue
        rules = ["R1.prior_explicit_support", "R1.no_new_information"]
        if judge is None:
            results.append(_span(trajectory, turn, "R1", fid, rules, refs + sorted(current_refs), "Semantic target equivalence has not been checked.", abstain=True))
            continue
        payload = {"task": trajectory.get("task", ""), "action": dict(action), "fact": fact, "observations": turn.get("observations", []), "prior_evidence": [index[ref][1] for ref in refs]}
        verdict = judge.check("R1", payload)
        if isinstance(verdict, dict) and verdict.get("verdict") == "no":
            continue
        returned_refs = verdict.get("evidence_refs", []) if isinstance(verdict, dict) else []
        valid_refs = (
            isinstance(returned_refs, list)
            and all(isinstance(ref, str) and ref in index for ref in returned_refs)
            and bool(set(returned_refs) & set(refs))
            and bool(set(returned_refs) & current_refs)
        )
        confirmed = isinstance(verdict, dict) and verdict.get("verdict") == "yes" and valid_refs
        rationale = verdict.get("rationale", "") if isinstance(verdict, dict) else "Malformed semantic result."
        results.append(_span(trajectory, turn, "R1", fid, rules + ["R1.local_target_check"], returned_refs if valid_refs else refs + sorted(current_refs), rationale or "Local semantic check was inconclusive.", eligible=confirmed, abstain=not confirmed))
    return results


def evaluate_turn(trajectory, turn, before, after, *, judge=None, config=None):
    """Return diagnostics and eligible spans without mutating the input ledgers.

    Labels describe observed patterns, not counterfactual necessity. Citation
    quotes and ledger deltas must have passed the pipeline's strict validator.
    ``confidence=1`` denotes satisfied rule predicates, not calibrated odds.
    """
    config = config or RuleConfig()
    action = turn.get("action", {})
    kind, tid = action.get("kind"), turn["turn_id"]
    result = []
    if kind in {"search", "read", "test"} and _no_new_information(trajectory, turn, before, after, config):
        result.extend(_r1(trajectory, turn, before, after, judge))
        target = action.get("target_id")
        candidate = action.get("candidate_id")
        already_supported = any(f.get("cid") == target and f.get("state") == "supported" and (not candidate or f.get("candidate_id") == candidate) for f in before.get("facts", []))
        if target and not already_supported:
            for previous in reversed(before.get("attempts", [])):
                if previous.get("turn", tid) >= tid:
                    continue
                if (previous.get("kind"), previous.get("target_id"), previous.get("method") or "", previous.get("candidate_id")) != (kind, target, action.get("method") or "", candidate):
                    continue
                if _similar_query(previous.get("query"), action.get("query"), config.query_similarity_threshold):
                    current_refs = [obs["evidence_id"] for obs in turn.get("observations", []) if obs.get("evidence_id")]
                    prior_refs = [obs["evidence_id"] for t in trajectory.get("turns", []) if t["turn_id"] == previous["turn"] for obs in t.get("observations", []) if obs.get("evidence_id")]
                    refs = prior_refs + current_refs
                    rules = ["R2.same_target_method", "R2.repeated_query", "R2.no_new_information"]
                    eligible, abstain = True, False
                    if config.r2_local_check:
                        old_turn = next(t for t in trajectory['turns'] if t['turn_id'] == previous['turn'])
                        verdict = (judge.check('R2a', {'task':trajectory['task'], 'target':target,
                                                     'prior_query':previous['query'], 'current_query':action.get('query'),
                                                     'prior_evidence':old_turn.get('observations',[]),
                                                     'current_observations':turn.get('observations',[])})
                                   if judge is not None else {})
                        if verdict.get('verdict') == 'no':
                            break
                        cited = set(verdict.get('evidence_refs', []))
                        eligible = (verdict.get('verdict') == 'yes' and cited <= set(refs)
                                    and bool(cited & set(prior_refs)) and bool(cited & set(current_refs)))
                        abstain = not eligible
                        rules.append('R2.local_equivalence_check')
                    result.append(_span(trajectory, turn, "R2", target, rules, refs,
                                        "Repeated attempt on an unresolved requirement has no recorded gain.",
                                        eligible=eligible, abstain=abstain))
                    break

    if kind == "decision" and action.get("decision_key") and before.get("revision") == after.get("revision"):
        previous = next((d for d in reversed(before.get("decisions", [])) if d.get("key") == action["decision_key"] and d.get("turn", tid) < tid), None)
        if previous and previous.get("revision") == before.get("revision"):
            intervening_tools = any(previous["turn"] < t["turn_id"] <= tid and t.get("action", {}).get("kind") in _TOOL_KINDS for t in trajectory.get("turns", []))
            if not intervening_tools:
                result.append(_span(trajectory, turn, "R3", action["decision_key"], ["R3.repeated_decision", "R3.no_intervening_tool_or_gain"], [], "Repeated decision key without new ledger information; diagnostic only."))

    if kind == "submit":
        candidate = action.get("candidate_id") or trajectory.get("submitted_candidate")
        for constraint in after.get("constraints", trajectory.get("constraints", [])):
            if constraint.get("required", False) and constraint.get("kind", "evidence") == "evidence" and not _constraint_supported(after, constraint, candidate):
                result.append(_span(trajectory, turn, "D2", constraint["cid"], ["D2.unsupported_required_constraint"], [], "Submission has a required constraint without recorded support; grounding is scored separately."))

    # Refutation alone does not establish a causal error. These are audit
    # candidates tied to explicit action targets, never reward-eligible spans.
    for fact in before.get("facts", []):
        if fact.get("state") != "refuted":
            continue
        related = _candidate_facts(after, fact.get("candidate_id"), fact.get("cid"))
        if related and not any(f.get("state") == "refuted" for f in related):
            continue
        if kind in _TOOL_KINDS | {"submit"} and action.get("fact_id") == fact.get("fid"):
            result.append(_span(trajectory, turn, "D1", fact["fid"], ["D1.refuted_fact_used_by_action"], _fact_refs(fact), "Action explicitly reuses a recorded refuted premise; causal interpretation requires audit."))
        if kind in _TOOL_KINDS | {"submit"} and action.get("candidate_id") and action.get("candidate_id") == fact.get("candidate_id"):
            result.append(_span(trajectory, turn, "D3", fact["fid"], ["D3.refuted_candidate_used_by_action"], _fact_refs(fact), "Action targets a candidate with an unresolved refutation; conflict resolution intent requires audit."))

    submitted_artifact = turn.get("artifact", {})
    if submitted_artifact.get("operation") == "submit":
        aid = submitted_artifact.get("artifact_id")
        contract = any(c.get("required") and c.get("kind") == "artifact" and c.get("artifact_id") == aid for c in after.get("constraints", trajectory.get("constraints", [])))
        artifact = after.get("artifacts", {}).get(aid, {})
        verified, submitted = artifact.get("last_verified_version"), artifact.get("submitted_version")
        test_id = artifact.get("test_turn")
        test_event = next((t for t in trajectory.get("turns", []) if t["turn_id"] == test_id and t["turn_id"] < tid), None)
        test_artifact = test_event.get("artifact", {}) if test_event else {}
        submission_event = next((t for t in trajectory.get("turns", []) if t["turn_id"] == tid), None)
        submission_artifact = submission_event.get("artifact", {}) if submission_event else {}
        test_is_observed = (
            test_artifact.get("artifact_id") == aid and test_artifact.get("operation") == "test"
            and test_artifact.get("version") == verified and test_artifact.get("passed") is True
            and artifact.get("last_test_passed") is not False
        )
        submit_is_observed = (
            submission_artifact.get("artifact_id") == aid
            and submission_artifact.get("operation") == "submit"
            and submission_artifact.get("version") == submitted
        )
        if contract and verified and submitted and verified != submitted and test_is_observed and submit_is_observed:
            refs = [f"turn:{test_id}", f"turn:{tid}"]
            result.append(_span(trajectory, turn, "D4", aid, ["D4.required_artifact", "D4.verified_submission_mismatch"], refs, "Submitted artifact differs from the last verified version; this does not by itself prove task failure.", eligible=config.enable_artifact_d4))
    return result


def decision_summary(trajectory, ledger, config=None):
    """Describe remaining obligations; never issue a forced stop command."""
    config = config or RuleConfig()
    required = [c for c in ledger.get("constraints", trajectory.get("constraints", [])) if c.get("required", False)]
    candidate = trajectory.get("submitted_candidate")
    if not candidate:
        candidate = next((t.get("action", {}).get("candidate_id") for t in reversed(trajectory.get("turns", [])) if t.get("action", {}).get("candidate_id")), None)
    supported = [c["cid"] for c in required if _constraint_supported(ledger, c, candidate)]
    gaps = [c["cid"] for c in required if c["cid"] not in supported]
    conflicts = [f["fid"] for f in ledger.get("facts", []) if candidate and f.get("candidate_id") == candidate and f.get("state") == "refuted"]
    saturated = []
    if config.saturation_count is not None:
        for cid in gaps:
            attempts = [a for a in ledger.get("attempts", []) if a.get("target_id") == cid]
            tail = attempts[-config.saturation_count:]
            if len(tail) != config.saturation_count or any(a.get("gain") is not False or not a.get("document_keys") for a in tail):
                continue
            first = tail[0]
            if all((a.get("kind"), a.get("method") or "") == (first.get("kind"), first.get("method") or "") and _similar_query(a.get("query"), first.get("query"), config.query_similarity_threshold) for a in tail):
                saturated.append(cid)
    if conflicts:
        status, suggestion = "conflict", "review"
    elif required and not gaps:
        status, suggestion = "sufficient", "submit"
    elif saturated:
        status, suggestion = "saturated", "pivot"
    elif gaps:
        status, suggestion = "critical_gap", "continue"
    else:
        status, suggestion = "incomplete", "review"
    turns = trajectory.get("turns", [])
    last_gain = ledger.get("last_gain_turn")
    return {
        "status": status, "suggested_action": suggestion, "forced_stop": False,
        "submitted": any(t.get("action", {}).get("kind") == "submit" or t.get("artifact", {}).get("operation") == "submit" for t in turns),
        "candidate_id": candidate, "open_gaps_at_submit": gaps,
        "critical_open_gaps": gaps, "supported_constraints": supported,
        "conflicting_facts": conflicts, "saturated_gaps": saturated,
        "stop_type": status,
        "turns_after_last_gain": sum(t["turn_id"] > last_gain for t in turns) if last_gain is not None else None,
    }
