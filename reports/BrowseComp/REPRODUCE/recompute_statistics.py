"""Portable offline recount of explicit decisions and experimental costs. No semantic labels generated."""
import csv,json,hashlib,collections,sys
from pathlib import Path
P=Path(__file__).resolve().parents[1]
def rows(n):return list(csv.DictReader((P/n).open(encoding='utf-8-sig')))
def main():
 scope=rows('STAGE_FUNCTION_MAPPING.csv');assert len(scope)==904 and len({r['case_id']for r in scope})==904
 ix={r['case_id']:r for r in scope};cost=rows('COST_AND_RESULT_3616.csv');assert len(cost)==3616 and len({(r['case_id'],r['repeat'])for r in cost})==3616
 for r in cost:
  s=ix[r['case_id']];d=json.loads((P/s['decision_path']).read_text(encoding='utf-8'));assert hashlib.sha256((P/s['decision_path']).read_bytes()).hexdigest()==s['decision_sha256']
  assert d['four'][int(r['repeat'])-1]['state']==r['state']
  assert int(r['generation_delta_low'])==int(r['new_gen'])+int(r['G'])-int(r['original_gen_high'])
  assert int(r['generation_delta_high'])==int(r['new_gen'])+int(r['G'])-int(r['original_gen_low'])
  for k in ['search','actor','prompt','open']:assert int(r[k+'_delta'])==int(r['new_'+k])-int(r['original_'+k])
 fn=rows('FUNCTION_FAMILY_MEMBERS.csv');fc=collections.defaultdict(list)
 for r in fn:fc[(r['family_id'],r['group'])].append(r)
 expected={(r['family_id'],r['cohort']):(int(r['stages']),int(r['questions']),int(r['original_runs']))for r in rows('FUNCTION_AB_DISTINCT_SQL.csv')}
 actual={k:(len({r['case_id']for r in a}),len({r['question_id']for r in a}),len({r['original_run_id']for r in a}))for k,a in fc.items()};assert actual==expected
 mc=collections.defaultdict(list)
 for r in rows('STAGE_MECHANISM_MAPPING.csv'):
  if r['canonical_status']=='OBSERVED_COMPATIBLE':assert r['status']=='OBSERVED'and r['canonical_id'];mc[(r['canonical_id'],r['group'])].append(r)
 expected={(r['canonical_id'],r['cohort']):(int(r['stages']),int(r['questions']),int(r['original_runs']),int(r['rollouts']))for r in rows('MECHANISM_AB_DISTINCT_SQL.csv')}
 actual={k:(len({r['case_id']for r in a}),len({r['question_id']for r in a}),len({r['original_run_id']for r in a}),len({(r['case_id'],r['repeat'])for r in a}))for k,a in mc.items()};assert actual==expected
 ev=[json.loads(l)for l in(P/'PRECISE_EVIDENCE_INDEX.jsonl').read_text(encoding='utf-8').splitlines()if l.strip()];assert {e['case_id']for e in ev}==set(ix)and all(e['exact_quote']and e['json_pointer'].startswith('/')for e in ev)
 assert len({e['evidence_id']for e in ev})==len(ev)
 result={'status':'OFFLINE_RECOUNT_PASS_NOT_SEMANTIC_GOLD','stages':len(scope),'rollouts':len(cost),'questions':len({r['question_id']for r in scope}),'original_runs':len({r['original_run_id']for r in scope}),'groups':dict(collections.Counter(r['group']if'group'in r else r['current_group']for r in scope)),'evidence_quotes':len(ev),'function_sql_rows_matched':len(fc),'mechanism_sql_rows_matched':len(mc),'transition_counts':dict(collections.Counter(r['original_state']+'->'+r['state']for r in cost)),'all_costs_recomputed':True,'semantic_labels_from_saved_model_decisions_only':True}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
