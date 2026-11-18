import csv,json,os
from pathlib import Path
from native_stages import stage_costs
B=Path('/file_storage01/home/weiyu/lanyi');P=B/'projects/deepsearch-world-pilot/probe_m1m2'
with (P/'stage_stats.csv').open(encoding='utf-8') as f:old={(r['trajectory_id'],r['stage_id']):r for r in csv.DictReader(f) if r['unit_type']=='tool_stage'}
markers={}
for name in ['Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a','Qwen3.5-9B']:
    t=json.loads((B/'models'/name/'tokenizer.json').read_bytes());a={r['content']:r['id'] for r in t['added_tokens']}
    markers[name]={k:a[k] for k in ['<tool_call>','</tool_call>','<tool_response>','</tool_response>']}
assert len({json.dumps(x,sort_keys=True) for x in markers.values()})==1
n=0
for tid in json.loads((P/'selection.json').read_bytes())['ids']:
    trace=json.loads((P.parent/'pilot-4b-190085/trajectories'/tid/'trajectory.json').read_bytes())
    r=stage_costs(trace,next(iter(markers.values())))
    for sid,costs in r['stages'].items():
        row=old[tid,sid]
        for name in ['generated_tokens','obs_tokens']:assert costs[name]==(int(row[name]) if row[name] else None)
        n+=1
result={'job_id':os.environ['SLURM_JOB_ID'],'compared_stages':n,'equal':True,'model_calls':0,'markers_equal_between_models':True}
(P/'round3'/('native-check-'+os.environ['SLURM_JOB_ID']+'.json')).write_text(json.dumps(result)+'\n')
print(json.dumps(result))
