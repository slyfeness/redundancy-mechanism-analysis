"""Pure phase-one reward arithmetic on verified native policy coordinates."""

from collections import defaultdict
import math
import re


PRIORITY = ("R2b", "R1")
FREEZE_KEYS = ("schema_version", "code_commit", "model_version", "prompt_sha256", "config_sha256")
DEFAULT_PRICES = {"R1": .05, "R2b": .10, "R2a": 0.0}


def freeze_identity(provenance):
    """Project the fields shared by a frozen audit and subsequent annotations."""
    if not isinstance(provenance, dict):
        return None
    values = {key: provenance.get(key) for key in FREEZE_KEYS}
    if any(not isinstance(value, str) or not value for value in values.values()):
        return None
    if any(not re.fullmatch(r"[0-9a-f]{64}", values[key]) for key in ("prompt_sha256", "config_sha256")):
        return None
    if provenance.get("tokenizer_version"):
        values["tokenizer_version"] = provenance["tokenizer_version"]
    return values


def _number(value, low=0.0, high=None):
    return (type(value) in (int, float) and math.isfinite(value)
            and value >= low and (high is None or value <= high))


def _settings(config):
    config = config or {}
    for key in ("normalize_by_std", "enable_optimizer_step"):
        if config.get(key, False) is not False:
            raise ValueError(f"{key} must be false in phase one")
    weight = config.get("w_g", .1)
    cap = config.get("trajectory_price_cap", .5)
    prices = DEFAULT_PRICES | config.get("prices", {})
    if not _number(weight) or not _number(cap) or set(prices) != set(DEFAULT_PRICES):
        raise ValueError("invalid phase-one price configuration")
    if not all(_number(price) for price in prices.values()) or prices["R2a"] != 0:
        raise ValueError("prices must be finite and nonnegative and R2a must have zero price")
    mode = config.get("price_mode", "fixed")
    reference = config.get("reference_cost")
    if mode not in ("fixed", "cost_weighted"):
        raise ValueError("unknown price_mode")
    if mode == "cost_weighted":
        if (not isinstance(reference, dict) or reference.get("split") != "dev"
                or not _number(reference.get("median")) or not reference["median"]
                or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("sample_sha256", "")))):
            raise ValueError("cost-weighted pricing requires a frozen development median and sample SHA-256")
    budget_gate = config.get("budget_failure_disables_local_prices", False)
    if type(budget_gate) is not bool:
        raise ValueError("budget_failure_disables_local_prices must be boolean")
    group_size = config.get("group_size")
    if group_size is not None and (type(group_size) is not int or group_size < 2):
        raise ValueError("group_size must be an integer >= 2")
    return weight, cap, prices, reference if mode == "cost_weighted" else None, budget_gate, group_size


def _positions(spans, length):
    if not isinstance(spans, (tuple, list)):
        raise ValueError("invalid token spans")
    indices = set()
    for span in spans:
        if (not isinstance(span, (tuple, list)) or len(span) != 2 or
                any(type(x) is not int for x in span) or not 0 <= span[0] < span[1] <= length):
            raise ValueError("invalid half-open token span")
        indices.update(range(*span))
    return indices


def _preflight(row, weight):
    if row.get("recording_complete") is not True:
        return "incomplete_log", set()
    if (row.get("result"), row.get("termination_reason")) not in {
        ("C", "normal"), ("W", "normal"), ("N", "budget_exhausted"), ("N", "empty_final"),
    }:
        return "invalid_outcome_or_termination", set()
    if not row.get("result_source"):
        return "missing_independent_result", set()
    if "Y" in row and (type(row["Y"]) not in (bool, int) or row["Y"] != int(row["result"] == "C")):
        return "inconsistent_independent_y", set()
    if row.get("token_alignment_status") != "verified":
        return "unverified_token_alignment", set()
    length = row.get("policy_token_count")
    if type(length) is not int or length <= 0:
        return "invalid_policy_token_axis", set()
    try:
        positions = _positions(row.get("policy_token_spans"), length)
    except ValueError:
        return "invalid_policy_token_spans", set()
    if not positions:
        return "empty_policy_token_mask", positions
    if weight and row["result"] == "C" and not _number(row.get("g"), high=1):
        return "unverified_grounding", positions
    if type(row.get("synthetic")) is not bool:
        return "missing_execution_mode", positions
    return None, positions


