"""Render/copy sealed human-readable records and verify a small local ZIP.

No semantic decisions are created here. Narrative and group membership are
read from Codex-authored files; tables are deterministic projections.
"""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

R=Path(__file__).resolve().parent
B=R.parent/'scicode_ab_mechanism_20261104'
F=R/'FINAL_SYNTHESIS'
P=F/'SciCode_AB249_Stage_Function_Mechanism_Analysis'

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def csvread(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
def table(head, rows):
    def cell(v):return str(v).replace('|','\\|').replace('\n','<br>')
    return '\n'.join(['| '+' | '.join(map(cell,head))+' |','| '+' | '.join(['---']*len(head))+' |']+['| '+' | '.join(map(cell,row))+' |'for row in rows])
def verbatim(v):return v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2)
def copy(src, rel):
    dst=P/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)

subprocess.run([sys.executable,str(R/'aggregate_sealed_reviews.py')],check=True,capture_output=True,text=True,encoding='utf-8')
s=read(F/'DETERMINISTIC_SUMMARY.json')
assert s['completed_stages']==249 and s['completed_rollouts']==996 and not s['missing']
assert s['synthesis_assignments']==249, 'Wait for complete hand-authored B synthesis; never fill missing labels.'
stages=csvread(F/'STAGE_INDEX.csv');branches=csvread(F/'BRANCH_RESULTS_AND_COSTS.csv')
fc=csvread(F/'FUNCTION_COUNTS.csv');oc=csvread(F/'OBSERVATION_AXIS_COUNTS.csv')
assert len(stages)==len({x['case_id']for x in stages})==249
assert len(branches)==len({x['branch_id']for x in branches})==996
sealed={x['case_id']:x['review_sha256']for x in read(R/'A_REVIEW_PROGRESS.json')['completed_records']}
sealed.update({x['case_id']:x['sha256']for x in read(B/'B_REVIEW_PROGRESS.json')['completed_records']})
assert len(sealed)==249
assert all(x['review_sha256']==sealed[x['case_id']] for x in stages)
for group in ['A','B']:
    assert sum(int(x['stages'])for x in fc if x['category']==group)==s['groups'][group]['stages']

coverage=table(['组别','Stage组','不同主问题','原目标轨迹','已审续跑','首句Stage','末段无G Stage'],[
    [g,s['groups'][g]['stages'],s['groups'][g]['main_problems'],s['groups'][g]['source_trajectories'],s['groups'][g]['rollouts'],s['groups'][g]['intervention_stages'].get('FIRST_SENTENCE',0),s['groups'][g]['intervention_stages'].get('TERMINAL_DROP_NO_ANCHOR',0)]for g in ['A','B']])
trans=table(['组别','原状态→新状态','续跑数'],[[g,k,v]for g in ['A','B']for k,v in sorted(s['groups'][g]['transitions'].items())])
functions=table(['组别','主工作族','Stage组','不同主问题','原目标轨迹','关联续跑（不是机制发生数）'],[[x[k]for k in ['category','primary_function','stages','main_problems','source_trajectories','linked_rollouts_not_mechanism_occurrences']]for x in fc])
observations=table(['组别','观察轴','有对应观察的Stage组','不同主问题','原目标轨迹'],[[x[k]for k in ['category','observed_link','stages','main_problems','source_trajectories']]for x in oc])
costs=table(['组别','生成加G明确下降','明确增加','区间跨零/持平','Prompt下降','Actor下降','工具下降'],[
    [g]+[s['groups'][g][k]for k in ['definite_recorded_generation_reductions_including_G','definite_recorded_generation_increases_including_G','generation_change_unresolved_or_zero','prompt_reductions','actor_reductions','tool_reductions']]for g in ['A','B']])
