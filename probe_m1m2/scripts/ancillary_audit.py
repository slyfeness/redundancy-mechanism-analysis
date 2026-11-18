"""Final bounded provenance/example export plus dataset metadata availability audit."""
import collections,csv,hashlib,json,os
from pathlib import Path
B=Path('/file_storage01/home/weiyu/lanyi');O=Path(os.environ['PROBE_OUT']);R=B/'projects/deepsearch-world-pilot/pilot-4b-190085'
def read(p):return json.loads(p.read_bytes())
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n')
availability={}
for path in sorted((B/'datasets/long-horizon-benchmarks-20261111/deepsearch-world').glob('*.jsonl')):
    c=collections.Counter()
    for line in path.open():
        row=json.loads(line);c['rows']+=1
        c['nonempty_question']+=isinstance(row.get('prompt'),str) and bool(row['prompt'].strip())
        ans=row.get('answers');c['nonempty_answer_list']+=isinstance(ans,list) and bool(ans)
        for name,typ in [('entity_list',list),('fuzzed_features',dict)]:
            try:v=json.loads(row[name]) if isinstance(row.get(name),str) else row.get(name)
            except (ValueError,TypeError):c[name+'_parse_error']+=1;continue
            c[name+'_nonempty_expected_type']+=isinstance(v,typ) and bool(v)
        c['explicit_constraint_field']+=any(k in row for k in ['constraints','atomic_constraints'])
        c['explicit_gold_evidence_field']+=any(k in row for k in ['evidence','evidence_doc_ids','gold_doc_ids','supporting_facts'])
    availability[path.name]=dict(c)
write(O/'dataset_field_availability.json',availability)

selection=read(O/'selection.json')['ids'];diagnostics=[];examples=[]
for tid in selection:
    folder=R/'trajectories'/tid;t=read(folder/'trajectory.json');rounds=t['rounds']
    for a,b in zip(rounds,rounds[1:]):
        aa=a.get('token_accounting',{});bb=b.get('token_accounting',{})
        expect=aa.get('prompt_token_ids',[])+aa.get('completion_token_ids',[]);actual=bb.get('prompt_token_ids',[])
        if actual[:len(expect)]==expect:continue
        common=next((i for i,(x,y) in enumerate(zip(expect,actual)) if x!=y),min(len(expect),len(actual)))
        before=(folder/f"round_{a['round_id']:03d}"/'actual_serialized_prompt.txt').read_text()+(folder/f"round_{a['round_id']:03d}"/'raw_model_completion.txt').read_text()
        after=(folder/f"round_{b['round_id']:03d}"/'actual_serialized_prompt.txt').read_text()
        cp=next((i for i,(x,y) in enumerate(zip(before,after)) if x!=y),min(len(before),len(after)))
        diagnostics.append({'trajectory_id':tid,'previous_round':a['round_id'],'round':b['round_id'],
            'equal_decoded_text_prefix':after.startswith(before),'common_native_tokens':common,'expected_prefix_tokens':len(expect),
            'common_chars':cp,'previous_chars':len(before),'before_difference':before[max(0,cp-40):cp+120],
            'after_difference':after[max(0,cp-40):cp+120]})
    for event in t['tool_events']:
        if event['tool_name'] in {'search','open'} and sum(x['tool_name']==event['tool_name'] for x in examples)<2:
            examples.append(event)
write(O/'samples'/'prefix_diagnostics.json',diagnostics);write(O/'samples'/'tool_return_examples.json',examples)
verdicts=[]
for tid in selection:
    p=R/'verdicts'/f'{tid}.json'
    if p.exists() and len(verdicts)<2:verdicts.append(read(p))
write(O/'samples'/'outcome_receipt_examples.json',verdicts)

vr=[json.loads(s) for s in (O/'visibility.jsonl').read_text().splitlines()]
(O/'round_visibility.jsonl').write_text((O/'visibility.jsonl').read_text())
by={(v['trajectory_id'],v['stage_id']):v for v in vr}
stages=list(csv.DictReader((O/'stage_stats.csv').open()))
with (O/'visibility.jsonl').open('w') as f:
    for s in stages:
        v=dict(by[(s['trajectory_id'],s['stage_id'].split(':')[0])]);v['stage_id']=s['stage_id']
        v['parallel_uses_same_pre_round_context']=s['is_parallel']=='True'
        f.write(json.dumps(v)+'\n')
write(O/'ancillary_receipt.json',{'job_id':os.environ.get('SLURM_JOB_ID'),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'dataset_field_availability':availability,'prefix_difference_cases':len(diagnostics),
    'equal_decoded_prefix_among_token_mismatches':sum(x['equal_decoded_text_prefix'] for x in diagnostics),
    'visibility_stage_rows':len(stages),'models_called':0,'training_steps':0})
print(json.dumps(read(O/'ancillary_receipt.json')),flush=True)
