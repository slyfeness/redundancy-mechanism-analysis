"""Exact model-call ownership on the existing native probability-ratio axis."""
from collections import OrderedDict
import math
import torch

from .schema import Unit


def units_from_stages(stages, span_offsets=None):
    """Merge split M1 stages by model call, retaining every parallel return."""
    offsets = span_offsets or {0: 0}
    calls = OrderedDict()
    for stage in stages:
        call = stage['model_call_index']
        entry = calls.setdefault(call, {'ranges': set(), 'events': [], 'kind': stage['unit_type']})
        span = stage.get('span_id')
        left, right = stage['gen_token_range']
        if right > left:
            if span not in offsets:
                raise ValueError('span offset is required for every M1 stage')
            entry['ranges'].add((offsets[span] + left, offsets[span] + right))
        entry['events'].extend(stage.get('tool_events', []))
    result, tool_index = [], 0
    for call, entry in calls.items():
        events, ranges = entry['events'], sorted(entry['ranges'])
        if not ranges:
            continue
        final = not events and call == next(reversed(calls)) and entry['kind'] in ('final', 'abstain')
        if final:
            uid = 'F'
        else:
            tool_index += 1
            uid = tool_index
        unique_events, seen = [], set()
        for event in events:
            identity = event.get('event_id') or event.get('tool_call_id')
            if identity is None or identity not in seen:
                unique_events.append(event)
            seen.add(identity)
        result.append(Unit(uid, ranges, sum(b-a for a,b in ranges),
                           sum(e['obs_tokens'] for e in unique_events),
                           [e['tool_name'] for e in unique_events], call,
                           'final' if final else 'tool' if events else 'unfinished'))
    return result


def write_token_advantages(trajectory, advantages):
    mask = trajectory.response_mask
    if not isinstance(mask, list) or any(type(x) not in (int, bool) or x not in (0, 1) for x in mask):
        raise ValueError('response mask must be binary')
    dense = torch.zeros(len(mask), dtype=torch.float64)
    owners = [None] * len(mask)
    for unit in trajectory.units:
        value = advantages.get(unit.unit_id)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('every unit requires a finite advantage')
        for start, stop in unit.token_ranges:
            if stop > len(mask):
                raise ValueError('unit token range outside probability-ratio axis')
            for pos in range(start, stop):
                if not mask[pos] or owners[pos] is not None:
                    raise ValueError('unit owns a prompt/tool token or overlaps another unit')
                owners[pos] = unit.unit_id
                dense[pos] = value
    if any(bool(m) != (owner is not None) for m, owner in zip(mask, owners)):
        raise ValueError('every probability-ratio token must belong to exactly one unit')
    return {'advantages': dense, 'mask': torch.tensor(mask, dtype=torch.bool), 'owners': owners}
