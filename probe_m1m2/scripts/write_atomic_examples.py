"""Store three Codex exploratory decompositions; never labels or gold evidence."""
import json
from pathlib import Path
O=Path(__file__).resolve().parents[1]
rows=json.loads((O/'samples/selected_dataset_rows.json').read_text(encoding='utf-8'))
plans={
28596:{'answer_type':'decade','variables':{'R':'mountain range','I':'island','H':'hunting technique'},
'conditions':['R is on the northern coast of I.','I is described as a southern island.','R has a cool climate.','R has a humid climate.','H became popular in R.','H was efficient in the rugged terrain of R.','H uses aircraft to navigate that terrain.'],
'answer_relation':'Return the decade when H reached its peak in R.',
'ambiguities':['southern island is not automatically the proper name South Island.','Aircraft does not uniquely mean helicopter without evidence.','Peak popularity needs a time comparison; the question does not specify a numerical measure.','fuzzed_features mixes multiple geographic/weather conditions in one entry.']},
193660:{'answer_type':'memoir title and publication time','variables':{'P':'literary figure','B':'birthplace','R':'region','U':'university','C':'country','M':'memoir'},
'conditions':['P is a literary figure.','P was born in B.','B is the capital of R.','R is disputed.','R is in the Caucasus.','P was born in the mid-20th century.','P is a professor at U.','U is a major university.','U is in the largest city of C.','P belongs to a national writers organization.','P translated M.','M concerns an American-Armenian family.','M concerns that family experience during the Armenian Genocide.','M was published in the early 2000s.','M was published in the capital of C.'],
'answer_relation':'Return the title and publication time of M, preserving which edition is meant.',
'ambiguities':['The country referred to by the country must be resolved consistently.','The original memoir and its translated edition have different publication events.','The fuzzed feature asks about a novel while the question says memoir; do not treat this as adjudicated truth.','Major and mid-20th century require operational definitions before automated coverage scoring.']},
230779:{'answer_type':'foundation mission attributed to a local news source','variables':{'F':'foundation','P':'founder','D':'cultural domain','W':'online platform','C':'funding mechanism','A':'broader approach'},
'conditions':['P established F.','F advances D.','P created W.','W uses C.','C enables creators in D to bypass traditional financial hurdles.','C is part of A.','A pools resources from the public.','A serves multiple objectives.','Notable nonprofits have used A to create shared resources.','A widely recognized volunteer-built online encyclopedia is offered as an example of that use.'],
'answer_relation':'Return the primary mission of F as attributed to a prominent local news source.',
'ambiguities':['Visionary and prominent are qualitative descriptions rather than reliable binary facts.','The relation C is part of A must not be lost when splitting clauses.','The question does not identify the local news source.','The mission is the output target; do not fill it from fuzzed_features as if already observed in the rollout.']}}
out=[]
for source_id,plan in plans.items():
    row=next(r for r in rows if r['id']==source_id)
    out.append({'status':'[推断] exploratory examples, not a frozen constraint list or gold labels',
                'source':'codex_exploratory_decomposition','source_dataset':'train.jsonl','source_id':source_id,
                'original_row':row,**plan})
(O/'samples/atomic_condition_examples.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
