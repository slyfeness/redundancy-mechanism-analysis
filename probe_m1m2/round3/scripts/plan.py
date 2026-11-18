"""Pairing rules for a 100-question, two-repetition, two-model expansion."""
import hashlib
import heapq

def select_questions(rows, old_ids, count=100):
    selected=heapq.nsmallest(count,rows,key=lambda q:hashlib.sha256(('dsw-pilot-v1|'+q['id']).encode()).hexdigest())
    ids=[q['id'] for q in selected]
    if len(selected)!=count or len(set(ids))!=count or ids[:len(old_ids)]!=old_ids:
        raise ValueError('Selection does not preserve the frozen pilot prefix or requested unique count')
    return selected

def build_tasks(selected):
    # Preserve historical stride 8; selecting two repetitions must not reseed later questions.
    return [dict(query_id=q['id'],repetition_id=r+1,seed=20261110+i*8+r,
                 run_id=f"{q['id']}__rep{r+1}",question_sha256=hashlib.sha256(q['question'].encode()).hexdigest())
            for i,q in enumerate(selected) for r in range(2)]

def reusable_receipt(task,verdict,terminal,trajectory_sha,recorded_task):
    if task!=recorded_task or verdict['run_id']!=task['run_id'] or verdict['seed']!=task['seed']:
        raise ValueError('Old result task, seed or question hash differs')
    if terminal['trajectory']['sha256']!=trajectory_sha or terminal['status']!=verdict['status']:
        raise ValueError('Old result integrity or terminal state differs')
    if type(verdict.get('correct')) is not bool:raise ValueError('Existing outcome unavailable')
    return True
