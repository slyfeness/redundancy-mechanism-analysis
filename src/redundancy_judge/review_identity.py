"""Configuration and provenance for independently authorized AI audits."""

import re


def review_identity(config):
    mode = config.get("review_mode", "human")
    if mode == "human":
        return {}
    if mode != "ai":
        raise ValueError("review_mode must be human or ai")
    policy = config.get("ai_review")
    required = {"primary_reviewer": "codex", "spot_checker": "claude-opus-5-5", "authorized_by": "user"}
    if (not isinstance(policy, dict) or set(policy) != {*required, "criteria_sha256"}
            or any(policy[key] != value for key, value in required.items())
            or not re.fullmatch(r"[0-9a-f]{64}", str(policy["criteria_sha256"]))):
        raise ValueError("AI review requires the authorized reviewers and frozen criteria SHA-256")
    return {"review_mode": mode, "ai_review": dict(policy)}
