"""Offline judge orchestration and turn-to-policy-token alignment."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math

from .schema import actor_view, validate_trajectory
from .ledger import CitationError, apply_delta, grounding_score, initial_ledger, record_turn, verify_citation
from .client import validate_submission_result


def _digest(trace):
    content = {k: v for k, v in trace.items() if k != "privileged"}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _submission_view(trace, ledger, resolved):
    """Use bound final-only parsing for scoring; never rewrite the prefix ledger."""
    view = deepcopy(trace)
    if resolved is not None:
        final = trace['turns'][-1]
        if (not isinstance(resolved, dict) or type(resolved.get('turn_id')) is not int
                or not trace['complete'] or final['action']['kind'] != 'submit'
                or resolved['turn_id'] != final['turn_id']):
            raise ValueError('resolved submission must refer to the last actual complete submit turn')
        parsed = validate_submission_result({k: v for k, v in resolved.items() if k != 'turn_id'}, final['conclusion'])
        view['submitted_candidate'] = parsed['candidate_id'] if parsed['status'] == 'resolved' else None
    candidate = view['submitted_candidate']
    facts = ledger.get('facts', [])
    matches = [fact for fact in facts if candidate is not None and fact.get('candidate_id') == candidate]
    # A new parser's unmatched literal value may be a representation mismatch.
    # It is unavailable grounding, not evidence of zero support or a new penalty.
    available = bool(matches) if resolved is not None else None
    grounding = None if resolved is not None and not available else grounding_score(view, ledger)
    metadata = {'submission_status': resolved['status'] if resolved is not None else 'not_resolved',
                'resolved_candidate_id': candidate if resolved is not None else None,
                'candidate_matching_fact_count': len(matches), 'candidate_total_fact_count': len(facts),
                'candidate_match_available': available}
    return view, grounding, metadata


def analyze_trajectory(raw, *, deltas=None, judge=None, rule_config=None):
    """Use replayed human/fixture deltas, or an explicitly configured local provider.

    Missing extraction is unknown, never evidence of no progress. Replayed deltas
    are not presented as independently validated semantic or causal ground truth.
    """
    from .rules import evaluate_turn, decision_summary
    trace = validate_trajectory(raw)
    registry = {o["evidence_id"]: dict(o, turn_id=t["turn_id"]) for t in trace["turns"] for o in t["observations"]}
    ledger = initial_ledger(trace)
    spans, history, errors = [], [], []
    citation_ok = True
    for turn in trace["turns"]:
        before = deepcopy(ledger)
        visible = {eid: obs for eid, obs in registry.items() if obs["turn_id"] <= turn["turn_id"]}
        try:
            if deltas is not None:
                delta = deepcopy(deltas.get(turn["turn_id"], deltas.get(str(turn["turn_id"]))))
            elif judge is not None:
                payload = dict(actor_view(trace), ledger=before, turn=deepcopy(turn), evidence=list(visible.values()))
                delta = judge.extract(payload)
                if not isinstance(delta, dict) or not isinstance(delta.get("facts"), list):
                    raise ValueError("judge extraction must return a facts list")
                for fact in delta["facts"]:
                    if fact.get("state") in ("supported", "refuted"):
                        for citation in fact.get("evidence", []):
                            verify_citation(citation, visible, turn["turn_id"])
                        if not hasattr(judge, "check"):
                            raise ValueError("live supported/refuted facts require a local support verifier")
                        verdict = judge.check("support", {"task": trace["task"], "constraints": trace["constraints"],
                                                          "fact": fact, "evidence": [visible[c["evidence_id"]] for c in fact["evidence"]]})
                        allowed = {c["evidence_id"] for c in fact["evidence"]}
                        refs = verdict.get("evidence_refs", [])
                        if verdict.get("verdict") != "yes" or not refs or not set(refs) <= allowed:
                            raise ValueError("support relation was not confirmed with valid citations")
            else:
                delta = None
            if delta is None:
                raise ValueError("no ledger extraction for this turn")
            # A semantic target is allowed only when the raw adapter did not specify it.
            target = delta.get("action_target", {})
            if not isinstance(target, dict) or set(target) - {"target_id", "fact_id", "candidate_id"}:
                raise ValueError("invalid action_target")
            if target.get("target_id") is not None and target["target_id"] not in {c["cid"] for c in trace["constraints"]}:
                raise ValueError("action_target refers to an unknown requirement")
            evaluated_turn = deepcopy(turn)
            for key, value in target.items():
                if not isinstance(value, str) or not value:
                    raise ValueError("action target values must be strings")
                if key in evaluated_turn["action"] and evaluated_turn["action"][key] != value:
                    raise ValueError("judge may not override the adapter's action target")
                evaluated_turn["action"][key] = value
            ledger = apply_delta(before, evaluated_turn, delta, registry)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            errors.append({"turn": turn["turn_id"], "kind": type(exc).__name__, "message": str(exc)})
            citation_ok &= not isinstance(exc, CitationError)
            evaluated_turn = turn
            ledger = record_turn(deepcopy(before), turn, None, before)
        # Only the current prefix is provided; outcome, gold and future candidate are absent.
        prefix = actor_view(trace)
        prefix["turns"] = [deepcopy(t) for t in trace["turns"] if t["turn_id"] <= turn["turn_id"]]
        if turn["action"]["kind"] == "submit":
            prefix["submitted_candidate"] = trace["submitted_candidate"]
        try:
            decisions = evaluate_turn(prefix, evaluated_turn, before, ledger, judge=judge, config=rule_config)
            for span in decisions:
                span["known_at"] = turn["turn_id"]
                span["prefix_reward_eligible"] = bool(span["reward_eligible"] and not errors and citation_ok)
            spans.extend(decisions)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            errors.append({"turn": turn["turn_id"], "kind": "RuleError", "message": str(exc)})
        history.append({"turn_id": turn["turn_id"], "revision_before": before["revision"],
                        "revision_after": ledger["revision"], "known": not any(e["turn"] == turn["turn_id"] for e in errors)})
    resolved_submission = None
    final = trace['turns'][-1]
    if (trace['complete'] and final['action']['kind'] == 'submit'
            and judge is not None and callable(getattr(judge, 'resolve_submission', None))):
        try:
            # This call happens only after ALL prefix/R decisions are complete.
            parsed = judge.resolve_submission({'task': trace['task'], 'constraints': deepcopy(trace['constraints']),
                                                'ledger': deepcopy(ledger), 'turn_id': final['turn_id'],
                                                'final_text': final['conclusion']})
            parsed = validate_submission_result(parsed, final['conclusion'])
            resolved_submission = dict(parsed, turn_id=final['turn_id'])
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            errors.append({'turn': final['turn_id'], 'kind': 'SubmissionResolutionError', 'message': str(exc)})
    scoring_trace, final_grounding, submission_metrics = _submission_view(trace, ledger, resolved_submission)
    for idx, span in enumerate(spans):
        span["sid"] = f"s{idx + 1}"
    report = {
        "schema_version": "1.0", "traj_id": trace["traj_id"], "task_id": trace["task_id"],
        "trace_digest": _digest(trace),
        "judge": {"mode": "replay" if deltas is not None else "local" if judge is not None else "unavailable",
                  "model": getattr(judge, "model", None), "privileged": False, "prompt_version": "ledger-v1.1-submission",
                  "r2_local_check": bool(getattr(rule_config, 'r2_local_check', False)),
                  "extraction_evidence_encoding": "text-ref-v1" if getattr(judge, "compact_evidence", False) else "full"},
        "ledger": ledger, "ledger_history": history, "spans": spans,
        "resolved_submission": resolved_submission,
        "decision": decision_summary(scoring_trace, ledger, config=rule_config),
        "metrics": {"turns": len(trace["turns"]), "gen_tokens": sum(trace["response_mask"]),
                    "tool_calls": sum(t["action"]["kind"] not in {"decision", "submit"} for t in trace["turns"]),
                    "grounding_score": final_grounding, **submission_metrics},
        "qa": {"parse_ok": not errors, "citations_verified": citation_ok, "errors": errors,
               "semantic_calibration": "not_established"},
    }
    if errors:
        for span in spans:
            span["reward_eligible"] = False
    return report


def build_process_inputs(raw, report, *, enable_artifact_d4=False, d4_weight=0.15):
    """Deterministic union of eligible spans; no tokenizer guesses or judge scores."""
    if type(d4_weight) not in (int, float) or not math.isfinite(d4_weight) or d4_weight < 0:
        raise ValueError("d4_weight must be finite and nonnegative")
    required = {"traj_id", "task_id", "trace_digest", "ledger", "spans", "qa"}
    if not isinstance(report, dict) or required - report.keys():
        raise ValueError("report requires traj_id, task_id, trace_digest, ledger, spans and qa")
    if not isinstance(report["ledger"], dict) or not isinstance(report["spans"], list) or not isinstance(report["qa"], dict):
        raise ValueError("report ledger/qa must be objects and spans must be a list")
    if {"parse_ok", "citations_verified"} - report["qa"].keys():
        raise ValueError("report qa requires parse_ok and citations_verified")
    trace = validate_trajectory(raw)
    if report["traj_id"] != trace["traj_id"] or report["task_id"] != trace["task_id"] or report["trace_digest"] != _digest(trace):
        raise ValueError("report is not bound to this exact normalized trajectory")
    turns = {t["turn_id"]: t for t in trace["turns"]}
    known_refs = {o["evidence_id"]: t["turn_id"] for t in trace["turns"] for o in t["observations"]}
    known_refs.update({f"turn:{tid}": tid for tid in turns})
    mask = trace["response_mask"]
    redundancy, deviations = [0.0] * len(mask), [0.0] * len(mask)
    qa = report.get("qa", {})
    valid = qa.get("parse_ok") is True and qa.get("citations_verified") is True
    _, grounding, _ = _submission_view(trace, report['ledger'], report.get('resolved_submission'))
    for span in report["spans"]:
        tids = span.get("turns")
        if not isinstance(tids, list) or not tids or any(type(t) is not int or t not in turns for t in tids):
            raise ValueError("span turns must be an explicit list of existing turn IDs")
        conf = span.get("confidence", 0)
        if type(conf) not in (int, float) or not math.isfinite(conf) or not 0 <= conf <= 1:
            raise ValueError("span confidence must be finite in [0,1]")
        refs = span.get("evidence_refs", [])
        if any(ref not in known_refs or known_refs[ref] > max(tids) for ref in refs):
            raise ValueError("span cites unavailable or future evidence")
        label = span.get("label")
        if not valid or span.get("abstain") or not span.get("reward_eligible"):
            continue
        if label not in {"R1", "R2"} and not (label == "D4" and enable_artifact_d4):
            continue
        if not refs:
            raise ValueError("reward-eligible spans must provide evidence references")
        for tid in set(tids):
            for index in range(turns[tid]["token_start"], turns[tid]["token_end"]):
                if mask[index]:
                    if label.startswith("R"):
                        redundancy[index] = max(redundancy[index], conf)
                    else:
                        deviations[index] = max(deviations[index], d4_weight * conf)
    # D4 has priority over an R label on the same token: local adjustment is applied once.
    for index, value in enumerate(deviations):
        if value:
            redundancy[index] = 0.0
    return {"traj_id": trace["traj_id"], "task_id": trace["task_id"], "outcome": trace["outcome"],
            "response_mask": mask, "redundancy": redundancy, "deviations": deviations,
            "grounding": grounding if grounding is not None else 0.0,
            "process_valid": valid and grounding is not None,
            "training_valid": trace["complete"],
            "redundant_fraction": sum(redundancy) / max(sum(mask), 1)}


def score_batch(traces, reports, *, config=None, control="targeted", seed=0, enable_artifact_d4=False,
                budget_failure_policy="exclude"):
    """Standalone CPU/GPU-neutral tensor interface for a rollout trainer."""
    import torch
    from .advantages import AdvantageConfig, compute_advantages, apply_control
    if len(traces) != len(reports) or not traces:
        raise ValueError("nonempty trajectories/reports must have matching length")
    cfg = config if config is not None else AdvantageConfig()
    if not isinstance(cfg, AdvantageConfig):
        raise ValueError("config must be an AdvantageConfig")
    cfg.validate()
    if budget_failure_policy not in {"exclude", "outcome_only"}:
        raise ValueError("budget_failure_policy must be exclude or outcome_only")
    identities = set()
    for trace in traces:
        if not isinstance(trace, dict) or any(key not in trace for key in ("traj_id", "task_id", "outcome", "response_mask")):
            raise ValueError("each trajectory requires traj_id, task_id, outcome and response_mask")
        identity = trace["traj_id"]
        if not isinstance(identity, str) or not identity:
            raise ValueError("traj_id must be a nonempty string")
        if identity in identities:
            raise ValueError(f"duplicate traj_id in batch: {identity}")
        identities.add(identity)
    rows = [build_process_inputs(t, r, enable_artifact_d4=enable_artifact_d4,
                                 d4_weight=cfg.deviation_weights["D4"]) for t, r in zip(traces, reports)]
    retained_budget = []
    if budget_failure_policy == "outcome_only":
        for trace, row in zip(traces, rows, strict=True):
            if (trace.get("termination_reason") == "budget_exhausted"
                    and trace.get("recording_complete") is True and trace["outcome"] == 0
                    and trace["complete"] is False and any(row["response_mask"])):
                row["training_valid"] = True
                row["process_valid"] = False
                retained_budget.append(row["traj_id"])
    width = max(len(row["response_mask"]) for row in rows)
    def padded(key):
        return torch.tensor([row[key] + [0] * (width - len(row[key])) for row in rows], dtype=torch.float32)
    result = compute_advantages(torch.tensor([r["outcome"] for r in rows], dtype=torch.float32),
                                [r["task_id"] for r in rows], padded("response_mask"), padded("redundancy"),
                                torch.tensor([r["grounding"] for r in rows]), padded("deviations"),
                                process_valid=torch.tensor([r["process_valid"] for r in rows]),
                                training_valid=torch.tensor([r["training_valid"] for r in rows]), config=cfg)
    result["effective_response_mask"] = padded("response_mask").bool() & result["valid_rows"].unsqueeze(1)
    result["advantages"] = apply_control(result["advantages"], result["trajectory_advantage"],
                                         result["effective_response_mask"], mode=control, seed=seed)
    result["returns"] = result["advantages"].clone()
    result["process_inputs"] = rows
    result["control"] = control
    result["config"] = asdict(cfg)
    result["budget_failure_policy"] = budget_failure_policy
    result["metrics"]["retained_budget_failures"] = retained_budget
    return result
