import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chain_extractor_v6 import check_groups, fallback, run_case, split_clauses


class V6Tests(unittest.TestCase):
    def test_split_and_group_reconstruct_original_text(self):
        q="1. First fact; 2. Second fact. Which place?"
        pieces=split_clauses(q)
        self.assertEqual([p["text"] for p in pieces],["1. First fact;","2. Second fact.","Which place?"])
        groups={"answer_type":"Place","conditions":[
            {"id":"c1","clauses":["Q1"]},{"id":"c2","clauses":["Q2"]},
            {"id":"c3","clauses":["Q3"],"asked":True}],"ignored":[]}
        self.assertTrue(check_groups(q,pieces,groups)["valid"])
        groups["ignored"]=["Q1"]
        self.assertFalse(check_groups(q,pieces,groups)["valid"])

    def test_cap_and_preserve_fallback_asked(self):
        q=" ".join(f"Fact {i}." for i in range(15))+" Asked?"
        clauses=split_clauses(q)
        result=fallback(clauses,None)
        self.assertEqual(result["answer_type"],"Asked?")
        self.assertEqual(len(result["conditions"]),11)
        self.assertTrue(check_groups(q,clauses,result)["valid"])

    def test_merge_unjudged_and_original_terminal(self):
        data={"question":"Test?","rings":[{"type":"start","thinking":"Start."},
            {"type":"call","stage":1,"thinking_before":"Start.","thinking_after":"It is Blue Bird.",
             "calls":[{"query":"test","returned":[]}]},
            {"type":"final","thinking":"Done.","formal_answer":"Blue Bird. Season two.","termination_reason":None}]}
        cfg={"url":"http://127.0.0.1:8000/v1","model":"stub","temperature":0,"seed":1,"reasoning_effort":"medium",
             "max_tokens":16384,"whole_max_tokens":32768,"timeout_seconds":1}
        p={k:k for k in ("S","A1","A2","B","F")}
        frozen={"answer_type":"Show","conditions":[{"id":"c1","text":"Test?"}]}
        def post(url,body,timeout):
            phase=body["messages"][0]["content"]
            payload=json.loads(body["messages"][1]["content"])
            output={}
            if phase=="S":
                output={"candidates":[{"name":"Blue Bird","ids":["S1"]}]}
            if phase=="B" and "missing_condition_ids" not in payload:
                output={"main_candidate":{"name":"Blue Bird (Season 2)","ids":["N1"]}}
            if phase=="F":
                output={"answer_kind":"作答","answer_ids":["Z1","Z2","F1"]}
            return 200,json.dumps({"choices":[{"finish_reason":"stop","message":{"content":json.dumps(output)}}]})
        with TemporaryDirectory() as tmp, patch("chain_extractor_v2.direct_post",side_effect=post):
            out=Path(tmp)
            result=run_case(data,frozen,p,cfg,out)
            states=[json.loads(line) for line in (out/"STATE.jsonl").read_bytes().splitlines()]
            self.assertIn("[Z1] Blue Bird. / [Z2] Season two.",(out/"CHAIN.md").read_text(encoding="utf-8"))
        self.assertEqual(result["candidate_merges"],1)
        self.assertEqual(states[1]["unjudged_conditions"],[{"id":"c1","status":"未判断"}])
        self.assertEqual(states[-1]["state"]["candidates"],[{"name":"Blue Bird (Season 2)","status":"当前"}])
        self.assertEqual(result["answer_kind"],"作答")
