"""Offline lexical diagnostics on the original judge inputs for pilot 182516."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import secrets

from ledger_grpo.browsecomp_adapter import canonical_candidate, submitted_candidate
from ledger_grpo.evaluation import paired_bootstrap
from regrade_pilot import ARMS, bind_arm, read, sha


def lexical_signals(final, gold, *, complete):
    """Report normalized equality and bounded text presence as distinct signals."""
    if not complete:
        return 'terminal_failure', False, False
    expected = canonical_candidate(gold)
    if not expected:
        raise ValueError('empty normalized gold answer')
    whole = canonical_candidate(final)
    fields = {value for line in final.splitlines() if (value := submitted_candidate(line))}
    present = re.search(rf'(?<!\w){re.escape(expected)}(?!\w)', whole) is not None
    if len(fields) > 1:
        return 'conflicting_answers', False, present
    if whole == expected:
        return 'whole_match', True, True
    if fields == {expected}:
        return 'explicit_match', True, True
    return 'explicit_mismatch' if fields else 'no_explicit_answer', False, present


def score_arm(source, arm, frozen, samples):
    summary, _, binding = bind_arm(source, arm, frozen, samples)
    inputs = read(source/f'eval-{arm}'/'LOCAL_JUDGE_INPUT.json')
    counts, alignment, scored = Counter(), {}, {'strict_match': [], 'literal_presence': []}
    for row, original in zip(summary['rows'], inputs, strict=True):
        status, strict, presence = lexical_signals(original['final'], original['gold'], complete=row['complete'])
        counts[status] += 1
        counts['strict_match'] += int(strict)
        counts['literal_presence'] += int(presence)
        counts['strict_matches_missing_formal_verdict'] += int(strict and row['outcome'] is None)
        counts['literal_presence_missing_formal_verdict'] += int(presence and row['outcome'] is None)
        for key, positive in (('strict_match', strict), ('literal_presence', presence)):
            scored[key].append(dict(row, outcome=int(positive)))
            if row['outcome'] is not None:
                category = ('t' if positive == bool(row['outcome']) else 'f') + ('p' if positive else 'n')
                alignment.setdefault(key, Counter())[category] += 1
    return {'sample_count': summary['sample_count'], 'completion_count': sum(r['complete'] for r in summary['rows']),
            'counts': dict(counts), 'formal_verdicts_available': summary['resolved_count'],
            'agreement_against_available_formal_verdicts': alignment, 'binding': binding}, scored


def export_discordance(run, rows, output):
    arms = ('outcome', 'targeted')
    signals = [rows[arm]['literal_presence'] for arm in arms]
    inputs = [read(run/f'eval-{arm}'/'LOCAL_JUDGE_INPUT.json') for arm in arms]
    blinded, selected = [], []
    for i, (left, right) in enumerate(zip(*signals, strict=True)):
        if (left['task_id'], left['sample_id']) != (right['task_id'], right['sample_id']):
            raise ValueError('discordance cases must share frozen sample identities')
        if left['outcome'] == right['outcome']:
            continue
        selected.append(left['sample_id'])
        for arm, row, saved in zip(arms, (left, right), inputs, strict=True):
            if row['complete']:
                blinded.append(({'task_id': row['task_id'], 'question': saved[i]['question'],
                                 'gold': saved[i]['gold'], 'final': saved[i]['final']},
                                {'arm': arm, 'sample_id': row['sample_id'], 'literal_presence': bool(row['outcome'])}))
    secrets.SystemRandom().shuffle(blinded)
    output.mkdir(mode=0o700, exist_ok=False)
    packet, identities = [], {}
    for i, (sample, binding) in enumerate(blinded, 1):
        case_id = f'case-{i:02d}'
        packet.append(dict(sample, case_id=case_id))
        identities[case_id] = binding
    for name, data in [('PACKET.json', packet), ('IDENTITIES.json', {'cases': identities, 'selected_pairs': selected})]:
        with (output/name).open('x', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False)
    print('discordant_pairs', len(selected), 'normal_submissions', len(packet), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--blind-discordance-dir', type=Path)
    args = parser.parse_args()
    run = args.store/'runs/pilot-182516'
    receipt = read(run/'BASELINE_EVALUATION_RECEIPT.json')
    p0_run = args.store/'runs'/receipt['run_name']
    if sha(p0_run/'EVAL-P0.json') != receipt['summary_sha256'] or read(p0_run/'EVAL-P0.json') != read(run/'EVAL-P0.json'):
        raise ValueError('P0 evaluation identity differs from the frozen original')
    plan = args.store/'plans/pilot-182406/PRIVATE_PLAN.json'
    tasks = read(plan)['evaluation_rows']
    frozen = {str(t['query_id']): t for t in tasks}
    if len(tasks) != len(frozen) or len(frozen) != 16:
        raise ValueError('expected sixteen frozen evaluation tasks')
    samples = [(str(t['query_id']), f"{t['query_id']}__rep{rep+1}", 2026111100+i*8+rep, t['question_sha256'])
               for i, t in enumerate(tasks) for rep in range(8)]
    results, rows = {}, {}
    for arm in ('P0', *ARMS):
        results[arm], rows[arm] = score_arm(p0_run if arm == 'P0' else run, arm, frozen, samples)
        print(arm, json.dumps(results[arm]['counts']), flush=True)

    comparisons = {}
    for reference in ('P0', 'outcome', 'trajectory', 'shuffled', 'uniform'):
        comparisons[f'targeted_minus_{reference}'] = {
            key: paired_bootstrap(rows[reference][key], rows['targeted'][key], seed=20261111,
                                  resamples=2000)['accuracy_delta'] for key in rows['targeted']}
    report = {'source_run': str(run), 'p0_run': str(p0_run), 'plan_sha256': sha(plan), 'source_sha256': sha(__file__),
              'protocol': 'normalized_whole_or_explicit_exact_answer_v1_and_literal_presence',
              'arms': results, 'paired_signal_deltas': comparisons}
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, allow_nan=False)
    if args.blind_discordance_dir is not None:
        export_discordance(run, rows, args.blind_discordance_dir)


if __name__ == '__main__':
    main()
