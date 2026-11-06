"""Recount explicitly model-authored memberships and saved objective costs."""
import csv,hashlib,json,sys
from collections import Counter
from pathlib import Path
P=Path(__file__).resolve().parent
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(batch):
 folder=P/'BATCH_REVIEW_RECORDS'/batch;b=load(folder/'BATCH_ANALYSIS.json')
 scope={r['case_id']:r for r in csv.DictReader((P/'CURRENT_SCOPE_904.csv').open(encoding='utf-8-sig'))}
 rows=[];mapping=[];groups=Counter();transitions=Counter();boundaries=Counter()
 for cid in b['case_ids']:
  f=P/'CURRENT_ADJUDICATIONS'/f'{cid}.json';d=load(f);v=load(P/'CURRENT_VALIDATION'/f'{cid}.json');s=scope[cid]
  assert d['batch_id']==batch and v['status']=='PASS' and v['decision_sha256']==sha(f)
  groups[s['current_group']]+=1
  for c in load(P/'CURRENT_COSTS'/f'{cid}.json')['costs']:
   rows.append({'case_id':cid,'question_id':s['question_id'],'original_run_id':s['original_run_id'],'group':s['current_group'],'original_state':s['original_state'],**c})
   transitions[s['original_state']+'->'+c['state']]+=1;boundaries[c['boundary_mode']]+=1
 for t in b['mechanism_tests']:
  assert len({(x['case_id'],x['local_id'])for x in t['links']})==len(t['links']),'Repeated authored local link'
  observed=[];not_observed=[];uncertain=[];excluded=[];stage=set();qs=set();runs=set()
  for l in t['links']:
   cid=l['case_id'];d=load(P/'CURRENT_ADJUDICATIONS'/f'{cid}.json');m=next(z for z in d['mechanism_links'] if z['local_id']==l['local_id']);s=scope[cid]
   for field,arr in [('observed_repeats',observed),('not_observed_repeats',not_observed),('uncertain_repeats',uncertain),('excluded_repeats',excluded)]:
    arr.extend([cid+f'__run{n}' for n in m[field]])
   if m['observed_repeats']:stage.add(cid);qs.add(s['question_id']);runs.add(s['original_run_id'])
   mapping.append({'test_id':t['id'],'case_id':cid,'question_id':s['question_id'],'group':s['current_group'],'local_id':l['local_id'],'observed':m['observed_repeats'],'not_observed':m['not_observed_repeats'],'uncertain':m['uncertain_repeats'],'excluded':m['excluded_repeats']})
  sets=[set(x)for x in [observed,not_observed,uncertain,excluded]]
  t['deterministic_counts']={'observed_stage_count':len(stage),'different_questions':len(qs),'original_runs':len(runs),'observed_rollouts':len(sets[0]),'not_observed_rollouts':len(sets[1]),'uncertain_rollouts':len(sets[2]),'excluded_rollouts':len(sets[3]),'observed_local_chain_occurrences':len(observed),'not_observed_local_chain_occurrences':len(not_observed),'uncertain_local_chain_occurrences':len(uncertain),'excluded_local_chain_occurrences':len(excluded),'total_distinct_rollouts_in_test':len(set().union(*sets)),'status_overlap_across_component_links':any(a&c for i,a in enumerate(sets)for c in sets[i+1:]),'counting_note':'Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.','observed_cases':sorted(stage),'question_ids':sorted(qs,key=int)}
 result={'batch_id':batch,'case_count':len(b['case_ids']),'question_count':len({scope[c]['question_id']for c in b['case_ids']}),'original_run_count':len({scope[c]['original_run_id']for c in b['case_ids']}),'rollout_count':len(rows),'groups':dict(groups),'transitions':dict(transitions),'boundary_modes_rollouts':dict(boundaries),'mechanism_tests':[{'id':t['id'],**t['deterministic_counts']}for t in b['mechanism_tests']],'explicit_membership_mapping':mapping,'cost_rows':rows,'semantic_counts_are_not_causal_support':True}
 (folder/'BATCH_COUNTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 text=[f'# {batch} 批次归纳',f"{result['case_count']} Stage / {result['question_count']}题 / {result['original_run_count']}原轨迹 / {result['rollout_count']}续跑；组别{dict(groups)}。",'以下机制是本人逐案裁定后的过程解释；统计由显式成员复算，非研究者独立人工金标准。']
 for section in ['functions','comparisons','mechanism_tests','unresolved']:
  text.append('\n## '+section)
  for z in b[section]:text.append('```json\n'+json.dumps(z,ensure_ascii=False,indent=2)+'\n```')
 text.append('\n## 限制\n'+b['limitations']);(folder/'BATCH_ANALYSIS.md').write_text('\n\n'.join(text),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items()if k not in ['cost_rows','explicit_membership_mapping']},ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
