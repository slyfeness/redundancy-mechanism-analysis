"""Check a completed public delivery, without interpreting model judgments."""
import collections,csv,hashlib,json
from pathlib import Path
P=Path(__file__).resolve().parents[1];R=P.parents[1]
read=lambda p:json.loads(p.read_bytes())
s=read(P/'comparison.json');plan=read(P/'selection.json')
with (P/'trajectory_outcomes.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
checks=[]
def require(name,ok):
    if not ok:raise AssertionError(name)
    checks.append(name)
require('100_distinct_questions',len(plan['query_ids'])==len(set(plan['query_ids']))==100)
require('400_unique_model_trajectory_rows',len(rows)==400 and len({(r['model'],r['trajectory_id']) for r in rows})==400)
require('same_200_tasks_for_each_model',all(len([r for r in rows if r['model']==m])==200 for m in ['4B','9B']))
require('exactly_two_per_model_per_question',all(
    collections.Counter(r['question_id'] for r in rows if r['model']==m)==
    collections.Counter({q:2 for q in plan['query_ids']}) for m in ['4B','9B']))
require('all_400_sealed_and_scored',not s['failures'] and all(s['models'][m]['overall']['sealed_trajectories']==200
    and s['models'][m]['overall']['scored_trajectories']==200 for m in ['4B','9B']))
require('paired_seed_and_question_identity',all(
    len({(r['seed'],r['question_id']) for r in rows if r['trajectory_id']==t})==1 for t in {r['trajectory_id'] for r in rows}))
require('64_old_records_reused',sum(r['reused']=='True' for r in rows)==64)
require('round2_217_stages_unchanged',s['round2_regression']=={'stages_compared':217,'all_equal':True})
require('no_optimization_or_external_models',s['optimizer_steps']==s['external_model_requests']==s['analysis_model_calls']==0)
require('prior_probe_files_unchanged',all(hashlib.sha256((R/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in read(P/'prior_files_sha256.json')))
integrity=read(P/'input_integrity.json')
require('400_integrity_checks',len(integrity)==400 and all(r['unchanged'] for r in integrity))
require('64_reused_source_hashes_match_pre_run',read(P/'publication_check.json')['reused_source_hashes_match_preparation']==64)
public=[p for p in P.rglob('*') if p.is_file() and not {'private','__pycache__'}&set(p.relative_to(P).parts)]
require('files_under_5MB',all(p.stat().st_size<5_000_000 for p in public))
require('all_UTF8',all(isinstance(p.read_text(encoding='utf-8'),str) for p in public))
result={'checks':checks,'passed':len(checks),'failed':0,'note':'Bookkeeping and integrity checks, not human correctness verification.'}
(P/'validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
