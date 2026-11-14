"""Descriptive costs, annotation audits, and paired task-cluster inference.

No model execution or third-party numerical dependencies. Missing measurements
remain missing; all costs, including failures, enter cost per success. Annotation
stages are descriptive observations, not independent inferential replicates.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


def _number(value: Any, name: str, *, positive: bool = False, upper: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result == 0) or (upper is not None and result > upper):
        raise ValueError(f"{name} is out of range or nonfinite")
    return result


def _validate_runs(rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each run must be a mapping")
        if not isinstance(row.get("task_id"), str) or not row["task_id"]:
            raise ValueError("task_id must be a nonempty string")
        if type(row.get("outcome")) not in (int, float, bool) or row["outcome"] not in (0, 1):
            raise ValueError("outcome must be 0 or 1")
        if type(row.get("complete")) is not bool:
            raise ValueError("complete must be boolean")
        _number(row.get("cost"), "cost")
        if row.get("budget") is not None:
            _number(row["budget"], "budget", positive=True)
        for key in ("gen_tokens", "tool_calls", "ctx_tokens"):
            if row.get(key) is not None:
                _number(row[key], key)
        if row.get("grounding_score") is not None:
            _number(row["grounding_score"], "grounding_score", upper=1)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _quantile(values: Sequence[float], fraction: float) -> float | None:
    """Linear interpolation at index (n-1)*fraction, including singleton data."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    weight = position - lower
    return (1 - weight) * ordered[lower] + weight * ordered[upper]


