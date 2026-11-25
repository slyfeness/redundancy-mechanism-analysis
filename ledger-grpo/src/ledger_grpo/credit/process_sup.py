"""Optional, explicit process supervision; never changes the reference allocator."""
import math


def _get(config, name, default=None):
    return config.get(name, default) if isinstance(config, dict) else getattr(config, name, default)


def _trajectories(group):
    return group.trajectories if hasattr(group, 'trajectories') else group


def eligible_group(group, credits):
    trajectories = list(_trajectories(group))
    if not trajectories or len(trajectories) != len(credits):
        raise ValueError('process supervision needs one credit result per trajectory')
    outcomes = [t.get('outcome', {}) if isinstance(t, dict) else t.outcome for t in trajectories]
    return (all(abs(c['A_hat']) < 1e-6 for c in credits)
            or all(not o.get('Y', False) for o in outcomes))


def verified_decision_tag(tag):
    return (tag.startswith('采纳') or tag.startswith('有效排除')
            or (tag.startswith('取到') and not tag.endswith('(未被用)')))


def select_masked_nll_units(group, credits, config):
    selected = [set() for _ in credits]
    if _get(config, 'process_sup', 'off') != 'masked_nll' or not eligible_group(group, credits):
        return selected
    for target, credit in zip(selected, credits):
        for unit, role in credit['role'].items():
            if (unit != 'F' and role == 'C'
                    and any(size > 0 and verified_decision_tag(tag)
                            for size, tag in credit['P'].get(unit, []))):
                target.add(unit)
    return selected


def _waterfill(units, weights, nu, mass, cap):
    """Allocate a prescribed token-weighted mass; finite sorted saturation."""
    values = {u: 0. for u in units}
    order = sorted((u for u in units if weights[u] > 0 and nu[u] > 0),
                   key=lambda u: nu[u] * cap / weights[u])
    remaining, total_weight = mass, sum(weights[u] for u in order)
    for index, unit in enumerate(order):
        level = remaining / total_weight
        capacity = nu[unit] * cap
        if level * weights[unit] > capacity:
            values[unit] = cap
            remaining -= capacity
            total_weight -= weights[unit]
        else:
            for receiver in order[index:]:
                values[receiver] = level * weights[receiver] / nu[receiver]
            break
    return values


def zero_sum_for_trajectory(credit, config):
    alpha, kappa = float(_get(config, 'alpha_zs', .1)), float(_get(config, 'kappa', 3.))
    if not math.isfinite(alpha) or not math.isfinite(kappa) or alpha < 0 or kappa <= 0:
        raise ValueError('invalid zero-sum scale or cap')
    nu, roles, weights = credit['nu'], credit['role'], credit['e']
    result = {u: 0. for u in roles}
    sides = [[u for u in roles if u != 'F' and roles[u] == role and weights[u] > 0 and nu[u] > 0]
             for role in ('C', 'R')]
    log = {'positive_mass': 0., 'negative_mass': 0., 'one_sided': not all(sides),
           'cap': kappa * alpha, 'weighted_sum': 0.}
    if not all(sides) or alpha == 0:
        return result, log
    cap = kappa * alpha
    mass = min(alpha, *(sum(nu[u] * cap for u in side) for side in sides))
    for sign, side in zip((1., -1.), sides):
        for unit, value in _waterfill(side, weights, nu, mass, cap).items():
            result[unit] = sign * value
    log.update(positive_mass=sum(nu[u] * max(s, 0.) for u, s in result.items()),
               negative_mass=sum(nu[u] * max(-s, 0.) for u, s in result.items()),
               weighted_sum=sum(nu[u] * s for u, s in result.items()))
    return result, log


def masked_nll_loss(logprobs, selected_mask, *, denominator):
    """No negative-label likelihood reversal; uses the RL fixed denominator."""
    import torch
    if denominator <= 0 or logprobs.shape != selected_mask.shape:
        raise ValueError('NLL mask shape and positive denominator are required')
    mask = selected_mask.to(device=logprobs.device, dtype=torch.bool)
    return -logprobs.masked_fill(~mask, 0.).sum() / denominator
