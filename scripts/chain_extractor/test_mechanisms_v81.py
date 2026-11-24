import unittest

from mechanisms_v81 import classify, belief_point, probe_points, validate_reader


class V81Tests(unittest.TestCase):
    def test_one_new_required_goal_keeps_step_exploratory(self):
        first={"answered_before":None,"needed":"需要","same_as":None,"result":"没结果"}
        old={**first,"same_as":{"step":3,"subgoal":1}}
        self.assertEqual(classify({"stage":8,"new_docs":0,"repeat_of":[],"candidate_changed":False}, [first,old], None),
                         "无收获的探索")

    def test_zero_new_documents_never_count_as_progress(self):
        goal={"answered_before":None,"needed":"需要","same_as":None,"result":"找到"}
        row={"stage":11,"new_docs":0,"repeat_of":[],"candidate_changed":True}
        self.assertNotEqual(classify(row,[goal],None),"有进展")

    def test_belief_first_correct_candidate_and_keep_flag(self):
        states=[{"stage":0,"candidate":None},{"stage":4,"candidate":"Blue Bird"},
                {"stage":5,"candidate":"Blue Bird, Season 3"},{"stage":6,"candidate":"Another"}]
        result=belief_point(states,{"Blue Bird":False,"Blue Bird, Season 3":True,"Another":False})
        self.assertEqual((result["t_belief"],result["kept"]),(5,False))
        self.assertEqual(probe_points(5,6,7),{4:["信念前一步"],5:["信念点"],6:["证据点"],7:["末步"]})

    def test_reader_v81_accepts_guess_and_ignores_missing(self):
        reply={"subgoals":[{"index":1,"same_as":None,"needed":"需要","answered_before":None,
                              "result":"只是猜测","reason":"#1 的归纳尚存疑"}],
               "established":False,"answer":None,"basis_steps":[],"established_reason":"#1 缺证"}
        self.assertTrue(validate_reader(reply,1,{1:1}))
