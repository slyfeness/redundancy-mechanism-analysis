"""Read model-authored decisions; validate references and compute counts only.

No semantic labels, reconstruction judgments, guide risks or memberships are
inferred here. Every mechanism membership and repeat list is authored by Codex.
"""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

SYN = Path(__file__).resolve().parent
ANALYSIS = SYN.parent
ROOT = ANALYSIS.parent
OUT = SYN / 'FINAL_STATISTICS'
CODES = {
    'M01': '材料被采用后真正改变对象或行动',
    'M02': '对象、角色、事件或范围解释成为工作前提',
    'M03': '实际读取覆盖与所需证据不匹配',
    'M04': '失败反馈是否落实为有效取证决策',
    'M05': '具体剩余条件如何控制推进与提交',
    'M06': '已形成判断之后再次确认',
    'M07': '已识别冲突是否持续限制候选选择',
}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def readl(p):
    return [json.loads(l) for l in p.read_text(encoding='utf-8-sig').splitlines() if l.strip()]


def writej(name, x):
    (OUT / name).write_text(json.dumps(x, ensure_ascii=False, indent=2), encoding='utf-8')


def writecsv(name, rows):
    if not rows:
        (OUT / name).write_text('', encoding='utf-8-sig')
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def normalized_original_cost(fact):
    if 'original_recorded_suffix' in fact:
        return fact['original_recorded_suffix']
    # Earlier deterministic schema for a complete response at the first-round
    # start. This is a field adapter, never a semantic or native-token claim.
    o = fact['original_recorded_complete_rounds_after_source_request_entry']
    return {'complete_current_original_response_is_after_cut': True,
            'whole_response_completion_tokens_from_cut_round_inclusive': o['completion_tokens'],
            'fully_post_cut_later_round_completion_tokens': o['completion_tokens'],
            'future_HTTP_prompt_tokens_excluding_entered_cut_round': o['future_round_prompt_tokens'],
            'post_cut_actual_tools': {'search': o['search_calls'], 'open': o['open_calls']},
            'generation_segments_including_current_round': o['actor_generation_segments_including_current_round']}


