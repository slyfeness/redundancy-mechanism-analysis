"""Read-only bounded inventory. Run on a Slurm CPU allocation, never on login."""
import json, hashlib, os, shutil
from pathlib import Path

B = Path('/file_storage01/home/weiyu/lanyi')
RUN = B / 'projects/deepsearch-world-pilot/pilot-4b-190085'
OUT = Path(os.environ['PROBE_OUT'])
OUT.mkdir(parents=True, exist_ok=True)
def dump(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')
def shape(x, depth=0):
    if depth > 3: return type(x).__name__
    if isinstance(x, dict): return {k:shape(v,depth+1) for k,v in x.items()}
    if isinstance(x,list): return {'length':len(x),'first':shape(x[0],depth+1) if x else None}
    if isinstance(x,str): return {'type':'str','chars':len(x)}
    return type(x).__name__
selected=json.loads((RUN/'sample_manifest.json').read_bytes())['selected'][:10]
paths=[RUN/'trajectories'/f"{q['query_id']}__rep{r}" for q in selected for r in (1,2)]
dump('selection.json',{'method':'first 10 in existing frozen manifest, reps 1 and 2','run':str(RUN),'ids':[p.name for p in paths]})
items=[]
for i,p in enumerate(paths):
    raw=p/'trajectory.json'; data=json.loads(raw.read_bytes())
    item={'id':p.name,'bytes':raw.stat().st_size,'sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'shape':shape(data)}
    if i==0:
        for f in (p/'round_001').iterdir():
            if f.suffix=='.json': item[f.name]=shape(json.loads(f.read_bytes()))
        item['tool']=shape(json.loads(next(p.glob('tool_*.json')).read_bytes()))
    items.append(item)
dump('inventory.json',items)
print(json.dumps({'n':len(items),'first':items[0]},ensure_ascii=False),flush=True)
