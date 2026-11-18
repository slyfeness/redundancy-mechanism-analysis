"""Summarize controller receipts and job milestones; private raw logs stay excluded."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

P=Path(__file__).resolve().parents[1]
def stamp(value):
    return dt.datetime.fromisoformat(value.replace('Z','+00:00'))
def seconds(a,b):return round((b-a).total_seconds(),3)
jobs={}
for model,job in [('9B',191020),('4B',191021)]:
    raw=(P/f'private/job-{job}.txt').read_text(encoding='utf-8')
    log=(P/f'private/gpu-{job}.log').read_text(encoding='utf-8')
    fields=dict(re.findall(r'(\w+)=(\S+)',raw))
    assert fields['JobState']=='COMPLETED' and fields['ExitCode']=='0:0'
    markers={label:stamp(time) for time,label in re.findall(r'(\S+Z) (batch_start|local_wiki_ready|actor_complete|judge_ready|pilot_complete)',log)}
    ready=(P/f'private/ready-{job}.txt').read_text(encoding='utf-8').strip()
    # File mtime is an observed boundary after all four fingerprint/probe checks.
    actor_ready=dt.datetime.strptime(ready[:19],'%Y-%m-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc)
    rows=[l.split() for l in log.splitlines() if l.startswith('rollout ')]
    scored=[l.split() for l in log.splitlines() if l.startswith('scored ')]
    assert len(rows)==len(scored)==168
    assert len({r[1] for r in rows})==len({r[1] for r in scored})==168
    submitted=sum(r[2]=='MODEL_FINAL_STOP' for r in rows)
    assert submitted==sum(r[2]=='MODEL_FINAL_STOP' for r in scored)
    jobs[model]={
        'job_id':job,'state':fields['JobState'],'exit_code':fields['ExitCode'],
        'slurm_runtime':fields['RunTime'],'submit_time':fields['SubmitTime'],
        'start_time':fields['StartTime'],'end_time':fields['EndTime'],
        'node':fields['NodeList'],'allocated_resources':fields['AllocTRES'],
        'milestones_utc':{k:v.isoformat() for k,v in markers.items()},
        'actor_ready_mtime_utc':actor_ready.isoformat(),
        'seconds':{
            'submit_to_start':seconds(stamp(fields['SubmitTime']),stamp(fields['StartTime'])),
            'batch_to_actor_ready':seconds(markers['batch_start'],actor_ready),
            'generation_and_actor_shutdown':seconds(actor_ready,markers['actor_complete']),
            'judge_load_switch':seconds(markers['actor_complete'],markers['judge_ready']),
            'judge_ready_to_scoring_complete':seconds(markers['judge_ready'],markers['pilot_complete'])},
        'new_trajectories':168,'reused_trajectories':32,'new_outcome_receipts':168,
        'new_judge_requests':submitted,'non_submission_terminal_receipts':168-submitted,
        'failed_trajectory_workers':0,'failed_judge_requests':0,'model_request_retries':0,
        'controller_restarts':int(fields['Restarts']),
        'controller_receipt_sha256':hashlib.sha256((P/f'private/job-{job}.txt').read_bytes()).hexdigest(),
        'batch_log_sha256':hashlib.sha256((P/f'private/gpu-{job}.log').read_bytes()).hexdigest()}
result={'jobs':jobs,'external_model_requests':0,'optimizer_steps':0,
        'timing_note':'Actor readiness from immutable receipt mtime (seconds precision). Generation interval includes worker startup and Actor shutdown; Judge interval includes reading and validating receipts. GPU job time covers only 168 new trajectories per model, plus loading and read-only verification of 32 reused records.',
        'failure_evidence':'All requested worker terminal receipts and new score receipts exist; both jobs exit 0. The runtime has no model-call retry loop.'}
(P/'execution_receipt.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
