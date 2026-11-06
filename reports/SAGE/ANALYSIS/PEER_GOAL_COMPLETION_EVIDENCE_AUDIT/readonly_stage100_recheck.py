import sys
sys.path.insert(0,'C:\\Users\\24413\\Desktop\\后训练\\sage100_v132_stage_20261102')
"""Read-only source-to-mapping/report audit. Does not generate semantic decisions."""
import hashlib,json,re
from pathlib import Path
from collections import Counter
from read_original import ROOT,load

def sha(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def pointer(d,p):
 for key in p.strip('/').split('/'):
  d=d[int(key)]if isinstance(d,list)else d[key.replace('~1','/').replace('~0','~')]
 return d
def save(p,d):
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)

manifest=read(ROOT/'SAMPLE_MANIFEST.json');records=[];viscount=Counter();counts=Counter()
assert sha((ROOT/'CONTINUOUS_WORK_STAGE_V1.3.2_FROZEN.md').read_bytes())=='c912aff074a4ccaeace7a0cf0dc3ec331323d7a02c4a9349d88270942966cf72'
assert sha((ROOT/'SAMPLE_MANIFEST.json').read_bytes())=='2815d9f2a12d39fc05c3629860c4046a8254f122728dcb454a497a2cbe2aa669'
for order in range(1,101):
 lid,d=load(order);paths={k:ROOT/folder/(lid+suffix)for k,folder,suffix in [('raw','RAW','/trajectory.json'),('chain','CHAINS','.md'),('decision','DECISIONS','.json'),('mapping','MAPPINGS','.json'),('report','REPORTS','_V1.3.2_完整Stage切分.md')]}
 m=read(paths['mapping']);dec=read(paths['decision']);report=paths['report'].read_text(encoding='utf-8');row=manifest['selected_ledger_records'][order-1]
 assert sha(paths['raw'].read_bytes())==row['raw_trajectory_sha256']==m['source_sha256']
 assert sha(paths['chain'].read_bytes())==dec['chain_sha256']==m['chain_sha256']
 assert d['question']==m['question'] and d['question'] in report
 assert m['sample_order']==order and len(m['stages'])==len(dec['stages'])
 assert m['original_round_metadata']==[{k:v for k,v in r.items()if k not in ['reasoning_content','content','tool_calls']}for r in d['rounds']]
 assert m['original_nontext_field_states']==[{k:r.get(k)for k in ['reasoning_content','content']if not r.get(k)}for r in d['rounds']]
 ranges={};events=[];positions=[];toolrounds=[];allfields=[]
 for si,s in enumerate(m['stages']):
  assert s['stage_id']==f'S{si+1:03d}'
  assert s['start_resolved']==([0,0,0]if si==0 else m['stages'][si-1]['stop_resolved'])
  assert all(s.get(k)for k in ['title','work','outcome','boundary_reason','keep_review'])
  assert all(s.get(k)==v for k,v in dec['stages'][si].items())
  lo,hi=tuple(s['start_resolved']),tuple(s['stop_resolved']);assert lo<hi
  # No boundary may split a reasoning-embedded actual protocol block.
  if lo[1]==0:
   rt=d['rounds'][lo[0]].get('reasoning_content')or''
   for match in re.finditer(r'<tool_call>.*?</tool_call>',rt,re.S):assert not match.start()<lo[2]<match.end()
  stage_positions=[]
  for x in s['items']:
   pos=tuple(x['position']);assert lo<=pos<hi;positions.append(pos);stage_positions.append(pos)
   if x['type']=='original_field':
    src=pointer(d,x['pointer']);a,b=x['start'],x['end'];assert src[a:b]==x['text']
    assert sha(src.encode())==x['field_sha256']and sha(x['text'].encode())==x['sha256']
    assert x['text'] in report and f'[{a},{b})' in report
    ranges.setdefault(x['pointer'],[]).append((a,b,x['text']));allfields.append(x)
   else:
    assert x['call']==pointer(d,x['call_pointer'])and x['event']==pointer(d,x['event_pointer'])
    c,e=x['call'],x['event'];assert(c['id'],c['name'],c['arguments'])==(e['tool_call_id'],e['name'],e['arguments'])
    assert json.dumps(c,ensure_ascii=False,indent=2)in report and json.dumps(e,ensure_ascii=False,indent=2)in report
    ei=int(x['event_pointer'].split('/')[-1]);events.append(ei);toolrounds.append(x['round']);counts[c['name']]+=1
    vv=x['visibility'];viscount[vv['status']]+=1
    seen=None
    for ri in range(pos[0]+1,len(d['rounds'])):
     rp=ROOT/'NATIVE'/lid/f'R{ri+1:03d}_request.json'
     if not rp.exists():continue
     req=read(rp);msgs=[(mi,msg)for mi,msg in enumerate(req['messages'])if msg.get('role')=='tool']
     if len(msgs)<=ei:continue
     mi,msg=msgs[ei];assert msg['tool_call_id']==e['tool_call_id'];assert json.loads(msg['content'])==e['observation']
     seen=(ri,mi,msg,rp);break
    if seen:
     ri,mi,msg,rp=seen;assert vv['first_visible_round']==d['rounds'][ri]['round']
     assert vv['actor_visible_return']==msg['content']and vv['actor_visible_return']in report
     assert vv['request_pointer']==f'/messages/{mi}/content'and vv['request_sha256']==sha(rp.read_bytes())
     assert vv['actor_visible_return_sha256']==sha(msg['content'].encode())
    else:assert vv['first_visible_round']is None and vv['actor_visible_return']is None
  assert stage_positions==sorted(stage_positions)
 assert positions==sorted(positions)and events==list(range(len(d['tool_events'])))
 assert m['stages'][-1]['stop_resolved']==[len(d['rounds']),0,0]
 for ri,r in enumerate(d['rounds']):
  for field in ['reasoning_content','content']:
   src=r.get(field)
   if isinstance(src,str):
    pieces=ranges.get(f'/rounds/{ri}/{field}',[]);cursor=0
    for a,b,t in pieces:assert a==cursor;cursor=b
    assert cursor==len(src)and ''.join(t for a,b,t in pieces)==src
 # Actual source batch order and unique ownership, including recovered repeated Call IDs.
 for batch in m['original_batch_protocol']:
  es=[pointer(d,p)for p in batch['return_pointers']];cs=[pointer(d,p)for p in batch['call_pointers']]
  assert len(es)==len(cs)and [e['batch_ordinal']for e in es]==list(range(1,len(es)+1))
  assert all(e['batch_id']==batch['batch_id']for e in es)
 final={**{k:d.get(k)for k in ['final_answer','final_validity_state','stop_reason']},'submission_event_indices':[i for i,e in enumerate(d['tool_events'])if e['name']=='submit_answer']}
 assert final==m['final']and json.dumps(final,ensure_ascii=False,indent=2)in report
 records.append({'sample_order':order,'id':lid,'rounds':len(d['rounds']),'stages':len(m['stages']),'call_count':len(events),'reasoning_characters':sum(len(r.get('reasoning_content')or'')for r in d['rounds']),'report_bytes':paths['report'].stat().st_size,'status':'MECHANICAL_PASS','files':{k:{'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}for k,p in paths.items()}})

result={'scope':'ALL_FROZEN_SAGE100','records':records,'trajectory_count':len(records),'stage_count':sum(r['stages']for r in records),'call_counts':dict(counts),'visibility':dict(viscount),'checks':'FROZEN_RAW_TO_MAPPING_TO_REPORT: Unicode fields, hashes, unique events, batch, order, actual first Actor visibility, Final, no embedded protocol cut','mechanical_status':'PASS','semantic_status':'CODEX_SELF_REVIEW_NOT_INDEPENDENT_HUMAN_GOLD','source_physical_dispatch_times':'NOT_RECORDED','gpu_started':False}
save(ROOT/'ANALYSIS'/'PEER_GOAL_COMPLETION_EVIDENCE_AUDIT'/'ALL100_SOURCE_MAPPING_REPORT_RECHECK.json',result)
print(json.dumps({k:v for k,v in result.items()if k!='records'},ensure_ascii=False,indent=2))
