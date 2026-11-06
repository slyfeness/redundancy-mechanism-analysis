"""Recheck delivered CSV counts and costs using only the extracted package.

No model requests, semantic classification, label inference or source mutation.
Run: python RECOMPUTE/recompute_packaged_statistics.py
"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

P=Path(__file__).resolve().parent.parent
def rows(name):return list(csv.DictReader((P/'STATISTICS'/name).open(encoding='utf-8-sig',newline='')))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
st=rows('STAGE_INDEX.csv');br=rows('BRANCH_RESULTS_AND_COSTS.csv')
fc=rows('FUNCTION_COUNTS.csv');ax=rows('OBSERVATION_AXIS_COUNTS.csv')
assert len(st)==len({r['case_id']for r in st})==249
assert len(br)==len({r['branch_id']for r in br})==996
assign=[]
for name in ['A_SYNTHESIS_HANDWRITTEN.csv','B_SYNTHESIS_HANDWRITTEN.csv']:
    assign.extend(csv.DictReader((P/'SYNTHESIS'/name).open(encoding='utf-8-sig',newline='')))
am={r['case_id']:r for r in assign};assert len(am)==249
states={r['case_id']:r for r in st}
for r in st:
    cid=r['case_id'];g=r['category']
    m=read(P/'MODEL_REVIEWS'/g/cid/'MODEL_REVIEW.json')
    assert r['primary_function']==am[cid]['primary_function']
    assert r['observed_links']==am[cid]['observed_links']
    assert hashlib.sha256((P/'MODEL_REVIEWS'/g/cid/'MODEL_REVIEW.json').read_bytes()).hexdigest()==r['review_sha256']
    assert len(m['rollouts'])==4
for r in fc:
    z=[x for x in st if x['category']==r['category']and x['primary_function']==r['primary_function']]
    assert len(z)==int(r['stages'])
    assert len({x['main_problem_id']for x in z})==int(r['main_problems'])
    assert len({x['trajectory_id']for x in z})==int(r['source_trajectories'])
    assert {x['case_id']for x in z}==set(r['case_ids'].split('|'))
for r in ax:
    z=[x for x in st if x['category']==r['category']and r['observed_link']in x['observed_links'].split('|')]
    assert len(z)==int(r['stages'])
    assert len({x['main_problem_id']for x in z})==int(r['main_problems'])
    assert {x['case_id']for x in z}==set(r['case_ids'].split('|'))
for r in br:
    g=r['category'];cid=r['case_id']
    costs=read(P/'MODEL_REVIEWS'/g/cid/'OBJECTIVE_COSTS.json')
    c=next(x for x in costs if x['branch_id']==r['branch_id'])
    old=c['original_suffix_recorded_request_costs'];lo,hi=c['original_generated_suffix_conservative_interval']
    n=c['new_generated_tokens'];teacher=c['teacher_prefill_tokens']
    assert int(r['saving_gen_plus_G_lower'])==lo-n-teacher
    assert int(r['saving_gen_plus_G_upper'])==hi-n-teacher
    assert int(r['saving_prompt_tokens'])==old['prompt_tokens']-c['new_prompt_tokens']
    assert int(r['new_actor'])==c['new_actor_calls']
    assert int(r['new_tools'])==c['new_tools_total']
    assert c['boundary_mode']=='RECONSTRUCTED_CHAR_EXACT'and c['native_token_exact_saving']is None
summary=read(P/'STATISTICS/DETERMINISTIC_SUMMARY.json')
for g in ['A','B']:
    z=[r for r in br if r['category']==g]
    assert dict(Counter(r['transition']for r in z))==summary['groups'][g]['transitions']
print(json.dumps({'stages':249,'rollouts':996,'function_rows':len(fc),'observation_rows':len(ax),'coverage_cost_states':'PASS','semantic_gold_claim':False}))
