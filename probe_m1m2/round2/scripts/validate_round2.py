"""Validate public artifacts and immutable inputs; no models, no network.

Run from any directory. With --private, additionally check citations against
the uncommitted private inspection file downloaded from CPU job 190949.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
from pathlib import Path
from rules import REPEAT_FLAGS, classify, selftest

O=Path(__file__).resolve().parents[1]
ROOT=O.parents[1]
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def csvread(name):
    with (O/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

args=argparse.ArgumentParser();args.add_argument('--private',action='store_true');args=args.parse_args()
checks=[]
def check(name, ok):
    if not ok:raise AssertionError(name)
    checks.append(name)

unit_count=selftest()
stages=csvread('redundancy_stage_flags.csv');outcomes=csvread('trajectory_outcomes.csv')
summary=read(O/'redundancy_summary.json');atomic=read(O/'atomic_conditions_pilot.json')
demo=read(O/'first_support_demo.json');examples=read(O/'example_review_index.json')
prior=read(O/'prior_files_sha256.json')
check('previous_probe_files_unchanged',all(sha(ROOT/r['path'])==r['sha256'] for r in prior))
check('20_frozen_selected_trajectories',set(x['trajectory_id'] for x in outcomes)==set(read(O.parent/'selection.json')['ids']) and len(outcomes)==20)
check('217_unique_tool_stages',len(stages)==217 and len({(x['trajectory_id'],x['stage_id']) for x in stages})==217)
check('same_10_questions_in_conditions',len(atomic)==10 and {q['question_id'] for q in atomic}=={o['question_id'] for o in outcomes})
check('all_conditions_sequential_and_linked',all([c['id'] for c in q['conditions']]==['C'+str(i+1) for i in range(len(q['conditions']))]
    and all(bool(c['feature_key'])==(c['source']=='fuzzed_features') for c in q['conditions']) for q in atomic))
check('all_original_hashes_verified',len(read(O/'input_integrity.json'))==20 and all(r['unchanged'] for r in read(O/'input_integrity.json')))
check('no_new_models_or_training',summary['new_judge_calls']==summary['model_calls']==summary['optimizer_steps']==0)
check('call_and_token_denominators',sum(int(r['n_tool_calls']) for r in outcomes)==217 and sum(int(r['total_generated_tokens']) for r in outcomes)==89695
      and sum(int(r['known_obs_tokens']) for r in outcomes)==114056)
check('missing_obs_not_zero_filled',sum(r['obs_tokens']=='' for r in stages)==7 and all(r['total_obs_tokens']=='' for r in outcomes if int(r['obs_missing_stages'])>0))
flags=[json.loads(x['flags']) for x in stages]
check('flag_counts',all(sum(k in f for f in flags)==v['calls'] for k,v in summary['overall']['classes'].items()))
check('union_deduplicated',sum(bool(set(f)&REPEAT_FLAGS) for f in flags)==summary['overall']['any_repeat']['calls']==52)
check('outcomes_reconciled',sum(r['submitted']=='True' for r in outcomes)==11 and sum(r['correct']=='True' for r in outcomes)==10)
check('rho_and_success_cost',all(r['rho_x']==sum(o['correct']=='True' for o in outcomes if o['question_id']==r['question_id'])/2 for r in read(O/'per_question_outcomes.json')))
check('three_demo_conditions_complete',len(demo['demos'])==3 and all(
    [c['condition_id'] for c in d['conditions']]==[c['id'] for q in atomic if q['source_question_id']==d['source_question_id'] for c in q['conditions']]
    for d in demo['demos']))
check('examples_at_most_eight',all(n<=8 for n in collections.Counter(e['class'] for e in examples).values()))
check('think_excerpts_30_words',all(not e['reason_excerpt'] or len(e['reason_excerpt'].split())<=30 for e in examples))

def citations(obj):
    if isinstance(obj,dict):
        if 'quote' in obj and 'field' in obj:yield obj
        for value in obj.values():yield from citations(value)
    elif isinstance(obj,list):
        for value in obj:yield from citations(value)

check('demo_excerpt_limits',all(len(c['quote'].split())<=(30 if c['field']=='reasoning' else 40) for c in citations(demo)))
check('feature_keys_short',all(len((c['feature_key'] or '').split())<=40 for q in atomic for c in q['conditions']))
public=[p for p in O.rglob('*') if p.is_file() and not any(x in {'private','__pycache__'} for x in p.relative_to(O).parts)]
check('public_files_below_5MB',all(p.stat().st_size<5_000_000 for p in public))
check('public_UTF8',all(p.read_text(encoding='utf-8') is not None for p in public))
secret=re.compile(r'(?:sk-[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)')
check('no_credential_patterns',not any(secret.search(p.read_text(encoding='utf-8')) for p in public))

if args.private:
    es=read(O/'private/run-190949/private/review_events.json')
    index={(e['trajectory_id'],e['stage_id']):e for e in es};past=collections.defaultdict(list)
    for e in es:
        actual=classify(e,past[e['trajectory_id']]);assert actual==(e['flags'],e['earlier_match_stage_ids'])
        past[e['trajectory_id']].append(e)
    check('recompute_all_217_rules',len(es)==217)
    for d in demo['demos']:
        for c in citations(d):
            e=index[d['trajectory_id'],c['stage_id']]
            body=(e['reasoning'] if c['field']=='reasoning' else e['tool_result']['text'] if c['field']=='text'
                  else next(r['caption'] for r in e['tool_result']['results'] if r['docid']==c['docid']))
            assert body[c['start']:c['end']]==c['quote'] and hashlib.sha256(body.encode()).hexdigest()==c['source_sha256']
        assert {r['stage_id'] for r in d['stage_review']}=={e['stage_id'] for e in es if e['trajectory_id']==d['trajectory_id']}
        for c in d['conditions']:
            if c['first_supported_stage']:
                support=index[d['trajectory_id'],c['first_supported_stage']]['stage_index']
                assert all(index[d['trajectory_id'],v['stage_id']]['stage_index']<=support for v in c['evidence'])
    check('exact_demo_quotes_and_no_future_citation',True)
    for e in examples:
        if e['reason_excerpt']:assert e['reason_excerpt'] in index[e['trajectory_id'],e['stage_id']]['reasoning']
    check('exact_example_quotes',True)
    questions=read(O/'private/run-190949/private/question_context.json')
    for p in public:
        text=p.read_text(encoding='utf-8')
        assert not any(q['prompt'] in text or json.dumps(q['prompt'],ensure_ascii=False)[1:-1] in text for q in questions),p
        assert not any(e['raw_return'] in text for e in es if len(e['raw_return'].split())>40),p
    check('no_full_prompts_or_long_raw_returns',True)

result={'synthetic_rule_tests_passed':unit_count,'artifact_checks_passed':len(checks),'failed':0,
        'checks':checks,'private_checks_executed':args.private,'new_model_calls':0,'optimizer_steps':0,
        'previous_probe_files_checked':len(prior),
        'note':'Tests validate bookkeeping, immutable files and quote locations, not semantic judgment quality.'}
(O/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
