"""Evaluate frozen stage judgments against independent human and deletion evidence."""

from collections import Counter, defaultdict
import math
import random

from .build_grpo_inputs import freeze_identity


LABELS = ("R1", "R2b")
DECISIONS = {"positive", "negative", "abstain"}
Z95 = 1.959963984540054
QUALITY_THRESHOLDS = {
    "min_precision": .90, "max_necessary_false_positive_rate": .05,
    "max_bplus_mark_rate": .05,
}


def _settings(config):
    options = {
        **QUALITY_THRESHOLDS, "max_bplus_contamination": .05,
        "min_positive_events": 100, "min_positive_questions": 15,
        "bootstrap_samples": 1000, "bootstrap_seed": 20261113,
    } | (config or {})
    for key in ("min_precision", "max_necessary_false_positive_rate",
                "max_bplus_mark_rate", "max_bplus_contamination"):
        value = options[key]
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError(f"invalid {key}")
    for key, limit in QUALITY_THRESHOLDS.items():
        if (options[key] < limit if key == "min_precision" else options[key] > limit):
            raise ValueError(f"{key} cannot weaken the phase-one quality threshold")
    for key in ("min_positive_events", "min_positive_questions", "bootstrap_samples"):
        if type(options[key]) is not int or options[key] < 1:
            raise ValueError(f"invalid {key}")
    if type(options["bootstrap_seed"]) is not int:
        raise ValueError("bootstrap_seed must be an integer")
    return options


def _interval(values, estimate, options):
    """Question bootstrap widened by a Wilson interval at Kish effective question count."""
    rng = random.Random(options["bootstrap_seed"])
    reps = []
    cluster_count = len(values)
    for _ in range(options["bootstrap_samples"]):
        replicate = rng.choices(values, k=cluster_count)
        denominator = sum(pair[1] for pair in replicate)
        if denominator:
            reps.append(sum(pair[0] for pair in replicate) / denominator)
    reps.sort()
    den = math.fsum(pair[1] for pair in values)
    effective_n = den**2 / math.fsum(pair[1]**2 for pair in values)
    z2 = Z95**2
    center = (estimate + z2 / (2 * effective_n)) / (1 + z2 / effective_n)
    half = Z95 * math.sqrt(estimate * (1 - estimate) / effective_n + z2 / (4 * effective_n**2)) / (
        1 + z2 / effective_n)
    lower, upper = center - half, center + half
    if reps:
        lower = min(lower, reps[math.floor(.025 * (len(reps) - 1))])
        upper = max(upper, reps[math.ceil(.975 * (len(reps) - 1))])
    return [max(0.0, lower), min(1.0, upper)], effective_n


def _metric(rows, is_numerator, is_denominator, options):
    clusters = defaultdict(lambda: [0., 0.])
    count = successes = 0
    for row in rows:
        if not is_denominator(row):
            continue
        weight = row["weight"]
        cluster = clusters[row["question_id"]]
        cluster[1] += weight
        count += 1
        if is_numerator(row):
            cluster[0] += weight
            successes += 1
    numerator = math.fsum(pair[0] for pair in clusters.values())
    denominator = math.fsum(pair[1] for pair in clusters.values())
    out = {"numerator": successes, "denominator": count, "questions": len(clusters),
           "weighted_numerator": numerator, "weighted_denominator": denominator,
           "estimate": None, "ci95": None, "effective_questions": None}
    if denominator:
        out["estimate"] = min(1.0, numerator / denominator)
        out["ci95"], out["effective_questions"] = _interval(list(clusters.values()), out["estimate"], options)
    return out


def _valid_review(row):
    probability = row.get("selection_probability")
    return (row.get("source") == "human" and row.get("independent") is True
            and isinstance(row.get("reviewer_id"), str) and bool(row["reviewer_id"].strip())
            and row.get("human_decision") in DECISIONS and type(row.get("necessary")) is bool
            and row.get("sample_kind") in ("natural", "protection")
            and type(probability) in (int, float) and 0 < probability <= 1
            and math.isfinite(1 / probability))


