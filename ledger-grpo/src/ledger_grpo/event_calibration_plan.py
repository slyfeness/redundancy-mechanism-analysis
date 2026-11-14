"""Freeze intervention cases and matched seeds before continuation."""

from collections import defaultdict
import random


def freeze_event_cases(events, tasks, heldout_ids, *, seed, max_rounds, selection=None):
    if set(tasks.values()) & set(heldout_ids):
        raise ValueError('calibration source overlaps the held-out tasks')
    grouped = defaultdict(list)
    identities = set()
    for event in events:
        sample = event['sample_id']
        key = sample, event['event_id']
        if key in identities or sample not in tasks:
            raise ValueError('prefix audit must bind each event to a unique source sample')
        identities.add(key)
        if event['parallel_calls'] == 1 and 2 <= event['continuation_round'] < max_rounds:
            grouped[tasks[sample]].append(event)
    if not grouped or (selection is None and set(grouped) != set(tasks.values())):
        raise ValueError('every source task must have an eligible event')

    randomizer = random.Random(seed)
    cases = (_engineering_cases(grouped, randomizer) if selection is None
             else _selected_cases(grouped, tasks, selection))
    randomizer.shuffle(cases)
    seeds = iter(randomizer.sample(range(1, 2**31), 4*len(cases)))
    for index, case in enumerate(cases, 1):
        case['case_id'] = f'E{index:03d}'
        orders = [['normal','delete'], ['delete','normal']] * 2
        randomizer.shuffle(orders)
        case['blocks'] = [{'seed': next(seeds), 'order': order} for order in orders]
    return {'design_seed': seed, 'max_rounds': max_rounds, 'eligible_events': sum(map(len, grouped.values())),
            'eligible_events_by_task': {task: len(eligible) for task, eligible in sorted(grouped.items())},
            'cases': cases}


def _selected_cases(grouped, tasks, selection):
    eligible = {(event['sample_id'], event['event_id']): event
                for events in grouped.values() for event in events}
    if not isinstance(selection, list) or not selection:
        raise ValueError('calibration selection requires a nonempty event list')
    keys = []
    for row in selection:
        if (not isinstance(row, dict) or set(row) != {'sample_id', 'event_id'}
                or any(not isinstance(value, str) for value in row.values())):
            raise ValueError('select each calibration event by sample ID and event ID')
        keys.append((row['sample_id'], row['event_id']))
    if len(set(keys)) != len(keys) or any(key not in eligible for key in keys):
        raise ValueError('calibration selection must contain unique, eligible events')
    return [{'task_id': tasks[key[0]], 'event': eligible[key]} for key in sorted(keys)]


def _engineering_cases(grouped, randomizer):
    cases = []
    for task, eligible in sorted(grouped.items()):
        eligible.sort(key=lambda row: (row['continuation_round'], row['sample_id'], row['event_id']))
        rounds = sorted({row['continuation_round'] for row in eligible})
        boundary = rounds[(len(rounds)-1)//2]
        early = [row for row in eligible if row['continuation_round'] <= boundary]
        late = [row for row in eligible if row['continuation_round'] > boundary]
        late_samples = {row['sample_id'] for row in late}
        early = [row for row in early if late_samples - {row['sample_id']}]
        if not early:
            raise ValueError('each source task needs an earlier and later event from distinct trajectories')
        first = randomizer.choice(early)
        second = randomizer.choice([row for row in late if row['sample_id'] != first['sample_id']])
        cases.extend({'task_id': task, 'depth': depth, 'event': event}
                     for depth, event in (('earlier', first), ('later', second)))

    return cases
