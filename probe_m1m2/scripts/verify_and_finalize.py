"""Independent stdlib audit of native artifacts; creates final diagnostic tables.
No tokenizer call, inference, response re-encoding or training is performed.
Shared parallel reasoning is left unassigned rather than arbitrarily duplicated.
"""
import collections, csv, hashlib, json, os, statistics
from pathlib import Path
B=Path('/file_storage01/home/weiyu/lanyi'); O=Path(os.environ['PROBE_OUT'])
R=B/'projects/deepsearch-world-pilot/pilot-4b-190085'
def read(p):return json.loads(p.read_bytes())
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def table(p,rows):
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def dist(xs):return {'n':len(xs),'mean':statistics.mean(xs) if xs else None,'median':statistics.median(xs) if xs else None,'min':min(xs) if xs else None,'max':max(xs) if xs else None}
def positions(xs,token):return [i for i,t in enumerate(xs) if t==token]
protocol=read(O/'token_protocol.json'); mk=protocol['markers']
for k in ['<think>','</think>','<tool_call>','</tool_call>','<tool_response>','</tool_response>']:assert len(mk[k]['ids'])==1
M={k:v['ids'][0] for k,v in mk.items() if len(v['ids'])==1}
model=Path(protocol['model']);tokenizer=read(model/'tokenizer.json')
added={t['content']:t for t in tokenizer.get('added_tokens',[])}
for k,v in mk.items():
    v['in_all_special_tokens']=v.pop('special')
    v['tokenizer_json_added_token']=added.get(k)
