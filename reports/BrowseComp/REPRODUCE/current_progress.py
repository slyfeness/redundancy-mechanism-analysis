"""Scope/import/checkpoint arithmetic. Does not generate semantic judgments."""
import argparse,collections,csv,hashlib,json
from pathlib import Path
from current_ownership import load_effective_scope
P=Path(__file__).resolve().parent;BASE=P.parent/'stage4_groupab_review'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):return list(csv.DictReader(p.open(encoding='utf-8-sig')))
def save(p,d):
 p.parent.mkdir(exist_ok=True,parents=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def csvsave(p,data):
 with p.open('w',encoding='utf-8-sig',newline='')as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
def init():
 assert not(P/'CURRENT_SCOPE_904.csv').exists(),'Scope already frozen'
 for name in ['CURRENT_ADJUDICATIONS','BATCH_REVIEW_RECORDS','REGISTRY_CURRENT','REGISTRY_PROPOSALS_CURRENT','CURRENT_VALIDATION']:(P/name).mkdir(exist_ok=True)
 state=rows(BASE/'final_tables_20261030/RESEARCH_STATE_COMPARISON_904.csv');ix={r['case_id']:r for r in rows(BASE/'final_tables_20261030/FULL_SOURCE_TRAJECTORY_INDEX_3616.csv')};owners={r['case_id']:r['owner']for r in rows(P/'ASSIGNMENTS.csv')};pilot={}
 for tag,folder in [('P1','function_mechanism_new10_20261031'),('P2','second10_deep_mechanism_20261031')]:
  d=P.parent/folder;receipt=load(d/'PACKAGE_VALIDATION.json');assert sha(Path(receipt['zip']))==receipt['sha256']
  for f in(d/'DECISIONS').glob('*.json'):
   x=load(f);cid=x['case_id'];assert cid not in pilot;pilot[cid]={'tag':tag,'decision_file':str(f),'decision_sha256':sha(f),'method_directory':str(d),'archive':receipt['zip'],'archive_sha256':receipt['sha256']}
 assert len(pilot)==20
 scope=[]
 for r in state:
  cid=r['case_id'];out=[r[f'repeat{i}_research_state']for i in range(1,5)];changes=sum(s!=r['original_research_state']for s in out);group='A'if r['original_research_state']=='C'and changes<=1 else'B'if changes>=3 else'OUTSIDE_CURRENT_AB';src=ix[cid]
  scope.append({'case_id':cid,'question_id':r['question_id'],'original_run_id':r['original_run_id'],'stage_id':r['stage_id'],'condition':r['condition'],'frozen_group':r['frozen_group'],'current_group':group,'original_state':r['original_research_state'],'four_outcomes':'/'.join(out),'cwn_changes':changes,'owner':owners[cid],'pilot_reuse':pilot[cid]['tag']if cid in pilot else'','factual_record':str(BASE/r['decision_file']),'factual_record_sha256':r['decision_sha256'],'source_bundle':src['complete_local_bundle'],'source_bundle_sha256':src['complete_local_bundle_sha256'],'existing_mechanical_receipt':str(P/'MECHANICAL'/f'{cid}.json')})
 assert len(scope)==904 and len({r['case_id']for r in scope})==904 and set(pilot)<=set(r['case_id']for r in scope)
 csvsave(P/'CURRENT_SCOPE_904.csv',scope);save(P/'PILOT20_IMPORT_RECEIPTS.json',pilot)
 for cid,item in pilot.items():
  original=Path(item['decision_file']);dest=P/'CURRENT_ADJUDICATIONS'/f'{cid}.json';assert not dest.exists();dest.write_bytes(original.read_bytes())
 save(P/'CURRENT_INPUT_MANIFEST.json',{'scope_sha256':sha(P/'CURRENT_SCOPE_904.csv'),'old_scope_retained':str(P/'SCOPE_904.csv'),'pilot20_imports':20,'remaining':884,'mechanical904_reused_not_semantic_completion':True,'method':'CURRENT_904_SCHEMA_V2.md','owners':dict(collections.Counter(r['owner']for r in scope if not r['pilot_reuse']))})
 status()
def status():
 scope=load_effective_scope(P/'CURRENT_SCOPE_904.csv');pilot=load(P/'PILOT20_IMPORT_RECEIPTS.json');done=[];ready=[]
 for r in scope:
  f=P/'CURRENT_ADJUDICATIONS'/f"{r['case_id']}.json"
  if not f.exists():continue
  d=load(f);assert d['case_id']==r['case_id'];assert len(d['four'])==4
  assert [x['state']for x in d['four']]==r['four_outcomes'].split('/')
  if r['case_id']in pilot:assert sha(f)==pilot[r['case_id']]['decision_sha256'];done.append(r)
  elif d.get('review_status')=='REVIEWED':
   vf=P/'CURRENT_VALIDATION'/f"{r['case_id']}.json"
   if vf.exists()and load(vf).get('status')=='PASS'and load(vf).get('decision_sha256')==sha(f):
    ready.append(r)
    batch=d.get('batch_id');bf=P/'BATCH_REVIEW_RECORDS'/str(batch)/'BATCH_ANALYSIS.json'
    if bf.exists()and r['case_id']in load(bf).get('case_ids',[]):done.append(r)
 progress={'scope':904,'completed_semantic_cases_including_pilots':len(done),'completed_rollouts':len(done)*4,'pilot_reused':20,'new_cases_checked_waiting_batch_or_done':len(ready),'remaining':904-len(done),'completed_by_owner':dict(collections.Counter(r['owner']for r in done)),'remaining_by_owner':dict(collections.Counter(r['owner']for r in scope if r['case_id']not in {z['case_id']for z in done})),'completed_by_current_group':dict(collections.Counter(r['current_group']for r in done)),'not_a_claim_of_independent_human_gold':True}
 save(P/'CURRENT_PROGRESS.json',progress);print(json.dumps(progress,ensure_ascii=False))
def batch(owner,num):
 scope=load_effective_scope(P/'CURRENT_SCOPE_904.csv');available=[r for r in scope if r['owner']==owner and not(P/'CURRENT_ADJUDICATIONS'/f"{r['case_id']}.json").exists()];chosen=[];seen=set()
 # Select pending cases by group, round-robin through different questions.
 for group in ['A','B']:
  for r in sorted(available,key=lambda r:(int(r['question_id']),r['case_id'])):
   if r['current_group']==group and r['question_id']not in seen and len([x for x in chosen if x['current_group']==group])<5:chosen.append(r);seen.add(r['question_id'])
 for r in available:
  if len(chosen)>=10:break
  if r['case_id']not in{x['case_id']for x in chosen}:chosen.append(r)
 folder=P/'BATCH_REVIEW_RECORDS'/f'{owner}_{num:03d}';folder.mkdir(exist_ok=True)
 assert not(folder/'01_CASES.csv').exists(),'Batch frozen; reuse it'
 csvsave(folder/'01_CASES.csv',chosen);print(json.dumps([{'case_id':r['case_id'],'group':r['current_group'],'original':r['original_state'],'new':r['four_outcomes']}for r in chosen],ensure_ascii=False,indent=2))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['init','status','batch']);a.add_argument('--owner',choices=['ROOT','PEER']);a.add_argument('--num',type=int);x=a.parse_args()
 if x.action=='init':init()
 elif x.action=='status':status()
 else:batch(x.owner,x.num)
