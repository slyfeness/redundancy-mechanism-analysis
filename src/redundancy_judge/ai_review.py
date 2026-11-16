"""Review the frozen R2b population with two separately attributed AI sets."""

from collections import Counter, defaultdict
from hashlib import sha256

from .build_grpo_inputs import bind_ai_review
from .review_identity import review_identity


DECISIONS = {"positive", "negative", "abstain"}
SPOT_SEED = "20261116"
SPOT_TARGET = 40


def review_units(judgments, original_plan):
    automatic = {}
    for row in judgments:
        if row["label"] == "R2b":
            eid = row["event_id"]
            if eid in automatic or row["decision"] not in DECISIONS or row["synthetic"] is not False:
                raise ValueError("invalid or duplicate frozen R2b judgment")
            automatic[eid] = row["decision"]
    units, covered = {}, set()
    for row in original_plan:
        if row["label"] != "R2b":
            continue
        eid, kind = row["event_id"], row["sample_kind"]
        unit = f"R2b:{eid}:{kind}"
        if eid not in automatic or kind not in {"natural", "protection"} or unit in units:
            raise ValueError("invalid or duplicate R2b review unit")
        units[unit] = eid
        covered.add(eid)
    for eid, decision in automatic.items():
        if decision == "positive" and eid not in covered:
            units[f"R2b:{eid}:full_positive"] = eid
    return units


def spot_check_list(reviews):
    mandatory = sorted(row["unit_id"] for row in reviews if row["decision"] != "positive")
    optional = sorted((row["unit_id"] for row in reviews if row["decision"] == "positive"),
                      key=lambda uid: (sha256(f"{SPOT_SEED}|{uid}".encode()).hexdigest(), uid))
    return [{"unit_id": uid, "selection": kind} for kind, selected in (
        ("all_nonpositive", mandatory), ("random", optional[:max(0, SPOT_TARGET - len(mandatory))]))
        for uid in selected]


def _review_index(rows, units, reviewer, adjudication):
    indexed = {}
    for row in rows:
        uid = row.get("unit_id")
        if (uid not in units or uid in indexed or row.get("event_id") != units[uid]
                or row.get("decision") not in DECISIONS or row.get("source") != "ai_review"
                or row.get("reviewer_id") != reviewer or row.get("independent") is not True
                or row.get("adjudication", False) is not adjudication
                or type(row.get("necessary")) is not bool
                or row["necessary"] and row["decision"] != "negative"
                or not isinstance(row.get("reason"), str) or not row["reason"].strip()):
            raise ValueError("invalid or duplicate AI " + ("spot review" if adjudication else "review"))
        indexed[uid] = row
    return indexed


def audit_ai_reviews(judgments, original_plan, primary_reviews, spot_reviews, config):
    policy = review_identity(config)
    if not policy:
        raise ValueError("AI review requires review_mode ai")
    metadata = policy["ai_review"]
    units = review_units(judgments, original_plan)
    by_event = {row["event_id"]: row for row in judgments if row["label"] == "R2b"}
    primary = _review_index(primary_reviews, units, metadata["primary_reviewer"], False)
    required_spot = spot_check_list(primary.values()) if len(primary) == len(units) else []
    spot = _review_index(spot_reviews, {r["unit_id"]: units[r["unit_id"]] for r in required_spot},
                         metadata["spot_checker"], True)
    pending = sorted(set(units) - primary.keys()) + [r["unit_id"] for r in required_spot if r["unit_id"] not in spot]
    matches = sum(row["decision"] == primary[uid]["decision"] for uid, row in spot.items())
    disagreements = [{"unit_id": uid, "event_id": units[uid], "primary_decision": primary[uid]["decision"],
                      "adjudicated_decision": row["decision"]}
                     for uid, row in sorted(spot.items()) if row["decision"] != primary[uid]["decision"]]
    regressions = sum(row["primary_decision"] == "positive" and row["adjudicated_decision"] == "negative"
                      for row in disagreements)
    bindings = {row["event_id"]: bind_ai_review(row.get("provenance"), policy) for row in by_event.values()}
    binding = next(iter(bindings.values()), None)
    bindings_are_valid = binding is not None and all(value == binding for value in bindings.values())
    approved = {}
    status = "PENDING_AI_REVIEW"
    decisions_by_event = defaultdict(set)
    spot_by_event = defaultdict(set)
    for uid, row in primary.items():
        decisions_by_event[units[uid]].add(row["decision"])
    for uid, row in spot.items():
        spot_by_event[units[uid]].add(row["decision"])
    decisions_by_event.update(spot_by_event)
    if not pending and spot:
        if bindings_are_valid and matches * 100 >= len(spot) * 95 and not regressions:
            status = "PASS"
            approved["R2b"] = {"status": "ai_approved", "synthetic": False,
                               "provenance": binding,
                               "event_ids": sorted(eid for eid, decisions in decisions_by_event.items()
                                                   if decisions == {"positive"} and by_event[eid]["decision"] == "positive")}
        else:
            status = "FAIL"
    return {**policy, "status": status, "labels": {
                "R1": {"status": "record_only"}, "R2a": {"status": "record_only"},
                "R2b": {"status": status, "events": len(decisions_by_event), "units": len(units),
                        "primary_decisions": dict(Counter(row["decision"] for row in primary.values())),
                        "spot_count": len(spot), "agreements": matches, "positive_to_negative": regressions,
                        "spot_primary_positives": sum(primary[uid]["decision"] == "positive" for uid in spot),
                        "agreement": matches / len(spot) if spot else None}},
            "freeze": binding if bindings_are_valid else None,
            "approved_labels": approved, "disagreements": disagreements, "unresolved_reviews": pending,
            "thresholds": {"min_agreement": .95, "max_positive_to_negative": 0},
            "skipped_checks": {"B_plus": "user-authorized AI audit uses independent spot adjudication",
                               "human_confidence_intervals": "AI audit uses the specified agreement and false-positive gates"}}
