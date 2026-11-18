"""Read original text to validate absence claims independently of token patterns."""
import collections,hashlib,json,os,re
from pathlib import Path
O=Path(os.environ['PROBE_OUT']);R=Path(json.loads((O/'selection.json').read_bytes())['run'])
counts=collections.Counter();missing=[];implicit=0;n=0
for tid in json.loads((O/'selection.json').read_bytes())['ids']:
    t=json.loads((R/'trajectories'/tid/'trajectory.json').read_bytes())
    for row in t['rounds']:
        if not row.get('response_received'):continue
        n+=1;rd=R/'trajectories'/tid/f"round_{row['round_id']:03d}"
        text=(rd/'raw_model_completion.txt').read_text();prompt=(rd/'actual_serialized_prompt.txt').read_text()
        implicit+=prompt.endswith('<think>\n')
        for marker in ['<summary>','</summary>','<answer>','</answer>','<plan>','</plan>']:
            counts[marker]+=text.count(marker)
        assert len(row['token_accounting']['completion_token_ids'])==row['completion_tokens']
    assert hashlib.sha256((R/'trajectories'/tid/'trajectory.json').read_bytes()).hexdigest()==next(x['sha256_before'] for x in json.loads((O/'input_integrity.json').read_bytes()) if x['trajectory_id']==tid)
summary=json.loads((O/'structure_summary.json').read_bytes())
summary['counters']['implicit_think_opening_without_generated_opening']=summary['counters'].pop('implicit_think_opening')
summary['counters']['prompt_ends_with_think_opening']=implicit
summary['literal_text_tag_counts']=dict(counts)
summary['round_token_distributions']['protocol_or_unclassified_body_tokens']=summary['round_token_distributions'].pop('protocol_tokens')
(O/'structure_summary.json').write_text(json.dumps(summary,separators=(',',':'))+'\n')
result={'job_id':os.environ.get('SLURM_JOB_ID'),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'raw_completion_texts':n,'literal_tag_counts':dict(counts),'prompts_ending_think_opening':implicit,
        'input_trajectory_hashes_still_equal':20,'model_requests':0,'optimizer_steps':0}
(O/'final_source_check.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
