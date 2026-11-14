"""Leave-one-out outcome credit and explicit prices on policy tool events."""

from collections import defaultdict
from dataclasses import dataclass
import math
from pathlib import Path
import random
import re
from statistics import median

import torch


@dataclass(frozen=True)
class EventPriceConfig:
    group_size: int
    loss_denominator: int
    median_event_cost: float
    price_fraction: float = 1.0
    grounding_weight: float = 0.1
    r1_price: float = 0.0
    r2a_price: float = 0.0
    r2b_price: float = 0.10
    uniform_price: float = 0.02
    trajectory_cap: float = 0.5
    seed: int = 20261111

    def __post_init__(self):
        if type(self.group_size) is not int or self.group_size < 2:
            raise ValueError('group_size must be an integer >= 2')
        if type(self.loss_denominator) is not int or self.loss_denominator <= 0:
            raise ValueError('loss_denominator must be a positive fixed integer')
        if not math.isfinite(self.median_event_cost) or self.median_event_cost <= 0:
            raise ValueError('median_event_cost must be positive and finite')
        if not 0 <= self.price_fraction <= 1:
            raise ValueError('price_fraction must be in [0,1]')
        for value in (self.grounding_weight, self.r1_price, self.r2a_price,
                      self.r2b_price, self.uniform_price, self.trajectory_cap):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('weights and prices must be finite and in [0,1]')


def event_cost(event):
    parts = event['event_cost']
    values = [parts[k] for k in ('generated_tokens', 'returned_tokens', 'tool_calls')]
    if any(type(x) is not int or x < 0 for x in values) or values[-1] != 1:
        raise ValueError('each priced event must have one call and measured nonnegative token costs')
    return sum(values)


def calibrate_event_cost(rows):
    costs = [event_cost(event) for row in rows for event in row['events']]
    if not costs:
        raise ValueError('a reference batch with measured event costs is required')
    return float(median(costs))


def scheduled_price_fraction(update, *, warmup, ramp):
    if any(type(x) is not int for x in (update,warmup,ramp)) or update < 1 or warmup < 0 or ramp < 1:
        raise ValueError('expected a positive update, nonnegative warmup and positive ramp')
    return min(1., max(0, update-warmup)/ramp)


def verify_semantic_calibration(config, receipts=None):
    """Recompute the pricing gates from the bound event-level audit data."""
    from .evaluation import read_event_calibration

    verified = {}
    if not config.price_fraction or not config.trajectory_cap:
        return verified
    for label, price in (('R1', config.r1_price), ('R2a', config.r2a_price)):
        if not price:
            continue
        try:
            receipt = (receipts or {})[label]
            path, digest = Path(receipt['cases_path']), receipt['evaluation_manifest_sha256']
            if not path.is_absolute() or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('expected an absolute path and SHA-256')
            measured = read_event_calibration(path, expected_sha256=digest, require_event_binding=True)[label]
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f'{label} requires event-bound calibration before pricing') from error
        if measured['counts'].get('engineering_cases'):
            raise ValueError(f'{label} engineering cases cannot establish calibration for pricing')
        precision, marked, contamination = (measured[k] for k in ('precision', 'bplus_mark_rate', 'bplus_contamination'))
        if (None in (precision, marked, contamination) or precision < .9 or marked > .05 or contamination > .05):
            raise ValueError(f'{label} requires deletion/human calibration before pricing')
        verified[label] = digest
    return verified


def validate_events(row):
    mask = row['response_mask']
    events = sorted(row['events'], key=lambda e: e['event_tokens'][0])
    end, seen = 0, set()
    for event in events:
        start, stop = event['event_tokens']
        identity = event['event_id']
        if (not isinstance(identity, str) or not identity or identity in seen
                or type(start) is not int or type(stop) is not int
                or not end <= start < stop <= len(mask) or not all(mask[start:stop])):
            raise ValueError('each event must own unique, non-overlapping policy tokens')
        if event['event_cost']['generated_tokens'] != stop-start:
            raise ValueError('event generation cost disagrees with its native span')
        if event['known_at'] != event['turn_id']:
            raise ValueError('event label must be decided at its own observation boundary')
        if event['label'] not in (None, 'R1', 'R2a', 'R2b'):
            raise ValueError('unsupported priced label')
        event_cost(event)
        seen.add(identity)
        end = stop
    return events


def _trainable(row):
    return (row['outcome'] in (0, 1) and row['recording_complete'] is True
            and bool(any(row['response_mask'])) and
            (row['termination_reason'] == 'normal' or
             (row['termination_reason'] == 'budget_exhausted' and row['outcome'] == 0)))


