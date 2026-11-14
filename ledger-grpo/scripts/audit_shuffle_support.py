"""Audit event relocation and token-weighted debit on the frozen shuffle control."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from math import comb, isfinite, prod
from pathlib import Path
import random
from statistics import fmean, quantiles


def width_support(candidate_widths, targeted_widths):
    pool, targets = Counter(candidate_widths), Counter(targeted_widths)
    if any(pool[width] < count for width, count in targets.items()):
        raise ValueError('targeted widths must be present in the original candidate pool')
    return {'exact_width_subsets': prod(comb(pool[width], count) for width, count in targets.items()),
            'maximum_relocated_events': sum(min(count, pool[width]-count) for width,count in targets.items()),
            'expected_relocated_events': sum(count*(1-count/pool[width]) for width,count in targets.items())}


def width(event):
    start, stop = event['event_tokens']
    if type(start) is not int or type(stop) is not int or not 0 <= start < stop:
        raise ValueError('event must have a positive native token width')
    return stop-start


def debit_mass(events):
    return sum(width(event)*event['price'] for event in events)


def verify_placement(targeted, shuffled, event_pools, *, seed, draws=20000):
    by_arm = []
    for arm in (targeted, shuffled):
        groups = defaultdict(list)
        for debit in arm:
            price = debit['price']
            if type(price) not in (float, int) or not isfinite(price) or price <= 0:
                raise ValueError('saved debit must be positive and finite')
            groups[debit['traj_id']].append(debit)
        by_arm.append(groups)
    targets, controls = by_arm
    if not targets or targets.keys() != controls.keys() or type(draws) is not int or draws < 40:
        raise ValueError('targeted and shuffled charges must match on the same trajectories')

    records, draw_inputs = [], []
    for tid, first in targets.items():
        second = controls[tid]
        pool = sorted(event_pools[tid], key=lambda e:e['event_tokens'][0])
        by_id = {e['event_id']: e for e in pool}
        if len(by_id) != len(pool) or len({d['event_id'] for d in first}) != len(first):
            raise ValueError('candidate and targeted events must have distinct IDs')
        for debit in first+second:
            if by_id[debit['event_id']]['event_tokens'] != debit['event_tokens']:
                raise ValueError('saved debit span differs from original measured event')
        prices = [e['price'] for e in first]
        selected = random.Random(f'{seed}:{tid}').sample(pool,len(prices))
        if [(e['event_id'],p) for e,p in zip(selected,prices,strict=True)] != [(e['event_id'],e['price']) for e in second]:
            raise ValueError('frozen shuffle cannot be reproduced')
        widths, target_widths = list(map(width,pool)), list(map(width,first))
        target_ids = {e['event_id'] for e in first}
        draw_inputs.append((widths, prices))
        records.append({'trajectory_id': tid, 'measured_events': len(pool), 'targeted_events': len(first),
                        'relocated_by_saved_shuffle': sum(e['event_id'] not in target_ids for e in second),
                        'targeted_debit_mass': debit_mass(first), 'shuffled_debit_mass': debit_mass(second),
                        'uniform_shuffle_expected_mass': sum(prices)*fmean(widths),
                        **width_support(widths,target_widths)})

    rng = random.Random(seed)
    resampled = [sum(sum(p*w for p,w in zip(prices,rng.sample(widths,len(prices)),strict=True))
                     for widths,prices in draw_inputs) for _ in range(draws)]
    interval = quantiles(resampled,n=40,method='inclusive')
    original, shuffled_mass = debit_mass(targeted), debit_mass(shuffled)
    return {'charged_trajectories': len(records), 'charged_events': len(targeted),
            'saved_shuffle_relocated_events': sum(row['relocated_by_saved_shuffle'] for row in records),
            'targeted_debit_mass': original, 'saved_shuffled_debit_mass': shuffled_mass,
            'saved_shuffled_minus_targeted_percent': 100*(shuffled_mass/original-1),
            'uniform_shuffle_expected_mass': sum(row['uniform_shuffle_expected_mass'] for row in records),
            'uniform_shuffle_debit_mass_95_percent_range': [interval[0],interval[-1]],
            'draws': draws, 'seed': seed,
            'exact_width_subsets': prod(row['exact_width_subsets'] for row in records),
            'exact_width_maximum_relocated_events': sum(row['maximum_relocated_events'] for row in records),
            'exact_width_expected_relocated_events': sum(row['expected_relocated_events'] for row in records),
            'trajectories': records}


def main():
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scored = args.run/'scored'
    paths = {arm:scored/f'{arm}-scores.pt' for arm in ('targeted','shuffled')}
    saved = {arm:torch.load(path, map_location='cpu', weights_only=True) for arm,path in paths.items()}
    with (scored/'NATIVE_BATCH.json').open('rb') as handle:
        batch_sha = hashlib.file_digest(handle,'sha256').hexdigest()
    if (any(row['control'] != arm or row['input_binding']['native_batch_sha256'] != batch_sha for arm,row in saved.items())
            or saved['targeted']['config'] != saved['shuffled']['config']):
        raise ValueError('expected both controls from the same frozen training batch and configuration')
    target = saved['targeted']['charged']
    pools = {tid:json.loads((scored/tid/'events.json').read_bytes())['events'] for tid in {row['traj_id'] for row in target}}
    report = verify_placement(target,saved['shuffled']['charged'],pools,seed=saved['targeted']['config']['seed'])
    report.update(scope='Frozen assignments and simulated random event placements. Debit mass is price times policy span width, before optimizer weighting.',
                  source_run=str(args.run),native_batch_sha256=batch_sha)
    with args.output.open('x',encoding='utf-8') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({key:value for key,value in report.items() if key!='trajectories'}),flush=True)


if __name__ == '__main__':
    main()
