import json
from pathlib import Path
import tempfile
import unittest

from chain_extractor import prepare, truncate, execute

def sample():
    text = "title: A\nOne."
    result = json.dumps([{"docid":"x","snippet":text}])
    return {"rounds":[
        {"round_id":1,"actor_visible_messages":[{"role":"user","content":"Synthetic question?"}],
         "reasoning_content":"s1","content":""},
        {"round_id":2,"actor_visible_messages":[{"role":"tool","content":result},{"role":"tool","content":result}],
         "reasoning_content":"s2","content":""},
        {"round_id":3,"actor_visible_messages":[{"role":"tool","content":result}],
         "reasoning_content":"s3","content":"Synthetic submission."}],
        "tool_events":[{"round_id":r,"dispatch_order":i,"exact_arguments":{"query":f"q{r}.{i}"},
                        "exact_result":result} for r,i in ((1,0),(1,1),(2,0))]}

class ExtractorTests(unittest.TestCase):
    def test_parallel_and_prior_ring(self):
        data=prepare(sample(),{"status":"MODEL_FINAL_STOP"},{"head":3,"tail":5})
        self.assertEqual([x["type"] for x in data["rings"]],["start","call","call","final"])
        calls=data["rings"][1]["calls"]
        self.assertEqual([x["query"] for x in calls],["q1.0","q1.1"])
        self.assertEqual(calls[1]["returned"][0]["snippet"],"title: A\nOne.")
        old=data["rings"][2]["calls"][0]["returned"][0]
        self.assertEqual(old,{"docid":"x","title":"A","previous_seen_rings":[1]})
        self.assertEqual(data["rings"][-1]["formal_answer"],"Synthetic submission.")

    def test_zero_calls_and_missing_reinjection(self):
        data=sample()
        data["rounds"]=data["rounds"][:1]
        d=prepare({**data,"tool_events":[]},{"status":"GENERATION_LENGTH_STOP"},{"head":3,"tail":5})
        self.assertEqual([x["type"] for x in d["rings"]],["start","final"])
        self.assertEqual(d["rings"][-1]["formal_answer"],"未交卷")
        d=prepare({**data,"tool_events":data["tool_events"][:1]},{"status":"CONTEXT_LIMIT_STOP"},{"head":3,"tail":5})
        self.assertIn("上下文写满",d["rings"][1]["thinking_after"])
        self.assertEqual(d["rings"][1]["calls"][0]["returned"],[])

    def test_thought_truncation(self):
        self.assertEqual(truncate("abcdefghijkl",{"head":3,"tail":5}),"abc[中间省略 4 字]hijkl")
        self.assertEqual(truncate("abcdefgh",{"head":3,"tail":5}),"abcdefgh")

    def test_retry_fallback_state_and_resume(self):
        replies=iter(['{"state":{"open":["c1"]},"quote":"s1"}','{','{','{"type":"call"}','{"type":"final"}'])
        requests=[]
        def post(endpoint,body):
            requests.append(json.loads(body["messages"][1]["content"]))
            raw=json.dumps({"choices":[{"message":{"content":next(replies),"reasoning":"stub"}}]})
            return 200,raw
        data=prepare(sample(),{"status":"MODEL_FINAL_STOP"},{"head":3,"tail":5})
        with tempfile.TemporaryDirectory() as d:
            args=(data,{"conditions":[{"id":"c1","text":"Synthetic"}]},"prompt",
                {"url":"http://127.0.0.1:9999/v1","model":"stub","temperature":0,"seed":42,
                 "reasoning_effort":"high","max_tokens":100},Path(d))
            first=execute(*args,post=post)
            self.assertEqual(len(requests),5)
            self.assertEqual(requests[1],requests[2])
            self.assertEqual(first[1]["output"],{"type":"call","extraction_failed":True,"state":{"open":["c1"]}})
            self.assertEqual(requests[3]["prior_chain"][1],first[1]["output"])
            self.assertEqual(execute(*args,post=post),first)
            self.assertEqual(len(requests),5)

if __name__=="__main__":
    unittest.main()
