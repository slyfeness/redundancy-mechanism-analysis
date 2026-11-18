"""Limit long generated answers to public excerpts; preserve private originals."""
import csv,hashlib,json,shutil
from pathlib import Path
P=Path(__file__).resolve().parents[1]
public=P/'trajectory_outcomes.csv';original=P/'private/trajectory_outcomes_full.csv'
if not original.exists():shutil.copyfile(public,original)
with original.open(encoding='utf-8',newline='') as f:
    reader=csv.DictReader(f);fields=list(reader.fieldnames);rows=list(reader)
assert 'final_answer_is_excerpt' not in fields
extra=['final_answer_is_excerpt','final_answer_original_words','final_answer_sha256']
clipped=[]
for row in rows:
    answer=row['final_answer'];words=answer.split();is_excerpt=len(words)>40
    row.update(final_answer_is_excerpt=is_excerpt,final_answer_original_words=len(words),
               final_answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
    if is_excerpt:
        row['final_answer']=' '.join(words[:40])+'…'
        clipped.append({'model':row['model'],'trajectory_id':row['trajectory_id'],'words_before':len(words)})
with public.open('w',encoding='utf-8',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields+extra);writer.writeheader();writer.writerows(rows)
check=json.loads((P/'publication_check.json').read_bytes())
check.update(generated_answer_public_excerpt_limit_words=40,
             generated_answer_excerpts=clipped,
             note='Only public CSV answer text is abbreviated; outcomes and all private original records are unchanged.')
(P/'publication_check.json').write_text(json.dumps(check,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'answer_excerpts':len(clipped),'private_original_sha256':hashlib.sha256(original.read_bytes()).hexdigest()}))
