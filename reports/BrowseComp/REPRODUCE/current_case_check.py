"""Check a saved authored case and recompute costs. No semantic judgments."""
import argparse,csv,hashlib,json,re
from pathlib import Path
from current_ownership import load_effective_scope
P=Path(__file__).resolve().parent
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ptr(d,p):
 for k in p.split('/')[1:]:d=d[int(k)]if isinstance(d,list)else d[k.replace('~1','/').replace('~0','~')]
 return d
def save(p,d):
 p.parent.mkdir(exist_ok=True,parents=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def run(cid):
 r=next(x for x in load_effective_scope(P/'CURRENT_SCOPE_904.csv')if x['case_id']==cid);f=P/'CURRENT_ADJUDICATIONS'/f'{cid}.json';d=load(f)
 assert d['review_status']=='REVIEWED'and d['reviewer']==r['owner']and d['batch_id'].startswith(r['owner']+'_')
 assert all(d[k]for k in ['function','prestate','stage_effect','guidance_review','local_chain','attribution_limit','source_review_sufficiency'])
 assert len(d['four'])==4 and [x['repeat']for x in d['four']]==[1,2,3,4]
 assert [x['state']for x in d['four']]==r['four_outcomes'].split('/')
 old=load(Path(r['factual_record']));receipt=load(Path(r['existing_mechanical_receipt']));assert receipt['status']=='MECHANICAL_PASS'and receipt['source_bundle_sha256']==r['source_bundle_sha256']
 # One current case only; do not repeat the previous 904-wide source audit.
 assert sha(Path(r['source_bundle']))==r['source_bundle_sha256'];b=load(Path(r['source_bundle']))
 refs={e['id']:e for e in old['evidence']};refs.update({e['id']:e for e in d.get('extra_evidence',[])})
 need=set(d['evidence_ids'])|{e['id']for e in d.get('extra_evidence',[])}
 for z in d['four']:
  assert all(z[k]for k in ['first_decision_divergence','first_actual_call_divergence','judgment','action','restoration','cost_location','quality','evidence']);need.update(z['evidence'])
 for link in d['mechanism_links']:
  assert all(link[k]for k in ['description','locus','stage_attribution','counterevidence'])
  partition=sum([link[k]for k in ['observed_repeats','not_observed_repeats','uncertain_repeats','excluded_repeats']],[]);assert sorted(partition)==[1,2,3,4]
  for rep in link['observed_repeats']:assert link['evidence_by_repeat'].get(str(rep))
  for es in link['evidence_by_repeat'].values():need.update(es)
 assert need<=set(refs),(cid,need-set(refs));verified=[]
 for eid in sorted(need):
  e=refs[eid];side=e.get('source',e.get('side'));data=b['original']if side=='original'else b['branches'][side[3:]];q=e.get('quote',e.get('exact_quote'));value=ptr(data,e['pointer']);assert isinstance(value,str)and q in value,(eid,e['pointer'])
  if '/retrieved_documents/'in e['pointer']:
   ps=e['pointer'].split('/');ev=data['tool_events'][int(ps[2])];doc=ev['retrieved_documents'][int(ps[4])];assert any(str(z['docid'])==str(doc['docid'])and q in z['snippet']for z in json.loads(ev['exact_result']))
  verified.append({'id':eid,'source':side,'pointer':e['pointer'],'quote':q,'char_ranges':[[m.start(),m.start()+len(q)]for m in re.finditer(re.escape(q),value)],'field_sha256':hashlib.sha256(value.encode()).hexdigest()})
 a=b['audit'];oc=a['original_suffix_cost'];bd=a['boundary'];cr=a['deleted_stage']['round_id'];future=[z for z in b['original']['rounds']if z['round_id']>=cr];total=sum(z.get('completion_tokens')or 0 for z in future)
 if bd['mode']=='NATIVE_TOKEN_EXACT':low=high=oc['completion_tokens']
 else:
  low=total-bd['covering_original_token_end'][0];high=total-bd['native_prefix_token_count'];assert oc['completion_tokens']is None
 costs=[]
 for i in range(1,5):
  ledger=next(z for z in b['ledger_rows']if int(z['repeat_id'])==i);path=b['branches'][str(i)];gen=sum(z.get('completion_tokens')or 0 for z in path['rounds']);prompt=sum(z.get('prompt_tokens')or 0 for z in path['rounds']);g=int(ledger.get('teacher_prefill_tokens')or 0)
  assert gen==int(ledger['completion_tokens'])and prompt==int(ledger['prompt_tokens'])
  assert path['metadata']['terminal_status']==ledger['terminal_status'];formal=path['metadata']['terminal_status']=='MODEL_FINAL_STOP';state=d['four'][i-1]['state']
  if state in ['C','W']:assert formal
  elif state=='N':assert not formal
  else:assert state=='UNCERTAIN' # Uncertain correctness does not assert absence of Final.
  oldprompt=oc['original_inflight_prompt_tokens']+oc['future_prompt_tokens'];search=int(ledger['search_calls']);actor=int(ledger['actor_calls']);oldopen=sum('open'in e['tool_name'].lower()for e in b['original']['tool_events']if e['round_id']>=cr);newopen=sum('open'in e['tool_name'].lower()for e in path['tool_events'])
  costs.append({'repeat':i,'state':d['four'][i-1]['state'],'terminal':path['metadata']['terminal_status'],'boundary_mode':bd['mode'],'original_gen_interval':[low,high],'new_gen':gen,'G':g,'generation_delta_interval':[gen+g-high,gen+g-low],'original_search':oc['search_calls'],'new_search':search,'search_delta':search-oc['search_calls'],'original_actor':oc['actor_calls'],'new_actor':actor,'actor_delta':actor-oc['actor_calls'],'original_open':oldopen,'new_open':newopen,'open_delta':newopen-oldopen,'original_prompt':oldprompt,'new_prompt':prompt,'prompt_delta':prompt-oldprompt,'prefix_replay_tokens':int(ledger.get('prefix_replay_tokens')or 0)})
 save(P/'CURRENT_COSTS'/f'{cid}.json',{'case_id':cid,'costs':costs,'source_bundle_sha256':r['source_bundle_sha256']})
 result={'case_id':cid,'status':'PASS','decision_sha256':sha(f),'source_bundle_sha256':r['source_bundle_sha256'],'prior_mechanical_receipt_reused':r['existing_mechanical_receipt'],'references':verified,'cost_rows':4,'semantic_truth':'Not certified by this deterministic validator; Codex analysis and researcher review separate.'};save(P/'CURRENT_VALIDATION'/f'{cid}.json',result);print(json.dumps({'case_id':cid,'status':'PASS','references':len(verified),'cost_rows':4},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('case');run(p.parse_args().case)
