from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from chain_extractor_v4 import check_claim, run_case, v4_prompts


class V4Tests(unittest.TestCase):
    def setUp(self):
        self.data={"question":"Which person worked in 1960?","rings":[
            {"type":"start","thinking":"Search for Mira."},
            {"type":"call","stage":1,"thinking_before":"Search for Mira.","thinking_after":"Mira painted it in 2008.",
             "calls":[{"query":"synthetic search","returned":[{"docid":"doc","snippet":"Mira painted it."}]}]},
            {"type":"final","thinking":"I now suspect Chandra.","formal_answer":"Mira.","termination_reason":None}]}
        self.conditions=[{"id":"c1","text":"Which person"},{"id":"c2","text":"worked in 1960?"}]
        self.cfg={"url":"http://127.0.0.1:8000/v1","model":"stub","temperature":0,"seed":1,
                  "reasoning_effort":"medium","max_tokens":16384,"whole_max_tokens":32768,"timeout_seconds":1}
        self.prompts={p:p for p in ("S","A1","A2","B","F","W")}

    def test_claim_words_filter_question_numbers_markdown_and_lowercase(self):
        refs=[{"id":"N1","text":"**Overview**: Summary"},
              {"id":"N2","text":"Here I saw the 1960s headlines, Reykjavík City and the River East near river at 75%."}]
        row=check_claim("fixture", refs, "Which person worked in 1960?", ["Records from Reykjavík City mention East and 75%."])
        self.assertEqual(set(row["keywords"]),{"75","reykjavík city","east"})
        self.assertEqual(row["status"],"有依据")
        self.assertEqual(check_claim("fixture",refs,"Which person worked in 1960?",[])["missing_keywords"],row["keywords"])

    def test_s_isolates_a_requests_and_merges_only_missing_b(self):
        calls=[]
        def post(url,body,timeout):
            phase=body["messages"][0]["content"]
            p=json.loads(body["messages"][1]["content"])
            calls.append((phase,p))
            out={}
            if phase=="A1":
                self.assertIn("queries",p)
                self.assertNotIn("calls",p)
                self.assertNotIn("returns",p)
                out={"looking_for":"look","plan_match":"一致","plan_ids":["P1"]}
            if phase=="A2":
                self.assertNotIn("thinking_before",p)
                self.assertIn("returns",p)
                out={"new_facts":[{"fact":"fact","ids":["doc-1"]}]}
            if phase=="B":
                if "missing_condition_ids" in p:
                    self.assertEqual(p["missing_condition_ids"],["c2"])
                    out={"conclusion":"must not override","condition_checks":[
                        {"id":"c1","confirmed":True,"ids":["N1"]},{"id":"c2","confirmed":True,"ids":["N1"]}]}
                else:
                    out={"conclusion":"initial conclusion","conclusion_ids":["N1"],
                         "condition_checks":[{"id":"c1","confirmed":False,"ids":[]}]}
            return 200,json.dumps({"choices":[{"finish_reason":"stop","message":{"content":json.dumps(out)}}]})
        with TemporaryDirectory() as d, patch("chain_extractor_v2.direct_post",side_effect=post):
            result=run_case(self.data,self.conditions,self.prompts,self.cfg,Path(d),"S")
            chain=(Path(d)/"CHAIN.md").read_text(encoding="utf-8")
            records=[json.loads(x) for x in (Path(d)/"STATE.jsonl").read_bytes().splitlines()]
        self.assertEqual([p for p,_ in calls],["S","A1","A2","B","B","F"])
        self.assertIn("initial conclusion",chain)
        self.assertNotIn("must not override",chain)
        self.assertIn("计划一致性：一致",chain)
        self.assertEqual(records[1]["state"]["confirmed"],["c2"])
        self.assertEqual(records[1]["condition_followup"]["missing_after"],[])
        self.assertEqual(result["condition_followups"],1)

    def test_w_has_citation_heading_and_final_thought(self):
        def post(url,body,timeout):
            p=json.loads(body["messages"][1]["content"])
            self.assertIn("S1",p["steps"][0]["heading"])
            self.assertIn("doc-1",p["steps"][0]["heading"])
            self.assertIn("T1-1",p["steps"][0]["heading"])
            source=p["terminal"]["last_thinking"]
            self.assertEqual(source,[{"id":"T2-1","text":"I now suspect Chandra."}])
            obj={"steps":[{"step":1}],"final":{"basis":"changed","basis_ids":["T2-1"]}}
            return 200,json.dumps({"choices":[{"finish_reason":"stop","message":{"content":json.dumps(obj)}}]})
        with TemporaryDirectory() as d, patch("chain_extractor_v2.direct_post",side_effect=post) as send:
            result=run_case(self.data,self.conditions,self.prompts,self.cfg,Path(d),"W")
            self.assertEqual(send.call_count,1)
            self.assertIn("I now suspect Chandra.",(Path(d)/"CHAIN.md").read_text(encoding="utf-8"))
            self.assertTrue(result["step_check"]["exact_order_and_count"])
