"""M1/M2 investigation, not a training parser. Native IDs are never re-encoded.

Missing persisted response masks remain null. Per-call all-one generation masks
are explicitly diagnostic derivatives, not claimed to be veRL training masks.
"""
import collections, csv, hashlib, importlib.metadata, json, os, re, statistics
from pathlib import Path
from transformers import AutoTokenizer

B=Path('/file_storage01/home/weiyu/lanyi')
OUT=Path(os.environ['PROBE_OUT'])
RUN=B/'projects/deepsearch-world-pilot/pilot-4b-190085'
MODEL=B/'models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a'
DATA=B/'datasets/long-horizon-benchmarks-20261111/deepsearch-world'
SAMPLES=OUT/'samples'; SAMPLES.mkdir(exist_ok=True)
def dump(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def csvout(name,rows):
    with (OUT/name).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def distribution(xs):
    return {'n':len(xs),'min':min(xs) if xs else None,'mean':statistics.mean(xs) if xs else None,
            'median':statistics.median(xs) if xs else None,'max':max(xs) if xs else None}
def locations(ids,needle):
    return [i for i in range(len(ids)-len(needle)+1) if ids[i:i+len(needle)]==needle]

tok=AutoTokenizer.from_pretrained(MODEL,local_files_only=True)
template=(MODEL/'chat_template.jinja').read_text()
(OUT/'chat_template.txt').write_text(template,encoding='utf-8')
markers=['<think>','</think>','<summary>','</summary>','<tool_call>','</tool_call>',
         '<tool_response>','</tool_response>','<answer>','</answer>','<plan>','</plan>',
         '<|im_start|>','<|im_end|>','<function=search>','<parameter=query>']
marker_info={m:{'ids':tok.encode(m,add_special_tokens=False),'special':m in tok.all_special_tokens} for m in markers}
dump(OUT/'token_protocol.json',{'model':str(MODEL),'template_sha256':sha(MODEL/'chat_template.jinja'),
    'markers':marker_info,'versions':{n:importlib.metadata.version(n) for n in ['transformers','tokenizers','torch','vllm']}})

# T2: synthetic three-round template rendering is deliberately separate from T3.
messages=[{'role':'user','content':'Synthetic question: identify a fictional archive.'}]
for i in range(1,4):
    messages += [{'role':'assistant','content':'','reasoning_content':f'THINK_SENTINEL_{i}: inspect the archive.',
                  'tool_calls':[{'id':f'c{i}','type':'function','function':{'name':'search','arguments':{'query':f'archive {i}'}}}]},
                 {'role':'tool','tool_call_id':f'c{i}','content':f'OBS_SENTINEL_{i}: fictional result.'}]
rendered=tok.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=True)
new_turn_rendered=tok.apply_chat_template(messages+[{'role':'user','content':'A new user question.'}],tokenize=False,add_generation_prompt=True,enable_thinking=True)
template_edge_tests={}
for name,ms in [('verl_8fd_system_prompt',[{}]),('verl_8fd_tool_append',[{'role':'tool','content':'Synthetic result'}])]:
    try:
        tok.apply_chat_template(ms,tokenize=True,add_generation_prompt=False)
        template_edge_tests[name]={'success':True}
    except Exception as exc:template_edge_tests[name]={'success':False,'error_type':type(exc).__name__,'error':str(exc)}
dump(SAMPLES/'template_edge_tests.json',{'synthetic':True,'new_user_turn_rendered':new_turn_rendered,
     'prior_think_after_new_user':{str(i):f'THINK_SENTINEL_{i}' in new_turn_rendered for i in range(1,4)},
     'generic_verl_8fd_template_cases':template_edge_tests})
dump(SAMPLES/'template_test.json',{'synthetic':True,'before':messages,'after':rendered,
    'reasoning_preserved':{str(i):f'THINK_SENTINEL_{i}' in rendered for i in range(1,4)},
    'observations_preserved':{str(i):f'OBS_SENTINEL_{i}' in rendered for i in range(1,4)}})

