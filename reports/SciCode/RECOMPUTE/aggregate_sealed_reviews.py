"""Deterministic joins/counts of sealed Codex decisions and immutable cost records.

No semantic classification, keyword rules, generated explanations or label defaults.
Stage commonality assignments are read only from Codex-authored synthesis CSVs.
"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PEER = ROOT.parent / 'scicode_ab_mechanism_20261104'
OUT = ROOT / 'FINAL_SYNTHESIS'
OUT.mkdir(exist_ok=True)

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

scope = read(ROOT / 'FROZEN_ANALYSIS_SCOPE.json')
expected = {x['case_id']: x for x in scope['cases']}
models = {}
for p in sorted(ROOT.glob('*/MODEL_REVIEW.json')):
    d = read(p)
    if d.get('review_status') == 'COMPLETE':
        models[d['case_id']] = (p, d)
for p in sorted((PEER / 'MODEL_REVIEWS/B').glob('*.json')):
    d = read(p)
    if d.get('review_status') == 'COMPLETE' and 'case_id' in d:
        assert d['case_id'] not in models
        models[d['case_id']] = (p, d)
assert set(models) <= set(expected)

assignments = {}
assignment_files = []
for p in [ROOT / 'A_SYNTHESIS_HANDWRITTEN.csv', PEER / 'B_SYNTHESIS_HANDWRITTEN.csv']:
    if not p.exists():
        continue
    assignment_files.append({'path': str(p), 'sha256': sha(p)})
    for row in csv.DictReader(p.open(encoding='utf-8-sig', newline='')):
        assert row['case_id'] not in assignments
        assignments[row['case_id']] = row

branch_rows = []
stage_rows = []
for cid, (mp, m) in sorted(models.items()):
    e = expected[cid]
    s = e['screening']
    assert m['category'] == s['category']
    assert len(m['rollouts']) == 4
    assert m['sources']
    assert m['original'] and m['guide_audit']
    assert m['stage_function'] and m['candidate_mechanism_chain']
    if m['category'] == 'A':
        cp = mp.parent / 'OBJECTIVE_COSTS.json'
        if 'source_sha256' not in read(cp)[0]:
            # Earlier seven reviews retain a coarse legacy cost projection.
            # Use the independently frozen common cut-window record, read only.
            cp = OUT / 'COMMON_COSTS' / (cid + '.json')
    else:
        cp = Path(m['objective_cost_record']['local_copy'])
    costs = read(cp)
    assert len(costs) == 4
    costs = {c['branch_id']: c for c in costs}
    assert set(costs) == set(s['branch_ids'])
    for i, ro in enumerate(m['rollouts'], 1):
        if 'official_state' not in ro:
            # Explicit legacy field-name mapping, not semantic relabeling.
            assert 'state' in ro and 'work_mapping' in ro
            ro = dict(ro, official_state=ro['state'],
                      work_reconstruction={'assessment':ro['function_reconstruction'],
                                           'verbatim_work_mapping':ro['work_mapping']},
                      judgment_change=ro['judgment_action_chain'],
                      action_chain=ro['judgment_action_chain'],
                      cost_localization=ro['cost_location'], unknowns=ro['unknown'])
        bid = ro['branch_id']
        assert bid == s['branch_ids'][i - 1]
        assert ro['official_state'] == s[f'rep{i}']
        assert ro['work_reconstruction'] and ro['evidence']
        c = costs[bid]
        assert c['source_sha256'] == e['source_sha256']
        old = c['original_suffix_recorded_request_costs']
        interval = c['original_generated_suffix_conservative_interval']
        g = c['teacher_prefill_tokens']
        new = c['new_generated_tokens']
        assert c['teacher_prefill_in_generated_count'] is False
        assert c['saving_generated_plus_teacher_interval'] == [interval[0]-new-g, interval[1]-new-g]
        assert c['saving_prompt_tokens'] == old['prompt_tokens']-c['new_prompt_tokens']
        assert c['saving_actor_calls'] == old['actor_calls']-c['new_actor_calls']
        assert c['saving_tools_total'] == old['tools_total']-c['new_tools_total']
        assert c['boundary_mode'] == 'RECONSTRUCTED_CHAR_EXACT'
        assert c['native_token_exact_saving'] is None
        branch_rows.append({
            'case_id':cid, 'category':m['category'], 'main_problem_id':m['main_problem_id'],
            'trajectory_id':m['trajectory_id'], 'branch_id':bid, 'rep':i,
            'intervention':m['intervention'], 'original_state':s['original_answer_state'],
            'new_state':ro['official_state'], 'transition':s['original_answer_state']+'->'+ro['official_state'],
            'boundary_mode':c['boundary_mode'],
            'original_generation_lower':interval[0], 'original_generation_upper':interval[1],
            'new_generated_tokens':new, 'teacher_prefill_tokens':g,
            'saving_gen_plus_G_lower':interval[0]-new-g, 'saving_gen_plus_G_upper':interval[1]-new-g,
            'original_prompt_tokens':old['prompt_tokens'], 'new_prompt_tokens':c['new_prompt_tokens'],
            'saving_prompt_tokens':c['saving_prompt_tokens'],
            'original_actor':old['actor_calls'], 'new_actor':c['new_actor_calls'],
            'original_tools':old['tools_total'], 'new_tools':c['new_tools_total'],
            'new_run_python':c['new_run_python_calls'], 'replayed_P_tokens':c['new_first_replay_P_input_tokens'],
            'review_file':str(mp), 'review_sha256':sha(mp),
            'cost_file':str(cp), 'cost_sha256':sha(cp),
            'work_reconstruction_verbatim':json.dumps(ro['work_reconstruction'],ensure_ascii=False),
            'judgment_change_verbatim':ro['judgment_change'],
            'action_chain_verbatim':ro['action_chain'],
            'cost_localization_verbatim':ro['cost_localization'],
            'unknowns_verbatim':json.dumps(ro.get('unknowns'),ensure_ascii=False)
        })
    stage_rows.append({
        'case_id':cid, 'category':m['category'], 'main_problem_id':m['main_problem_id'],
        'official_subproblem_id':m['official_subproblem_id'], 'trajectory_id':m['trajectory_id'],
        'intervention':m['intervention'], 'original_state':s['original_answer_state'],
        'new_states':'/'.join(s[f'rep{i}'] for i in range(1,5)),
        'state_changes':s['state_changes_vs_original'],
        'primary_function':assignments.get(cid,{}).get('primary_function'),
        'observed_links':assignments.get(cid,{}).get('observed_links'),
        'u_to_target_status_verbatim':assignments.get(cid,{}).get('u_to_target_status'),
        'counterevidence_from_synthesis_verbatim':assignments.get(cid,{}).get('important_counterevidence_or_limit'),
        'stage_function_verbatim':m['stage_function'],
        'candidate_chain_verbatim':json.dumps(m['candidate_mechanism_chain'],ensure_ascii=False),
        'review_file':str(mp), 'review_sha256':sha(mp), 'cost_file':str(cp), 'cost_sha256':sha(cp)
    })

def save_csv(name, rows):
    if not rows:
        return
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

save_csv('STAGE_INDEX.csv', stage_rows)
save_csv('BRANCH_RESULTS_AND_COSTS.csv', branch_rows)

summary = {'scope_sha256':sha(ROOT/'FROZEN_ANALYSIS_SCOPE.json'),
           'planned_stages':len(expected), 'completed_stages':len(models),
           'completed_rollouts':len(branch_rows), 'missing':sorted(set(expected)-set(models)),
           'synthesis_assignments':len(assignments), 'assignment_files':assignment_files,
           'mechanical_scope':'joins, statuses, source/cost provenance and arithmetic; not semantic gold validation',
           'groups':{}}
function_rows=[]
axis_rows=[]
for group in ['A','B']:
    ss=[x for x in stage_rows if x['category']==group]
    rr=[x for x in branch_rows if x['category']==group]
    summary['groups'][group]={
        'stages':len(ss), 'main_problems':len({x['main_problem_id'] for x in ss}),
        'source_trajectories':len({x['trajectory_id'] for x in ss}), 'rollouts':len(rr),
        'intervention_stages':dict(Counter(x['intervention'] for x in ss)),
        'original_stage_states':dict(Counter(x['original_state'] for x in ss)),
        'transitions':dict(Counter(x['transition'] for x in rr)),
        'definite_recorded_generation_reductions_including_G':sum(x['saving_gen_plus_G_lower']>0 for x in rr),
        'definite_recorded_generation_increases_including_G':sum(x['saving_gen_plus_G_upper']<0 for x in rr),
        'generation_change_unresolved_or_zero':sum(x['saving_gen_plus_G_lower']<=0<=x['saving_gen_plus_G_upper'] for x in rr),
        'prompt_reductions':sum(x['saving_prompt_tokens']>0 for x in rr),
        'actor_reductions':sum(x['original_actor']>x['new_actor'] for x in rr),
        'tool_reductions':sum(x['original_tools']>x['new_tools'] for x in rr),
        'native_exact_token_savings_available':False,
        'no_independent_branch_savings_summed':True}
    summary['groups'][group]['u_to_target_status_verbatim_counts']=dict(Counter(x['u_to_target_status_verbatim']for x in ss if x['u_to_target_status_verbatim']))
    for family in sorted({x['primary_function']for x in ss if x['primary_function']}):
        z=[x for x in ss if x['primary_function']==family]
        function_rows.append({'category':group,'primary_function':family,'stages':len(z),
                              'main_problems':len({x['main_problem_id']for x in z}),
                              'source_trajectories':len({x['trajectory_id']for x in z}),
                              'linked_rollouts_not_mechanism_occurrences':4*len(z),
                              'case_ids':'|'.join(x['case_id']for x in z)})
    axes=sorted({a for x in ss for a in (x['observed_links'] or '').split('|') if a})
    for axis in axes:
        z=[x for x in ss if axis in (x['observed_links'] or '').split('|')]
        axis_rows.append({'category':group,'observed_link':axis,'stages':len(z),
                          'main_problems':len({x['main_problem_id']for x in z}),
                          'source_trajectories':len({x['trajectory_id']for x in z}),
                          'not_all_four_rollouts_claimed_as_support':True,
                          'case_ids':'|'.join(x['case_id']for x in z)})
save_csv('FUNCTION_COUNTS.csv',function_rows)
save_csv('OBSERVATION_AXIS_COUNTS.csv',axis_rows)
(OUT/'DETERMINISTIC_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
