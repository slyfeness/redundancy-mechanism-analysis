"""Local artifact consistency/privacy/size gate. Not a training quality test."""
import ast,collections,csv,hashlib,json,re
from pathlib import Path
O=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
required=['REPORT.md','commands.log','chat_template.txt','stage_mapping_check.csv','stage_stats.csv','visibility.jsonl']
assert all((O/p).is_file() for p in required)
for k in range(1,4):
    for kind in ['messages','tokens']:assert (O/'samples'/f'traj_{k}_{kind}.json').is_file()
checks=list(csv.DictReader((O/'stage_mapping_check.csv').open(encoding='utf-8-sig')))
stages=list(csv.DictReader((O/'stage_stats.csv').open(encoding='utf-8-sig')))
vis=[json.loads(s) for s in (O/'visibility.jsonl').read_text().splitlines()]
s=read(O/'structure_summary.json');v=read(O/'verification.json')
assert len(checks)==20 and len({r['question_id'] for r in checks})==10
assert all(n==2 for n in collections.Counter(r['question_id'] for r in checks).values())
assert len(stages)==len(vis)==s['tool_stages']+s['final_stages']==228
assert {(x['trajectory_id'],x['stage_id']) for x in stages}=={(x['trajectory_id'],x['stage_id']) for x in vis}
assert all(r['n_tool_calls']=='1' for r in stages if r['unit_type']=='tool_stage')
native=read(O/'native_training/native_training_summary.json') if (O/'native_training/native_training_summary.json').exists() else None
if native:
    assert native['mask_checks_passed']==20 and native['native_training_input_checks_passed']==20
    assert sum(row['pass']=='True' for row in checks)==native['stage_mapping_complete']==s['mapping_pass']
    assert all(row['mask_construction_verified']=='True' for row in checks)
else:
    assert s['mapping_pass']==0 and v['training_mask_verified'] is False
assert sum(int(c['native_generated_tokens']) for c in checks)==s['total_native_tokens']==89695
assert sum(int(c['diagnostic_mapped_tokens']) for c in checks)==s['mapped_native_tokens']==69074
assert all(int(c['diagnostic_partition_sum'])==int(c['native_generated_tokens']) for c in checks)
assert sum(int(c['tool_returns']) for c in checks)==217
assert v['native_id_checks']==228 and v['input_hash_checks']==20
for p in (O/'scripts').glob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'))
secret_patterns=[r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',r'\bgh[pousr]_[A-Za-z0-9]{25,}',r'\bsk-[A-Za-z0-9_-]{24,}']
files=[]
for p in O.rglob('*'):
    if not p.is_file() or '.git' in p.parts:continue
    assert p.stat().st_size<=5_000_000,f'file over 5 MB: {p}'
    assert p.suffix.lower() not in {'.safetensors','.pt','.pth','.bin','.parquet'},p
    text=p.read_text(encoding='utf-8-sig')
    for pat in secret_patterns:assert not re.search(pat,text),f'possible secret: {p}'
    if p.suffix=='.json':json.loads(text)
    if p.suffix=='.jsonl':
        for line in text.splitlines():json.loads(line)
    files.append({'path':p.relative_to(O).as_posix(),'bytes':p.stat().st_size})
result={'checks_passed':True,'files':len(files),'max_file_bytes':max(x['bytes'] for x in files),
    'three_sample_pairs':True,'stage_visibility_keys_match':True,'source_trajectory_checks':20,
    'missing_persisted_training_mask_explicit':True,'models_called':0,'training_updates':0,
    'native_cpu_mask_checks':native['mask_checks_passed'] if native else None,
    'note':'Delivery consistency; native CPU preparation verified separately. No model forward or actual training on 190085.'}
(O/'delivery_check.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
