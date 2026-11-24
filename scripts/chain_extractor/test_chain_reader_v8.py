import unittest

from chain_reader_v8 import validate_subgoals, validate_reader, useful_labels
from mechanisms_v7 import derive
from test_mechanisms_v7 import state


class ReaderTests(unittest.TestCase):
    def test_frozen_string_steps_are_recognized_and_empty_steps_are_not(self):
        fix={"12":["e12"],"14":["e14"],"15":["e15"],"16":["e16"],"17":["e17"],"18":[]}
        original=[state(0),*(state(i) for i in range(1,19)),state(19,kind="final")]
        result=derive(original,["c1"],dict.fromkeys(range(1,19),0),fix,{}, {}, {},[],"length")
        self.assertEqual([x["stage"] for x in result["steps"] if x.get("strict_repeat")],[12,14,15,16,17])

    def test_subgoal_per_parallel_query_and_citations(self):
        row={"subgoals":[{"query_index":1,"object":"X","attribute":"birthdate","ids":["P1"]}],
             "plan_match":"一致","plan_ids":["P1"],"plan_note":""}
        self.assertTrue(validate_subgoals(row,1,{"P1"}))
        self.assertFalse(validate_subgoals(row,2,{"P1"}))
        self.assertFalse(validate_subgoals(row,1,{"P2"}))

    def test_reader_only_allows_real_prefix_coordinates(self):
        row={"subgoals":[{"index":1,"same_as":{"step":1,"subgoal":2},"needed":"需要","answered_before":None,
                          "result":"没结果","reason":"step 1"}],
             "answerable":False,"answer":None,"basis_steps":[],"answer_reason":"step 2"}
        self.assertTrue(validate_reader(row,2,{1:2,2:1}))
        self.assertFalse(validate_reader(row,2,{1:1,2:1}))
        row["subgoals"][0]["same_as"]={"step":2,"subgoal":1}
        self.assertFalse(validate_reader(row,2,{1:2,2:1}))

    def test_unknown_inference_keeps_frozen_strict_class(self):
        self.assertEqual(useful_labels(strict=True,after=False,progress=False,goals=None),"严格重复")
        self.assertIsNone(useful_labels(strict=False,after=False,progress=False,goals=None))
