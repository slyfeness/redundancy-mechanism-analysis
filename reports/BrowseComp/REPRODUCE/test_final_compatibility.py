import unittest
from final_recount import apply_compatibility, distinct_counts

class CompatibilityTest(unittest.TestCase):
 def row(self):
  return {'case_id':'x','local_id':'a','candidate_id':'P1_K3','repeat':'1','status':'OBSERVED','source_decision_sha256':'abc','question_id':'q','original_run_id':'r'}
 def test_specific_review_overrides_prior_positive_without_erasing_observation(self):
  a=apply_compatibility(self.row(),{'canonical':'N003','approved':[1],'held':[],'move':[],'sha':'abc','source':'prior'}, {'canonical':'N003','approved':[],'held':[1],'move':[],'sha':'abc','source':'special'})
  self.assertEqual(a['status'],'OBSERVED');self.assertEqual(a['canonical_status'],'UNCERTAIN_DEFINITION');self.assertEqual(a['compatibility_source'],'special')
 def test_move_open_is_not_false_behavior_absence(self):
  a=apply_compatibility(self.row(),{'canonical':'N003','approved':[],'held':[],'move':[1],'sha':'abc','source':'special'},None)
  self.assertEqual(a['status'],'OBSERVED');self.assertEqual(a['canonical_status'],'OPEN_CHAIN');self.assertEqual(a['canonical_id'],'')
 def test_modified_source_rejected(self):
  with self.assertRaises(AssertionError):apply_compatibility(self.row(),{'canonical':'P1_K3','approved':[1],'held':[],'move':[],'sha':'bad','source':'x'},None)
 def test_nonobserved_never_promoted_by_overlay(self):
  r=self.row();r['status']='NOT_OBSERVED'
  a=apply_compatibility(r,{'canonical':'P1_K3','approved':[1],'held':[],'move':[],'sha':'abc','source':'x'},None)
  self.assertEqual(a['canonical_status'],'NOT_OBSERVED_LOCAL')
 def test_distinct_stage_question_and_rollout(self):
  r=self.row();self.assertEqual(distinct_counts([r,r,r|{'local_id':'b'},r|{'repeat':'2'}]),{'stages':1,'questions':1,'original_runs':1,'rollouts':2})

if __name__=='__main__':unittest.main()
