"""Local files -> audited reports -> explicit tensor advantages."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def read_jsonl(path):
    return _parse_jsonl(Path(path).read_text(encoding='utf-8-sig'), path)


def _parse_jsonl(text, path):
    rows = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f'{path}:{line_number}: invalid JSON') from exc
            if not isinstance(row, dict):
                raise ValueError(f'{path}:{line_number}: expected object')
            rows.append(row)
    return rows


def _write_torch_once(path, value):
    import torch

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.partial', delete=False) as stream:
        pending = Path(stream.name)
    try:
        torch.save(value, pending)
        os.link(pending, path)
    finally:
        pending.unlink()


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, 'detach'):
        return value.detach().cpu().tolist()
    return value


def write_json(path, value, *, lines=False):
    path = Path(path)
    # Exclusive creation preserves prior reports. Use a new output path for a new run.
    data = _jsonable(value)
    text = ('\n'.join(json.dumps(row, ensure_ascii=False, allow_nan=False) for row in data) if lines
            else json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def _align(traces, reports):
    ids = [t['traj_id'] for t in traces]
    report_ids = [r['traj_id'] for r in reports]
    if len(ids) != len(set(ids)) or len(report_ids) != len(set(report_ids)) or set(ids) != set(report_ids):
        raise ValueError('trajectory/report IDs must match one-to-one without duplicates')
    by_id = {r['traj_id']: r for r in reports}
    return [by_id[tid] for tid in ids]


def _score(traces, reports, config, **kwargs):
    from .pipeline import score_batch
    result = score_batch(traces, _align(traces, reports), config=config, **kwargs)
    result['skip_update'] = not bool(result['valid_rows'].any())
    return result


def _demo(output):
    from .advantages import AdvantageConfig
    from .examples import synthetic_examples
    from .pipeline import analyze_trajectory
    from .rules import RuleConfig
    from .evaluation import summarize_runs
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('demo output directory must be new or empty')
    traces, deltas = synthetic_examples()
    rules = RuleConfig(enable_artifact_d4=True)
    config = AdvantageConfig(process_enabled=True)
    reports = [analyze_trajectory(t, deltas=deltas[t['traj_id']], rule_config=rules) for t in traces]
    scores = _score(traces, reports, config, enable_artifact_d4=True)
    scores['example_notice'] = 'Synthetic interface smoke test. No model, real task evaluation, calibration, or training.'
    runs = [{'task_id': t['task_id'], 'sample_id': t['traj_id'], 'outcome': t['outcome'], 'complete': t['complete'],
             'cost': r['metrics']['gen_tokens'], 'budget': t.get('budget_tokens'), **r['metrics']} for t, r in zip(traces, reports)]
    for name, data, lines in [('trajectories.jsonl', traces, True), ('deltas.json', deltas, False),
                              ('reports.jsonl', reports, True), ('scores.json', scores, False),
                              ('runs.jsonl', runs, True), ('summary.json', summarize_runs(runs), False),
                              ('config.json', asdict(config), False), ('rules.json', asdict(rules), False)]:
        write_json(output / name, data, lines=lines)
    print(json.dumps({'output_dir': str(output.resolve()), 'synthetic': True, 'trajectories': len(traces),
                      'valid_rows': scores['metrics']['valid_row_count']}, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    analyze = sub.add_parser('analyze', help='build citation-linked ledger and conservative labels')
    analyze.add_argument('--trajectories', required=True)
    source = analyze.add_mutually_exclusive_group(required=True)
    source.add_argument('--deltas', help='JSON mapping traj_id -> turn_id -> replay delta')
    source.add_argument('--judge-base-url', help='explicit loopback endpoint, e.g. http://127.0.0.1:8000/v1')
    analyze.add_argument('--judge-model')
    analyze.add_argument('--judge-timeout', type=float, default=30)
    analyze.add_argument('--compact-evidence', action='store_true', help='send each distinct extraction evidence text once')
    analyze.add_argument('--rules', help='RuleConfig JSON')
    analyze.add_argument('--output', required=True)
    score = sub.add_parser('score', help='compute advantages for complete same-task groups')
    score.add_argument('--trajectories', required=True)
    score.add_argument('--reports', required=True)
    score.add_argument('--config', help='AdvantageConfig JSON; default process_enabled=false')
    score.add_argument('--enable-artifact-d4', action='store_true')
    score.add_argument('--control', choices=['targeted', 'uniform', 'shuffle', 'trajectory'], default='targeted')
    score.add_argument('--seed', type=int, default=0)
    score.add_argument('--output', required=True)
    event_score = sub.add_parser('score-events', help='compute revised GRPO credit from validated event receipts')
    event_score.add_argument('--rows', required=True, help='JSONL trajectory rows with event receipts')
    event_score.add_argument('--config', required=True, help='EventPriceConfig JSON')
    event_score.add_argument('--arm', choices=['outcome','trajectory','targeted','shuffled','uniform'], default='targeted')
    event_score.add_argument('--native-batch', type=Path, help='verify the prepared batch and emit a trainer-readable PyTorch score')
    event_score.add_argument('--semantic-calibration', type=Path, help='event-bound audit report required for positive R1 or R2a prices')
    event_score.add_argument('--output', required=True)
    prepare_sampler = sub.add_parser('prepare-sampler-grpo', help='bind native SAGE or SciCode logs to score-events inputs')
    prepare_sampler.add_argument('--dataset', choices=['sage', 'scicode'], required=True)
    prepare_sampler.add_argument('--manifest', required=True, help='JSONL with source bindings and independently verified outcomes')
    prepare_sampler.add_argument('--tokenizer', required=True, help='local tokenizer directory used by the sampler')
    prepare_sampler.add_argument('--output', type=Path, required=True, help='new batch output directory')
    prepare_sampler.add_argument('--emit-process-traces', action='store_true',
                                 help='export actor-visible stage traces using manifest process_frames')
    sampler_diagnostics = sub.add_parser('diagnose-sampler-events', help='bind stage judge reports to native tool events')
    sampler_diagnostics.add_argument('--prepared', type=Path, required=True)
    sampler_diagnostics.add_argument('--reports', required=True)
    sampler_diagnostics.add_argument('--output', required=True)
    event_audit = sub.add_parser('audit-events', help='evaluate matched human and deletion labels')
    event_audit.add_argument('--cases', required=True)
    event_audit.add_argument('--output', required=True)
    event_audit.add_argument('--for-pricing', action='store_true',
                             help='require same-tool-event deletion bindings and include the input manifest path')
    gap_audit = sub.add_parser('audit-gaps', help='attach independent gap reviews to a fixed evaluation')
    gap_audit.add_argument('--evaluation', required=True, help='frozen EVAL JSON')
    gap_audit.add_argument('--requirements', required=True, help='task-to-required-gap mapping JSON')
    gap_audit.add_argument('--reviews', required=True, help='independent review JSON bound to the input digests')
    gap_audit.add_argument('--output', required=True)
    evaluate = sub.add_parser('evaluate', help='summarize measured run costs and accuracy')
    evaluate.add_argument('--runs', required=True)
    evaluate.add_argument('--output', required=True)
    compare = sub.add_parser('compare', help='paired bootstrap with task as resampling unit')
    compare.add_argument('--baseline', required=True)
    compare.add_argument('--candidate', required=True)
    compare.add_argument('--resamples', type=int, default=2000)
    compare.add_argument('--seed', type=int, default=0)
    compare.add_argument('--output', required=True)
    event_compare = sub.add_parser('compare-events', help='compare fixed-task evaluation summaries for event pricing')
    event_compare.add_argument('--baseline', required=True, help='baseline EVAL JSON')
    event_compare.add_argument('--candidate', required=True, help='candidate EVAL JSON')
    event_compare.add_argument('--output', required=True)
    audit = sub.add_parser('audit', help='compare judge annotations with independent annotations')
    audit.add_argument('--gold', required=True)
    audit.add_argument('--predictions', required=True)
    audit.add_argument('--output', required=True)
    demo = sub.add_parser('demo', help='offline synthetic end-to-end fixture; no model calls')
    demo.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv)
    if args.command == 'demo':
        _demo(args.output_dir)
        return 0
    if Path(args.output).exists():
        raise FileExistsError(f'output already exists: {args.output}')
    if args.command == 'analyze':
        from .pipeline import analyze_trajectory
        from .rules import RuleConfig
        rules = RuleConfig(**(read_json(args.rules) if args.rules else {}))
        traces, judge, deltas = read_jsonl(args.trajectories), None, None
        if len({t['traj_id'] for t in traces}) != len(traces):
            raise ValueError('duplicate trajectory IDs')
        if args.deltas:
            deltas = read_json(args.deltas)
            if not isinstance(deltas, dict) or set(deltas) != {t['traj_id'] for t in traces}:
                raise ValueError('replay deltas must match exactly the trajectory IDs')
        else:
            from .client import LocalJudge
            judge = LocalJudge(args.judge_base_url, args.judge_model, timeout=args.judge_timeout,
                               compact_evidence=args.compact_evidence)
        reports = [analyze_trajectory(t, deltas=deltas[t['traj_id']] if deltas is not None else None,
                                      judge=judge, rule_config=rules) for t in traces]
        write_json(args.output, reports, lines=True)
        print(json.dumps({'reports': len(reports), 'qa_failed': sum(not r['qa']['parse_ok'] for r in reports),
                          'judge_requests': getattr(judge, 'requests', 0), 'judge_usage': getattr(judge, 'usage', None)}))
    elif args.command == 'score':
        from .advantages import AdvantageConfig
        cfg = AdvantageConfig(**(read_json(args.config) if args.config else {}))
        result = _score(read_jsonl(args.trajectories), read_jsonl(args.reports), cfg,
                        control=args.control, seed=args.seed, enable_artifact_d4=args.enable_artifact_d4)
        write_json(args.output, result)
        print(json.dumps({'valid_rows': result['metrics']['valid_row_count'], 'skip_update': result['skip_update'],
                          'process_enabled': cfg.process_enabled}))
    elif args.command == 'score-events':
        from .event_price import EventPriceConfig, score_event_prices
        config = EventPriceConfig(**read_json(args.config))
        calibration = read_json(args.semantic_calibration) if args.semantic_calibration else None
        if args.native_batch is None:
            result = score_event_prices(read_jsonl(args.rows), config, arm=args.arm, semantic_calibration=calibration)
            write_json(args.output, result)
        else:
            from .hf_native import prepare_native_records

            source_rows, native_bytes = Path(args.rows).read_bytes(), args.native_batch.read_bytes()
            rows_digest = hashlib.sha256(source_rows).hexdigest()
            batch = json.loads(native_bytes)
            if batch.get('event_rows_sha256') != rows_digest:
                raise ValueError('event rows do not match the prepared native batch')
            rows = _parse_jsonl(source_rows.decode('utf-8-sig'), args.rows)
            by_id = {row['traj_id']: row['outcome'] for row in rows}
            trajectories = batch['trajectories']
            if any(item['id'] not in by_id or by_id[item['id']] != item['reward'] for item in trajectories):
                raise ValueError('native rewards do not match the event rows')
            result = score_event_prices(rows, config, arm=args.arm, semantic_calibration=calibration)
            prepare_native_records(trajectories, result)
            binding = {'native_batch_sha256': hashlib.sha256(native_bytes).hexdigest(),
                       'event_rows_sha256': rows_digest}
            if 'policy_snapshot_sha256' in batch:
                snapshot = batch['policy_snapshot_sha256']
                if not isinstance(snapshot, str) or re.fullmatch(r'[0-9a-f]{64}', snapshot) is None:
                    raise ValueError('invalid recorded policy snapshot digest')
                binding['policy_snapshot_sha256'] = snapshot
            result.update(config=asdict(config), input_binding=binding)
            _write_torch_once(args.output, result)
        print(json.dumps(result['metrics'],ensure_ascii=False))
    elif args.command == 'prepare-sampler-grpo':
        from transformers import AutoTokenizer
        from .sampler_grpo import adapt_sampler_trajectory

        manifest = read_jsonl(args.manifest)
        if not manifest or len({item['traj_id'] for item in manifest}) != len(manifest):
            raise ValueError('expected nonempty manifest with unique training sample IDs')
        roots = [Path(item['artifact_root']).resolve(strict=True) for item in manifest]
        if len(set(roots)) != len(roots) or any(args.output.resolve().is_relative_to(root) for root in roots):
            raise ValueError('each sample must use a separate source, with output outside the sources')
        tokenizer = AutoTokenizer.from_pretrained(Path(args.tokenizer).resolve(strict=True), local_files_only=True)
        rows, trajectories, coverage = [], [], []
        traces, bindings = [], []
        for item, root in zip(manifest, roots, strict=True):
            row, native, observed = adapt_sampler_trajectory(
                args.dataset, root, traj_id=item['traj_id'], task_id=item['task_id'],
                outcome=item['outcome'], tokenizer=tokenizer,
                process_frames=item['process_frames'] if args.emit_process_traces else None)
            for field in ('source_trajectory_id', 'source_trajectory_sha256'):
                if observed[field] != item[field]:
                    raise ValueError(f'{field} does not match the independently bound outcome manifest')
            rows.append(row)
            trajectories.append(native)
            for projection in observed.pop('process_traces', []):
                trace = projection.pop('trace')
                traces.append(trace)
                bindings.append(dict(projection, traj_id=trace['traj_id'], source_traj_id=row['traj_id'],
                                     source_trajectory_sha256=observed['source_trajectory_sha256']))
            coverage.append(dict(observed, traj_id=row['traj_id']))
        args.output.mkdir(parents=True, exist_ok=False)
        event_rows = args.output / 'EVENT_ROWS.jsonl'
        write_json(event_rows, rows, lines=True)
        native_batch = {'trajectories': trajectories, 'event_rows_sha256': hashlib.sha256(event_rows.read_bytes()).hexdigest()}
        if args.emit_process_traces:
            for name, records in (('PROCESS_TRACES.jsonl', traces), ('PROCESS_EVENT_BINDINGS.jsonl', bindings)):
                path = args.output/name
                write_json(path, records, lines=True)
                native_batch.setdefault('process_artifacts_sha256', {})[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(args.output/'NATIVE_BATCH.json', native_batch)
        write_json(args.output/'COVERAGE.json', {'dataset': args.dataset, 'rows': coverage})
    elif args.command == 'diagnose-sampler-events':
        from .browsecomp_events import semantic_event_predictions

        paths = (args.prepared/'PROCESS_TRACES.jsonl', Path(args.reports), args.prepared/'PROCESS_EVENT_BINDINGS.jsonl')
        native_batch = json.loads((args.prepared/'NATIVE_BATCH.json').read_bytes())
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != native_batch['process_artifacts_sha256'].get(path.name)
               for path in (paths[0], paths[2])):
            raise ValueError('process artifacts differ from their prepared native batch')
        inputs = [read_jsonl(path) for path in paths]
        traces, reports, bindings = ({row['traj_id']: row for row in records} for records in inputs)
        if (not traces or not traces.keys() == reports.keys() == bindings.keys()
                or any(len(items) != len(index) for items,index in zip(inputs,(traces,reports,bindings),strict=True))):
            raise ValueError('process traces, reports and event bindings must cover the same stage IDs exactly once')
        result = []
        for identity, trace in traces.items():
            binding = bindings[identity]
            events = semantic_event_predictions(binding, trace, reports[identity], binding['measured_events'])
            result.append({'traj_id': identity, 'source_traj_id': binding['source_traj_id'],
                           'source_trajectory_sha256': binding['source_trajectory_sha256'],
                           'stage_index': binding['stage_index'], 'events': events, 'process_only': True})
        write_json(args.output, result, lines=True)
    elif args.command == 'audit-events':
        from .evaluation import read_event_calibration
        write_json(args.output, read_event_calibration(args.cases, require_event_binding=args.for_pricing))
    elif args.command == 'audit-gaps':
        from .evaluation import audit_gap_reviews
        write_json(args.output, audit_gap_reviews(args.evaluation, args.requirements, args.reviews))
    elif args.command == 'evaluate':
        from .evaluation import summarize_runs
        write_json(args.output, summarize_runs(read_jsonl(args.runs)))
    elif args.command == 'compare':
        from .evaluation import paired_bootstrap
        write_json(args.output, paired_bootstrap(read_jsonl(args.baseline), read_jsonl(args.candidate), resamples=args.resamples, seed=args.seed))
    elif args.command == 'compare-events':
        from .evaluation import paired_event_diagnostics
        baseline, candidate = read_json(args.baseline), read_json(args.candidate)
        if baseline.get('gap_review') and candidate.get('gap_review') and any(
                baseline['gap_review'][key] != candidate['gap_review'][key]
                for key in ('requirements_sha256', 'protocol_id')):
            raise ValueError('paired gap reviews require the same frozen requirements and review protocol')
        write_json(args.output, paired_event_diagnostics(baseline['rows'], candidate['rows']))
    elif args.command == 'audit':
        from .evaluation import evaluate_annotations
        write_json(args.output, evaluate_annotations(read_jsonl(args.predictions), read_jsonl(args.gold)))
    return 0


def entrypoint():
    try:
        return main()
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        print(f'ledger-grpo: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
