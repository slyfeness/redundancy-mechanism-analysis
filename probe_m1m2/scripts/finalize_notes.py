"""Annotate absent Final on the last existing Stage, without inventing a Stage."""
import collections,csv,json
from pathlib import Path
O=Path(__file__).resolve().parents[1]
stages=list(csv.DictReader((O/'stage_stats.csv').open(encoding='utf-8')))
checks=list(csv.DictReader((O/'stage_mapping_check.csv').open(encoding='utf-8')))
for check in checks:
    if check['has_final']=='True':continue
    match=[s for s in stages if s['trajectory_id']==check['trajectory_id']]
    if match:
        row=match[-1];parts=[a for a in row['anomaly'].split(';') if a]
        if 'trajectory_no_final' not in parts:parts.append('trajectory_no_final')
        row['anomaly']=';'.join(parts)
with (O/'stage_stats.csv').open('w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(stages[0]));w.writeheader();w.writerows(stages)
summary=json.loads((O/'structure_summary.json').read_text())
unfinished=json.loads((O/'unfinished_generations.json').read_text())
summary['anomaly_counts']=dict(collections.Counter(a for s in stages+unfinished for a in s['anomaly'].split(';') if a))
summary['measurement_conventions']={
    'context_tokens_at_call':'native prompt length before the model call, excludes this call completion',
    'is_parallel':'multiple tool calls emitted in one model round, not proof of overlapping execution',
    'obs_tokens':'actual next-prompt return block including delimiters; null without next-prompt evidence',
    'empty':'zero-length tool payload, not an independent judgment about task relevance',
    'protocol_or_unclassified_body_tokens':'residual generated text; may include unfinished non-Final prose',
    'stage_stats':'one row per tool or submitted Final; shared parallel thought is not duplicated; unfinished generation stays separate'}
(O/'structure_summary.json').write_text(json.dumps(summary,separators=(',',':'))+'\n')
print(json.dumps({'last_existing_stage_marked_no_final':sum('trajectory_no_final' in s['anomaly'] for s in stages),'unfinished_units_separate':len(unfinished)}))