def _label_approved(label, event, row, approved):
    approval = approved.get(label)
    if not isinstance(approval, dict) or approval.get("status") != "PASS":
        return False
    if approval.get("synthetic") is not row["synthetic"]:
        return False
    row_provenance = row.get("provenance")
    provenance = freeze_identity(row_provenance)
    if event.get("provenance") is not None and freeze_identity(event["provenance"]) != provenance:
        return False
    return provenance is not None and provenance == freeze_identity(approval.get("provenance"))


def _event_cost(event):
    cost = event.get("event_cost")
    if not isinstance(cost, dict):
        return None
    generated, returned = cost.get("generated_tokens"), cost.get("returned_tokens")
    if any(type(value) is not int or value < 0 for value in (generated, returned)):
        return None
    return generated + returned


def _price_candidates(row, policy, prices, reference, approvals):
    buckets = defaultdict(list)
    rejected = []
    candidates = []
    for event in row.get("events", ()):
        identity = event.get("event_id")
        if not isinstance(identity, str) or not identity:
            rejected.append({"event_id": identity, "reason": "missing_event_identity"})
            continue
        buckets[identity].append(event)
    for identity, events in buckets.items():
        if any(event.get("protected") or event.get("protection_reasons") for event in events):
            rejected.append({"event_id": identity, "reason": "protected_event"})
            continue
        options = [event for label in PRIORITY for event in events
                   if event.get("label") == label and event.get("decision") == "positive"
                   and event.get("reward_eligible") is True]
        if not options:
            continue
        # Establish precedence before approval. An unapproved primary label
        # cannot be repriced automatically as a secondary diagnosis.
        event = options[0]
        label = event["label"]
        if event.get("stage_type") != "tool" or event.get("parallel_group_id") is not None:
            rejected.append({"event_id": identity, "reason": "ineligible_stage_type_or_parallel_group"})
            continue
        if not prices[label]:
            continue
        if not _label_approved(label, event, row, approvals):
            rejected.append({"event_id": identity, "reason": "unapproved_label_or_mismatched_freeze"})
            continue
        try:
            positions = _positions(event.get("charge_token_spans"), row["policy_token_count"])
        except ValueError:
            positions = set()
        if not positions or not positions <= policy:
            rejected.append({"event_id": identity, "reason": "invalid_charge_token_spans"})
            continue
        duplicates = [item for item in options if item["label"] == label and item != event]
        if duplicates:
            rejected.append({"event_id": identity, "reason": "conflicting_duplicate_event_records"})
            continue
        cost = _event_cost(event)
        if reference is not None and cost is None:
            rejected.append({"event_id": identity, "reason": "unverified_event_cost"})
            continue
        multiplier = 1.0 if reference is None else min(cost / reference["median"], 2.0)
        candidates.append(({
            "event_id": identity, "label": label, "charge_token_spans": event["charge_token_spans"],
            "event_cost": cost, "multiplier": multiplier, "base_price": prices[label] * multiplier,
        }, positions))

    owners = defaultdict(list)
    for event, indices in candidates:
        for index in indices:
            owners[index].append(event["event_id"])
    conflicts = {identity for identities in owners.values() if len(identities) > 1 for identity in identities}
    for identity in sorted(conflicts):
        rejected.append({"event_id": identity, "reason": "overlapping_charge_spans"})
    return [(event, indices) for event, indices in candidates if event["event_id"] not in conflicts], rejected


