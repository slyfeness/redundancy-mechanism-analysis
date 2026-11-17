"""Bind a single native policy batch to R2b prices and a zero-price R1 sidecar."""

from collections import Counter
from copy import deepcopy
import re

from .event_price import score_event_prices, validate_events
from .hf_native import native_turn_layout


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _sha256(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _labeler_versions(versions):
    if not isinstance(versions, dict) or not _nonempty(versions.get('judge_model')):
        raise ValueError('labeler_versions requires the judge_model identity')
    prompts = versions.get('prompt_hashes')
    if (not isinstance(prompts, dict) or not prompts
            or any(not _nonempty(name) or not _sha256(digest) for name, digest in prompts.items())):
        raise ValueError('labeler_versions requires named SHA-256 prompt_hashes')
    commit = versions.get('code_commit')
    if not isinstance(commit, str) or re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit) is None:
        raise ValueError('labeler_versions requires the full code_commit digest')
    return deepcopy(versions)


def _indexed(records, key, role):
    result = {}
    for row in records:
        identity = row.get(key) if isinstance(row, dict) else None
        if not _nonempty(identity) or identity in result:
            raise ValueError(f'{role} requires unique nonempty {key} values')
        result[identity] = row
    return result


def _native_events(row, turns):
    if not isinstance(row.get('events'), list):
        raise ValueError('events must be a list')
    try:
        events = validate_events(row)
    except (IndexError, KeyError, TypeError) as error:
        raise ValueError('malformed native event receipt') from error
    turn_index, previous_index, previous_turn = 0, -1, -1
    for event in events:
        if event['label'] not in (None, 'R2b'):
            raise ValueError('pricing events require R2b or null labels')
        turn = event['turn_id']
        if type(turn) is not int or type(event['known_at']) is not int or turn < 0:
            raise ValueError('event known_at and turn_id must be nonnegative integer observation boundaries')
        start, stop = event['event_tokens']
        while turn_index < len(turns) and turns[turn_index]['token_end'] <= start:
            turn_index += 1
        if (turn_index == len(turns)
                or not turns[turn_index]['token_start'] <= start < stop <= turns[turn_index]['token_end']):
            raise ValueError('event span must belong to one native policy turn')
        # BrowseComp uses recorder round IDs, which can skip calls with no policy tokens.
        if turn_index == previous_index and previous_turn != turn:
            raise ValueError('events within one native policy turn disagree on turn_id')
        if turn_index != previous_index and turn <= previous_turn:
            raise ValueError('event turn_id must follow native turn order')
        previous_index, previous_turn = turn_index, turn
    return events


def _exclusion_reason(row, mask):
    explicit = row.get('exclusion_reason')
    if explicit is not None:
        if not _nonempty(explicit):
            raise ValueError('exclusion_reason must be a nonempty string')
        return explicit
    if row['outcome'] is None:
        return 'unresolved_outcome'
    if not row['recording_complete']:
        return 'recording_incomplete'
    if not any(mask):
        return 'no_policy_tokens'
    stop = row['termination_reason']
    if stop != 'normal' and not (stop == 'budget_exhausted' and row['outcome'] == 0):
        return f'termination_{stop}'
    return None


def _r1_sidecar(diagnostics, pricing_rows, dispositions, snapshot):
    index = {row['traj_id']: i for i, row in enumerate(pricing_rows)}
    measured = {(row['traj_id'], event['event_id']): event['turn_id']
                for row in pricing_rows for event in row['events']}
    entries, seen = [], set()
    for record in diagnostics:
        if not isinstance(record, dict):
            raise ValueError('R1 diagnostic must be an object')
        traj, event = record.get('traj_id'), record.get('event_id')
        if not _nonempty(traj) or traj not in index or not _nonempty(event) or (traj, event) in seen:
            raise ValueError('R1 diagnostic requires a unique event ID within its expected native trajectory')
        receipt = dispositions[index[traj]]
        if record.get('task_id') != receipt['task_id'] or record.get('policy_snapshot_id') != snapshot:
            raise ValueError('R1 diagnostic task or policy snapshot does not match the native trajectory')
        turn, known = record.get('turn_id'), record.get('known_at')
        if (type(turn) is not int or type(known) is not int or not 0 <= known <= turn
                or measured.get((traj, event), turn) != turn):
            raise ValueError('R1 diagnostic must match the observed turn and use a causal known_at')
        if record.get('prediction') not in ('positive', 'negative', 'uncertain') or not _nonempty(record.get('reason')):
            raise ValueError('R1 diagnostic requires a valid prediction and reason')
        versions = record.get('labeler_versions', receipt['labeler_versions'])
        entries.append({**{key: record[key] for key in ('traj_id', 'task_id', 'policy_snapshot_id', 'event_id',
                                                        'turn_id', 'known_at', 'prediction', 'reason')},
                        'labeler_versions': _labeler_versions(versions)})
        seen.add((traj, event))
    entries.sort(key=lambda row: (index[row['traj_id']], row['turn_id']))
    return {'policy_snapshot_id': snapshot, 'label': 'R1', 'price': 0.0, 'diagnostics': entries}


