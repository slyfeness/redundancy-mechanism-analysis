"""Join independent branch grades into the existing event-calibration schema."""

from collections import Counter
import re


_BUDGET = {'CONTEXT_LIMIT_STOP', 'SAFETY_CEILING_STOP', 'GENERATION_LENGTH_STOP'}


def paired_calibration_row(case, audited_event, audit_sha256, branches):
    """Use four common seeds and a control that reproduces the archived outcome."""
    event_id, trajectory = case['event_id'], case['trajectory_sha256']
    if (event_id, trajectory) != (audited_event['event_id'], audited_event['trajectory_sha256']):
        raise ValueError('review case does not identify the audited event')
    if type(case['original_correct']) is not bool or type(case['guide_confounded']) is not bool:
        raise ValueError('review must resolve the original outcome and guide status')
    keyed, runtimes = {}, set()
    for result, grade in branches:
        binding = result['identity']
        condition, seed = binding['condition'], binding['seed']
        if (condition not in {'normal', 'delete'} or type(seed) is not int or (seed, condition) in keyed
                or binding['audit_sha256'] != audit_sha256
                or binding['sample_id'] != audited_event['sample_id']
                or binding['event_id'] != event_id or binding['trajectory_sha256'] != trajectory
                or binding['continuation_round'] != audited_event['continuation_round']
                or binding['prefix_sha256'] != audited_event[f'{condition}_prompt_sha256']):
            raise ValueError('branch receipt does not bind a unique audited prefix and seed')
        runtime = binding['runtime_sha256']
        if not isinstance(runtime, str) or not re.fullmatch('[0-9a-f]{64}', runtime):
            raise ValueError('branch runtime identity is missing')
        runtimes.add(runtime)
        terminal = result['terminal']
        if grade is not None and (type(grade) is not bool or terminal != 'MODEL_FINAL_STOP'):
            raise ValueError('independent grade requires a normal submission')
        keyed[seed, condition] = grade if terminal == 'MODEL_FINAL_STOP' else False if terminal in _BUDGET else None

    seeds = sorted({seed for seed, _ in keyed})
    if len(seeds) != 4 or len(keyed) != 8 or len(runtimes) != 1:
        raise ValueError('event requires four common seeds and one shared runtime')
    pairs = [(keyed[seed, 'normal'], keyed[seed, 'delete']) for seed in seeds]
    stable_control = sum(normal is case['original_correct'] for normal, _ in pairs) >= 3
    comparable = stable_control and not case['guide_confounded'] and all(None not in pair for pair in pairs)
    counts = Counter('unresolved' if None in (normal, deleted) else
                     'both_correct' if normal and deleted else 'normal_only_correct' if normal else
                     'delete_only_correct' if deleted else 'both_failed' for normal, deleted in pairs)
    deletions = [{'condition_id': 'single-tool-deletion-v1', 'repetition_id': seed, 'comparable': comparable,
                  'correct': deleted, 'normal_correct': normal, 'intervention_scope': 'single_tool_event',
                  'target_trajectory_sha256': trajectory, 'target_event_id': event_id}
                 for seed, (normal, deleted) in zip(seeds, pairs, strict=True)]
    return {**case, 'deletions': deletions, 'paired_counts': dict(counts), 'stable_control': stable_control}