write(O/'token_protocol.json',protocol)
selection=read(O/'selection.json')['ids'];assert len(selection)==20
assert len({s.rsplit('__rep',1)[0] for s in selection})==10
oldstats=list(csv.DictReader((O/'stage_stats.csv').open()))
table(O/'round_stats_pre_audit.csv',oldstats)
oldby={(r['trajectory_id'],r['stage_id']):r for r in oldstats}
checks=[];stages=[];rounds_out=[];shared=[];errors=[];export_checks=[];allreturns=[]
input_manifest=read(O/'input_integrity.json')
for n,tid in enumerate(selection):
    p=R/'trajectories'/tid/'trajectory.json';t=read(p)
    assert sha(p)==next(x['sha256_before'] for x in input_manifest if x['trajectory_id']==tid)
    rounds=[r for r in t['rounds'] if r.get('response_received')];tool_events=t['tool_events'];gen=0;assigned=0;fail=[];prefixbad=0;prev=None
    texts=read(O/'samples'/f'traj_{n+1}_tokens.json') if n<3 else None
    msgs=read(O/'samples'/f'traj_{n+1}_messages.json') if n<3 else None
    has_final=False;roundsum=0
    for ri,r in enumerate(rounds):
        rid=r['round_id'];a=r['token_accounting'];ids=a['completion_token_ids'];prompt=a['prompt_token_ids'];choice=r['raw_response']['choices'][0]
        assert ids==choice['token_ids'];assert prompt==r['raw_response']['prompt_token_ids'];assert a['exact_prompt_token_ids_equal']
        assert len(ids)==r['completion_tokens']==len(choice['logprobs']['content'])
        if prev is not None and prompt[:len(prev)]!=prev:prefixbad+=1
        prev=prompt+ids;gen+=len(ids)
        ev=[e for e in tool_events if e['round_id']==rid];calls=r.get('tool_calls') or []
        assert len(calls)==len(ev)
        for c,e in zip(calls,ev):
            assert c['id']==e['tool_call_id'];assert c['function']['name']==e['tool_name']
            assert json.loads(c['function']['arguments'])==json.loads(e['exact_arguments'])
        final=not calls and r.get('finish_reason')=='stop' and bool(r.get('content'));has_final|=final
        old=oldby[(tid,f'R{rid}')];anomaly=[]
        cats=['protocol']*len(ids)
        # The last prompt block contains the opening think token. It is not a generated action.
        implicit=M['<think>'] in prompt[-4:]
        think_starts=[0] if implicit else positions(ids,M['<think>'])
        closes=positions(ids,M['</think>'])
        spans=[]
        for start in think_starts:
            stop=next((k+1 for k in closes if k>=start),len(ids))
            cats[start:stop]=['think']*(stop-start);spans.append({'kind':'think','start':start,'end':stop,'opening_in_prompt':implicit})
            if not any(k>=start for k in closes):anomaly.append('unclosed_think')
        if implicit and positions(ids,M['<think>']):anomaly.append('unexpected_additional_think_opening')
        starts=positions(ids,M['<tool_call>']);ends=positions(ids,M['</tool_call>'])
        assert len(starts)==len(ends)==len(calls)
        for start,end in zip(starts,ends):
            assert end>start
            if any(c=='think' for c in cats[start:end+1]):anomaly.append('tool_call_inside_unclosed_think')
            cats[start:end+1]=['call']*(end+1-start);spans.append({'kind':'call','start':start,'end':end+1})
        if final:cats=['final' if c=='protocol' else c for c in cats]
        if r.get('finish_reason')=='length':anomaly+=['completion_truncated','no_final_submission']
        if len(calls)>1:anomaly.append('parallel_shared_thought_ownership_undecided')
        counts=collections.Counter(cats);assert sum(counts.values())==len(ids);roundsum+=len(ids)
        sid=f'R{rid}';sids=[sid]*len(ids) if len(calls)==1 or final else [None]*len(ids)
        if len(calls)>1:
            sids=[None]*len(ids)
            for j,(s,e) in enumerate(zip(starts,ends),1):sids[s:e+1]=[f'{sid}:T{j}']*(e+1-s)
            shared.append({'trajectory_id':tid,'round':rid,'unassigned_tokens':sids.count(None),'reason':'common thinking/protocol cannot be uniquely assigned without a design decision'})
        assigned+=sum(s is not None for s in sids)
        obs=[None]*len(ev);obs_spans=[]
        if ev and ri+1<len(rounds):
            nxt=rounds[ri+1];np=nxt['token_accounting']['prompt_token_ids'];nm=nxt['actor_visible_messages']
            suffix=nm[-len(ev):]
            assert all(m.get('role')=='tool' and m.get('tool_call_id')==e['tool_call_id'] and m.get('content')==e['exact_result'] for m,e in zip(suffix,ev))
            opens=positions(np,M['<tool_response>']);cl=positions(np,M['</tool_response>'])
            if len(opens)==len(cl) and len(opens)>=len(ev):
                for j,(s,e) in enumerate(zip(opens[-len(ev):],cl[-len(ev):])):
                    assert e>s;obs[j]=e+1-s
                    obs_spans.append({'event_id':ev[j]['event_id'],'next_round':nxt['round_id'],'start':s,'end':e+1,'stage_id':-1,'mask':0,'provenance':'diagnostic_observation_span_in_next_native_prompt_not_persisted_training_mask'})
        if texts is not None:
            tr=next(x for x in texts['rounds'] if x['round_id']==rid)
            assert tr['prompt_ids']==prompt and tr['completion_ids']==ids
            tr.update(diagnostic_stage_ids=sids,token_categories=cats,protocol_token_spans=spans,diagnostic_observation_spans=obs_spans)
            mr=next(x for x in msgs['rounds'] if x['round_id']==rid)
            req=read(R/'trajectories'/tid/f'round_{rid:03d}'/'raw_request.json')
            assert mr['request_messages']==req['messages'];assert mr['assistant_message']==choice['message'];assert mr['tool_events']==ev
        rrow={'trajectory_id':tid,'round':rid,'generated_tokens':len(ids),'think_tokens':counts['think'],'call_tokens':counts['call'],'summary_tokens':0,'final_tokens':counts['final'],'protocol_tokens':counts['protocol'],'n_tool_calls':len(calls),'anomaly':';'.join(anomaly)}
        rounds_out.append(rrow)
        if len(calls)>1:fail.append(f'round_{rid}_parallel_shared_thought_unassigned')
        if not calls and not final:fail.append(f'round_{rid}_no_final_incomplete_generation')
        if 'unclosed_think' in anomaly:fail.append(f'round_{rid}_unclosed_think')
        for j,event in enumerate(ev or [None]):
            if event is None and not final:
                # A partial unfinished generation is not relabeled as a submitted Final.
                errors.append(dict(rrow,reason='unfinished generation: neither tool stage nor Final'));continue
            status='ok';err=[]
            if event:
                raw=event.get('exact_result','')
                if event['tool_name'] not in {'search','open'}:status='fail';err.append('unknown_tool')
                elif not raw:status='empty'
                else:
                    try:parsed=json.loads(raw)
                    except ValueError:parsed={}
                    if isinstance(parsed,dict) and parsed.get('error'):status='timeout' if 'timeout' in str(parsed['error']).lower() else 'fail'
                allreturns.append({'trajectory_id':tid,'event_id':event['event_id'],'tool_name':event['tool_name'],'status':status})
            parallel=len(calls)>1
            stages.append({'question_id':t['metadata']['task']['query_id'],'trajectory_id':tid,
                'stage_id':f'{sid}:T{j+1}' if parallel else sid,'unit_type':'tool_stage' if event else 'final',
                'n_tool_calls':1 if event else 0,'is_parallel':parallel,'tool_status':status,
                'think_tokens':None if parallel else counts['think'],'summary_tokens':None if parallel else 0,
                'call_tokens':ends[j]+1-starts[j] if parallel else counts['call'],
                'obs_tokens':obs[j] if event else None,'context_tokens_at_call':len(prompt),'has_summary':False,
                'anomaly':';'.join(anomaly+err),'final_tokens':counts['final'] if final else 0,
                'protocol_other_tokens':None if parallel else counts['protocol'],
                'generated_tokens':ends[j]+1-starts[j] if parallel else len(ids),
                'stage_assignment_provenance':'native_ID_diagnostic; shared_parallel_thought_unassigned' if parallel else 'native_ID_diagnostic; training_mask_unavailable',
                'obs_token_provenance':'next_native_prompt_tool_block_including_delimiters' if event and obs[j] is not None else 'not_observed'})
        if event is not None and status!='ok':fail.append(f'round_{rid}_tool_failure_recorded')
    if not has_final:fail.append('no_final_submission')
    if assigned!=gen:fail.append('unassigned_generation_tokens')
    checks.append({'trajectory_id':tid,'question_id':t['metadata']['task']['query_id'],'pass':False,
        'failure_items':';'.join(['persisted_response_ids_and_response_mask_absent']+fail),
        'reason':'inference artifacts only; no veRL training mask, no substitution by re-tokenization',
        'native_generated_tokens':gen,'diagnostic_mapped_tokens':assigned,'diagnostic_partition_sum':roundsum,
        'native_calls':len(rounds),'exact_prefix_failures':prefixbad,'tool_calls':len(tool_events),'tool_returns':len(tool_events),
        'has_final':has_final,'terminal_status':t['metadata']['terminal_status']})
    if texts is not None:
        assert texts['response_ids'] is None and texts['response_mask'] is None
        write(O/'samples'/f'traj_{n+1}_tokens.json',texts)
        export_checks.append({'trajectory_id':tid,'all_native_ids_exact':True,'messages_exact':True,'training_mask_absence_preserved':True,'rounds':len(rounds)})
    assert sha(p)==next(x['sha256_before'] for x in input_manifest if x['trajectory_id']==tid)