def score_coexist_handoff(rows, config, *, native_batch, expected_policy_snapshot_id, r1_diagnostics=()):
    """Validate the original batch, then score only native R2b marks in batch order.

    Each score-events row carries policy_snapshot_id, labeler_versions, and an
    optional exclusion_reason. The R1 sidecar has event-level predictions and
    may cover recorder events without measurable native token spans.
    """
    snapshot = expected_policy_snapshot_id
    if not _nonempty(snapshot) or not isinstance(native_batch, dict):
        raise ValueError('an expected policy snapshot and native batch are required')
    binding = [native_batch[key] for key in ('policy_snapshot_id', 'policy_snapshot_sha256') if key in native_batch]
    if 'policy_snapshot_sha256' in native_batch and not _sha256(native_batch['policy_snapshot_sha256']):
        raise ValueError('invalid native policy snapshot SHA-256')
    if not binding or any(value != snapshot for value in binding):
        raise ValueError('native batch does not match the expected policy snapshot')
    if config.r1_price or config.r2a_price:
        raise ValueError('coexist handoff prices R2b only')

    trajectories = native_batch.get('trajectories')
    if not isinstance(trajectories, list) or not trajectories:
        raise ValueError('native batch requires a nonempty trajectories list')
    native = _indexed(trajectories, 'id', 'native batch')
    by_id = _indexed(rows, 'traj_id', 'scoring rows')
    if native.keys() != by_id.keys():
        raise ValueError('scoring rows must cover exactly the native trajectory IDs')

    pricing_rows, dispositions = [], []
    for traj, original in native.items():
        row = by_id[traj]
        task, reward = original.get('query_id'), original.get('reward')
        if not _nonempty(task) or row.get('task_id') != task:
            raise ValueError(f'{traj}: task_id does not match the native query_id')
        outcome = row.get('outcome')
        if ('reward' not in original or 'outcome' not in row or outcome != reward
                or (outcome is not None and type(outcome) is not int)
                or (reward is not None and (type(reward) not in (int, float) or reward not in (0, 1)))):
            raise ValueError(f'{traj}: outcome does not match the independently verified native reward')
        if row.get('policy_snapshot_id') != snapshot:
            raise ValueError(f'{traj}: policy_snapshot_id does not match the expected policy snapshot')
        versions = _labeler_versions(row.get('labeler_versions'))
        if type(row.get('recording_complete')) is not bool or not _nonempty(row.get('termination_reason')):
            raise ValueError(f'{traj}: recording_complete and termination_reason are required')
        ground = row.get('grounding')
        if ('grounding' not in row or ground is not None
                and (type(ground) not in (int, float) or not 0 <= ground <= 1)):
            raise ValueError(f'{traj}: grounding must be a validated proportion or null')
        layout = native_turn_layout(original)
        mask = row.get('response_mask')
        if (mask != layout['response_mask'] or not isinstance(mask, list)
                or any(type(bit) not in (bool, int) or bit not in (0, 1) for bit in mask)):
            raise ValueError(f'{traj}: response_mask does not match the exact native span layout')
        events = _native_events(row, layout['turns'])
        exclusion = _exclusion_reason(row, mask)
        pricing_rows.append({**row, 'events': events, 'recording_complete': exclusion is None})
        dispositions.append(dict(traj_id=traj, task_id=task, policy_snapshot_id=snapshot, labeler_versions=versions,
                                 reason=exclusion, r2b_event_ids=[event['event_id'] for event in events
                                                                 if event['label'] == 'R2b']))

    scores = score_event_prices(pricing_rows, config, arm='targeted')
    counts = Counter(row['task_id'] for row in pricing_rows)
    for receipt, valid in zip(dispositions, scores['valid_rows'].tolist(), strict=True):
        if valid:
            receipt.update(status='marked', reason='r2b_marked' if receipt['r2b_event_ids'] else 'no_r2b_marks')
        else:
            reason = 'incomplete_native_group' if counts[receipt['task_id']] != config.group_size else 'peer_trajectory_excluded'
            receipt.update(status='excluded', reason=receipt['reason'] or reason)
    return {'scores': scores, 'dispositions': dispositions,
            'r1_sidecar': _r1_sidecar(r1_diagnostics, pricing_rows, dispositions, snapshot)}
