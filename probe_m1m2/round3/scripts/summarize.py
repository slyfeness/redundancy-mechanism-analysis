"""Read-only paired expansion analysis. No inference, training, or re-tokenization."""
import collections,csv,hashlib,json,os,statistics,sys,time
from pathlib import Path
from native_stages import stage_costs
from rules import classify,REPEAT_FLAGS,selftest

BASE=Path('/file_storage01/home/weiyu/lanyi')
STORE=BASE/'projects/deepsearch-world-pilot'
selection,run9,run4=map(Path,sys.argv[1:])
O=STORE/'probe_m1m2/round3'/('analysis-'+os.environ['SLURM_JOB_ID'])
O.mkdir(parents=True,exist_ok=False);(O/'private').mkdir()
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(name,obj):(O/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def table(name,rows):
    with (O/name).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def distribution(xs):
    xs=[x for x in xs if x is not None]
    return dict(n=len(xs),min=min(xs) if xs else None,median=statistics.median(xs) if xs else None,
                mean=statistics.mean(xs) if xs else None,max=max(xs) if xs else None)

tasks=read(selection/'task_manifest.json')['tasks'];plan=read(selection/'selection.json')
reused_expected={(model,r['run_id']):r for model,rows in read(selection/'reuse_manifest.json').items() for r in rows}
questions={q['id']:q for q in read(selection/'PILOT_PRIVATE.json')}
old16=set(plan['query_ids'][:16]);old10=set(plan['query_ids'][:10])
original20={r['trajectory_id']:r for r in read(STORE/'probe_m1m2/round2/run-190949/redundancy_summary.json')['per_trajectory']}
original_stages={}
with (STORE/'probe_m1m2/round2/run-190949/redundancy_stage_flags.csv').open(encoding='utf-8') as f:
    original_stages={(r['trajectory_id'],r['stage_id']):r for r in csv.DictReader(f)}
outcomes=[];stages=[];integrity=[];failures=[];comparison=[];examples=[];quote_redactions=[];start=time.monotonic()
def strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for v in value.values():yield from strings(v)
    elif isinstance(value,list):
        for v in value:yield from strings(v)
def long_verbatim_overlap(answer,events):
    # Publication guard only: never changes original answers or score receipts.
    words=answer.split()
    if len(words)<=40:return False
    windows={tuple(words[i:i+41]) for i in range(len(words)-40)}
    for event in events:
        raw=event.get('exact_result','')
        try:value=json.loads(raw)
        except (ValueError,TypeError):value=raw
        for text in strings(value):
            tokens=text.split()
            if any(tuple(tokens[i:i+41]) in windows for i in range(len(tokens)-40)):return True
    return False
FLAGS=['S_exact','S_near','S_allseen','S_empty','O_exact','O_samecontent','O_unseen']
for size,root,modeldir in [('4B',run4,'Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a'),('9B',run9,'Qwen3.5-9B')]:
    if (root/'task_manifest.json').exists():assert read(root/'task_manifest.json')['tasks']==tasks
    tokenizer=read(BASE/'models'/modeldir/'tokenizer.json')
    added={t['content']:t['id'] for t in tokenizer['added_tokens']}
    mk={k:added[k] for k in ['<tool_call>','</tool_call>','<tool_response>','</tool_response>']}
    for task in tasks:
        tid=task['run_id'];qid=task['query_id'];folder=root/'trajectories'/tid
        p=folder/'trajectory.json';vp=root/'verdicts'/(tid+'.json');tp=folder/'TERMINAL.json'
        q=questions[qid];cohort='original16' if qid in old16 else 'new84'
        r={'model':size,'trajectory_id':tid,'question_id':qid,'source_question_id':q['source_id'],
           'cohort':cohort,'reused':qid in old16,'seed':task['seed'],'submitted':None,'correct':None,
           'judge_source':None,'terminal_status':None,'n_tool_calls':None,'total_generated_tokens':None,
           'known_obs_tokens':None,'obs_missing_stages':None,'exact_total_cost':None,
           'repeat_calls':None,'shared_generated_tokens':None,'final_answer':'','gold_answers':json.dumps(q['answers'],ensure_ascii=False)}
        if not p.exists() or not tp.exists():
            failures.append({'model':size,'trajectory_id':tid,'reason':'missing_sealed_trajectory'})
            outcomes.append(r);continue
        before=sha(p);trace=read(p);terminal=read(tp)
        assert before==terminal['trajectory']['sha256']
        if (size,tid) in reused_expected:assert before==reused_expected[size,tid]['trajectory_sha256']
        assert trace['metadata']['task']==task
        assert size in trace['metadata']['model']
        costs=stage_costs(trace,mk)
        rs={r['round_id']:r for r in trace['rounds'] if r.get('response_received')}
        prior=[];events=sorted(trace['tool_events'],key=lambda e:(e['dispatch_utc'],e['dispatch_order']))
        for i,e in enumerate(events):
            rid=e['round_id'];rr=rs[rid];parallel=len(rr.get('tool_calls') or [])>1
            sid=f'R{rid}:T{e["tool_ordinal"]}' if parallel else f'R{rid}'
            args=json.loads(e['exact_arguments']);raw=e['exact_result']
            try:parsed=json.loads(raw)
            except (ValueError,TypeError):parsed=None
            item={'model':size,'trajectory_id':tid,'question_id':qid,'stage_id':sid,'round':rid,'stage_index':i,
                  'tool':e['tool_name'],'query':'','docid':None,'start':None,'docids':[],
                  'body_sha256':'unavailable:'+str(e['event_id']),
                  'round_shared_tokens':next((x['tokens'] for x in costs['shared_rounds'] if x['round']==rid),0),**costs['stages'][sid]}
            valid=True
            if item['tool']=='search':
                item['query']=args.get('query','');parameter=item['query']
                hits=parsed.get('results') if isinstance(parsed,dict) else parsed
                valid=isinstance(hits,list) and all(isinstance(h,dict) and 'docid' in h for h in hits)
                if valid:item['docids']=[str(h['docid']) for h in hits]
            elif item['tool']=='open':
                item.update(docid=str(args.get('docid','')),start=args.get('start',0))
                item['docids']=[item['docid']];parameter=json.dumps({'docid':item['docid'],'start':item['start']},ensure_ascii=False)
                valid=isinstance(parsed,dict) and isinstance(parsed.get('text'),str)
                if valid:item['body_sha256']=hashlib.sha256(parsed['text'].encode()).hexdigest()
            else:parameter=json.dumps(args,ensure_ascii=False);valid=False
            flags,matches=classify(item,prior)
            if item['tool']=='search' and not valid:
                flags=[f for f in flags if f not in {'S_empty','S_allseen'}]
                matches={k:v for k,v in matches.items() if k in flags}
            same_round=any(p['round']==rid and p['stage_id'] in sum(matches.values(),[]) for p in prior)
            item.update(flags=flags,earlier_match_stage_ids=matches,query_or_docid_start=parameter,
                        return_parsed=valid,is_any_repeat=bool(set(flags)&REPEAT_FLAGS),same_round_match=same_round)
            if size=='4B' and (tid,sid) in original_stages:
                old=original_stages[tid,sid]
                assert flags==json.loads(old['flags'])
                for name in ['generated_tokens','obs_tokens']:
                    assert item[name]==(int(old[name]) if old[name] else None)
                comparison.append({'trajectory_id':tid,'stage_id':sid,'flags_equal':True,'token_counts_equal':True})
            prior.append(item);stages.append(item)
            if item['is_any_repeat'] or 'S_near' in flags:
                rank=hashlib.sha256(('round3|'+size+'|'+tid+'|'+sid).encode()).hexdigest()
                examples.append({'model':size,'trajectory_id':tid,'stage_id':sid,'flags':flags,'query':parameter,'rank':rank})
        missing=sum(e['obs_tokens'] is None for e in prior);obs=sum(e['obs_tokens'] or 0 for e in prior)
        submitted=terminal['status']=='MODEL_FINAL_STOP'
        r.update(submitted=submitted,terminal_status=terminal['status'],n_tool_calls=len(events),
                 total_generated_tokens=costs['total_generated_tokens'],known_obs_tokens=obs,obs_missing_stages=missing,
                 exact_total_cost=costs['total_generated_tokens']+obs if missing==0 else None,
                 repeat_calls=sum(e['is_any_repeat'] for e in prior),shared_generated_tokens=costs['shared_tokens'],
                 final_answer=trace['rounds'][-1].get('content','') if submitted else '')
        vh=None
        if vp.exists():
            vh=sha(vp);v=read(vp)
            if (size,tid) in reused_expected:assert vh==reused_expected[size,tid]['verdict_sha256']
            assert v['run_id']==tid and v['seed']==task['seed'] and v['status']==terminal['status']
            assert v['tool_calls']==len(events) and v['generated_tokens']==costs['total_generated_tokens']
            assert type(v['correct']) is bool
            r.update(correct=v['correct'],judge_source=('reused_' if qid in old16 else 'new_')+
                     ('local_gpt_oss_120b' if v.get('judge') else 'terminal_rule_no_model'))
        else:failures.append({'model':size,'trajectory_id':tid,'reason':'outcome_missing'})
        assert sha(p)==before and (vh is None or sha(vp)==vh)
        integrity.append({'model':size,'trajectory_id':tid,'sha256':before,'verdict_sha256':vh,'unchanged':True})
        if long_verbatim_overlap(r['final_answer'],events):
            quote_redactions.append({'model':size,'trajectory_id':tid,'reason':'more_than_40_contiguous_source_words'})
            r['final_answer']='[Withheld in public CSV: long verbatim tool-return excerpt; original unchanged in private storage.]'
        outcomes.append(r)
        print(size,len([o for o in outcomes if o['model']==size]),tid,r['correct'],flush=True)

def aggregate(rows):
    keys={(r['model'],r['trajectory_id']) for r in rows};es=[e for e in stages if (e['model'],e['trajectory_id']) in keys]
    known=[r for r in rows if r['correct'] is not None];complete=[r for r in rows if r['n_tool_calls'] is not None]
    gen=sum(r['total_generated_tokens'] or 0 for r in complete);obs=sum(r['known_obs_tokens'] or 0 for r in complete)
    def metrics(flags):
        tagged=[e for e in es if set(e['flags'])&flags];g=sum(e['generated_tokens'] for e in tagged);o=sum(e['obs_tokens'] or 0 for e in tagged)
        shared=sum({(e['model'],e['trajectory_id'],e['round']):e['round_shared_tokens'] for e in tagged}.values())
        return {'calls':len(tagged),'fraction_of_calls':len(tagged)/len(es) if es else None,
          'trajectories':len({(e['model'],e['trajectory_id']) for e in tagged}),
          'generated_tokens_attributable':g,'generated_fraction_lower_bound':g/gen if gen else None,
          'shared_generated_tokens_possible':shared,'generated_fraction_upper_bound':(g+shared)/gen if gen else None,
          'known_obs_tokens':o,'known_obs_fraction':o/obs if obs else None,'missing_obs':sum(e['obs_tokens'] is None for e in tagged)}
    return {'requested_trajectories':len(rows),'sealed_trajectories':len(complete),'scored_trajectories':len(known),
      'correct':sum(r['correct'] is True for r in known),'accuracy':sum(r['correct'] is True for r in known)/len(known) if known else None,
      'accuracy_denominator':'available outcomes; also see missing count','missing_outcomes':len(rows)-len(known),
      'submitted':sum(r['submitted'] is True for r in rows),'total_tool_calls':len(es),'total_generated_tokens':gen,
      'known_obs_tokens':obs,'missing_obs':sum(e['obs_tokens'] is None for e in es),
      'shared_generated_tokens':sum(r['shared_generated_tokens'] or 0 for r in complete),
      'termination':dict(collections.Counter(r['terminal_status'] for r in complete)),
      'rules':{f:metrics({f}) for f in FLAGS},'any_repeat':metrics(REPEAT_FLAGS),
      'tools_per_trajectory':distribution([r['n_tool_calls'] for r in complete]),
      'gen_tokens_per_trajectory':distribution([r['total_generated_tokens'] for r in complete]),
      'repeat_calls_per_trajectory':distribution([r['repeat_calls'] for r in complete])}

per_question=[]
for qid in plan['query_ids']:
    entry={'question_id':qid,'source_question_id':questions[qid]['source_id'],'cohort':'original16' if qid in old16 else 'new84'}
    for size in ['4B','9B']:
        rows=[r for r in outcomes if r['question_id']==qid and r['model']==size];wins=[r for r in rows if r['correct'] is True]
        costs=[r for r in wins if r['exact_total_cost'] is not None];best=min(costs,key=lambda r:r['exact_total_cost']) if costs else None
        known=sum(r['correct'] is not None for r in rows)
        entry[size]={'correct':len(wins),'known':known,'rho_x':len(wins)/2 if known==2 else None,
                     'any_success':bool(wins) if known==2 else None,
                     'minimum_successful_cost':best['exact_total_cost'] if best else None,
                     'calls_at_minimum_cost':best['n_tool_calls'] if best else None,
                     'minimum_successful_calls':min((r['n_tool_calls'] for r in wins),default=None)}
    per_question.append(entry)

models={size:{'overall':aggregate([r for r in outcomes if r['model']==size]),
              'cohorts':{c:aggregate([r for r in outcomes if r['model']==size and r['cohort']==c]) for c in ['original16','new84']},
              'outcome_groups':{label:aggregate([r for r in outcomes if r['model']==size and r['correct']==v]) for label,v in [('correct',True),('incorrect',False)]}}
        for size in ['4B','9B']}
joint=collections.Counter()
for task in tasks:
    pair={r['model']:r for r in outcomes if r['trajectory_id']==task['run_id']}
    joint[f"4B={pair['4B']['correct']},9B={pair['9B']['correct']}"]+=1
summary={'question_count':100,'repetitions':2,'models':models,'per_question':per_question,'paired_outcomes':dict(joint),
         'round2_regression':{'stages_compared':len(comparison),'all_equal':True},'failures':failures,
         'same_round_rule_matches':sum(e['same_round_match'] for e in stages),
         'cost_note':'Same native ID Stage accounting as round2; shared parallel generation not duplicated; missing terminal obs is not zero.',
         'semantic_note':'Rule flags measure repetition, not removable semantic redundancy. S_near and O_unseen excluded from union.',
         'judge':'local gpt-oss-120b; frozen score.py prompt and parameters',
         'new_judge_requests_expected':sum(r['submitted'] is True and not r['reused'] for r in outcomes),
         'old_judge_outcomes_reused':sum(r['reused'] and r['correct'] is not None for r in outcomes),
         'external_model_requests':0,'optimizer_steps':0,'analysis_model_calls':0,
         'synthetic_rule_tests':selftest(),'analysis_elapsed_seconds':time.monotonic()-start}
dump('comparison.json',summary);dump('input_integrity.json',integrity);dump('per_question.json',per_question)
dump('publication_check.json',{'checked_trajectories':len(integrity),'verbatim_excerpt_limit_words':40,'redactions':quote_redactions,
    'reused_source_hashes_match_preparation':len([x for x in integrity if (x['model'],x['trajectory_id']) in reused_expected])})
dump('regression_vs_round2.json',comparison)
table('trajectory_outcomes.csv',outcomes)
table('redundancy_stage_flags.csv',[{k:json.dumps(e[k],ensure_ascii=False) if isinstance(e[k],(dict,list)) else e[k] for k in
    ['model','trajectory_id','question_id','stage_id','tool','query_or_docid_start','flags','earlier_match_stage_ids','generated_tokens','obs_tokens','return_parsed','same_round_match']} for e in stages])
dump('example_candidates.json',sorted(examples,key=lambda x:x['rank'])[:32])
print(json.dumps({'output':str(O),'complete':not failures,'4B_correct':models['4B']['overall']['correct'],
                  '9B_correct':models['9B']['overall']['correct'],'failures':len(failures)}),flush=True)