text=(F/'MAIN_REPORT_TEMPLATE.md').read_text(encoding='utf-8')
for key,val in {'COVERAGE_TABLE':coverage,'TRANSITION_TABLE':trans,'FUNCTION_TABLE':functions,'OBSERVATION_TABLE':observations,'COST_TABLE':costs}.items():text=text.replace('{{'+key+'}}',val)
assert '{{'not in text
P.mkdir(exist_ok=True)
(P/'01_SciCode_249组_AB共性与作用机制分析.md').write_text(text,encoding='utf-8')
for src,rel in [(R/'SHARED_REVIEW_PROTOCOL.md','RULES/SHARED_REVIEW_PROTOCOL.md'),(R/'FROZEN_ANALYSIS_SCOPE.json','RULES/FROZEN_ANALYSIS_SCOPE.json'),(R/'SYNTHESIS_WORKING_NOTES.md','RULES/SYNTHESIS_WORKING_NOTES.md'),(R/'A_SYNTHESIS_HANDWRITTEN.csv','SYNTHESIS/A_SYNTHESIS_HANDWRITTEN.csv'),(B/'B_SYNTHESIS_HANDWRITTEN.csv','SYNTHESIS/B_SYNTHESIS_HANDWRITTEN.csv'),(R/'A_REVIEW_PROGRESS.json','AUDITS/A_REVIEW_PROGRESS.json'),(B/'B_REVIEW_PROGRESS.json','AUDITS/B_REVIEW_PROGRESS.json'),(R/'aggregate_sealed_reviews.py','RECOMPUTE/aggregate_sealed_reviews.py'),(R/'build_synthesis_delivery.py','RECOMPUTE/build_synthesis_delivery.py')]:copy(src,rel)
rule=R.parent/'scicode_stage_remaining95_20261103/CODE_STAGE_V1.0_CANDIDATE.md'
copy(rule,'RULES/'+rule.name)
for name in ['STAGE_INDEX.csv','BRANCH_RESULTS_AND_COSTS.csv','FUNCTION_COUNTS.csv','OBSERVATION_AXIS_COUNTS.csv','DETERMINISTIC_SUMMARY.json']:
    copy(F/name,'STATISTICS/'+name)
copy(R/'recompute_packaged_statistics.py','RECOMPUTE/recompute_packaged_statistics.py')
copy(F/'EARLY_COST_PROJECTION_RECONCILIATION.json','AUDITS/EARLY_COST_PROJECTION_RECONCILIATION.json')

manifest_sources=[]
for row in stages:
    cid=row['case_id'];group=row['category'];mp=Path(row['review_file']);m=read(mp)
    assert digest(mp)==row['review_sha256']
    rel='MODEL_REVIEWS/'+group+'/'+cid
    copy(mp,rel+'/MODEL_REVIEW.json')
    cp=Path(row['cost_file']);assert digest(cp)==row['cost_sha256'];copy(cp,rel+'/OBJECTIVE_COSTS.json')
    if group=='A':
        for name in ['RESOLVED_EVIDENCE.json','RECHECK_PROTOCOL_AND_STATE_AUDIT.json','PROTOCOL_AND_STATE_AUDIT.json','U_FROZEN_STAGE.json','READING_CHECKPOINT.md']:
            q=mp.parent/name
            if q.exists():copy(q,rel+'/'+name)
    else:
        cd=B/cid
        for name in ['U_FROZEN_STAGE.json','READING_CHECKPOINT.md']:
            q=cd/name
            if q.exists():copy(q,rel+'/'+name)
        for q in cd.glob('*PROTOCOL*CHECK*.json'):copy(q,rel+'/'+q.name)
    page=['# '+cid+'｜'+group,'',
          '原状态 '+row['original_state']+'；四次新状态 '+row['new_states']+'；条件 '+row['intervention'],
          '', '## 原Stage工作','',m['stage_function'],'','## 原P/U及后续使用','']
    for k in ['pre_state','U_goal','U_operations','U_product','judgment_before_after','original_suffix_use','evidence']:
        assert k in m['original'], (cid,k)
        page+=['### '+k,'',verbatim(m['original'][k]),'']
    page+=['## G与完整P审计','',verbatim(m['guide_audit']),'']
    for ro in m['rollouts']:
        page+=['## '+ro['branch_id'],'',verbatim(ro),'']
    page+=['## 四次对照','',verbatim(m.get('cross_rollout_comparison',m.get('cross_rollout_comparisons',{}))),'','## 候选判断—行动链','',verbatim(m['candidate_mechanism_chain']),'','## 限制','',verbatim(m.get('limits',[])),'','精确证据、SHA和原始路径见本目录JSON及关联的原始文件。原始代码未重新运行。']
    (P/rel/'逐组分析.md').write_text('\n'.join(page),encoding='utf-8')
    manifest_sources.append({'case_id':cid,'review_original_path':str(mp),'review_sha256':digest(mp),'cost_original_path':str(cp),'cost_sha256':digest(cp),'original_and_new_raw_sources':m['sources']})
