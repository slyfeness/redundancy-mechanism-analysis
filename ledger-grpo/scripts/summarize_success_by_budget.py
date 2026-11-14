"""Compare observed blind-reviewed successes within evaluation cost budgets."""

import argparse
import json
from pathlib import Path
from statistics import fmean

from ledger_grpo.evaluation import paired_event_diagnostics
from summarize_blind_result_review import load_reviewed_rows


_CAPS = {'tool_calls': (5, 10, 15, 20), 'gen_tokens': (4000, 8000, 12000, 16000, 20000)}


def apply_budget(rows, key, cap):
    result = []
    for row in rows:
        cost = row.get(key)
        score = row['outcome']
        if (cost is not None and (type(cost) is not int or cost < 0)) or score not in (0, 1, None):
            raise ValueError('observed budgets require nonnegative counts and binary or unknown outcomes')
        if score == 0 or (cost is not None and cost > cap):
            within_budget = 0
        elif cost is None:
            within_budget = None
        else:
            within_budget = score
        result.append({'task_id': row['task_id'], 'sample_id': row['sample_id'], 'outcome': within_budget})
    return result


def curve(rows, key, caps):
    points = []
    for cap in caps:
        scores = [item['outcome'] for item in apply_budget(rows, key, cap)]
        correct, unknown, n = scores.count(1), scores.count(None), len(scores)
        points.append({'budget': cap, 'correct': correct, 'unknown': unknown, 'samples': n,
                       'rate': correct/n if not unknown else None, 'bounds': [correct/n, (correct+unknown)/n]})
    return points


def summarize(rows, summaries, reviews):
    analysis = {}
    for key, budgets in _CAPS.items():
        observed = {row[key] for group in rows.values() for row in group if row.get(key) is not None}
        grid = sorted(observed | {0} | set(budgets))
        curves = {arm: curve(group, key, grid) for arm, group in rows.items()}
        for arm, points in curves.items():
            if points[-1]['bounds'] != summaries[arm]['diagnostic_accuracy_bounds']:
                raise ValueError('largest budget does not recover the original blind accuracy bounds')
        comparisons = {}
        for cap in budgets:
            capped = {arm: apply_budget(group, key, cap) for arm, group in rows.items()}
            comparisons[str(cap)] = {arm: paired_event_diagnostics(baseline, capped['targeted'])['delta']['outcome']
                                     for arm, baseline in capped.items() if arm != 'targeted'}
        analysis[key] = {'curves': curves, 'targeted_minus_comparators': comparisons}
    tool_profile = {}
    for arm, group in rows.items():
        by_outcome = {str(outcome): [row['tool_calls'] for row in group if row['outcome'] == outcome]
                      for outcome in (0, 1, None)}
        tool_profile[arm] = {status: {'samples': len(calls), 'mean_tool_calls': fmean(calls)
                                    if calls and None not in calls else None}
                             for status, calls in by_outcome.items()}
    return {'scope': 'Observed successes at or under each cost cap, scored offline by one independent model. '
                     'No rollout was interrupted or rerun under a new limit. Intervals are pointwise, '
                     'resampling tasks within one trained run per arm.',
            'evaluation_sha256': {arm: row['evaluation_sha256'] for arm,row in summaries.items()},
            'review_batches': reviews, 'budget_profiles': analysis, 'tool_calls_by_blind_outcome': tool_profile}


def plot(report, output):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from matplotlib.ticker import PercentFormatter

    labels = {'P0': ('Before training', '#778191'), 'outcome': ('Outcome only', '#284969'),
              'trajectory': ('Trajectory penalty', '#18867c'), 'targeted': ('Targeted events', '#b83d39'),
              'shuffled': ('Shuffled events', '#957330'), 'uniform': ('Uniform events', '#75599f')}
    fig, axes = plt.subplots(1, 2, figsize=(10.9, 4.6), sharey=True)
    for ax, (key, profile) in zip(axes, report['budget_profiles'].items(), strict=True):
        scale = 1000 if key == 'gen_tokens' else 1
        for arm, points in profile['curves'].items():
            label, color = labels[arm]
            ax.step([point['budget']/scale for point in points], [point['rate'] for point in points], where='post',
                    linewidth=2.6 if arm == 'targeted' else 1.4, color=color, label=label,
                    linestyle='--' if arm == 'P0' else '-', zorder=3 if arm == 'targeted' else 2)
        ax.set_xlabel('Generated tokens per trajectory (thousands)' if scale == 1000 else 'Tool calls per trajectory')
        ax.set_ylim(bottom=0)
        ax.set_xlim(left=0)
        ax.grid(axis='y', alpha=.24)
        ax.spines[['right', 'top']].set_visible(False)
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    axes[0].set_ylabel('Share of rollouts correct within budget')
    fig.suptitle('Observed BrowseComp-Plus success by cost budget', x=.10, y=.95, ha='left', fontsize=15, weight='semibold')
    fig.text(.10, .88, '16 held-out tasks, 8 samples per task and arm · offline blind review', color='#4a5360', fontsize=10)
    handles, legend = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend, loc='lower center', bbox_to_anchor=(.5, .025), ncol=3, frameon=False)
    fig.subplots_adjust(left=.10, right=.98, bottom=.24, top=.81, wspace=.16)
    with output.open('xb') as handle:
        fig.savefig(handle, format='png', dpi=180, facecolor='white')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--additional-review', type=Path, action='append', default=[])
    parser.add_argument('--evaluations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plot', type=Path)
    args = parser.parse_args()
    rows, summaries, _, reviews, _ = load_reviewed_rows(args.review, args.evaluations, additions=args.additional_review)
    report = summarize(rows, summaries, reviews)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    if args.plot:
        plot(report, args.plot)


if __name__ == '__main__':
    main()
