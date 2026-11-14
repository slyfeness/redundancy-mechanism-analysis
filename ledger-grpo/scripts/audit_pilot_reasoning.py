"""Recover reasoning-length diagnostics from saved native recorder fields."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from ledger_grpo.evaluation import reasoning_usage, summarize_reasoning_usage


def read(path):
    return json.loads(path.read_bytes())


def audit_folder(folder, *, expected_summary=None):
    tasks = read(folder/'task_manifest.json')['tasks']
    metrics = read(folder/'TRAJECTORY_METRICS.json')
    rows = []
    for task, metric in zip(tasks, metrics, strict=True):
        tid = task['run_id']
        if (not re.fullmatch(r'\d+__rep[1-8]',tid) or tid != metric['id']
                or str(task['query_id']) != str(metric['query_id'])):
            raise ValueError('recorded trajectory order differs from the task manifest')
        raw = read(folder/'trajectories'/tid/'trajectory.json')
        if raw['metadata']['terminal_status'] != metric['terminal']:
            raise ValueError('recorded trajectory ending differs from metrics')
        rows.append(dict(task_id=str(task['query_id']),sample_id=tid,**reasoning_usage(raw['rounds'])))
    identities = {(r['task_id'],r['sample_id']) for r in rows}
    if len(identities) != len(rows):
        raise ValueError('duplicate trajectory identities')
    if expected_summary is not None and identities != {(r['task_id'],r['sample_id']) for r in expected_summary['rows']}:
        raise ValueError('reasoning report task identities differ from fixed evaluation')
    return dict(summarize_reasoning_usage(rows), sample_count=len(rows), rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--baseline-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arms', nargs='+', choices=('train-P0','P0','outcome','trajectory','targeted','shuffled','uniform'), required=True)
    args = parser.parse_args()
    run, baseline, output = args.run.resolve(strict=True), args.baseline_run.resolve(strict=True), args.output.resolve()
    if output.is_relative_to(run) or output.is_relative_to(baseline) or output.exists():
        raise ValueError('reasoning audit requires a new output outside the frozen runs')
    report = {}
    for arm in dict.fromkeys(args.arms):
        if arm == 'train-P0':
            report[arm] = audit_folder(run/'train-P0')
        elif arm == 'P0':
            receipt = read(run/'BASELINE_EVALUATION_RECEIPT.json')
            source = baseline/'EVAL-P0.json'
            if (baseline.name != receipt['run_name'] or hashlib.sha256(source.read_bytes()).hexdigest() != receipt['summary_sha256']
                    or read(source) != read(run/'EVAL-P0.json')):
                raise ValueError('baseline reasoning source differs from the bound P0 evaluation')
            report[arm] = audit_folder(baseline/'eval-P0',expected_summary=read(source))
        else:
            report[arm] = audit_folder(run/f'eval-{arm}',expected_summary=read(run/f'EVAL-{arm}.json'))
    output.parent.mkdir(parents=True,exist_ok=True)
    pending = output.with_suffix('.partial')
    with pending.open('x',encoding='utf-8') as handle:
        json.dump({'source_run':str(run),'baseline_run':str(baseline),'arms':report},handle,ensure_ascii=False,allow_nan=False)
    pending.rename(output)
    print(json.dumps({arm:{k:v for k,v in values.items() if k != 'rows'} for arm,values in report.items()}),flush=True)


if __name__ == '__main__':
    main()