selection=json.loads((OUT/'selection.json').read_bytes())
stats=[]; checks=[]; visibility=[]; inventory=[]; tagcounts=collections.Counter(); tools=collections.Counter()
global_counts=collections.Counter(); prefix_failures=[]
for ti,tid in enumerate(selection['ids']):
    folder=RUN/'trajectories'/tid; raw=folder/'trajectory.json'; before_hash=sha(raw)
    t=json.loads(raw.read_bytes()); qid=t['metadata']['task']['query_id']
    rounds=t['rounds']; events=t['tool_events']; native_export=[]; message_export=[]; retained=[]
    fails=[]; totalgen=0; mapped=0; generated_parts=0; has_final=False; prev=None; prefixbad=0
    global_counts['trajectories']+=1
    persisted_response='response_ids' in t and 'response_mask' in t
    if not persisted_response: fails.append('persisted_response_ids_and_response_mask_absent')
    for r in rounds:
        rid=r['round_id']; sid=f'R{rid}'; a=r.get('token_accounting',{})
        ids=a.get('completion_token_ids',[]); prompt=a.get('prompt_token_ids',[])
        if not r.get('response_received'):
            fails.append(f'round_{rid}_no_response');continue
        totalgen+=len(ids)
        text=tok.decode(ids,skip_special_tokens=False)
        ptext=tok.decode(prompt,skip_special_tokens=False)
        ev=[e for e in events if e['round_id']==rid]
        calls=r.get('tool_calls') or []
        ncall=len(calls); parallel=ncall>1
        final=not ncall and r.get('finish_reason')=='stop' and bool(r.get('content'))
        has_final |= final
        for e in ev: tools[e['tool_name']]+=1
        if prev is not None:
            expected=prev['prompt']+prev['ids']; equal=prompt[:len(expected)]==expected
            global_counts['prefix_pairs']+=1;global_counts['prefix_mismatch']+=int(not equal)
            if not equal: prefixbad+=1;prefix_failures.append({'trajectory_id':tid,'round':rid})
        loc={m:locations(ids,v['ids']) for m,v in marker_info.items()}
        for m in markers: tagcounts[m]+=len(loc[m])
        # Classify generated token ownership by exact marker ID spans, no text re-tokenization.
        categories=['other']*len(ids)
        spans=[]; anomaly=[]
        def mark(start,end,kind):
            if not 0<=start<=end<=len(ids): raise ValueError('invalid token interval')
            for k in range(start,end): categories[k]=kind
            spans.append({'kind':kind,'start':start,'end':end})
        for kind,opening,closing in [('think','<think>','</think>'),('summary','<summary>','</summary>'),('call','<tool_call>','</tool_call>')]:
            starts=loc[opening]; ends=loc[closing]; implicit=False
            if kind=='think' and not starts and '<think>' in ptext[-32:]: starts=[0];implicit=True
            for start in starts:
                eligible=[j for j in ends if j>=start]
                if eligible: end=eligible[0]+len(marker_info[closing]['ids'])
                else: end=len(ids);anomaly.append(f'unclosed_{kind}')
                mark(start,end,kind)
            if implicit: global_counts['implicit_think_opening']+=1
        if len(loc['<summary>'])>1: anomaly.append('multiple_summary')
        if parallel:
            anomaly.append('parallel_shared_thought_ownership_undecided')
            fails.append(f'round_{rid}_parallel_shared_thought')
        if ncall!=len(ev): anomaly.append('call_return_mismatch');fails.append(f'round_{rid}_call_return_mismatch')
        if r.get('finish_reason')=='length':anomaly.append('completion_truncated')
        if r.get('prompt_truncated') or r.get('truncation',{}).get('occurred'):anomaly.append('history_truncated')
        if not ncall and not final:anomaly.append('no_final_submission')
        if any(k.startswith('unclosed_') for k in anomaly):fails.append(f'round_{rid}_incomplete_protocol')
        for k in range(len(ids)):
            if categories[k]=='other' and final:categories[k]='final'
        counts=collections.Counter(categories)
        generated_parts+=sum(counts.values())
        stage_ids=[sid]*len(ids) if not parallel and (ncall==1 or final) else [None]*len(ids)
        mapped+=sum(x is not None for x in stage_ids)
        # Observations are located only in the actual *next* prompt, never re-tokenized.
        obs_info=[]
        for e in ev:
            result=e.get('exact_result','')
            obs_info.append({'event_id':e['event_id'],'chars':len(result),'sha256':hashlib.sha256(result.encode()).hexdigest()})
        obs_tokens=None
        if ev and rid != rounds[-1]['round_id']:
            later=next((nr for nr in rounds if nr['round_id']>rid and nr.get('response_received')),None)
            if later:
                nextids=later['token_accounting']['prompt_token_ids']
                opens=locations(nextids,marker_info['<tool_response>']['ids']);closes=locations(nextids,marker_info['</tool_response>']['ids'])
                pairs=[(s,next((e+len(marker_info['</tool_response>']['ids']) for e in closes if e>s),None)) for s in opens]
                valid=[p for p in pairs if p[1] is not None]
                # The final N response blocks correspond to this round if all are present.
                if len(valid)>=len(ev):
                    last=valid[-len(ev):]
                    if all(e.get('exact_result','').strip() in tok.decode(nextids[s:end],skip_special_tokens=False)
                           for e,(s,end) in zip(ev,last)):
                        obs_tokens=sum(end-s for s,end in last)
        status='ok'
        if not ev and ncall:status='fail'
        for e in ev:
            result=e.get('exact_result','')
            try: er=json.loads(result)
            except (ValueError,TypeError):er={}
            if not result: status='empty'
            elif isinstance(er,dict) and er.get('error'):status='timeout' if 'timeout' in str(er['error']).lower() else 'fail'
        stats.append({'question_id':qid,'trajectory_id':tid,'stage_id':sid,
            'unit_type':'tool_stage' if ncall else ('final' if final else ('summary_unit' if counts['summary'] else 'unresolved')),
            'n_tool_calls':ncall,'is_parallel':parallel,'tool_status':status,'think_tokens':counts['think'],
            'summary_tokens':counts['summary'],'call_tokens':counts['call'],'obs_tokens':obs_tokens,
            'context_tokens_at_call':len(prompt),'has_summary':bool(counts['summary']),'anomaly':';'.join(anomaly),
            'final_tokens':counts['final'],'protocol_other_tokens':counts['other'],'generated_tokens':len(ids),
            'stage_assignment_provenance':'diagnostic_native_call_not_training_mask',
            'obs_token_provenance':'next_native_prompt_tag_blocks_including_delimiters' if obs_tokens is not None else 'not_observed'})
        visible=[];absent=[]
        for prior in retained:
            found=bool(prior['text']) and prior['text'].strip() in ptext
            (visible if found else absent).append({'kind':prior['kind'],'id':prior['id']})
        visibility.append({'trajectory_id':tid,'stage_id':sid,'prompt_tokens':len(prompt),
            'comparison':'exact stripped substring in decoded native prompt; absent does not prove semantic deletion',
            'visible':visible,'not_exactly_found':absent,'truncation':r.get('truncation'),
            'prompt_native_verified':a.get('exact_prompt_token_ids_equal')})
        reasoning=r.get('reasoning_content') or ''
        if reasoning:retained.append({'kind':'think','id':f'R{rid}','text':reasoning})
        for j,s in enumerate(re.findall(r'<summary>(.*?)</summary>',text,re.S)):
            retained.append({'kind':'summary','id':f'R{rid}:{j}','text':s})
        for e in ev:retained.append({'kind':'tool','id':str(e['event_id']),'text':e.get('exact_result','')})
        native_export.append({'round_id':rid,'prompt_ids':prompt,'completion_ids':ids,
            'prompt_decoded':ptext,'completion_decoded':text,
            'derived_generation_mask':[1]*len(ids),'diagnostic_stage_ids':stage_ids,
            'token_categories':categories,'protocol_token_spans':spans,'tool_observations':obs_info,
            'source':'trajectory.rounds[].token_accounting; generation mask is derived, not persisted training mask'})
        request=json.loads((folder/f'round_{rid:03d}'/'raw_request.json').read_bytes())
        message_export.append({'round_id':rid,'request_messages':request['messages'],
            'logical_messages':r.get('full_history'),'actor_visible_messages':r.get('actor_visible_messages'),
            'assistant_message':r['raw_response']['choices'][0]['message'],
            'tool_events':ev})
        prev={'ids':ids,'prompt':prompt}
    if not has_final:fails.append('no_final_submission')
    if generated_parts!=totalgen:fails.append('generated_partition_mismatch')
    if mapped!=totalgen:fails.append('unassigned_generation_tokens')
    checks.append({'trajectory_id':tid,'question_id':qid,'pass':not fails,'failure_items':';'.join(sorted(set(fails))),
        'reason':'native per-call IDs exist; no persisted veRL response_ids/response_mask in this inference run',
        'native_generated_tokens':totalgen,'diagnostic_mapped_tokens':mapped,
        'diagnostic_partition_sum':generated_parts,'native_calls':len(native_export),'exact_prefix_failures':prefixbad,
        'tool_calls':sum(len(r.get('tool_calls') or []) for r in rounds),'tool_returns':len(events),
        'has_final':has_final,'terminal_status':t['metadata']['terminal_status']})
    assert sha(raw)==before_hash
    inventory.append({'trajectory_id':tid,'path':str(raw),'bytes':raw.stat().st_size,'sha256_before':before_hash,'sha256_after':sha(raw)})
    if ti<3:
        dump(SAMPLES/f'traj_{ti+1}_messages.json',{'trajectory_id':tid,'rounds':message_export})
        dump(SAMPLES/f'traj_{ti+1}_tokens.json',{'trajectory_id':tid,
            'response_ids':t.get('response_ids'),'response_mask':t.get('response_mask'),
            'missing_reason':'Inference recorder stores native IDs per call, not veRL AgentLoopOutput or a training tensor.',
            'rounds':native_export})
    print(json.dumps({'trajectory_id':tid,'rounds':len(rounds),'calls':len(events),'native_tokens':totalgen,'mapped':mapped,'prefix_bad':prefixbad}),flush=True)