def score_event_prices(rows, config, *, arm='targeted', semantic_calibration=None):
    """Consume verified event coordinates. Failed rows can pay via their peers.

    Ablations share outcome/grounding among process arms. Random placement
    reuses the exact per-event prices on a uniform sample of distinct events.
    Uniform charges a prespecified small price on all measurable events.
    Trajectory broadcasts the mean local debit only on successful trajectories.
    """
    if arm not in {'outcome', 'trajectory', 'targeted', 'shuffled', 'uniform'}:
        raise ValueError('unknown event-price experiment arm')
    verified = verify_semantic_calibration(config, semantic_calibration) if arm in {'trajectory','targeted','shuffled'} else {}
    if not rows or len({row['traj_id'] for row in rows}) != len(rows):
        raise ValueError('expected a nonempty batch with unique trajectory identities')
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row['task_id']].append(index)
        if any(type(bit) not in (bool, int) or bit not in (0, 1) for bit in row['response_mask']):
            raise ValueError('response mask must be binary')
    events = [validate_events(row) for row in rows]
    width = max(len(row['response_mask']) for row in rows)
    advantages = torch.zeros((len(rows), width), dtype=torch.float32)
    effective = torch.zeros_like(advantages, dtype=torch.bool)
    valid = torch.zeros(len(rows), dtype=torch.bool)
    base_advantages = torch.zeros(len(rows), dtype=torch.float32)
    prices = {'R1': config.r1_price, 'R2a': config.r2a_price, 'R2b': config.r2b_price, None: 0.0}
    dropped, all_wrong, charged = [], [], []
    metrics = dict(peer_gate_open_rows=0, retained_budget_failures=0, grounding_observed=0,
                   charged_events=0, charged_policy_tokens=0, charged_budget_events=0,
                   charged_total=0.0, ground_bonus_total=0.0)
    for task, indices in groups.items():
        if len(indices) != config.group_size or not all(_trainable(rows[i]) for i in indices):
            dropped.append(task)
            continue
        correct = sum(rows[i]['outcome'] for i in indices)
        if not correct:
            all_wrong.append(task)
        rewards = []
        for i in indices:
            row = rows[i]
            g = row.get('grounding')
            if g is not None and (type(g) not in (int, float) or not math.isfinite(g) or not 0 <= g <= 1):
                raise ValueError('grounding must be a validated proportion or unknown')
            bonus = (config.grounding_weight * g if g is not None and row['outcome'] and arm != 'outcome' else 0.)
            rewards.append(row['outcome'] + bonus)
            metrics['grounding_observed'] += int(row['outcome'] == 1 and g is not None)
            metrics['ground_bonus_total'] += bonus
        for i, reward in zip(indices, rewards, strict=True):
            row = rows[i]
            valid[i] = True
            effective[i, :len(row['response_mask'])] = torch.tensor(row['response_mask'], dtype=torch.bool)
            base_advantages[i] = reward - (sum(rewards) - reward) / (config.group_size-1)
            advantages[i, effective[i]] = base_advantages[i]
            peer = correct - row['outcome'] > 0
            budget = row['termination_reason'] == 'budget_exhausted'
            metrics['peer_gate_open_rows'] += int(peer)
            metrics['retained_budget_failures'] += int(budget)
            gate_open = row['outcome'] == 1 if arm == 'trajectory' else peer
            if arm == 'outcome' or not gate_open:
                continue
            if arm == 'uniform':
                debits = [(e, config.uniform_price*config.price_fraction) for e in events[i]
                          if config.uniform_price and config.price_fraction]
            else:
                debits = [(e, prices[e['label']] * config.price_fraction * min(2., event_cost(e)/config.median_event_cost))
                          for e in events[i] if prices[e['label']] and config.price_fraction]
            if not debits:
                continue
            total = sum(p for _, p in debits)
            scale = min(1., config.trajectory_cap/total)
            debits = [(e, p*scale) for e,p in debits if p*scale > 0]
            if arm == 'trajectory':
                broadcast = sum((e['event_tokens'][1]-e['event_tokens'][0])*p for e,p in debits) / int(effective[i].sum())
                advantages[i, effective[i]] -= broadcast
                metrics['charged_policy_tokens'] += int(effective[i].sum()) if broadcast else 0
            else:
                if arm == 'shuffled':
                    rng = random.Random(f'{config.seed}:{row["traj_id"]}')
                    debits = list(zip(rng.sample(events[i], len(debits)), [p for _,p in debits], strict=True))
                for e,p in debits:
                    start,stop = e['event_tokens']
                    advantages[i,start:stop] -= p
                    metrics['charged_policy_tokens'] += stop-start
            metrics['charged_events'] += len(debits)
            metrics['charged_budget_events'] += len(debits) if budget else 0
            metrics['charged_total'] += sum(p for _,p in debits)
            charged.extend({'traj_id': row['traj_id'], 'event_id': e['event_id'],
                            'event_tokens': e['event_tokens'], 'price': p} for e,p in debits)
    metrics.update(valid_row_count=int(valid.sum()), invalid_training_groups=dropped,
                   all_wrong_groups=all_wrong, effective_action_tokens=int(effective.sum()))
    result = dict(advantages=advantages, effective_response_mask=effective, valid_rows=valid,
                  trajectory_advantage=base_advantages,
                  process_inputs=[{k: row[k] for k in ('traj_id','task_id','response_mask')} for row in rows],
                  metrics=metrics, charged=charged, loss_denominator=config.loss_denominator,
                  control=arm, skip_update=not bool((advantages != 0).any()))
    if verified:
        result['semantic_calibration_sha256'] = verified
    return result
