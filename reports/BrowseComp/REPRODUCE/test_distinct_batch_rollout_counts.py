"""Check actual published counts against literal per-case memberships; no semantic inference."""
import json
from pathlib import Path
P=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def expected(batch,test):
 result={k:set()for k in ['observed','not_observed','uncertain','excluded']}
 chain_counts={k:0 for k in result}
 for link in test['links']:
  case=read(P/'CURRENT_ADJUDICATIONS'/(link['case_id']+'.json'))
  m=next(x for x in case['mechanism_links']if x['local_id']==link['local_id'])
  for status in result:
   nums=m[status+'_repeats'];result[status].update((link['case_id'],n)for n in nums);chain_counts[status]+=len(nums)
 return result,chain_counts
def main():
 checked=0
 for f in sorted((P/'BATCH_REVIEW_RECORDS').glob('ROOT_*/BATCH_COUNTS.json')):
  published=read(f);authored=read(f.parent/'BATCH_ANALYSIS.json');byid={x['id']:x for x in authored['mechanism_tests']}
  for counted in published['mechanism_tests']:
   e,c=expected(authored['batch_id'],byid[counted['id']])
   for status,values in e.items():
    key=status+'_rollouts'
    assert counted[key]==len(values),(authored['batch_id'],counted['id'],key,'published',counted[key],'actual_distinct',len(values))
    if status+'_local_chain_occurrences'in counted:assert counted[status+'_local_chain_occurrences']==c[status]
   checked+=1
 print(json.dumps({'distinct_membership_tests':checked,'status':'PASS','semantic_inference':False}))
if __name__=='__main__':main()
