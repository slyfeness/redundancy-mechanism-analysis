"""Render frozen authored text and exact statistical tables. No semantic classification."""
import csv,json,collections,hashlib,shutil
from pathlib import Path
from final_recount import P,O,load,readcsv,save,csvsave,sha,distinct_counts

def table(headers,rows):
 def esc(x):return str(x).replace('|','\\|').replace('\n','<br>')
 return '\n'.join(['|'+'|'.join(headers)+'|','|'+'|'.join(['---']*len(headers))+'|']+['|'+'|'.join(esc(v)for v in r)+'|'for r in rows])+'\n'
def md(name,text):(O/name).write_text(text.rstrip()+'\n',encoding='utf-8')
def main():
 scope=readcsv(P/'CURRENT_SCOPE_904.csv');ix={r['case_id']:r for r in scope};summary=load(O/'COMPUTED_SUMMARY.json');defs=load(O/'FROZEN_CANDIDATE_DEFINITIONS.json');costs=readcsv(O/'COST_AND_RESULT_3616.csv')
 fdefs=load(P/'PEER_FINAL_FUNCTION_DEFINITIONS_AUTHORED.json')['functions'];fidx={f['id']:f for f in fdefs}
 files=['PEER_FINAL_FUNCTION_GROUPINGS_AUTHORED.json','ROOT_FINAL_FUNCTION_DECISIONS_AUTHORED.json'];entries=[];unclassified=[]
 for name in files:
  d=load(P/name);entries.extend(d['entries']);u=d.get('unclassified',[]);unclassified.extend(u.get('cases',[])if isinstance(u,dict)else u)
 add=load(P/'WORK_NOTES/PEER_FUNCTION_724_RELATION_CHECK_ADDENDUM_AUTHORED.json')
 # Addendum membership is explicit model text, not a phrase-based classifier.
 cid='724__rep4__S009__FIRST_SENTENCE';a=next(e for e in entries if e['case_id']==cid)
 entries.append(a|{'family_id':'PF_OPEN_RELATION_CHECK','semantic_addendum_source':'WORK_NOTES/PEER_FUNCTION_724_RELATION_CHECK_ADDENDUM_AUTHORED.json'})
 groups=collections.defaultdict(list)
 for e in entries:
  assert e['case_id']in ix and e['family_id']in fidx
  assert sha(P/'CURRENT_ADJUDICATIONS'/f"{e['case_id']}.json")==e['case_decision_sha256']
  if e.get('source_function_file')and e.get('source_function_file_sha256'):assert sha(P/e['source_function_file'])==e['source_function_file_sha256']
  groups[(e['case_id'],e['family_id'])].append(e)
 unids={e['case_id']for e in unclassified};assert {k[0]for k in groups}|unids==set(ix),'All 904 must be explicitly grouped or retained unclassified'
 members=[]
 for(cid,fid),es in groups.items():
  r=ix[cid];members.append({'case_id':cid,'family_id':fid,'function_name':fidx[fid]['name'],'question_id':r['question_id'],'original_run_id':r['original_run_id'],'group':r['current_group'],'condition':r['condition'],'original_state':r['original_state'],'four_outcomes':r['four_outcomes'],'source_explicit_memberships':json.dumps(es,ensure_ascii=False)})
 csvsave(O/'FUNCTION_FAMILY_MEMBERS.csv',members);save(O/'FUNCTION_FAMILY_DEFINITIONS.json',{'functions':fdefs,'note':'Model-authored neutral original-U functions; not NEW mechanism labels or proof of removability.','sources':{n:sha(P/n)for n in files},'explicit_unclassified':unclassified})
 fcount=[]
 for fid in fidx:
  for group in ['A','B','OUTSIDE_CURRENT_AB']:
   for cond in ['FIRST_SENTENCE','TERMINAL_DROP_NO_ANCHOR','ALL_CONDITIONS']:
    a=[r for r in members if r['family_id']==fid and r['group']==group and(cond=='ALL_CONDITIONS'or r['condition']==cond)]
    if a:fcount.append({'family_id':fid,'group':group,'condition':cond,'stages':len({r['case_id']for r in a}),'questions':len({r['question_id']for r in a}),'original_runs':len({r['original_run_id']for r in a}),'associated_rollouts':4*len({r['case_id']for r in a})})
 csvsave(O/'FUNCTION_AB_COUNTS.csv',fcount)
 records=readcsv(O/'STAGE_FUNCTION_MAPPING.csv')
 for r in records:
  r['common_function_families']=' | '.join(fid for cid,fid in groups if cid==r['case_id']);r['function_grouping_status']='EXPLICIT_MEMBER'if r['common_function_families']else'EXPLICITLY_UNCLASSIFIED'
 csvsave(O/'STAGE_FUNCTION_MAPPING.csv',records)
 # Many-to-many intersections use explicit sets, not inferred assignments.
 links=readcsv(O/'STAGE_MECHANISM_MAPPING.csv');inter=[]
 for fid in fidx:
  fids={r['case_id']for r in members if r['family_id']==fid}
  for mid in defs:
   for g in ['A','B','OUTSIDE_CURRENT_AB']:
    a=[r for r in links if r['case_id']in fids and r['canonical_id']==mid and r['group']==g and r['canonical_status']=='OBSERVED_COMPATIBLE']
    if a:inter.append({'family_id':fid,'mechanism_id':mid,'group':g}|distinct_counts(a))
 csvsave(O/'FUNCTION_MECHANISM_INTERSECTIONS.csv',inter)
 counts=readcsv(O/'MECHANISM_AB_DISTINCT_SQL.csv');mc={(r['canonical_id'],r['cohort']):r for r in counts};fc={(r['family_id'],r['group']):r for r in fcount if r['condition']=='ALL_CONDITIONS'}
 def fmt(r):return '/'.join(str(r.get(k,0))for k in ['stages','questions','original_runs','rollouts'])if r else'0/0/0/0'
 def ffmt(r):return '/'.join(str(r.get(k,0))for k in ['stages','questions','original_runs','associated_rollouts'])if r else'0/0/0/0'
 ft=table(['原U共同功能','A：Stage/题/run/关联续跑','B：Stage/题/run/关联续跑'],[[f['name'],ffmt(fc.get((f['id'],'A'))),ffmt(fc.get((f['id'],'B')))]for f in fdefs])
 mt=table(['具体候选链（定义保持原文）','A：Stage/题/run/已观察续跑','B：Stage/题/run/已观察续跑'],[[v['authored_definition']['name']+' ('+k.split('_')[0]+('_'+k.split('_')[1]if k.startswith('P')else'')+')',fmt(mc.get((k,'A'))),fmt(mc.get((k,'B')))]for k,v in defs.items()])
 st=table(['项目','实数'],[['原Stage',summary['completed_stages']],['不同题目',summary['different_questions']],['原轨迹',summary['original_runs']],['续跑',summary['rollouts']],['A/B/单列',f"{summary['groups']['A']}/{summary['groups']['B']}/{summary['groups']['OUTSIDE_CURRENT_AB']}"],['FIRST_SENTENCE/TERMINAL Stage',f"{summary['conditions_stages']['FIRST_SENTENCE']}/{summary['conditions_stages']['TERMINAL_DROP_NO_ANCHOR']}"],['精确证据引用',summary['evidence_quotes']]])
 tr=[];ct=[]
 for g in ['A','B','OUTSIDE_CURRENT_AB']:
  for cond in ['FIRST_SENTENCE','TERMINAL_DROP_NO_ANCHOR']:
   a=[r for r in costs if r['current_group']==g and r['condition']==cond]
   if not a:continue
   for old,new in sorted({(r['original_state'],r['state'])for r in a}):tr.append([g,cond,old+'→'+new,sum(r['original_state']==old and r['state']==new for r in a)])
   ct.append([g,cond,len(a),sum(int(r['generation_delta_high'])<0 for r in a),sum(int(r['generation_delta_low'])>0 for r in a),sum(int(r['generation_delta_low'])<=0<=int(r['generation_delta_high'])for r in a),sum(int(r['search_delta'])<0 for r in a),sum(int(r['search_delta'])>0 for r in a),sum(int(r['actor_delta'])<0 for r in a),sum(int(r['actor_delta'])>0 for r in a),sum(int(r['prompt_delta'])<0 for r in a),sum(int(r['prompt_delta'])>0 for r in a)])
 tt=table(['组','干预','原→新','续跑数'],tr)
 ctable=table(['组','干预','续跑','生成降','生成升','生成同/区间跨0','Search降','Search升','Actor降','Actor升','Prompt降','Prompt升'],ct)
 tokens={'[[SCOPE_TABLE]]':st,'[[FUNCTION_TABLE]]':ft,'[[MECHANISM_TABLE]]':mt,'[[TRANSITION_TABLE]]':tt,'[[COST_TABLE]]':ctable}
 for name in ['FINAL_904_STAGE_SYNTHESIS.md','EVIDENCE_QUALITY_AUDIT.md']:
  text=(O/name).read_text(encoding='utf-8')
  for k,v in tokens.items():text=text.replace(k,v)
  assert '[['not in text;md(name,text)
 md('STAGE_FUNCTION_ATLAS.md','# 原Stage共性功能图谱\n\n'+ft+'\n数字为多归显式成员，不能跨行相加。关联四续跑不表示四次都恢复此功能。\n\n'+'\n\n'.join('## '+f['name']+'\n\n'+ '\n\n'.join('**'+k+'**：'+f[k]for k in ['prestate','work','product','boundary','state_variants','mechanism_not_implied'])for f in fdefs)+'\n\n## 明确保留的未归/混合\n\n```json\n'+json.dumps(unclassified,ensure_ascii=False,indent=2)+'\n```')
 md('CROSS_STAGE_MECHANISM_ATLAS.md','# 深层作用机制及证据边界\n\n'+mt+'\n各行是具体窗口中观察的候选作用链，不是该原U已证明因果必要/冗余。原文归属见locus、stage_attribution，兼容性与行为四态分列。\n\n'+'\n\n'.join('## '+k+'：'+v['authored_definition']['name']+'\n\n定义源：'+v['source']+'；SHA '+v['source_sha256']+'\n\n```json\n'+json.dumps(v['authored_definition'],ensure_ascii=False,indent=2)+'\n```'for k,v in defs.items())+'\n\n以上为本次统计的候选定义版本快照，非研究者正式冻结机制。候选ID保持独立，开放链完整保存。')
 md('A_B_FUNCTION_COMPARISON.md','# A/B原工作、前态与删后作用对照\n\n'+ft+'\nA不是冗余组、B不是必要工作组。前态与机制的具体解释见总综合及FUNCTION_FAMILY_MEMBERS原function/P/effect。\n\n'+mt+'\n原U功能与NEW过程的多对多交叉完整保存在FUNCTION_MECHANISM_INTERSECTIONS.csv；不是按表面名称合并。明确未归成员保原功能说明，未自动填标签。')
 md('CORRECTNESS_CHANGE_ANALYSIS.md','# 原新正确性完整对照\n\n'+tt+'\nC/W/N/UNCERTAIN来自既有封存语义评价，不在本轮重判或改EM。N→W不是正确改善，C主体正确不证明附证完整。机制全部匹配窗口的结果见MECHANISM_RESULT_TRANSITIONS.csv；各行先按Stage×repeat去重，跨机制可重叠，不相加。不同原Stage独立干预不合成同一轨迹。')
 md('COMPUTATION_COST_ANALYSIS.md','# 真实切点后续成本\n\n'+ctable+'\nNATIVE_TOKEN_EXACT与CHAR_EXACT_RETOKENIZED分列保存在COST_AND_RESULT_3616.csv；生成Δ=[new+G−original_high,new+G−original_low]，G只一次；Prompt已含G及实际前缀重放，不另加。仅原生精确为单点；CHAR保守范围不能报伪精确净省。生成减少可来自工作实例/篇幅重组，也可来自无Final提前终止、缺证答复或G答案补偿。每支归因见DECISIONS四条cost_location/quality，不能把全部净差算被删U本体。\n\nSearch/Open/Actor/Prompt分项；末纯认知四重建可更短也可更长。这里统计数量分布，不相加独立分支节省。按机制的费用方向见MECHANISM_COST_DIRECTIONS.csv，所有原始值可从逐支账本复算。没有用U字符或Token长度直接代替节省，也没有从不可分离原延迟报精确时延收益。')
 # Copy audit inputs and source cards, not huge original token arrays.
 sources=[]
 for r in scope:
  fp=Path(r['factual_record']);assert sha(fp)==r['factual_record_sha256'];dest=O/'FACTUAL_RECORDS'/f"{r['case_id']}.json";dest.parent.mkdir(exist_ok=True);shutil.copy2(fp,dest)
  sources.append({k:r[k]for k in ['case_id','question_id','original_run_id','stage_id','condition','source_bundle','source_bundle_sha256','factual_record','factual_record_sha256']}|{'relative_source_from_workspace':str(Path(r['source_bundle']).relative_to(P.parent)) if Path(r['source_bundle']).is_relative_to(P.parent)else'OUTSIDE_WORKSPACE_USE_ABSOLUTE_PATH','decision_in_package':'DECISIONS/'+r['case_id']+'.json'})
 csvsave(O/'SOURCE_TRAJECTORY_INDEX.csv',sources);shutil.copy2(P/'UNRESOLVED_CASES.csv',O/'UNRESOLVED_CASES.csv')
 opens=[r for r in links if not r['canonical_id']or r['canonical_status']=='UNCERTAIN_DEFINITION'];csvsave(O/'OPEN_AND_UNCERTAIN_LOCAL_CHAINS.csv',opens)
 shutil.copytree(P/'BATCH_REVIEW_RECORDS',O/'BATCH_REVIEW_RECORDS',dirs_exist_ok=True)
 for dirname in ['CURRENT_VALIDATION','MECHANICAL','REGISTRY_CURRENT']:shutil.copytree(P/dirname,O/'AUDIT_INPUTS'/dirname,dirs_exist_ok=True)
 afiles=['CURRENT_SCOPE_904.csv','CURRENT_INPUT_MANIFEST.json','CURRENT_PROGRESS.json','CURRENT_OWNER_HANDOFF_001.json','PILOT20_IMPORT_RECEIPTS.json','CURRENT_904_SCHEMA_V2.md','SHARED_REVIEW_PROTOCOL.md','PEER_FINAL_REGISTRY_COMPATIBILITY_REVIEW_v2.json','PEER_N003_DEFINITION_COMPATIBILITY_REVIEW.json','PEER_FINAL_FUNCTION_DEFINITIONS_AUTHORED.json','PEER_FINAL_FUNCTION_GROUPINGS_AUTHORED.json','PEER_FINAL_OPEN_CHAIN_REVIEW_AUTHORED.json','ROOT_FINAL_FUNCTION_DECISIONS_AUTHORED.json','ROOT_FINAL_FUNCTION_SELECTORS_AUTHORED.tsv','PEER_FINAL_FUNCTION_SELECTORS_AUTHORED.tsv']
 for n in afiles:
  dest=O/'AUDIT_INPUTS'/n;dest.parent.mkdir(exist_ok=True,parents=True);shutil.copy2(P/n,dest)
 for n in ['final_recount.py','final_render.py','test_final_compatibility.py','current_case_check.py','current_ownership.py','current_progress.py','current_batch_counts.py','test_all_registry_memberships_in_global_index.py','test_distinct_batch_rollout_counts.py']:
  dest=O/'REPRODUCE'/n;dest.parent.mkdir(exist_ok=True);shutil.copy2(P/n,dest)
 save(O/'FUNCTION_COMPLETENESS_RECEIPT.json',{'scope':904,'explicitly_grouped_stages':len({r['case_id']for r in members}),'explicitly_unclassified_stages':sorted(set(ix)-{r['case_id']for r in members}),'function_membership_rows':len(members),'families':len(fdefs),'no_keyword_inference':True,'source_sha256':{n:sha(P/n)for n in files}})
 print(json.dumps({'function_rows':len(members),'grouped_stages':len({r['case_id']for r in members}),'unclassified':sorted(set(ix)-{r['case_id']for r in members}),'files':len(list(O.rglob('*')))},ensure_ascii=False))

if __name__=='__main__':main()
