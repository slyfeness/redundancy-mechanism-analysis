"""CPU-only preparation; no model access. All full data stays on bulk storage."""
import hashlib,json,os,time
from pathlib import Path
from plan import select_questions,build_tasks,reusable_receipt

B=Path('/file_storage01/home/weiyu/lanyi/projects/deepsearch-world-pilot')
O=B/'probe_m1m2/round3'/('selection-'+os.environ['SLURM_JOB_ID'])
O.mkdir(parents=True,exist_ok=False)
def read(p):return json.loads(p.read_bytes())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(name,value):
    (O/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

old=read(B/'pilot-4b-190085/sample_manifest.json')['selected']
old_ids=[r['query_id'] for r in old]
dedup=B/'dedup-183955/TRAIN_DEDUP.jsonl'
start=time.monotonic();before=sha(dedup)
with dedup.open(encoding='utf-8') as f:selected=select_questions((json.loads(l) for l in f),old_ids)
tasks=build_tasks(selected)
assert [r['id'] for r in selected[:10]]==list(dict.fromkeys(x.rsplit('__rep',1)[0] for x in read(B/'probe_m1m2/selection.json')['ids']))
dump('PILOT_PRIVATE.json',selected)
dump('PILOT_ACTOR.json',[{'id':q['id'],'question':q['question']} for q in selected])
dump('task_manifest.json',{'tasks':tasks})
reuse={};integrity=[]
for model,run in [('4B','pilot-4b-190085'),('9B','pilot-184534')]:
    src=B/run;old_tasks={t['run_id']:t for t in read(src/'task_manifest.json')['tasks']}
    reused=[]
    for task in tasks:
        if task['run_id'] not in old_tasks:continue
        tid=task['run_id'];folder=src/'trajectories'/tid;tp=folder/'trajectory.json';vp=src/'verdicts'/(tid+'.json')
        th=sha(tp);vh=sha(vp)
        reusable_receipt(task,read(vp),read(folder/'TERMINAL.json'),th,old_tasks[tid])
        reused.append({'run_id':tid,'trajectory_dir':str(folder),'verdict_path':str(vp),
                       'trajectory_sha256':th,'verdict_sha256':vh})
        integrity.append({'model':model,**reused[-1]})
    assert len(reused)==32
    reuse[model]=reused
dump('reuse_manifest.json',reuse)
assert sha(dedup)==before
dump('selection.json',{'questions':100,'samples_per_question':2,'models':['4B','9B'],
    'total_trajectories':400,'reused_per_model':32,'new_per_model':168,
    'method':'First 100 by SHA256(dsw-pilot-v1|query_id); first 16 identical to original manifest',
    'seed_base':20261110,'seed_stride':8,'query_ids':[r['id'] for r in selected],
    'source_ids':[r['source_id'] for r in selected],
    'dedup_sha256':before,'actor_input_sha256':sha(O/'PILOT_ACTOR.json'),
    'private_input_sha256':sha(O/'PILOT_PRIVATE.json'),'task_manifest_sha256':sha(O/'task_manifest.json'),
    'reused_source_hashes_verified':True,'model_calls':0,'elapsed_seconds':time.monotonic()-start})
print(json.dumps({'output':str(O),'questions':100,'reused_per_model':32,'new_per_model':168}),flush=True)