def _summary(values: Sequence[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean": _mean(values),
        "median": statistics.median(values) if values else None,
        "std": statistics.stdev(values) if len(values) >= 2 else None,
        "p90": _quantile(values, .9),
        "p95": _quantile(values, .95),
    }


def summarize_runs(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize runs, retaining availability and the task replication unit.

    accuracy/completion are run-weighted descriptive rates. Budget statistics
    use only rows with measured budgets; relative error is ABSOLUTE error
    abs(cost-budget)/budget. Excess is in cost units, conditional on cost>budget.
    within_task_cv averages sample-std/mean only across tasks with >=2 runs and
    strictly positive mean cost. Costs must use the same unit across rows.
    Empty denominators are None; coverage is zero for empty inputs.
    """
    _validate_runs(rows)
    n = len(rows)
    costs = [float(row["cost"]) for row in rows]
    successes = sum(int(row["outcome"]) for row in rows)
    budget_rows = [row for row in rows if row.get("budget") is not None]
    excesses = [float(row["cost"] - row["budget"]) for row in budget_rows if row["cost"] > row["budget"]]
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[row["task_id"]].append(float(row["cost"]))
    cvs = [statistics.stdev(values) / statistics.fmean(values)
           for values in by_task.values() if len(values) >= 2 and statistics.fmean(values) > 0]
    optional = {}
    for key in ("gen_tokens", "tool_calls", "ctx_tokens", "grounding_score"):
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        optional[key] = {**_summary(values), "coverage": len(values) / n if n else 0.0}
    return {
        "run_count": n,
        "task_count": len(by_task),
        "success_count": successes,
        "accuracy": successes / n if n else None,
        "completion_rate": sum(row["complete"] for row in rows) / n if n else None,
        "cost": _summary(costs),
        "cost_per_success": math.fsum(costs) / successes if successes else None,
        "budget_count": len(budget_rows),
        "budget_coverage": len(budget_rows) / n if n else 0.0,
        "over_budget_rate": len(excesses) / len(budget_rows) if budget_rows else None,
        "mean_relative_budget_error": _mean([abs(row["cost"] - row["budget"]) / row["budget"] for row in budget_rows]),
        "mean_excess_when_over": _mean(excesses),
        "within_task_cv": _mean(cvs),
        "within_task_cv_task_count": len(cvs),
        "optional_fields": optional,
    }


def _annotation_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, int, str], Mapping[str, Any]]:
    result = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each annotation must be a mapping")
        for key in ("task_id", "traj_id"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"annotation {key} must be a nonempty string")
        if type(row.get("turn_id")) is not int or row["turn_id"] < 0:
            raise ValueError("annotation turn_id must be a nonnegative integer")
        if row.get("label") not in {"R", "R1", "R2", "R3", "D", "D1", "D2", "D3", "D4"}:
            raise ValueError("annotation label must be R/D or a supported R/D subtype")
        if row.get("verdict") not in {"positive", "negative", "uncertain"}:
            raise ValueError("annotation verdict must be positive, negative, or uncertain")
        key = (row["task_id"], row["traj_id"], row["turn_id"], row["label"])
        if key in result:
            raise ValueError(f"duplicate annotation key: {key}")
        result[key] = row
    return result


def _classification(records: Sequence[tuple[str, str, str]], *, macro: bool = True) -> dict[str, Any]:
    confusion = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "abstain_positive": 0, "abstain_negative": 0}
    known = [(task, pred, gold) for task, pred, gold in records if gold != "uncertain"]
    for _, pred, gold in known:
        if pred == "uncertain":
            confusion[f"abstain_{gold}"] += 1
        elif gold == "positive":
            confusion["tp" if pred == "positive" else "fn"] += 1
        else:
            confusion["fp" if pred == "positive" else "tn"] += 1
    tp, fp, fn = confusion["tp"], confusion["fp"], confusion["fn"]
    missed = fn + confusion["abstain_positive"]
    task_ids = {task for task, _, _ in known}
    result = {
        "total_count": len(records),
        "sample_count": len(known),
        "task_count": len(task_ids),
        "uncertain_gold_count": len(records) - len(known),
        "confusion": confusion,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + missed) if tp + missed else None,
        "f1": 2 * tp / (2 * tp + fp + missed) if 2 * tp + fp + missed else None,
        "abstention_rate": (confusion["abstain_positive"] + confusion["abstain_negative"]) / len(known) if known else None,
    }
    if macro:
        per_task = [_classification([record for record in known if record[0] == task], macro=False) for task in sorted(task_ids)]
        result["macro_by_task"] = {
            name: _mean([item[name] for item in per_task if item[name] is not None])
            for name in ("precision", "recall", "f1", "abstention_rate")
        }
        result["macro_by_task"]["contributing_tasks"] = {
            name: sum(item[name] is not None for item in per_task)
            for name in ("precision", "recall", "f1", "abstention_rate")
        }
    return result


def evaluate_annotations(predicted: Sequence[Mapping[str, Any]], gold: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit pre-enumerated annotation units (task,traj,turn,label).

    Gold must enumerate negative as well as positive units: positive-only gold
    cannot estimate false positives. Keys must be unique. Missing predictions
    count as abstentions; unexpected prediction keys are rejected. Gold-uncertain
    units are counted but excluded from scoring. Recall/F1 count abstention on
    a gold positive as a missed detection. No stage-independent confidence
    interval is computed; task macro averages accompany pooled descriptions.
    This is aligned classification, not temporal-span overlap evaluation.
    """
    predictions = _annotation_index(predicted)
    truth = _annotation_index(gold)
    unexpected = predictions.keys() - truth.keys()
    if unexpected:
        raise ValueError(f"prediction keys absent from gold: {sorted(unexpected)}")
    labels: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    families: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for key, row in truth.items():
        verdict = predictions[key]["verdict"] if key in predictions else "uncertain"
        record = (row["task_id"], verdict, row["verdict"])
        labels[row["label"]].append(record)
        families[row["label"][0]].append(record)
    return {
        "alignment": "task_id,traj_id,turn_id,label",
        "gold_count": len(truth),
        "prediction_count": len(predictions),
        "missing_prediction_count": len(truth.keys() - predictions.keys()),
        "task_count": len({key[0] for key in truth}),
        "by_label": {label: _classification(records) for label, records in sorted(labels.items())},
        "by_family": {family: _classification(records) for family, records in sorted(families.items())},
    }


def paired_bootstrap(
    baseline_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    seed: int = 0,
    resamples: int = 1000,
) -> dict[str, Any]:
    """Equal-task-weight paired bootstrap; deltas are candidate minus baseline.

    First average repeated runs within each task, then resample matched TASKS
    with replacement, jointly for both metrics. Task sets and per-task sample
    counts must match exactly. If any sample_id is supplied, every row on both
    sides must supply it; unique (task_id,sample_id) sets must match. Without
    IDs, sample counts are checked but seed/run identity cannot be verified.
    Percentile 95% intervals use linear interpolation. One task produces a
    degenerate descriptive interval, not evidence of population certainty.
    """
    _validate_runs(baseline_rows)
    _validate_runs(candidate_rows)
    if not baseline_rows or not candidate_rows:
        raise ValueError("paired bootstrap requires nonempty samples")
    if type(seed) is not int or seed < 0 or type(resamples) is not int or resamples < 1:
        raise ValueError("seed must be nonnegative and resamples must be positive integers")
    groups = []
    for rows in (baseline_rows, candidate_rows):
        by_task: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            by_task[row["task_id"]].append(row)
        groups.append(by_task)
    baseline, candidate = groups
    if baseline.keys() != candidate.keys():
        raise ValueError("baseline and candidate task sets must match exactly")
    for task in baseline:
        if len(baseline[task]) != len(candidate[task]):
            raise ValueError(f"sample counts differ for task {task!r}")
    all_rows = list(baseline_rows) + list(candidate_rows)
    use_ids = any("sample_id" in row for row in all_rows)
    if use_ids:
        identities = []
        for rows in (baseline_rows, candidate_rows):
            keys = set()
            for row in rows:
                sample = row.get("sample_id")
                if not isinstance(sample, (str, int)) or isinstance(sample, bool) or sample == "":
                    raise ValueError("all paired rows must provide string/integer sample_id")
                key = (row["task_id"], sample)
                if key in keys:
                    raise ValueError("duplicate task/sample identity")
                keys.add(key)
            identities.append(keys)
        if identities[0] != identities[1]:
            raise ValueError("baseline and candidate sample identities must match")
    tasks = sorted(baseline)
    deltas = {"accuracy": [], "cost": []}
    for task in tasks:
        for name, key in (("accuracy", "outcome"), ("cost", "cost")):
            deltas[name].append(statistics.fmean(row[key] for row in candidate[task]) - statistics.fmean(row[key] for row in baseline[task]))
    samples: dict[str, list[float]] = {"accuracy": [], "cost": []}
    rng = random.Random(seed)
    n = len(tasks)
    for _ in range(resamples):
        indices = [rng.randrange(n) for _ in range(n)]
        for metric in samples:
            samples[metric].append(statistics.fmean(deltas[metric][i] for i in indices))
    return {
        "task_count": n,
        "run_count_per_arm": len(baseline_rows),
        "seed": seed,
        "resamples": resamples,
        "unit": "task_id",
        "weighting": "equal_task_after_within_task_mean",
        "sample_identity_verified": use_ids,
        **{f"{metric}_delta": {
            "estimate": statistics.fmean(deltas[metric]),
            "ci95": [_quantile(samples[metric], .025), _quantile(samples[metric], .975)],
        } for metric in samples},
    }


def deletion_category(original_success: bool, outcomes: Sequence[bool], guide_confounded: bool = False) -> str:
    """Classify four deletion repeats, not causal redundancy or necessity truth.

    A: original correct and at most one outcome change. B_plus: originally
    correct and >=3 changes; B_minus: originally wrong and >=3 changes. All
    other unconfounded cases are gray. Replacement work, multiple copies,
    and sampling uncertainty still require separate causal review.
    """
    if type(original_success) is not bool or type(guide_confounded) is not bool:
        raise ValueError("original_success and guide_confounded must be booleans")
    if len(outcomes) != 4 or any(type(value) is not bool for value in outcomes):
        raise ValueError("exactly four boolean deletion outcomes are required")
    if guide_confounded:
        return "confounded"
    changes = sum(value != original_success for value in outcomes)
    if original_success and changes <= 1:
        return "A"
    if changes >= 3:
        return "B_plus" if original_success else "B_minus"
    return "gray"


def audit_event_labels(cases, *, require_event_binding=False):
    """Separate human precision and the two deletion-based B+ denominators.

    A case must refer to one matched event and intervention. Four independently
    evaluated repeats of that intervention are required for deletion metrics.
    """
    counts = defaultdict(lambda: defaultdict(int))
    identities = set()
    for case in cases:
        identity = case['case_id'], case['label']
        if not isinstance(identity[0], str) or not identity[0]:
            raise ValueError('calibration requires a case identifier')
        repeats = case['deletions']
        if require_event_binding:
            trajectory, event_id = case.get('trajectory_sha256'), case.get('event_id')
            if (not isinstance(trajectory, str) or not re.fullmatch(r'[0-9a-f]{64}', trajectory)
                    or not isinstance(event_id, str) or not event_id):
                raise ValueError('calibration case lacks its original trajectory and tool event identity')
            if any(r['comparable'] is True and (r.get('intervention_scope') != 'single_tool_event'
                    or r.get('target_trajectory_sha256') != trajectory or r.get('target_event_id') != event_id)
                   for r in repeats):
                raise ValueError('comparable deletion must target the same single tool event')
            identity = trajectory, event_id, case['label']
        if identity in identities:
            raise ValueError('calibration requires unique event/label identities')
        identities.add(identity)
        label, verdict, human = case['label'], case['prediction'], case['human_verdict']
        if label not in {'R1','R2a','R2b'} or verdict not in {'positive','negative','uncertain'} or human not in {'redundant','necessary','uncertain'}:
            raise ValueError('invalid event calibration label or verdict')
        evaluated = case.get('prediction_evaluated', True)
        if type(evaluated) is not bool or (not evaluated and verdict != 'uncertain'):
            raise ValueError('unevaluated predictions must remain uncertain')
        scope = case.get('calibration_scope', 'calibration')
        if scope not in ('engineering', 'calibration'):
            raise ValueError('invalid event calibration scope')
        c = counts[label]
        c['cases'] += 1
        if scope == 'engineering':
            c['engineering_cases'] += 1
        c['abstentions'] += int(verdict == 'uncertain')
        if verdict == 'positive':
            c['marked'] += 1
            c['marked_human_reviewed'] += int(human != 'uncertain')
            c['marked_human_redundant'] += int(human == 'redundant')
        condition_ids = {r['condition_id'] for r in repeats}
        if (len(repeats) != 4 or len({r['repetition_id'] for r in repeats}) != 4
                or len(condition_ids) != 1 or not all(r['comparable'] is True for r in repeats)):
            c['unmatched_or_confounded'] += 1
            continue
        category = deletion_category(case['original_correct'], [r['correct'] for r in repeats],
                                     guide_confounded=case['guide_confounded'])
        c[category] += 1
        if category == 'B_plus' and not evaluated:
            c['bplus_unevaluated'] += 1
        if category != 'confounded' and verdict == 'positive':
            c['marked_deletion_comparable'] += 1
            c['marked_bplus'] += int(category == 'B_plus')
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None
    return {label: {'counts': dict(c),
                    'precision': ratio(c['marked_human_redundant'], c['marked_human_reviewed']),
                    'human_coverage_among_marked': ratio(c['marked_human_reviewed'], c['marked']),
                    'bplus_mark_rate': None if c.get('bplus_unevaluated') else ratio(c['marked_bplus'], c['B_plus']),
                    'bplus_contamination': ratio(c['marked_bplus'], c['marked_deletion_comparable']),
                    'deletion_coverage_among_marked': ratio(c['marked_deletion_comparable'], c['marked'])}
            for label,c in counts.items()}


def read_event_calibration(path, *, expected_sha256=None, require_event_binding=False):
    """Audit the exact manifest bytes used for event pricing or diagnostics."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('calibration manifest SHA-256 differs from the frozen settings')
    cases = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    if any(not isinstance(case, dict) for case in cases):
        raise ValueError('calibration manifest rows must be JSON objects')
    provenance = {'evaluation_manifest_sha256': digest}
    if require_event_binding:
        provenance['cases_path'] = str(path.resolve())
    return {label: dict(stats, **provenance) for label, stats in
            audit_event_labels(cases, require_event_binding=require_event_binding).items()}


def reasoning_usage(rounds):
    """Keep native usage and estimates from recorded reasoning text separate."""
    received = [r for r in rounds if r.get('response_received') is True]
    exact, derived = [], []
    for row in received:
        native = row.get('reasoning_tokens')
        if type(native) is int and native >= 0:
            exact.append(native)
        accounting = row.get('token_accounting') or {}
        estimate = accounting.get('reasoning_field_retokenized_tokens')
        if (accounting.get('reasoning_retokenized_is_derived_not_serving_usage') is True
                and type(estimate) is int and estimate >= 0):
            derived.append(estimate)
    return {'reasoning_rounds':len(received), 'reasoning_observed_rounds':len(exact),
            'reasoning_tokens':sum(exact) if exact else None,
            'reasoning_derived_rounds':len(derived),
            'reasoning_derived_tokens':sum(derived) if derived else None}


def summarize_reasoning_usage(rows):
    result = {'reasoning_rounds':sum(r.get('reasoning_rounds') or 0 for r in rows)}
    for count, tokens, average in (
        ('reasoning_observed_rounds','reasoning_tokens','reasoning_tokens_per_round'),
        ('reasoning_derived_rounds','reasoning_derived_tokens','reasoning_derived_tokens_per_round'),
    ):
        selected = [r for r in rows if r.get(count) and r.get(tokens) is not None]
        covered = sum(r[count] for r in selected)
        total = sum(r[tokens] for r in selected)
        result.update({count:covered, tokens:total if covered else None,
                       average:total/covered if covered else None})
    return result


def audit_gap_reviews(evaluation_path, requirements_path, review_path):
    """Attach independently reviewed evidence closure to a frozen fixed evaluation."""
    evaluation_raw = Path(evaluation_path).read_bytes()
    requirements_raw = Path(requirements_path).read_bytes()
    review_raw = Path(review_path).read_bytes()
    evaluation, requirements, review = map(json.loads, (evaluation_raw, requirements_raw, review_raw))
    if any(not isinstance(value, dict) for value in (evaluation, requirements, review)):
        raise ValueError('gap audit inputs must be JSON objects')
    source_digest = hashlib.sha256(evaluation_raw).hexdigest()
    requirements_digest = hashlib.sha256(requirements_raw).hexdigest()
    if review.get('evaluation_sha256') != source_digest:
        raise ValueError('review evaluation SHA-256 differs from the frozen evaluation')
    if review.get('requirements_sha256') != requirements_digest:
        raise ValueError('review requirements SHA-256 differs from the frozen gap list')
    protocol = review.get('protocol_id')
    if not isinstance(protocol, str) or not protocol.strip():
        raise ValueError('independent gap review requires a protocol identifier')

    rows, checks = evaluation['rows'], review['checks']
    if not all(isinstance(items, list) and all(isinstance(item, dict) for item in items) for items in (rows, checks)):
        raise ValueError('evaluation rows and gap checks must be lists of objects')
    identities = {(row['task_id'], row['sample_id']) for row in rows}
    if not rows or len(identities) != len(rows) or set(requirements) != {task for task, _ in identities}:
        raise ValueError('required gaps must cover the unique samples of every fixed evaluation task')
    for gaps in requirements.values():
        if (not isinstance(gaps, dict) or not gaps or any(not gap_id.strip() or
                not isinstance(description, str) or not description.strip() for gap_id, description in gaps.items())):
            raise ValueError('each task requires named gaps with descriptions')

    reviewed = {}
    for check in checks:
        task, sample, gap = (check[k] for k in ('task_id', 'sample_id', 'gap_id'))
        key = task, sample, gap
        if (task, sample) not in identities or gap not in requirements[task] or key in reviewed:
            raise ValueError('gap review contains a duplicate or an out-of-manifest sample or gap')
        verdict = check['verdict']
        if verdict not in {'closed', 'open', 'unknown'}:
            raise ValueError('invalid gap verdict')
        if verdict == 'closed':
            refs = check.get('evidence_refs')
            if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                raise ValueError('a closed gap requires evidence references')
        reviewed[key] = verdict

    total = observed = 0
    by_task = defaultdict(list)
    for row in rows:
        task, sample = row['task_id'], row['sample_id']
        verdicts = [reviewed.get((task, sample, gap), 'unknown') for gap in requirements[task]]
        expected, unknown, closed = len(verdicts), verdicts.count('unknown'), verdicts.count('closed')
        total += expected
        observed += expected - unknown
        row['necessary_gap_closure'] = closed / expected if not unknown else None
        row['necessary_gap_closure_bounds'] = [closed / expected, (closed + unknown) / expected]
        by_task[task].append(row['necessary_gap_closure_bounds'])
    lower, upper = [statistics.fmean(statistics.fmean(bounds[i] for bounds in task) for task in by_task.values())
                    for i in (0, 1)]
    evaluation['mean_necessary_gap_closure'] = lower if observed == total else None
    evaluation['gap_review'] = {'evaluation_sha256': source_digest, 'requirements_sha256': requirements_digest,
                                'review_sha256': hashlib.sha256(review_raw).hexdigest(), 'protocol_id': protocol,
                                'expected': total, 'observed': observed, 'bounds': [lower, upper]}
    return evaluation


def paired_event_diagnostics(baseline, candidate, *, seed=20261111, resamples=2000, additional_metrics=()):
    """Compare fixed-task summaries, preserving coverage of partial measurements."""
    keys = ('outcome','cost','tool_calls','measured_return_tokens','exact_repeat_events',
            'unmarked_event_cost','budget_exhausted','explicit_abandon') + tuple(additional_metrics)
    if type(resamples) is not int or resamples < 1:
        raise ValueError('resamples must be a positive integer')
    indexed = [{(r['task_id'],r['sample_id']):r for r in rows} for rows in (baseline,candidate)]
    if any(len(i) != len(r) for i,r in zip(indexed,(baseline,candidate),strict=True)):
        raise ValueError('duplicate task/sample identities')
    left,right = indexed
    if not left or left.keys() != right.keys():
        raise ValueError('fixed evaluation identities must match')
    gaps_reviewed = all('necessary_gap_closure_bounds' in row for row in (*baseline, *candidate))
    if gaps_reviewed:
        keys += ('necessary_gap_closure',)
    tasks = defaultdict(list)
    for identity in sorted(left):
        tasks[identity[0]].append(identity)
    result = {}
    for key in keys:
        values = []
        for ids in tasks.values():
            a,b = [[index[i].get(key) for i in ids] for index in (left,right)]
            if any(v is None for v in a+b):
                continue
            values.append(statistics.fmean(b)-statistics.fmean(a))
        # Billing gaps affect normal submissions while automatic terminal
        # failures stay resolved. Complete-case accuracy can therefore be
        # entirely driven by the failure-only tasks.
        usable = bool(values) and (key not in {'outcome', 'necessary_gap_closure'} or len(values) == len(tasks))
        rng = random.Random(seed)
        samples = [statistics.fmean(rng.choices(values,k=len(values))) for _ in range(resamples)] if usable else []
        result[key] = {'task_count':len(values), 'intended_task_count':len(tasks),
                       'estimate':_mean(values) if usable else None,
                       'ci95':[_quantile(samples,.025),_quantile(samples,.975)] if samples else None}
    # Bounds over possible values of missing binary verdicts on these fixed
    # tasks. They are not sampling intervals and assume no missingness model.
    def outcome_bounds(index):
        by_task = [[index[i]['outcome'] for i in ids] for ids in tasks.values()]
        low = statistics.fmean(sum(v == 1 for v in values)/len(values) for values in by_task)
        high = statistics.fmean(sum(v == 1 or v is None for v in values)/len(values) for values in by_task)
        return [low, high]

    a,b = outcome_bounds(left), outcome_bounds(right)
    result['outcome'].update(baseline_outcome_bounds=a, candidate_outcome_bounds=b,
                             missing_verdict_delta_bounds=[b[0]-a[1],b[1]-a[0]])
    if gaps_reviewed:
        def gap_bounds(index):
            return [statistics.fmean(statistics.fmean(index[j]['necessary_gap_closure_bounds'][i] for j in ids)
                                     for ids in tasks.values()) for i in (0, 1)]

        a, b = gap_bounds(left), gap_bounds(right)
        result['necessary_gap_closure'].update(baseline_bounds=a, candidate_bounds=b,
                                                missing_review_delta_bounds=[b[0]-a[1], b[1]-a[0]])
    return {'unit':'task_id', 'seed':seed, 'resamples':resamples, 'delta':result}
