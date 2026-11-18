import hashlib
import unittest
from plan import select_questions, build_tasks, reusable_receipt

class PlanTests(unittest.TestCase):
    def rows(self,n=110):
        return [{'id':hashlib.sha256(str(i).encode()).hexdigest(),'question':f'Fictional item {i}?','answers':['X']} for i in range(n)]
    def test_fixed_rank_preserves_original_prefix(self):
        r=self.rows();old=sorted(r,key=lambda q:hashlib.sha256(('dsw-pilot-v1|'+q['id']).encode()).hexdigest())[:16]
        chosen=select_questions(iter(r),[q['id'] for q in old],100)
        self.assertEqual(chosen[:16],old);self.assertEqual(len(chosen),100)
        self.assertEqual(select_questions(reversed(r),[q['id'] for q in old],100),chosen)
    def test_mismatched_old_selection_rejected(self):
        with self.assertRaises(ValueError):select_questions(iter(self.rows()),['not_present'],100)
    def test_200_tasks_seeds_keep_historical_stride_8(self):
        tasks=build_tasks(self.rows(100))
        self.assertEqual(len(tasks),200)
        self.assertEqual([x['seed'] for x in tasks[:4]],[20261110,20261111,20261118,20261119])
        self.assertEqual(len({x['run_id'] for x in tasks}),200)
        self.assertEqual({x['repetition_id'] for x in tasks},{1,2})
    def test_reuse_requires_matching_seed_and_hash(self):
        t=build_tasks(self.rows(1))[0]
        receipt={'run_id':t['run_id'],'seed':t['seed'],'status':'MODEL_FINAL_STOP','correct':True}
        terminal={'status':'MODEL_FINAL_STOP','trajectory':{'sha256':'abc'}}
        self.assertTrue(reusable_receipt(t,receipt,terminal,'abc',t))
        for r,term,sha,task in [(dict(receipt,seed=0),terminal,'abc',t),(receipt,terminal,'bad',t),
                                (receipt,terminal,'abc',dict(t,question_sha256='bad'))]:
            with self.assertRaises(ValueError):reusable_receipt(t,r,term,sha,task)

if __name__=='__main__':unittest.main()