table(O/'stage_stats.csv',stages);table(O/'stage_mapping_check.csv',checks);table(O/'round_token_stats.csv',rounds_out)
write(O/'parallel_shared_tokens.json',shared);write(O/'unfinished_generations.json',errors)
summary=read(O/'structure_summary.json')
summary.update(tool_stages=sum(s['unit_type']=='tool_stage' for s in stages),final_stages=sum(s['unit_type']=='final' for s in stages),
    stage_count_per_trajectory=dist([sum(s['trajectory_id']==tid for s in stages) for tid in selection]),
    stage_count_excludes_unfinished_generations=True,unfinished_generation_units=len(errors),
    failed_tool_events=sum(e['status']!='ok' for e in allreturns),tool_events=len(allreturns),
    parallel_tool_events=sum(s['is_parallel'] for s in stages),shared_parallel_unassigned_tokens=sum(s['unassigned_tokens'] for s in shared),
    token_distributions={k:dist([s[k] for s in stages if s[k] is not None]) for k in ['think_tokens','summary_tokens','call_tokens','obs_tokens','context_tokens_at_call','final_tokens','protocol_other_tokens']},
    round_token_distributions={k:dist([s[k] for s in rounds_out]) for k in ['think_tokens','call_tokens','summary_tokens','final_tokens','protocol_tokens']},
    anomaly_counts=dict(collections.Counter(a for s in stages+errors for a in s['anomaly'].split(';') if a)),
    mapped_native_tokens=sum(c['diagnostic_mapped_tokens'] for c in checks),total_native_tokens=sum(c['native_generated_tokens'] for c in checks))
summary.pop('failed_tool_rounds',None)
write(O/'structure_summary.json',summary)
config=read(R/'config_manifest.json');write(O/'run_config.json',config)
freeze=read(R/'EXECUTION_FREEZE.json');write(O/'tool_schema.json',freeze['actor']['frozen_native_tool_schema'])
write(O/'verification.json',{'job_id':os.environ.get('SLURM_JOB_ID'),'script_sha256':sha(Path(__file__)),
    'native_id_checks':len(rounds_out),'tool_call_return_id_argument_checks':len(allreturns),
    'sample_export_checks':export_checks,'input_hash_checks':len(input_manifest),
    'models_called':0,'optimizer_steps':0,'new_trajectories':0,
    'training_mask_verified':False,'parallel_ownership_decided':False,
    'note':'All diagnostic checks above passed; requested actual veRL mask mapping remains unverified.'})
print(json.dumps({'verification':read(O/'verification.json'),'summary':summary}),flush=True)