def _reviews(human_annotations, identities, outside_audit, plan):
    grouped = defaultdict(list)
    unresolved, disagreements, resolved = [], [], []
    for row in human_annotations:
        key = (row.get("event_id"), row.get("label"))
        info = {"event_id": key[0], "label": key[1], "reviewer_id": row.get("reviewer_id")}
        if key in outside_audit:
            unresolved.append(dict(info, reason="review_outside_audit_split"))
        elif key not in identities:
            unresolved.append(dict(info, reason="missing_frozen_judgment"))
        elif not _valid_review(row):
            unresolved.append(dict(info, reason="not_independent_human_review"))
        elif plan is not None and (*key, row["sample_kind"]) not in plan:
            unresolved.append(dict(info, reason="review_outside_frozen_plan"))
        elif (plan is not None and plan[*key, row["sample_kind"]] is not None
              and plan[*key, row["sample_kind"]] != row["selection_probability"]):
            unresolved.append(dict(info, reason="review_probability_differs_from_frozen_plan"))
        else:
            grouped[(*key, row["sample_kind"])].append(row)
    for (event_id, label, kind), group in grouped.items():
        info = {"event_id": event_id, "label": label, "sample_kind": kind}
        independent = [row for row in group if row.get("adjudication") is not True]
        adjudicators = [row for row in group if row.get("adjudication") is True]
        reviewers = {row["reviewer_id"] for row in independent}
        decisions = {(row["human_decision"], row["necessary"]) for row in independent}
        probabilities = {row["selection_probability"] for row in group}
        if len(probabilities) != 1 or not independent or len(reviewers) != len(independent):
            unresolved.append(dict(info, reason="invalid_or_duplicate_review_records"))
            continue
        if len(decisions) > 1:
            adjudicator = (adjudicators[0] if len(adjudicators) == 1
                           and adjudicators[0]["reviewer_id"] not in reviewers else None)
            disagreements.append(dict(info, reviewer_ids=sorted(reviewers),
                                      decisions=sorted(decisions),
                                      adjudicator_id=adjudicator["reviewer_id"] if adjudicator else None))
            if adjudicator is None:
                unresolved.append(dict(info, reason="adjudication_required"))
                continue
            review = adjudicator
        else:
            review = independent[0]
        resolved.append({**identities[event_id, label], **info, "human_decision": review["human_decision"],
                         "necessary": review["necessary"], "protection_reason": review.get("protection_reason"),
                         "reviewer_ids": sorted(reviewers), "weight": 1 / review["selection_probability"]})
    return resolved, disagreements, unresolved


def _review_plan(planned_reviews, identities):
    if planned_reviews is None:
        return None
    plan = {}
    for row in planned_reviews:
        key = (row["event_id"], row["label"], row["sample_kind"])
        probability = row.get("selection_probability")
        if (key in plan or key[:2] not in identities or key[2] not in ("natural", "protection")
                or (probability is not None and (type(probability) not in (int, float)
                                                 or not 0 < probability <= 1))):
            raise ValueError(f"invalid or duplicate planned human review {key!r}")
        plan[key] = probability
    return plan


def _human_metrics(rows, options):
    verified = [row for row in rows if row["human_decision"] != "abstain"]
    return {
        "events": len(rows), "questions": len({row["question_id"] for row in rows}),
        "unresolved_human_decisions": len(rows) - len(verified),
        "precision": _metric(verified, lambda r: r["human_decision"] == "positive",
                             lambda r: r["decision"] == "positive", options),
        "recall": _metric(verified, lambda r: r["decision"] == "positive",
                          lambda r: r["human_decision"] == "positive", options),
        "necessary_false_positive_rate": _metric(rows, _price_candidate, lambda r: r["necessary"], options),
        "abstention_rate": _metric(rows, lambda r: r["decision"] == "abstain", lambda r: True, options),
        "priceable_coverage": _metric(rows, _price_candidate, lambda r: True, options),
        "protection_reasons": dict(Counter(row["protection_reason"] for row in rows if row["protection_reason"])),
    }


