"""Use only recorded native token IDs, with round2's per-tool Stage rules."""
def positions(ids,token):return [i for i,x in enumerate(ids) if x==token]

def stage_costs(trace,markers):
    rounds=[r for r in trace['rounds'] if r.get('response_received')]
    output={};shared=0;shared_rounds=[];total=0
    for ri,r in enumerate(rounds):
        rid=r['round_id'];ids=r['token_accounting']['completion_token_ids'];total+=len(ids)
        calls=r.get('tool_calls') or [];events=[e for e in trace['tool_events'] if e['round_id']==rid]
        if len(calls)!=len(events):raise ValueError('Call/return count mismatch')
        if not events:continue
        starts=positions(ids,markers['<tool_call>']);ends=positions(ids,markers['</tool_call>'])
        if len(starts)!=len(ends) or len(starts)!=len(calls):raise ValueError('Native call boundary mismatch')
        if any(e<=s for s,e in zip(starts,ends)):raise ValueError('Native call span invalid')
        obs=[None]*len(events)
        if ri+1<len(rounds):
            nxt=rounds[ri+1];messages=nxt['actor_visible_messages'][-len(events):]
            if len(messages)!=len(events) or not all(m.get('role')=='tool' and m.get('tool_call_id')==e['tool_call_id']
                and m.get('content')==e['exact_result'] for m,e in zip(messages,events)):
                raise ValueError('Next-context return binding mismatch')
            np=nxt['token_accounting']['prompt_token_ids']
            opens=positions(np,markers['<tool_response>']);closes=positions(np,markers['</tool_response>'])
            if len(opens)==len(closes) and len(opens)>=len(events):
                spans=list(zip(opens[-len(events):],closes[-len(events):]))
                if all(e>s for s,e in spans):obs=[e+1-s for s,e in spans]
        parallel=len(calls)>1
        if parallel:
            count=len(ids)-sum(e+1-s for s,e in zip(starts,ends));shared+=count
            shared_rounds.append({'round':rid,'tokens':count})
        for j,_ in enumerate(events):
            sid=f'R{rid}:T{j+1}' if parallel else f'R{rid}'
            output[sid]={'generated_tokens':ends[j]+1-starts[j] if parallel else len(ids),'obs_tokens':obs[j]}
    return {'stages':output,'total_generated_tokens':total,'shared_tokens':shared,'shared_rounds':shared_rounds}