csvout('stage_stats.csv',stats);csvout('stage_mapping_check.csv',checks)
with (OUT/'visibility.jsonl').open('w',encoding='utf-8') as f:
    for v in visibility:f.write(json.dumps(v,ensure_ascii=False)+'\n')
dump(OUT/'input_integrity.json',inventory)
summary={'n_trajectories':len(checks),'n_questions':len(set(c['question_id'] for c in checks)),
    'mapping_pass':sum(c['pass'] for c in checks),'native_call_generation_partition_pass':sum(c['native_generated_tokens']==c['diagnostic_partition_sum'] for c in checks),
    'round_units':len(stats),'tool_stages':sum(s['unit_type']=='tool_stage' for s in stats),
    'stage_count_per_trajectory':distribution([sum(s['trajectory_id']==c['trajectory_id'] for s in stats) for c in checks]),
    'parallel_call_rounds':sum(s['is_parallel'] for s in stats),'tool_rounds':sum(s['n_tool_calls']>0 for s in stats),
    'failed_tool_rounds':sum(s['tool_status']!='ok' for s in stats),'final_trajectories':sum(c['has_final'] for c in checks),
    'completion_truncated_trajectories':len(set(s['trajectory_id'] for s in stats if 'completion_truncated' in s['anomaly'])),
    'history_truncated_trajectories':len(set(s['trajectory_id'] for s in stats if 'history_truncated' in s['anomaly'])),
    'terminal_status':dict(collections.Counter(c['terminal_status'] for c in checks)),
    'token_distributions':{k:distribution([s[k] for s in stats if s[k] is not None]) for k in ['think_tokens','summary_tokens','call_tokens','obs_tokens','context_tokens_at_call','final_tokens','protocol_other_tokens']},
    'markers':dict(tagcounts),'tools':dict(tools),'counters':dict(global_counts),
    'visibility_not_exactly_found':dict(collections.Counter(a['kind'] for v in visibility for a in v['not_exactly_found'])),
    'zero_model_requests':True,'optimizer_steps':0,'sampling_requests':0}
