from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from chain_extractor_v5 import V5Protocol, check_conditions, fallback_conditions, run_case


class V5Tests(unittest.TestCase):
    def test_merged_conditions_are_locatable_without_counting_asked(self):
        question="Find a painter. She worked in Turin. She studied sculpture. Where was she born?"
        obj={"answer_type":"Birthplace", "conditions":[
            {"id":"c1","text":"Find a painter."},
            {"id":"c2","text":"She worked in Turin; She studied sculpture"},
            {"id":"c3","text":"Where was she born?","asked":True},
        ]}
        self.assertTrue(check_conditions(question,obj)["valid"])
        self.assertFalse(check_conditions(question,{**obj,"answer_type":""})["valid"])
        self.assertFalse(check_conditions(question,{**obj,"conditions":obj["conditions"][1:]})["valid"])

    def test_fallback_keeps_asked_separate_and_limits_other_conditions(self):
        question=" ".join(f"Condition {i}." for i in range(15))+" Where was she born?"
        result=fallback_conditions(question,"Place")
        self.assertEqual(result["answer_type"],"Place")
        self.assertEqual(len(result["conditions"]),11)
        self.assertEqual(result["conditions"][-1]["text"],"Where was she born?")
        self.assertTrue(check_conditions(question,result)["valid"])

    def test_only_seen_docids_are_removed_from_keyword_audit(self):
        proto=V5Protocol("Painter")
        proto.observe({"calls":[{"returned":[{"docid":"91802"}]}]})
        result=proto.check_claim("test",[{"id":"N1","text":"A hit 91802 reports 1932."}], "Who?", [])
        self.assertEqual(result["keywords"],["1932"])
        self.assertEqual(result["missing_keywords"],["1932"])
        self.assertEqual(result["ignored_docids"],["91802"])

    def test_current_and_prior_checking_objects_cannot_become_current(self):
        cfg={"url":"http://127.0.0.1:8000/v1","model":"stub","temperature":0,"seed":1,
             "reasoning_effort":"medium","max_tokens":16384,"whole_max_tokens":32768,"timeout_seconds":1}
        data={"question":"Which painter?", "rings":[
            {"type":"start","thinking":"Planning."},
            *[{"type":"call","stage":i,"calls":[{"query":"test","returned":[]}],
               "thinking_before":"Plan.","thinking_after":"I am checking an archive."} for i in (1,2)],
            {"type":"final","thinking":"I cannot answer.","formal_answer":"I cannot answer.","termination_reason":None}
        ]}
        frozen={"answer_type":"Painter","conditions":[{"id":"c1","text":"Which painter?"}]}
        seen=[]
        def post(url,body,timeout):
            phase=body["messages"][0]["content"]
            payload=json.loads(body["messages"][1]["content"])
            self.assertEqual(payload["所问对象类型"],"Painter")
            out={}
            if phase=="B":
                seen.append(phase)
                name="An Archive" if len(seen)==1 else "Another place"
                out={"checking_object":{"name":name,"ids":["N1"]},
                     "main_candidate":{"name":" AN   ARCHIVE ","ids":["N1"]},
                     "condition_checks":[{"id":"c1","confirmed":False,"ids":[]}]}
            if phase=="F":
                out={"final_answer":"拒答","unresolved":"No answer"}
            return 200,json.dumps({"choices":[{"finish_reason":"stop","message":{"content":json.dumps(out)}}]})
        with TemporaryDirectory() as folder, patch("chain_extractor_v2.direct_post",side_effect=post):
            target=Path(folder)
            result=run_case(data,frozen,{p:p for p in ("S","A1","A2","B","F")},cfg,target)
            state=[json.loads(line) for line in (target/"STATE.jsonl").read_bytes().splitlines()]
            report=(target/"CHAIN.md").read_text(encoding="utf-8")
        self.assertEqual(state[-1]["state"]["candidates"],[])
        self.assertEqual(result["candidate_conflicts"],2)
        self.assertIn("正在核实：Another place",report)
        self.assertIn("答案：拒答",report)
