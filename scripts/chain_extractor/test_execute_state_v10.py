import tempfile
import unittest
from pathlib import Path

from execute_state_v10 import checked, step_inputs


class ExecutionTests(unittest.TestCase):
    def test_failure_feedback_is_attached_and_stops_after_two_retries(self):
        effects=[]
        def send(path,key,prompt,body,cfg,max_retries):
            effects.append(body)
            return {"bad":1},None,[{"finish_reason":"stop","error":None}]
        result=checked(Path(tempfile.gettempdir()),"x","p",{"orig":1},{},lambda _:["矛盾"],send)
        self.assertIsNone(result["parsed"])
        self.assertEqual(len(result["attempts"]),3)
        self.assertEqual(effects[0],{"orig":1})
        self.assertEqual(effects[1],{"orig":1,"上一次校验错误":["矛盾"]})

    def test_action_and_evidence_are_temporally_scoped(self):
        step={"before":[{"id":"P1"}],"after":[{"id":"N1"}],"queries":["q"],"returns":[1],
              "candidate_before":None,"candidate_after":"a","excluded_before":[],"excluded_after":[],
              "v7_B":{"main_candidate":None,"excluded":[]},"final_sentences":[{"id":"F1"}],"after_marker":None}
        a,b=step_inputs([{"id":"A"}],[],step)
        self.assertNotIn("本次返回",a)
        self.assertNotIn("调用前思考",b)
        self.assertNotIn("下一轮思考",b)
        self.assertNotIn("正式答案",a)


if __name__=="__main__":
    unittest.main()
