"""Join explicit model-authored decisions; hash, count and export only. No semantic classifier."""
import collections,csv,hashlib,json,shutil
from pathlib import Path
P=Path(__file__).resolve().parent
O=P/'FINAL_904_STAGE_ATLAS_20261101'

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def readcsv(p):return list(csv.DictReader(p.open(encoding='utf-8-sig')))
def save(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def csvsave(p,rows,fields=None):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8-sig',newline='')as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def distinct_counts(a):
 return {'stages':len({r['case_id']for r in a}),'questions':len({r['question_id']for r in a}),'original_runs':len({r['original_run_id']for r in a}),'rollouts':len({(r['case_id'],str(r['repeat']))for r in a})}
def apply_compatibility(row,prior,special):
 r=dict(row);v=special or prior;r['canonical_id']=r['candidate_id'];r['compatibility_source']='explicit_source_membership'
 if v:
  assert r['source_decision_sha256']==v['sha'],(r['case_id'],'source_changed')
  r['canonical_id']=v['canonical'];r['compatibility_source']=v['source']
 if r['status']!='OBSERVED':r['canonical_status']={'NOT_OBSERVED':'NOT_OBSERVED_LOCAL','UNCERTAIN':'UNCERTAIN_OBSERVATION','EXCLUDED':'EXCLUDED_WINDOW'}[r['status']]
 elif not v or int(r['repeat'])in v['approved']:r['canonical_status']='OBSERVED_COMPATIBLE'
 elif int(r['repeat'])in v['held']:r['canonical_status']='UNCERTAIN_DEFINITION'
 elif int(r['repeat'])in v['move']:r['canonical_status']='OPEN_CHAIN';r['canonical_id']=''
 else:raise AssertionError((r['case_id'],r['local_id'],r['repeat'],'unaccounted observation'))
 return r

def canonical_definitions():
 defs={}
 for f in sorted((P/'REGISTRY_CURRENT').glob('V*.json')):
  for x in load(f).get('candidates',[]):
   d=x.get('original_authored_record',x)
   if d.get('definition')and x['registry_id']not in defs:defs[x['registry_id']]={'registry_id':x['registry_id'],'source':str(f.relative_to(P)),'source_sha256':sha(f),'authored_definition':d}
 assert len(defs)==16
 return defs

def main():
 O.mkdir(exist_ok=True);scope=readcsv(P/'CURRENT_SCOPE_904.csv');ix={x['case_id']:x for x in scope};imports=load(P/'PILOT20_IMPORT_RECEIPTS.json');progress=load(P/'CURRENT_PROGRESS.json')
 assert progress['completed_semantic_cases_including_pilots']==904 and len(ix)==904
 defs=canonical_definitions();save(O/'FROZEN_CANDIDATE_DEFINITIONS.json',defs)
 aliases={x:'P1_'+x for x in ['K1','K2','K3']}|{x:'P2_'+x for x in ['R1','R2','R3']}
 peer={};specific={}
 for e in load(P/'PEER_FINAL_REGISTRY_COMPATIBILITY_REVIEW_v2.json')['entries']:
  peer[(e['case_id'],e['local_id'])]={'canonical':e['registry_id'],'approved':e['approved_observed_repeats'],'held':[]if e['compatibility_decision']=='MOVE_OPEN'else e['held_observed_repeats'],'move':e['held_observed_repeats']if e['compatibility_decision']=='MOVE_OPEN'else[],'sha':e['source_decision_sha256'],'source':'PEER_FINAL_REGISTRY_COMPATIBILITY_REVIEW_v2.json','reason':e['model_review_reason']}
 for e in load(P/'PEER_N003_DEFINITION_COMPATIBILITY_REVIEW.json')['entries']:
  specific[(e['case_id'],e['local_id'])]={'canonical':'N003_WRONG_CONSTRAINT_TARGET_DISPATCHES_UNREQUIRED_CHECK','approved':e['keep_canonical_observed_repeats'],'held':e['compatibility_uncertain_repeats'],'move':e['move_open_observed_repeats'],'sha':e['source_decision_sha256'],'source':'PEER_N003_DEFINITION_COMPATIBILITY_REVIEW.json','reason':e['reason_authored_by_codex']}
 rows=[];changes=[]
 for r in readcsv(P/'STAGE_MECHANISM_MAPPING.csv'):
  key=(r['case_id'],r['local_id']);r['source_decision_sha256']=sha(P/'CURRENT_ADJUDICATIONS'/f"{r['case_id']}.json")
  r['candidate_id']=aliases.get(r['candidate_id'],r['candidate_id']);a=apply_compatibility(r,peer.get(key),specific.get(key))
  if a['canonical_id']not in defs:
   a['canonical_id']='';a['canonical_status']='OPEN_CHAIN'if r['status']=='OBSERVED'else 'OPEN_'+r['status']
  a['compatibility_reason']=(specific.get(key)or peer.get(key)or{}).get('reason','Explicit model-authored source candidate membership retained; no text-derived assignment.')
  rows.append(a)
  if key in specific or key in peer:changes.append(a)
 csvsave(O/'STAGE_MECHANISM_MAPPING.csv',rows);csvsave(O/'DEFINITION_COMPATIBILITY_OVERLAY.csv',changes)
 # Four outcomes/costs: 884 current checked records, 20 previously sealed pilots unchanged.
 costs=[];evidence=[];records=[]
 pilotcost={};pilotevidence={}
 for tag in ['P1','P2']:
  folder=Path(next(v['method_directory']for v in imports.values()if v['tag']==tag))/'DELIVERY'
  for c in readcsv(folder/'COSTS_40.csv'):pilotcost[(c['case_id'],int(c['repeat']))]=c
  for line in (folder/'PRECISE_EVIDENCE_INDEX.jsonl').read_text(encoding='utf-8').splitlines():
   e=json.loads(line);e['evidence_id']=e['evidence_id'].split('_',1)[1];pilotevidence[(e['case_id'],e['evidence_id'])]=e
 for s in scope:
  cid=s['case_id'];f=P/'CURRENT_ADJUDICATIONS'/f'{cid}.json';d=load(f);assert d['case_id']==cid and [z['state']for z in d['four']]==s['four_outcomes'].split('/')
  if cid in imports:
   assert sha(f)==imports[cid]['decision_sha256'];old=load(Path(s['factual_record']));refs={e['id']:e for e in old['evidence']}
   for eid in d['evidence_ids']:
    e=pilotevidence[(cid,eid)];evidence.append(e|{'evidence_id':cid+'::'+eid,'local_evidence_id':eid})
   # The original pilot CSV lacks only original Open. Read that field from its already local source, without semantic relabelling.
   b=load(Path(s['source_bundle']));cut=b['audit']['deleted_stage']['round_id'];oldopen=sum('open'in e['tool_name'].lower()for e in b['original']['tool_events']if e['round_id']>=cut)
   cs=[]
   for i in range(1,5):
    x=pilotcost[(cid,i)];cs.append({'repeat':i,'state':x['new_state'],'terminal':x['terminal_status'],'boundary_mode':x['boundary_mode'],'original_gen_interval':[int(x['original_suffix_gen_low']),int(x['original_suffix_gen_high'])],'new_gen':int(x['new_generation']),'G':int(x['teacher_tokens_once']),'generation_delta_interval':[int(x['generation_delta_low']),int(x['generation_delta_high'])],'original_search':int(x['original_search']),'new_search':int(x['new_search']),'search_delta':int(x['search_delta']),'original_actor':int(x['original_actor']),'new_actor':int(x['new_actor']),'actor_delta':int(x['actor_delta']),'original_open':oldopen,'new_open':int(x['new_open']),'open_delta':int(x['new_open'])-oldopen,'original_prompt':int(x['original_prompt']),'new_prompt':int(x['new_prompt']),'prompt_delta':int(x['prompt_delta']),'prefix_replay_tokens':int(x['prefix_replay_tokens'])})
  else:
   v=load(P/'CURRENT_VALIDATION'/f'{cid}.json');assert v['status']=='PASS'and v['decision_sha256']==sha(f)and v['source_bundle_sha256']==s['source_bundle_sha256'];cs=load(P/'CURRENT_COSTS'/f'{cid}.json')['costs']
   batch=load(P/'BATCH_REVIEW_RECORDS'/d['batch_id']/'BATCH_ANALYSIS.json');assert cid in batch['case_ids']
   for e in v['references']:evidence.append({'evidence_id':cid+'::'+e['id'],'local_evidence_id':e['id'],'case_id':cid,'source_side':e['source'],'json_pointer':e['pointer'],'exact_quote':e['quote'],'unicode_occurrences':e['char_ranges'],'source_sha256':s['source_bundle_sha256'],'source_path':s['source_bundle'],'field_sha256':e['field_sha256']})
  for c in cs:
   i=c['repeat'];assert c['state']==s['four_outcomes'].split('/')[i-1]
   assert c['generation_delta_interval']==[c['new_gen']+c['G']-c['original_gen_interval'][1],c['new_gen']+c['G']-c['original_gen_interval'][0]]
   costs.append({k:s[k]for k in ['case_id','question_id','original_run_id','current_group','condition','original_state']}|{'repeat':i}|{k:v for k,v in c.items()if k not in ['generation_delta_interval','original_gen_interval']}|{'original_gen_low':c['original_gen_interval'][0],'original_gen_high':c['original_gen_interval'][1],'generation_delta_low':c['generation_delta_interval'][0],'generation_delta_high':c['generation_delta_interval'][1]})
  records.append({k:s[k]for k in ['case_id','question_id','original_run_id','stage_id','condition','current_group','original_state','four_outcomes','source_bundle','source_bundle_sha256','factual_record','factual_record_sha256']}|{'decision_path':'DECISIONS/'+cid+'.json','decision_sha256':sha(f),'function':d['function'],'local_chain':d['local_chain'],'attribution_limit':d['attribution_limit'],'guidance_review':d['guidance_review']})
  dest=O/'DECISIONS'/f'{cid}.json';dest.parent.mkdir(exist_ok=True);shutil.copy2(f,dest)
 assert len(costs)==3616 and len({(x['case_id'],x['repeat'])for x in costs})==3616
 assert {x['case_id']for x in evidence}==set(ix)
 csvsave(O/'COST_AND_RESULT_3616.csv',costs);csvsave(O/'STAGE_FUNCTION_MAPPING.csv',records)
 with(O/'PRECISE_EVIDENCE_INDEX.jsonl').open('w',encoding='utf-8')as f:
  for e in evidence:f.write(json.dumps(e,ensure_ascii=False)+'\n')
 # Canonical positives deduplicate multiple component chains at Stage x repeat. Other local observations remain open.
 counts=[];cx={(c['case_id'],str(c['repeat'])):c for c in costs}
 for k in sorted({(r['canonical_id'],r['group'],r['condition'],r['canonical_status'])for r in rows if r['canonical_id']}):
  a=[r for r in rows if(r['canonical_id'],r['group'],r['condition'],r['canonical_status'])==k]
  counts.append(dict(zip(['mechanism_id','group','condition','status'],k))|distinct_counts(a))
 csvsave(O/'MECHANISM_SUPPORT_COUNTEREXAMPLES.csv',counts)
 transition=[];directions=[]
 for mid in defs:
  for group in ['A','B','OUTSIDE_CURRENT_AB']:
   for cond in ['FIRST_SENTENCE','TERMINAL_DROP_NO_ANCHOR']:
    a=[r for r in rows if r['canonical_id']==mid and r['group']==group and r['condition']==cond and r['canonical_status']=='OBSERVED_COMPATIBLE'];keys={(r['case_id'],r['repeat'])for r in a};cc=[cx[k]for k in keys]
    for old,new in sorted({(c['original_state'],c['state'])for c in cc}):
     z=[r for r in a if cx[(r['case_id'],r['repeat'])]['original_state']==old and cx[(r['case_id'],r['repeat'])]['state']==new]
     transition.append({'mechanism_id':mid,'group':group,'condition':cond,'original_state':old,'new_state':new}|distinct_counts(z))
    if cc:
     directions.append({'mechanism_id':mid,'group':group,'condition':cond,'rollouts':len(cc),'gen_definitely_lower':sum(c['generation_delta_high']<0 for c in cc),'gen_definitely_higher':sum(c['generation_delta_low']>0 for c in cc),'gen_zero_or_interval_crosses_zero':sum(c['generation_delta_low']<=0<=c['generation_delta_high']for c in cc),'search_lower':sum(c['search_delta']<0 for c in cc),'search_higher':sum(c['search_delta']>0 for c in cc),'actor_lower':sum(c['actor_delta']<0 for c in cc),'actor_higher':sum(c['actor_delta']>0 for c in cc),'prompt_lower':sum(c['prompt_delta']<0 for c in cc),'prompt_higher':sum(c['prompt_delta']>0 for c in cc),'native_exact':sum(c['boundary_mode']=='NATIVE_TOKEN_EXACT'for c in cc)})
 csvsave(O/'MECHANISM_RESULT_TRANSITIONS.csv',transition);csvsave(O/'MECHANISM_COST_DIRECTIONS.csv',directions)
 summary={'completed_stages':904,'rollouts':3616,'different_questions':len({s['question_id']for s in scope}),'original_runs':len({s['original_run_id']for s in scope}),'groups':dict(collections.Counter(s['current_group']for s in scope)),'conditions_stages':dict(collections.Counter(s['condition']for s in scope)),'boundaries_rollouts':dict(collections.Counter(c['boundary_mode']for c in costs)),'transitions':dict(collections.Counter(c['original_state']+'->'+c['state']for c in costs)),'evidence_quotes':len(evidence),'canonical_definitions':len(defs),'local_chain_rows':len(rows),'compatibility_rows':len(changes),'observed_open_chain_rows':sum(r['canonical_status']=='OPEN_CHAIN'for r in rows),'uncertain_definition_rows':sum(r['canonical_status']=='UNCERTAIN_DEFINITION'for r in rows),'no_semantic_label_generation':True,'counts_are_not_causal_proof':True}
 save(O/'COMPUTED_SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