def main():
    OUT.mkdir(exist_ok=True)
    inputs = [SYN / 'ROOT_NORMALIZED_LINKS_FINAL.jsonl', SYN / 'PEER_NORMALIZED_LINKS.jsonl',
              SYN / 'ALL340_MODEL_AUTHORED_MEMBERSHIPS.jsonl',
              ANALYSIS / 'OUTCOME_SCREENING_ALL100/ALL_646_STAGE_SCREENING.csv',
              SYN / 'CROSSQUESTION_LINKING_PROTOCOL.md', SYN / 'PEER_TARGET_RELATION_AUDIT.jsonl']
    rows = list(csv.DictReader(inputs[3].open(encoding='utf-8-sig', newline='')))
    screen = {x['unit_id']: x for x in rows if x['screen_group'] in ('A', 'B')}
    base = {x['unit_id']: x for x in readl(inputs[2])}
    links = readl(inputs[0]) + readl(inputs[1])
    peer_positions = {(x['unit_id'], x['mechanism_id']): x for x in readl(inputs[5])}
    errors = []
    ids = Counter(x['unit_id'] for x in links)
    if len(links) != 340 or set(ids) != set(screen) or any(v != 1 for v in ids.values()):
        errors.append({'coverage': len(links), 'unique': len(ids),
                       'missing': sorted(set(screen) - set(ids)),
                       'unexpected': sorted(set(ids) - set(screen))})
    linkage_rows, evidence_rows, costs, unclassified = [], [], [], []
    dimensions = defaultdict(list)
    all_stats = {}
    for x in links:
        u = x['unit_id']
        b, s = base[u], screen[u]
        source_path = ANALYSIS / 'STAGE_REVIEWS' / (u + '.json')
        review = json.loads(source_path.read_text(encoding='utf-8-sig'))
        evid = {e['evidence_id']: e for e in review['evidence']}
        cost_path = ANALYSIS / 'COST_FACTS' / (u + '.json')
        fact = json.loads(cost_path.read_text(encoding='utf-8-sig'))
        original = normalized_original_cost(fact)
        rollouts = {int(r['repeat_id']): r for r in review['rollouts']}
        if set(rollouts) != {1, 2, 3, 4}:
            errors.append([u, 'rollout_coverage'])
        if not x['mechanisms']:
            reason = x.get('not_classified_reason', '')
            if not reason:
                errors.append([u, 'empty_unclassified_reason'])
            unclassified.append({'unit_id': u, 'group': s['screen_group'],
                                 'question_key': s['question_key'], 'reason': reason})
        seen_codes = set()
        for m in x['mechanisms']:
            code = m['mechanism_id']
            position = peer_positions.get((u, code), {})
            m = {**m, 'target_relation': m.get('target_relation', position.get('target_relation')),
                 'target_relation_basis': m.get('target_relation_basis', m.get('basis',
                                          position.get('basis', position.get('target_relation_basis', ''))))}
            if m.get('target_relation') not in ('DIRECT_U', 'DOWNSTREAM_ONLY', 'UNCLEAR') or not m.get('target_relation_basis'):
                errors.append([u, code, 'missing_target_position'])
            if code not in CODES or code in seen_codes:
                errors.append([u, 'invalid_or_duplicate_code', code])
            seen_codes.add(code)
            if not m.get('specific_state_update') or not m.get('limit'):
                errors.append([u, code, 'missing_semantic_text'])
            refs = set()
            for idx in m['relation_indices']:
                if not isinstance(idx, int) or not 0 <= idx < len(b['relations']):
                    errors.append([u, code, 'invalid_relation_index', idx])
                    continue
                refs.update(b['relations'][idx]['evidence_ids'])
            if not refs:
                errors.append([u, code, 'no_evidence'])
            for e_id in sorted(refs):
                if e_id not in evid:
                    errors.append([u, code, 'missing_evidence', e_id])
                    continue
                evidence_rows.append({'unit_id': u, 'mechanism_id': code,
                                      'review_file': str(source_path),
                                      'review_sha256': sha(source_path),
                                      'evidence': evid[e_id]})
            sets = {}
            for key in ('support_repeats', 'counter_repeats', 'uncertain_repeats'):
                vals = m.get(key, [])
                if len(vals) != len(set(vals)) or any(v not in (1, 2, 3, 4) for v in vals):
                    errors.append([u, code, key, vals])
                sets[key] = set(vals)
            rec = {'unit_id': u, 'group': s['screen_group'], 'question_key': s['question_key'],
                   'trajectory_id': s['trajectory_id'], 'stage_id': s['stage_id'],
                   'condition': s['condition'], 'original_outcome': s['original_outcome'],
                   'mechanism_id': code, 'relation_indices': m['relation_indices'],
                   'target_relation': m['target_relation'], 'target_relation_basis': m['target_relation_basis'],
                   **{k: sorted(v) for k, v in sets.items()},
                   'specific_state_update': m['specific_state_update'], 'limit': m['limit']}
            linkage_rows.append(rec)
            dimensions[(code, s['screen_group'])].append(rec)
        for c in fact['records']:
            repeat = int(c['repeat_id'])
            n = c['actual_new_suffix_cost']
            interval = c.get('conservative_new_minus_original_completion_count_interval')
            if interval is None:
                assert original['complete_current_original_response_is_after_cut']
                delta = n['completion_tokens'] - original['whole_response_completion_tokens_from_cut_round_inclusive']
                interval = [delta, delta]
            new_outcome = s[f'run{repeat}']
            actual_outcome = rollouts[repeat]['outcome']
            if actual_outcome != new_outcome:
                errors.append([u, repeat, 'outcome_disagreement', actual_outcome, new_outcome])
            direction = 'UNCERTAIN_INTERVAL'
            if interval[1] < 0:
                direction = 'CONSERVATIVE_DECREASE'
            elif interval[0] > 0:
                direction = 'CONSERVATIVE_INCREASE'
            elif interval == [0, 0]:
                direction = 'NO_RECORDED_CHANGE'
            costs.append({'unit_id': u, 'group': s['screen_group'], 'question_key': s['question_key'],
                          'trajectory_id': s['trajectory_id'], 'stage_id': s['stage_id'],
                          'condition': s['condition'], 'repeat_id': repeat,
                          'original_outcome': s['original_outcome'], 'new_outcome': new_outcome,
                          'terminal': rollouts[repeat].get('terminal', rollouts[repeat].get('stop_reason')),
                          'new_generation_tokens': n['completion_tokens'],
                          'original_generation_lower': original['fully_post_cut_later_round_completion_tokens']
                          if not original['complete_current_original_response_is_after_cut']
                          else original['whole_response_completion_tokens_from_cut_round_inclusive'],
                          'original_generation_upper': original['whole_response_completion_tokens_from_cut_round_inclusive'],
                          'new_minus_old_generation_lower': interval[0],
                          'new_minus_old_generation_upper': interval[1], 'generation_direction': direction,
                          'new_prompt_tokens': n['prompt_tokens'],
                          'P_replay_tokens_derived': n['replayed_P_prefill_tokens_derived'],
                          'G_prefill_tokens_derived': n['teacher_prefill_tokens_derived'],
                          'new_prompt_excluding_P_including_G': c['new_prompt_excluding_replayed_P_including_G'],
                          'old_future_HTTP_prompt_excluding_entered_round': original['future_HTTP_prompt_tokens_excluding_entered_cut_round'],
                          'new_search': n['search_calls'], 'old_suffix_search': original['post_cut_actual_tools']['search'],
                          'delta_search': n['search_calls'] - original['post_cut_actual_tools']['search'],
                          'new_open': n['open_calls'], 'old_suffix_open': original['post_cut_actual_tools']['open'],
                          'delta_open': n['open_calls'] - original['post_cut_actual_tools']['open'],
                          'new_actor_requests': n['actor_requests'],
                          'old_suffix_generation_segments': original['generation_segments_including_current_round'],
                          'delta_actor_segments': n['actor_requests'] - original['generation_segments_including_current_round'],
                          'boundary_mode': c['source_boundary_mode'], 'native_exact_savings': '',
                          'cost_fact_file': str(cost_path), 'cost_fact_sha256': sha(cost_path),
                          'new_trajectory_sha256': c['trajectory_sha256']})
    audit = {'scope': '340 A/B only; mechanical linkage, outcomes and cost recomputation; not semantic gold',
             'units': len(ids), 'rows': len(linkage_rows), 'paths': len(costs), 'errors': errors,
             'input_sha256': {str(p): sha(p) for p in inputs}}
    writej('RECOMPUTATION_AUDIT.json', audit)
    if errors:
        raise SystemExit(json.dumps(errors, ensure_ascii=False))
    support_detail = []
    summary = []
    for code in CODES:
        for group in ('A', 'B'):
            records = dimensions[(code, group)]
            positive = [r for r in records if r['support_repeats']]
            direct = [r for r in positive if r['target_relation'] == 'DIRECT_U']
            direct_paths = {(r['unit_id'], rep) for r in direct for rep in r['support_repeats']}
            direct_counters = {(r['unit_id'], rep) for r in records if r['target_relation'] == 'DIRECT_U'
                               for rep in r['counter_repeats']}
            paths = {(r['unit_id'], rep) for r in records for rep in r['support_repeats']}
            counters = {(r['unit_id'], rep) for r in records for rep in r['counter_repeats']}
            unknown = {(r['unit_id'], rep) for r in records for rep in r['uncertain_repeats']}
            summary.append({'mechanism_id': code, 'description': CODES[code], 'group': group,
                            'support_stage_count': len({r['unit_id'] for r in positive}),
                            'support_question_count': len({r['question_key'] for r in positive}),
                            'support_original_trajectory_count': len({r['trajectory_id'] for r in positive}),
                            'support_rollout_count': len(paths), 'counterexample_rollout_count': len(counters),
                            'direct_U_support_stage_count': len({r['unit_id'] for r in direct}),
                            'direct_U_support_question_count': len({r['question_key'] for r in direct}),
                            'direct_U_support_original_trajectory_count': len({r['trajectory_id'] for r in direct}),
                            'direct_U_support_rollout_count': len(direct_paths),
                            'direct_U_counterexample_rollout_count': len(direct_counters),
                            'uncertain_rollout_count': len(unknown),
                            'linked_stage_count': len(records),
                            'conditions': dict(Counter(r['condition'] for r in positive))})
            for c in costs:
                pair = (c['unit_id'], c['repeat_id'])
                roles = [label for label, pool in [('SUPPORT', paths), ('COUNTEREXAMPLE', counters),
                                                  ('UNCERTAIN', unknown)] if pair in pool]
                if roles:
                    position_rec = next(r for r in records if r['unit_id'] == c['unit_id'])
                    support_detail.append({'mechanism_id': code, 'evidence_roles': '|'.join(roles),
                                           'target_relation': position_rec['target_relation'], **c})
    transitions = Counter((c['group'], c['condition'], c['original_outcome'], c['new_outcome']) for c in costs)
    mechanism_transitions = Counter((c['mechanism_id'], c['group'], c['condition'], c['evidence_roles'],
                                     c['original_outcome'], c['new_outcome']) for c in support_detail)
    writej('MECHANISM_AB_COUNTS.json', summary)
    writecsv('MECHANISM_AB_COUNTS.csv', [{**r, 'conditions': json.dumps(r['conditions'])} for r in summary])
    writej('MODEL_AUTHORED_STAGE_LINKS.json', linkage_rows)
    writecsv('UNCLASSIFIED_STAGES.csv', unclassified)
    by_unit = defaultdict(list)
    for r in linkage_rows:
        by_unit[r['unit_id']].append(r)
    coverage = []
    for u, s in screen.items():
        candidates = by_unit[u]
        direct = [r for r in candidates if r['target_relation'] == 'DIRECT_U' and r['support_repeats']]
        coverage.append({'unit_id': u, 'group': s['screen_group'], 'question_key': s['question_key'],
                         'trajectory_id': s['trajectory_id'], 'stage_id': s['stage_id'],
                         'condition': s['condition'], 'has_direct_U_support': bool(direct),
                         'direct_mechanisms': '|'.join(r['mechanism_id'] for r in direct),
                         'downstream_mechanisms': '|'.join(r['mechanism_id'] for r in candidates
                                                         if r['target_relation'] == 'DOWNSTREAM_ONLY'),
                         'unclear_mechanisms': '|'.join(r['mechanism_id'] for r in candidates
                                                      if r['target_relation'] == 'UNCLEAR'),
                         'no_mechanism_links': not candidates})
    writecsv('ALL340_LINKAGE_COVERAGE.csv', coverage)
    writecsv('NO_DIRECT_U_MECHANISM_SUPPORT.csv', [r for r in coverage if not r['has_direct_U_support']])
    writej('COVERAGE_SUMMARY.json', {'groups': {
        g: {'reviewed_stages': sum(r['group'] == g for r in coverage),
            'distinct_questions': len({r['question_key'] for r in coverage if r['group'] == g}),
            'direct_supported_stages': sum(r['group'] == g and r['has_direct_U_support'] for r in coverage),
            'no_direct_supported_stages': sum(r['group'] == g and not r['has_direct_U_support'] for r in coverage),
            'no_links_stages': sum(r['group'] == g and r['no_mechanism_links'] for r in coverage)}
        for g in ('A', 'B')}, 'total': len(coverage), 'all_four_paths': len(costs),
        'multi_labels_not_additive': True, 'not_independent_human_gold': True})
    writecsv('ALL1360_COST_AND_OUTCOME.csv', costs)
    writecsv('MECHANISM_ROLLOUT_SUPPORT_COUNTEREXAMPLES.csv', support_detail)
    writej('ALL_AB_OUTCOME_TRANSITIONS.json', [{'group': k[0], 'condition': k[1], 'old': k[2],
                                             'new': k[3], 'n': n} for k, n in sorted(transitions.items())])
    writej('MECHANISM_OUTCOME_TRANSITIONS.json', [{'mechanism_id': k[0], 'group': k[1],
                                                'condition': k[2], 'role': k[3], 'old': k[4],
                                                'new': k[5], 'n': n} for k, n in sorted(mechanism_transitions.items())])
    cost_groups = defaultdict(list)
    for c in support_detail:
        cost_groups[(c['mechanism_id'], c['group'], c['condition'], c['target_relation'], c['evidence_roles'])].append(c)
    grouped_cost = []
    for key, vals in sorted(cost_groups.items()):
        z = dict(zip(['mechanism_id', 'group', 'condition', 'target_relation', 'evidence_roles'], key))
        z['n_paths'] = len(vals)
        z['generation_direction_counts'] = dict(Counter(c['generation_direction'] for c in vals))
        for field in ('delta_search', 'delta_open', 'delta_actor_segments'):
            z[field + '_direction_counts'] = dict(Counter('DECREASE' if c[field] < 0 else 'INCREASE'
                                                          if c[field] > 0 else 'SAME' for c in vals))
        z['mean_new_generation'] = sum(c['new_generation_tokens'] for c in vals) / len(vals)
        z['mean_new_prompt'] = sum(c['new_prompt_tokens'] for c in vals) / len(vals)
        z['note'] = 'Direction counts per independent branch, not summed hypothetical savings; P/G separated in detail.'
        grouped_cost.append(z)
    writej('MECHANISM_COST_DISTRIBUTIONS.json', grouped_cost)
    with (OUT / 'MECHANISM_PRECISE_EVIDENCE_INDEX.jsonl').open('w', encoding='utf-8') as f:
        for r in evidence_rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    summary_md = ['# A/B分开：全340组模型作用链链接统计', '',
                  '主表只统计原U实际承担该动作的DIRECT_U链接；只在其他后继发生的链不拿来给U归同类功能。所有链的观察数另列。支持数不等于删除成功、冗余率或因果必要性。一个Stage可多重归属；支持与反证可重叠，详见逐路径具体限制。', '']
    for group in ('A', 'B'):
        summary_md += [f'## {group}类', '', '| 共性作用链 | U直接相关Stage | 不同题目 | 原轨迹 | 支持续跑 | 反证续跑 | 含后继观察Stage |',
                       '|---|---:|---:|---:|---:|---:|---:|']
        for r in summary:
            if r['group'] == group:
                summary_md.append(f"| {r['mechanism_id']} {r['description']} | {r['direct_U_support_stage_count']} | {r['direct_U_support_question_count']} | {r['direct_U_support_original_trajectory_count']} | {r['direct_U_support_rollout_count']} | {r['direct_U_counterexample_rollout_count']} | {r['support_stage_count']} |")
        summary_md.append('')
    summary_md += [f'未归入这七条链的Stage：{len(unclassified)}，完整保留原因，不强行归类。', '',
                   '成本表分别保存新生成、原后缀保守区间、P重放、G预填、Search/Open/Actor。没有NATIVE_TOKEN_EXACT切点，故精确原生净节省均为空；独立删除分支的差值不相加为可实现总收益。']
    (OUT / 'AB_MECHANISM_COUNTS.md').write_text('\n'.join(summary_md) + '\n', encoding='utf-8')
    print(json.dumps({'units': len(ids), 'paths': len(costs), 'mechanism_rows': len(linkage_rows),
                      'unclassified': len(unclassified), 'errors': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
