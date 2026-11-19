"""Pure LedgerCredit calculations for the frozen round4 protocol."""
from collections import defaultdict
from math import fsum
from statistics import mean, pstdev


VARIANTS = ("any_u", "any_u_prime", "open_u", "open_u_prime")
EPS = 1e-12


def clip(value):
    return max(-1.0, min(1.0, value))


def is_nonzero(value):
    return abs(value) > EPS


def outcomes(group):
    """A complete title group yields a binary success rate and outcome advantages."""
    if len(group) != 8 or any(type(row["correct"]) is not bool or type(row["submitted"]) is not bool for row in group):
        return None
    rho = sum(row["correct"] for row in group) / 8
    rewards = [int(row["correct"]) - 0.2 * (not row["submitted"]) for row in group]
    center = mean(rewards)
    scale = max(pstdev(rewards), 0.3)
    return rho, [(reward - center) / scale for reward in rewards]


def peer_weights(stage, other_trajectories, progress_key):
    """At most one other stage from each trajectory, with stable tie breaking."""
    peers = []
    for candidates in other_trajectories:
        eligible = []
        for candidate in candidates:
            dz = abs(stage[progress_key] - candidate[progress_key])
            db = abs(stage["b_before"] - candidate["b_before"])
            weight = max(0.0, 1 - dz) * max(0.0, 1 - db)
            if weight > 0.5:
                eligible.append((weight, candidate))
        if eligible:
            peers.append(max(eligible, key=lambda x: x[0]))
    return peers


def stage_advantages(trajectories, a_out, rho, progress, ungated):
    """Return per-stage outputs. Tokens outside Stage spans keep A_out."""
    gain_key = f"c_new_{progress}"
    progress_key = f"z_before_{progress}"
    stage_u = {}
    for stages in trajectories:
        for stage in stages:
            gate = 1.0 if ungated else rho
            stage_u[stage["event_key"]] = stage[gain_key] - 0.2 * gate * stage["idle"]
    output = {}
    for index, stages in enumerate(trajectories):
        baseline = a_out[index]
        token_count = sum(stage["generated_tokens"] for stage in stages)
        center = (fsum(clip(stage_u[stage["event_key"]]) * stage["generated_tokens"] for stage in stages) /
                  token_count) if token_count else 0.0
        other_trajectories = [traj for i, traj in enumerate(trajectories) if i != index]
        for stage in stages:
            key = stage["event_key"]
            u = stage_u[key]
            a_re = baseline + 0.3 * abs(baseline) * (clip(u) - center)
            peers = peer_weights(stage, other_trajectories, progress_key)
            a_st = 0.0
            if peers:
                peer_mean = fsum(w * stage_u[p["event_key"]] for w, p in peers) / fsum(w for w, _ in peers)
                a_st = clip(u - peer_mean)
            output[key] = {"u": u, "A_re": a_re, "A_st": a_st, "A": a_re + 0.3 * a_st,
                           "peer_count": len(peers), "u_center": center}
    return output


def add_progress(stages, evidence, gold):
    """Deduplicate returned labeled documents and bind pre-round progress."""
    targets = evidence | gold
    ever = {"any": set(), "open": set()}
    in_context = {"any": set(), "open": set()}
    by_round = defaultdict(list)
    for stage in stages:
        by_round[stage["round"]].append(stage)
    for members in by_round.values():
        starts = {key: len(seen) / len(evidence) if evidence else 0.0 for key, seen in in_context.items()}
        for stage in members:
            docs = targets & set(stage["docids"]) if stage["return_parsed"] else set()
            for progress in ever:
                eligible = docs if progress == "any" or stage["tool"] == "open" else set()
                stage[f"z_before_{progress}"] = starts[progress]
                stage[f"c_new_{progress}"] = len(eligible - ever[progress])
                ever[progress].update(eligible)
                if stage["observation_visible"]:
                    in_context[progress].update(eligible)
    return {key: len(seen) for key, seen in ever.items()}
