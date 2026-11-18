"""Read-only CPU analysis; private review material is never in public allowlist."""
import collections,csv,hashlib,json,os,statistics,time,unicodedata
from pathlib import Path
from rules import classify,REPEAT_FLAGS,selftest

BEGIN=time.monotonic()
B=Path('/file_storage01/home/weiyu/lanyi')
P=B/'projects/deepsearch-world-pilot/probe_m1m2'
R=B/'projects/deepsearch-world-pilot/pilot-4b-190085'
O=P/'round2'/('run-'+os.environ['SLURM_JOB_ID']); O.mkdir(parents=True,exist_ok=False)
(O/'private').mkdir()
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,value):
    (O/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def csvwrite(name,rows):
    with (O/name).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def number(s):return int(s) if s not in ('',None) else None
ids=read(P/'selection.json')['ids']
qids=list(dict.fromkeys(t.rsplit('__rep',1)[0] for t in ids))
data=read(P/'samples/selected_dataset_rows.json')
assert len(data)==len(qids)==10 and len(ids)==20
questions={hashlib.sha256(' '.join(unicodedata.normalize('NFKC',r['prompt']).casefold().split()).encode()).hexdigest():r for r in data}
assert set(questions)==set(qids)
stats=list(csv.DictReader((P/'stage_stats.csv').open(encoding='utf-8-sig')))
by={(x['trajectory_id'],x['stage_id']):x for x in stats}
expected={x['trajectory_id']:x['sha256_before'] for x in read(P/'input_integrity.json')}
all_events=[];outcomes=[];private=[];integrity=[];shared=[]
for tid in ids:
    path=R/'trajectories'/tid/'trajectory.json';before=sha(path);assert before==expected[tid]
    raw=read(path);qid=tid.rsplit('__rep',1)[0];question=questions[qid]
    assert hashlib.sha256(question['prompt'].encode()).hexdigest()==raw['metadata']['task']['question_sha256']
    vp=R/'verdicts'/(tid+'.json');verdict=read(vp);vs=sha(vp)
    assert verdict['run_id']==tid and verdict['status']==raw['metadata']['terminal_status']
    events=sorted(raw['tool_events'],key=lambda e:(e['dispatch_utc'],e['dispatch_order']))
    round_by={r['round_id']:r for r in raw['rounds'] if r.get('response_received')}
    prior=[]
    for index,e in enumerate(events):
        rr=round_by[e['round_id']];parallel=len(rr.get('tool_calls') or [])>1
        sid=f"R{e['round_id']}"+(f":T{e['tool_ordinal']}" if parallel else '')
        st=by[(tid,sid)];assert st['unit_type']=='tool_stage'
        args=json.loads(e['exact_arguments']);parsed=json.loads(e['exact_result']) if e['tool_name'] in {'search','open'} else None
        event={'trajectory_id':tid,'question_id':qid,'stage_id':sid,'stage_index':index,'round':e['round_id'],
               'tool':e['tool_name'],'generated_tokens':number(st['generated_tokens']),
               'obs_tokens':number(st['obs_tokens']),'docids':[], 'query':'','docid':None,'start':None,'body_sha256':None}
        if e['tool_name']=='search':
            hits=parsed['results'] if isinstance(parsed,dict) else parsed
            assert isinstance(hits,list)
            event.update(query=args['query'],docids=[str(x['docid']) for x in hits])
            label=args['query']
        elif e['tool_name']=='open':
            assert isinstance(parsed,dict) and isinstance(parsed.get('text'),str)
            docid=str(args['docid']);start=args.get('start',0)
            event.update(docid=docid,start=start,docids=[docid],body_sha256=hashlib.sha256(parsed['text'].encode()).hexdigest())
            label=json.dumps({'docid':docid,'start':start},ensure_ascii=False)
        else:label=json.dumps(args,ensure_ascii=False)
        flags,matches=classify(event,prior)
        event.update(query_or_docid_start=label,flags=flags,earlier_match_stage_ids=matches,
                     is_any_repeat=bool(set(flags)&REPEAT_FLAGS),
                     same_round_match=any(p['round']==event['round'] and p['stage_id'] in sum(matches.values(),[]) for p in prior))
        prior.append(event);all_events.append(event)
        private.append(dict(event,reasoning=rr.get('reasoning_content'),raw_return=e['exact_result'],
                            tool_result=parsed,dispatch_utc=e['dispatch_utc'],return_utc=e.get('return_utc')))
    for rr in round_by.values():
        ev=[e for e in prior if e['round']==rr['round_id']]
        if len(ev)>1:
            tokens=len(rr['token_accounting']['completion_token_ids'])-sum(e['generated_tokens'] for e in ev)
            shared.append({'trajectory_id':tid,'round':rr['round_id'],'tokens':tokens,'stage_ids':[e['stage_id'] for e in ev]})
    known=sum(e['obs_tokens'] or 0 for e in prior);missing=sum(e['obs_tokens'] is None for e in prior)
    submitted=verdict['status']=='MODEL_FINAL_STOP'
    final=next((r.get('content') for r in reversed(raw['rounds']) if submitted and r.get('content')),None)
    gen=sum(len(r['token_accounting']['completion_token_ids']) for r in round_by.values())
    assert gen==verdict['generated_tokens'] and len(events)==verdict['tool_calls']
    outcomes.append({'trajectory_id':tid,'question_id':qid,'source_question_id':question['id'],
        'submitted':submitted,'final_answer':final or '', 'gold_answers':json.dumps(question['answers'],ensure_ascii=False),
        'correct':verdict['correct'],'judge_source':'已有结果','judge_model':verdict.get('judge'),
        'outcome_basis':'existing_local_judge' if submitted else 'existing_non_submission_failure',
        'terminal_status':verdict['status'],'n_tool_calls':len(events),'total_generated_tokens':gen,
        'total_obs_tokens':known if not missing else None,'known_obs_tokens':known,'obs_missing_stages':missing,
        'known_total_cost':gen+known,'exact_total_cost':gen+known if not missing else None})
    assert sha(path)==before and sha(vp)==vs
    integrity.append({'trajectory_id':tid,'trajectory_sha256':before,'verdict_sha256':vs,'unchanged':True})

FLAGS=['S_exact','S_near','S_allseen','S_empty','O_exact','O_samecontent','O_unseen']
def aggregate(selected_outcomes):
    tids={r['trajectory_id'] for r in selected_outcomes};events=[e for e in all_events if e['trajectory_id'] in tids]
    total_gen=sum(r['total_generated_tokens'] for r in selected_outcomes)
    total_obs=sum(r['known_obs_tokens'] for r in selected_outcomes)
    def metric(sub):
        gs=sum(e['generated_tokens'] or 0 for e in sub);obs=sum(e['obs_tokens'] or 0 for e in sub)
        keys={(e['trajectory_id'],e['stage_id']) for e in sub}
        shared_possible=sum(s['tokens'] for s in shared if any((s['trajectory_id'],sid) in keys for sid in s['stage_ids']))
        return {'calls':len(sub),'call_fraction':len(sub)/len(events) if events else None,
            'trajectories':len({e['trajectory_id'] for e in sub}),
            'generated_tokens_attributable':gs,'generated_share_lower_bound':gs/total_gen if total_gen else None,
            'shared_generated_tokens_possible':shared_possible,
            'generated_share_upper_bound':(gs+shared_possible)/total_gen if total_gen else None,
            'known_obs_tokens':obs,'known_obs_share':obs/total_obs if total_obs else None,
            'obs_missing_stages':sum(e['obs_tokens'] is None for e in sub)}
    return {'n_trajectories':len(tids),'total_calls':len(events),'total_generated_tokens':total_gen,
        'known_obs_tokens':total_obs,'obs_missing_stages':sum(r['obs_missing_stages'] for r in selected_outcomes),
        'classes':{flag:metric([e for e in events if flag in e['flags']]) for flag in FLAGS},
        'any_repeat':metric([e for e in events if e['is_any_repeat']])}
per=[]
for row in outcomes:
    ev=[e for e in all_events if e['trajectory_id']==row['trajectory_id']]
    per.append({'trajectory_id':row['trajectory_id'],'correct':row['correct'],'terminal_status':row['terminal_status'],
                'n_tool_calls':len(ev),'repeat_calls':sum(e['is_any_repeat'] for e in ev),
                'repeat_fraction':sum(e['is_any_repeat'] for e in ev)/len(ev) if ev else None,
                'flags':dict(collections.Counter(f for e in ev for f in e['flags']))})
pq=[]
for qid in qids:
    rows=[r for r in outcomes if r['question_id']==qid];wins=[r for r in rows if r['correct'] is True]
    assert len(rows)==2
    knownwins=[r for r in wins if r['exact_total_cost'] is not None]
    best=min(knownwins,key=lambda r:r['exact_total_cost']) if knownwins else None
    pq.append({'question_id':qid,'source_question_id':questions[qid]['id'],'successes':len(wins),'n':2,'rho_x':len(wins)/2,
        'minimum_successful_total_cost':best['exact_total_cost'] if best else None,
        'minimum_cost_trajectory_id':best['trajectory_id'] if best else None,
        'calls_at_minimum_cost':best['n_tool_calls'] if best else None,
        'minimum_successful_calls':min(r['n_tool_calls'] for r in wins) if wins else None,
        'successes_with_unknown_cost':len(wins)-len(knownwins)})
groups={'normal_submission':[r for r in outcomes if r['submitted']],
        'actor_call_budget_20':[r for r in outcomes if r['terminal_status']=='SAFETY_CEILING_STOP'],
        'unfinished_generation':[r for r in outcomes if r['terminal_status']=='GENERATION_LENGTH_STOP'],
        'correct':[r for r in outcomes if r['correct'] is True],
        'incorrect_or_no_submission':[r for r in outcomes if r['correct'] is False],
        'submitted_incorrect':[r for r in outcomes if r['submitted'] and r['correct'] is False]}
summary={'source_run':190085,'job_id':os.environ['SLURM_JOB_ID'],'overall':aggregate(outcomes),
    'groups':{k:aggregate(v) for k,v in groups.items()},'per_trajectory':per,'per_question':pq,
    'shared_parallel_generation':shared,'same_round_flagged_stages':sum(e['same_round_match'] for e in all_events),
    'normalization':'Unicode lower; delete Unicode P* punctuation (no NFKC); collapse/strip whitespace; near uses resulting word sets',
    'order':'actual dispatch timestamp then dispatch_order, including earlier-dispatched same-round calls; descriptive, not intent or causality',
    'repeat_union':['S_exact','S_allseen','O_exact','O_samecontent'],
    'cost_scope':'all generated tokens in denominator including Final/unfinished; shared parallel tokens not arbitrarily assigned; obs is prior Stage next-prompt accounting, missing remains unknown',
    'S_allseen_warning':'seen docid does not prove same passage or absence of useful new text',
    'new_judge_calls':0,'existing_judge_model':'gpt-oss-120b','existing_judge_calls_in_selected':sum(r['submitted'] for r in outcomes),
    'selftests_passed':selftest(),'model_calls':0,'optimizer_steps':0,'source_hashes_unchanged':True,'elapsed_seconds':time.monotonic()-BEGIN}
write('redundancy_summary.json',summary);write('private/review_events.json',private)
write('private/question_context.json',[{'question_id':q,**questions[q]} for q in qids])
write('input_integrity.json',integrity)
public=[]
for e in all_events:
    public.append({k:(json.dumps(e[k],ensure_ascii=False) if isinstance(e[k],(list,dict)) else e[k]) for k in
        ['trajectory_id','stage_id','tool','query_or_docid_start','flags','earlier_match_stage_ids','generated_tokens','obs_tokens','same_round_match']})
csvwrite('redundancy_stage_flags.csv',public);csvwrite('trajectory_outcomes.csv',outcomes)
write('per_question_outcomes.json',pq)
print(json.dumps({'job_id':summary['job_id'],'overall':summary['overall'],'outcomes':[{k:r[k] for k in ['trajectory_id','source_question_id','correct','terminal_status','n_tool_calls']} for r in outcomes]}),flush=True)
