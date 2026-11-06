"""Compare published rows to every explicitly authored registry membership."""
import csv,json
from pathlib import Path
P=Path(__file__).resolve().parent
def main():
    rows=list(csv.DictReader((P/'STAGE_MECHANISM_MAPPING.csv').open(encoding='utf-8-sig')))
    published={(r['case_id'],r['local_id'],int(r['repeat']),r['status']):r for r in rows}
    completed={r['case_id'] for r in rows}
    errors=[];checked=0
    for f in sorted((P/'REGISTRY_CURRENT').glob('V*.json')):
        for c in json.loads(f.read_text(encoding='utf-8')).get('candidates',[]):
            for m in c.get('explicit_memberships',[]):
                if m['case_id'] not in completed:continue
                for field,status in [('observed','OBSERVED'),('not_observed','NOT_OBSERVED'),('uncertain','UNCERTAIN'),('excluded','EXCLUDED')]:
                    for rep in m[field]:
                        key=(m['case_id'],m['local_id'],rep,status);r=published.get(key)
                        checked+=1
                        if r is None or r['candidate_id']!=c['registry_id'] or Path(r.get('registry_source','')).name!=f.name:
                            errors.append({'key':key,'expected_candidate':c['registry_id'],'expected_registry':f.name,'actual_candidate':r['candidate_id'] if r else None,'actual_registry':r.get('registry_source') if r else None})
    print(json.dumps({'checked_explicit_rows':checked,'status':'FAIL' if errors else 'PASS','errors':errors,'semantic_inference':False},ensure_ascii=False))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