def _price_candidate(row):
    return (row["decision"] == "positive" and row.get("reward_eligible") is True
            and not row.get("protected") and not row.get("protection_reasons"))


def _legacy_category(link):
    if link.get("reviewed") is not True or link.get("mapping_reliable") is not True:
        return "unreliable_mapping"
    for flag in ("function_reconstructed", "successor_guidance"):
        if link.get(flag):
            return flag
    original, branches = link.get("original_result"), link.get("branch_results")
    if (original not in ("C", "W", "N") or not isinstance(branches, (list, tuple))
            or len(branches) != 4 or any(value not in ("C", "W", "N") for value in branches)):
        return "incomplete_outcome"
    if original == "C":
        changed = sum(value != "C" for value in branches)
        if changed >= 3:
            return "B+"
        if changed <= 1:
            return "A"
        return "gray"
    if branches.count("C") >= 3:
        return "B-"
    return "other_transition"


def _legacy_metrics(rows, links, options):
    associations = defaultdict(list)
    for link in links:
        associations[link.get("event_id")].append(link)
    combined = []
    for row in rows:
        entries = associations.get(row["event_id"], ())
        if not entries:
            continue
        category = _legacy_category(entries[0]) if len(entries) == 1 else "ambiguous_multiple_links"
        combined.append(dict(row, legacy_category=category, weight=1.0))
    reliable = [row for row in combined if row["legacy_category"] in {"A", "B+", "B-", "gray", "other_transition"}]
    return {
        "bplus_mark_rate": _metric(reliable, _price_candidate, lambda r: r["legacy_category"] == "B+", options),
        "bplus_contamination": _metric(reliable, lambda r: r["legacy_category"] == "B+", _price_candidate, options),
        "link_counts": dict(Counter(row["legacy_category"] for row in combined)),
    }


def _status(rows, reviews, natural, protection, legacy, identity, options):
    if not any(row["human_decision"] != "abstain" for row in reviews):
        return "PENDING_HUMAN_REVIEW"
    required = [(natural["precision"], "min_precision", True),
                (natural["necessary_false_positive_rate"], "max_necessary_false_positive_rate", False),
                (protection["necessary_false_positive_rate"], "max_necessary_false_positive_rate", False),
                (legacy["bplus_mark_rate"], "max_bplus_mark_rate", False),
                (legacy["bplus_contamination"], "max_bplus_contamination", False)]
    for value, threshold, lower in required:
        point = value["estimate"]
        if point is not None and (point < options[threshold] if lower else point > options[threshold]):
            return "FAIL"
    positive_population = [row for row in rows if row["decision"] == "positive"]
    audited_positive_ids = {row["event_id"] for row in reviews if row["sample_kind"] == "natural"
                            and row["decision"] == "positive" and row["human_decision"] != "abstain"}
    positive = natural["precision"]
    all_positives_audited = len(audited_positive_ids) == len(positive_population)
    sample_target_met = (positive["denominator"] >= options["min_positive_events"]
                         and positive["questions"] >= options["min_positive_questions"])
    if identity is None or (not sample_target_met and not all_positives_audited):
        return "INSUFFICIENT_EVIDENCE"
    for value, threshold, lower in required:
        interval = value["ci95"]
        if interval is None or (interval[0] < options[threshold] if lower else interval[1] > options[threshold]):
            return "INSUFFICIENT_EVIDENCE"
    return "PASS"