(P/'SOURCE_INDEX.json').write_text(json.dumps(manifest_sources,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

readme='''# 交付阅读顺序

先读01主报告；STATISTICS为全范围确定性统计，SYNTHESIS为Codex逐行写的共性索引，MODEL_REVIEWS按A/B保留249组、每组四条续跑的具体判断和原文定位。SOURCE_INDEX保存完整原新轨迹的本机/服务器来源及SHA；大轨迹原件仍在原位置，未删除也未改写。

观察轴数量不是已证因果机制数量，关联四条不是四次机制发生。CODE_STAGE规范保持原文件名；本次未改规范或Stage。FIRST_SENTENCE是ORACLE_ANCHORED，末段无G分列。程序没有生成语义标签。

解压后运行python RECOMPUTE/recompute_packaged_statistics.py，仅依赖Python标准库，即可独立核对全部组/分支、工作族/观察轴支持ID与不同题目数、官方状态及切点成本算式，不需要连接服务器或运行模型。原工作目录另保留aggregate_sealed_reviews.py读取已封存逐组记录重新生成统计。研究者尚未作人工金标准验收。
'''
(P/'README.md').write_text(readme,encoding='utf-8')
audit={'stages':249,'rollouts':996,'missing_cases':[], 'unique_branch_ids':len({x['branch_id']for x in branches}),
       'functions_cover_each_stage_once':True,'cost_arithmetic_and_states':'PASS',
       'new_gpu_generation_or_scoring':False,'semantic_status':'Codex first-pass detailed review and cross-case self-audit; researcher review pending',
       'no_native_exact_savings_claim':True,'all_original_files_read_only':True,
       'source_scope_sha256':s['scope_sha256']}
(P/'FINAL_VALIDATION.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
subprocess.run([sys.executable,str(P/'RECOMPUTE/recompute_packaged_statistics.py')],check=True)
payload=[{'path':p.relative_to(P).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}for p in sorted(P.rglob('*'))if p.is_file()and p.name not in ['MANIFEST.json','SHA256SUMS.txt']]
(P/'MANIFEST.json').write_text(json.dumps({'files':payload,'payload_files':len(payload),'payload_bytes':sum(x['bytes']for x in payload)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
checks=[(digest(p),p.relative_to(P).as_posix())for p in sorted(P.rglob('*'))if p.is_file()and p.name!='SHA256SUMS.txt']
(P/'SHA256SUMS.txt').write_text(''.join(h+'  '+name+'\n'for h,name in checks),encoding='utf-8')
desktop=Path(os.environ['USERPROFILE'])/'OneDrive/Desktop'
assert desktop.is_dir()
zp=desktop/'SciCode_AB249_Stage共性与作用机制_完整分析.zip'
assert not zp.exists(), 'Do not overwrite an existing delivery.'
with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED,compresslevel=6)as z:
    for p in sorted(P.rglob('*')):
        if p.is_file():z.write(p,p.relative_to(P).as_posix())
verify=F/('ZIP_READBACK_'+digest(zp)[:12]);verify.mkdir(exist_ok=False)
with zipfile.ZipFile(zp)as z:
    assert z.testzip()is None
    for info in z.infolist():
        target=(verify/info.filename).resolve()
        assert target.is_relative_to(verify.resolve())
    z.extractall(verify)
for h,name in checks:
    assert digest(verify/name)==h
assert (verify/'SHA256SUMS.txt').read_bytes()==(P/'SHA256SUMS.txt').read_bytes()
receipt={'zip_path':str(zp),'sha256':digest(zp),'archive_files':len(checks)+1,'zip_bytes':zp.stat().st_size,
         'crc':'PASS','actual_extract_sha_checks':len(checks),'all_extract_SHA':'PASS',
         'stages':249,'rollouts':996,'researcher_gold_standard_claimed':False}
(F/'DELIVERY_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