dump(OUT/'structure_summary.json',summary);dump(OUT/'prefix_failures.json',prefix_failures)

# Dataset schema counts are recomputed by streaming files; examples are capped.
dataset={}; wanted=set(c['question_id'] for c in checks); selected_rows=[]
for path in sorted(DATA.glob('*.jsonl')):
    n=0;schemas=collections.Counter();examples=[];h=hashlib.sha256()
    with path.open('rb') as f:
        for line in f:
            h.update(line); row=json.loads(line);n+=1;schemas[tuple(sorted(row))]+=1
            if len(examples)<2: examples.append(row)
            prompt=row.get('prompt')
            if isinstance(prompt,str):
                key=hashlib.sha256(' '.join(__import__('unicodedata').normalize('NFKC',prompt).casefold().split()).encode()).hexdigest()
                if key in wanted and path.name=='train.jsonl':selected_rows.append(row)
    dataset[path.name]={'rows':n,'sha256':h.hexdigest(),'schemas':[{'fields':list(s),'count':c} for s,c in schemas.items()]}
    dump(SAMPLES/(path.stem+'_examples.json'),examples)
dump(OUT/'dataset_inventory.json',dataset);dump(SAMPLES/'selected_dataset_rows.json',selected_rows)
source_paths=[
    B/'projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4/src/native_spans.py',
    B/'projects/browsecomp-qwen35-9b-grpo-smoke/runs/stability-tenstep-v4/src/prepare_training.py',
    B/'projects/swap-paper-repro/third_party/verl-8fdc4d3f202f41461f4de9f42a637228e342668b/verl/experimental/agent_loop/tool_agent_loop.py',
    B/'projects/swap-paper-repro/third_party/verl-8fdc4d3f202f41461f4de9f42a637228e342668b/verl/experimental/agent_loop/agent_loop.py',
    B/'envs/successful_phase05_20261007/lib/python3.11/site-packages/qwen_agent/agents/fncall_agent.py',
    Path('/persist_data/home/weiyu/lanyi/projects/deepsearch-world-pilot/actor4b-v1/actor.py')]
source_audit=[]
for path in source_paths:
    if path.exists():
        lines=path.read_text().splitlines()
        source_audit.append({'path':str(path),'sha256':sha(path),'lines':len(lines),
            'relevant_lines':[{'line':i,'text':s} for i,s in enumerate(lines,1)
                 if re.search(r'response_mask|response_ids|AgentLoopOutput|summary|MAX_LLM_CALL|merge_exact|action_offsets|MODEL_|phase06_runtime|tool_response_ids',s)]})
    else:source_audit.append({'path':str(path),'missing':True})
dump(OUT/'source_audit.json',source_audit)
dump(OUT/'execution_receipt.json',{'job_id':os.environ.get('SLURM_JOB_ID'),'source_sha256':sha(Path(__file__)),
    'zero_model_requests':True,'zero_training':True,'input_hashes_unchanged':True})
print(json.dumps(summary,ensure_ascii=False),flush=True)