def audit_judge(judgments, human_annotations=(), legacy_links=(), *, planned_reviews=None, config=None):
    """Measure audit results separately by label. Only a bound human audit can approve prices."""
    options = _settings(config)
    identities = {}
    outside_audit = set()
    judged = list(judgments)
    explicit_split = any("split" in row for row in judged)
    for row in judged:
        label = row.get("label")
        if label not in LABELS or row.get("synthetic") is not False:
            continue
        event_id = row.get("event_id")
        key = (event_id, label)
        if explicit_split and row.get("split") != "audit":
            outside_audit.add(key)
            continue
        if not event_id or not row.get("question_id") or row.get("decision") not in DECISIONS or key in identities:
            raise ValueError(f"invalid or duplicate frozen judgment {key!r}")
        identities[key] = row

    plan = _review_plan(planned_reviews, identities)
    reviews, disagreements, unresolved = _reviews(human_annotations, identities, outside_audit, plan)
    links = list(legacy_links)
    approved, labels = {}, {}
    for label in LABELS:
        rows = [row for key, row in identities.items() if key[1] == label]
        own = [row for row in reviews if row["label"] == label]
        natural = _human_metrics([row for row in own if row["sample_kind"] == "natural"], options)
        protection = _human_metrics([row for row in own if row["sample_kind"] == "protection"], options)
        legacy = _legacy_metrics(rows, links, options)
        identity = freeze_identity(rows[0].get("provenance") or {}) if rows else None
        if any(freeze_identity(row.get("provenance") or {}) != identity for row in rows):
            identity = None
        status = _status(rows, own, natural, protection, legacy, identity, options)
        completeness = None
        if plan is not None:
            scheduled = {key for key in plan if key[1] == label}
            settled = {(row["event_id"], label, row["sample_kind"]) for row in own
                       if row["human_decision"] != "abstain"}
            outstanding = [{"event_id": key[0], "label": label, "sample_kind": key[2]}
                           for key in sorted(scheduled - settled)]
            completeness = {"planned": len(scheduled), "settled": len(settled), "outstanding": outstanding}
            if outstanding and status != "FAIL":
                status = "PENDING_HUMAN_REVIEW"
        if status == "PASS" and any(row["label"] == label and row["reason"] != "review_outside_audit_split"
                                    and row["reason"] != "review_outside_frozen_plan" for row in unresolved):
            status = "PENDING_HUMAN_REVIEW"
        if status == "PASS":
            approved[label] = {"status": status, "provenance": identity, "synthetic": False}
        labels[label] = {
            "status": status, "events": len(rows), "questions": len({row["question_id"] for row in rows}),
            "automatic_decisions": dict(Counter(row["decision"] for row in rows)),
            "automatic_priceable_events": sum(_price_candidate(row) for row in rows),
            "automatic": {
                "abstention_rate": _metric([dict(row, weight=1.0) for row in rows],
                                           lambda r: r["decision"] == "abstain", lambda r: True, options),
                "priceable_coverage": _metric([dict(row, weight=1.0) for row in rows],
                                              _price_candidate, lambda r: True, options),
            },
            "natural": natural, "protection": protection, "legacy": legacy, "provenance": identity,
            "review_plan": completeness,
            "failure_cases": [
                {key: row[key] for key in ("event_id", "question_id", "sample_kind", "decision", "human_decision",
                                          "necessary", "protection_reason", "reviewer_ids")}
                for row in own if (row["decision"] == "positive" and row["human_decision"] == "negative")
                or (_price_candidate(row) and row["necessary"])
                or (row["decision"] != "positive" and row["human_decision"] == "positive")
            ],
        }
    statuses = {row["status"] for row in labels.values()}
    status = next(candidate for candidate in ("FAIL", "PENDING_HUMAN_REVIEW", "INSUFFICIENT_EVIDENCE", "PASS")
                  if candidate in statuses)
    return {
        "status": status, "labels": labels, "approved_labels": approved,
        "disagreements": disagreements, "unresolved_reviews": unresolved, "thresholds": options,
        "split_filter": "audit" if explicit_split else "caller_supplied_audit_population",
        "excluded_outside_audit": len(outside_audit),
        "confidence_interval": {"level": .95, "unit": "question", "bootstrap": "percentile",
                                "boundary": "Wilson with Kish effective question count"},
    }
