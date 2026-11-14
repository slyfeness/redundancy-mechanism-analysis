"""Freeze paired intervention seeds and export a prefix-only review packet."""

import argparse
import hashlib
import html
import json
from pathlib import Path

from transformers import AutoTokenizer

from ledger_grpo.event_calibration_plan import freeze_event_cases
from run_event_deletion_branch import bind_branch


RUBRIC = (
    '只根据目标调用及当时已经看到的证据判断。R1 指已有证据支持的同一事实被再次核验，且返回没有新增有效支持。'
    'R2a 指对同一未解决缺口发起近义检索，检索策略及有效返回均未推进。'
    '逐字重复另属 R2b。初次核验、独立来源、冲突处理、新证据或有依据的策略改变均应保留。'
    '每个标签可填 redundant、necessary 或 uncertain。necessary 表示有可见的保留理由，'
    'uncertain 表示证据不足。引用消息编号并简述依据。'
)


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def write(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def project_message(message, number):
    role = message['role']
    row = {'ref': f'M{number:03d}', 'role': role, 'content': message['content']}
    if role == 'assistant':
        row['reasoning'] = message.get('reasoning_content') or message.get('reasoning') or ''
        row['calls'] = [call['function'] for call in message.get('tool_calls', [])]
    return row


def render_packet(packet):
    escape = html.escape
    header = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
              '<title>单事件删除盲评</title><style>body{font:16px/1.5 system-ui;max-width:960px;margin:36px auto;'
              'padding:0 20px;color:#173154}section{border-top:1px solid #c6d1df;margin:24px 0;padding-top:12px}'
              'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6fa;padding:12px}'
              'summary{cursor:pointer;margin-top:7px}</style><h1>单事件删除盲评</h1>')
    sections = [header, f'<p>{escape(packet["rubric"])}</p>']
    for case in packet['cases']:
        sections.append(f'<section><h2>{escape(case["case_id"])}</h2><p>{escape(case["question"])}</p>')
        for title, messages in (('目标调用和返回', case['target']), ('调用前可见记录', case['history'])):
            sections.append(f'<h3>{title}</h3>')
            for message in messages:
                details = [message.get('reasoning') or '', message['content'] or '']
                details.extend(json.dumps(call, ensure_ascii=False) for call in message.get('calls', []))
                body = escape('\n'.join(value for value in details if value))
                sections.append(f'<details><summary>{escape(message["ref"])} · {escape(message["role"])}</summary>'
                                f'<pre>{body}</pre></details>')
        sections.append('</section>')
    return '\n'.join(sections) + '</html>\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--split', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261111)
    parser.add_argument('--calibration-selection', type=Path, help='Frozen list of sample_id/event_id objects')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rollout = args.run / 'train-P0'
    audit, audit_sha = read(args.audit)
    native, batch_sha = read(args.run / 'scored/NATIVE_BATCH.json')
    split, split_sha = read(args.split)
    config, config_sha = read(rollout / 'config_manifest.json')
    tasks = {entry['id']: str(entry['query_id']) for entry in native['trajectories']}
    if (audit['batch_sha256'] != batch_sha or len(tasks) != len(native['trajectories'])
            or not set(tasks.values()) <= set(map(str, split['training_ids']))):
        raise ValueError('prefix audit, native training source and split do not agree')
    selection, selection_sha = read(args.calibration_selection) if args.calibration_selection else (None, None)
    if args.calibration_selection and selection is None:
        parser.error('calibration selection must contain an event list')
    plan = freeze_event_cases(audit['pairs'], tasks, list(map(str, split['evaluation_ids'])), seed=args.seed,
                              max_rounds=config['max_actor_calls'], selection=selection)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    blind = []
    for case in plan['cases']:
        event = case['event']
        raw, _, pair, _, _ = bind_branch(rollout, audit, event['sample_id'], event['event_id'], tokenizer)
        messages = pair['normal']['messages']
        question = messages[0]['content']
        task = raw['metadata']['task']
        if (messages[0]['role'] != 'user' or any(m['role'] == 'user' for m in messages[1:])
                or hashlib.sha256(question.encode()).hexdigest() != task['question_sha256']
                or str(task['query_id']) != case['task_id'] or task['run_id'] != event['sample_id']
                or [m['role'] for m in messages[-2:]] != ['assistant', 'tool']):
            raise ValueError('review packet cannot prove the original question and current event')
        rows = [project_message(message, i) for i, message in enumerate(messages[1:], 1)]
        blind.append({'case_id': case['case_id'], 'question': question, 'history': rows[:-2], 'target': rows[-2:]})

    args.output.mkdir(mode=0o700, exist_ok=False)
    packet = {'rubric': RUBRIC, 'cases': blind}
    write(args.output / 'BLIND_REVIEW.json', packet)
    with (args.output / 'BLIND_REVIEW.html').open('x', encoding='utf-8') as handle:
        handle.write(render_packet(packet))
    _, review_sha = read(args.output / 'BLIND_REVIEW.json')
    plan.update(protocol='browsecomp-event-calibration-plan-v1', scope='Engineering cases from the pilot training split.',
                calibration_scope='engineering',
                audit_sha256=audit_sha, batch_sha256=batch_sha, split_sha256=split_sha, config_sha256=config_sha,
                blind_review_sha256=review_sha)
    if selection_sha:
        plan.update(calibration_scope='calibration', scope='Cases from a frozen event calibration selection.',
                    selection_sha256=selection_sha)
    write(args.output / 'PLAN.json', plan)
    write(args.output / 'BLIND_VERDICTS_TEMPLATE.json', {'reviewer': '', 'packet_sha256': review_sha,
          'cases': {case['case_id']: {label: {'verdict': None, 'evidence': [], 'rationale': ''}
                    for label in ('R1', 'R2a')} for case in blind}})
    print(json.dumps({'eligible_events': plan['eligible_events'], 'frozen_events': len(blind),
                      'planned_continuations': sum(len(block['order']) for case in plan['cases'] for block in case['blocks'])}),
          flush=True)


if __name__ == '__main__':
    main()