def build_grpo_inputs(annotations, config=None, approved_labels=None):
    """Build a standalone preview. The caller supplies complete same-question groups."""
    weight, cap, prices, reference, budget_gate, group_size = _settings(config)
    approvals = approved_labels or {}
    groups = defaultdict(list)
    identities = set()
    for row in annotations:
        question, identity = row.get("question_id"), row.get("trajectory_id")
        if not question or not identity or identity in identities:
            raise ValueError("each trajectory requires a question ID and globally unique trajectory ID")
        identities.add(identity)
        groups[question].append(row)

    results, excluded = [], []
    assertions = {"policy_mask": True, "peer_gate": True, "no_overlap": True,
                  "trajectory_price_cap": True, "leave_one_out": True}
    for question, rows in groups.items():
        issues = []
        if len(rows) < 2 or (group_size is not None and len(rows) != group_size):
            issues.append("incomplete_question_group")
        if len({row.get("synthetic") for row in rows}) > 1:
            issues.append("mixed_synthetic_and_real_rows")
        checks = [_preflight(row, weight) for row in rows]
        row_reasons = {row["trajectory_id"]: check[0] for row, check in zip(rows, checks) if check[0]}
        if issues or row_reasons:
            excluded.append({"question_id": question, "group_reasons": issues, "row_reasons": row_reasons,
                             "trajectory_ids": [row["trajectory_id"] for row in rows]})
            continue
        y = [int(row["result"] == "C") for row in rows]
        reward = [1 + weight * row["g"] if success and weight else float(success)
                  for row, success in zip(rows, y)]
        budget_protection = budget_gate and any(row["termination_reason"] == "budget_exhausted" for row in rows)
        scored = []
        for i, (row, (_, policy)) in enumerate(zip(rows, checks)):
            gate = int(any(success for j, success in enumerate(y) if j != i))
            outcome = reward[i] - math.fsum(value for j, value in enumerate(reward) if j != i) / (len(rows) - 1)
            candidates, rejected = _price_candidates(row, policy, prices, reference, approvals)
            total = math.fsum(event["base_price"] for event, _ in candidates)
            scale = min(1.0, cap / total) if total else 1.0
            mask = [int(index in policy) for index in range(row["policy_token_count"])]
            advantages = [outcome if bit else 0.0 for bit in mask]
            for event, positions in candidates:
                event["debit"] = gate * scale * event["base_price"] if not budget_protection else 0.0
                for index in positions:
                    advantages[index] -= event["debit"]
            event_debits = [event for event, _ in candidates]
            assertions["policy_mask"] &= all(advantage == 0.0 for advantage, bit in zip(advantages, mask) if not bit)
            assertions["peer_gate"] &= bool(gate) or all(event["debit"] == 0 for event in event_debits)
            assertions["trajectory_price_cap"] &= math.fsum(event["debit"] for event in event_debits) <= cap + 1e-12
            assertions["no_overlap"] &= sum(len(indices) for _, indices in candidates) == len(
                set().union(*(indices for _, indices in candidates)))
            assertions["leave_one_out"] &= math.isclose(outcome, reward[i] - (
                math.fsum(reward) - reward[i]) / (len(rows)-1), abs_tol=1e-12)
            scored.append({
                "trajectory_id": row["trajectory_id"], "result": row["result"], "Y": y[i],
                "termination_reason": row["termination_reason"],
                "raw_termination_reason": row.get("raw_termination_reason", row["termination_reason"]),
                "g": row.get("g"), "R": reward[i], "outcome_advantage": outcome, "peer_gate": gate,
                "scale": scale, "budget_process_disabled": budget_protection, "policy_mask": mask,
                "token_advantages": advantages, "event_debits": event_debits, "excluded_events": rejected,
            })
        results.append({"question_id": question, "synthetic": rows[0]["synthetic"], "trajectories": scored})
    return {
        "status": "COMPUTED" if results and all(assertions.values()) else "NO_VALID_GROUPS" if not results else "FAIL",
        "groups": results, "excluded": excluded, "assertions": assertions,
        "formal_training_usable": False, "optimizer_steps": 0,
    }
