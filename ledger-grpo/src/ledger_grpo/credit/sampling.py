"""Whole-group ledger sampling and loss-level Horvitz--Thompson correction."""
import hashlib
import json
import math
import random


def _probability(q):
    if not isinstance(q, (float, int)) or not math.isfinite(q) or not 0 < q <= 1:
        raise ValueError('ledger sampling probability must be in (0, 1]')


def select_group(qid, training_step, q=1., seed=0):
    _probability(q)
    key = json.dumps([seed, training_step, str(qid)], ensure_ascii=False, separators=(',', ':')).encode()
    value = int.from_bytes(hashlib.sha256(key).digest()[:8], 'big') / 2**64
    return value < q


def corrected_loss(base_loss, full_loss, selected, q, correction=True):
    _probability(q)
    if not selected:
        return base_loss
    if full_loss is None:
        raise ValueError('selected groups require the full loss')
    return base_loss + (full_loss - base_loss) / q if correction else full_loss


def select_review_units(rows, top_fraction, random_fraction, *, seed=0):
    if not 0 <= top_fraction <= 1 or not 0 <= random_fraction <= 1:
        raise ValueError('review fractions must be in [0, 1]')
    ids = [row['unit'] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('review unit ids must be unique')
    priority = lambda row: row['tokens'] * abs(row['delta_advantage']) * row['error_rate']
    ranked = sorted(enumerate(rows), key=lambda item: (-priority(item[1]), item[0]))
    selected = {row['unit'] for _, row in ranked[:math.ceil(len(rows) * top_fraction)]}
    remaining = [u for u in ids if u not in selected]
    rng = random.Random(seed)
    selected.update(rng.sample(remaining, math.ceil(len(remaining) * random_fraction)))
    return [u for u in ids if u in selected]


def merge_review_confidence(primary, secondary):
    if not set(secondary).issubset(primary):
        raise ValueError('review cannot introduce unknown units')
    return {u: u not in secondary or primary[u] == secondary[u] for u in primary}
