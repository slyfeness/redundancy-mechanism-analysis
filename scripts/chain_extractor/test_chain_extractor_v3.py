from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from chain_extractor_v3 import numbered, checked_ids, claim_keywords, check_claim, run_case


class SentenceIdsTest(unittest.TestCase):
    def test_numbers_real_sentences_but_not_marker(self):
        text = "First 3.14 is a number. Next? Yes!\n- A line\n- Another"
        rows = numbered(text, "N")
        self.assertEqual([row["id"] for row in rows],["N1","N2","N3","N4","N5"])
        self.assertIn("3.14", rows[0]["text"])
        self.assertEqual(numbered("（无，轨迹在此终止：原因）","N"),[])
        rows = numbered("x"*401+"；last","D-")
        self.assertEqual([len(row["text"]) for row in rows],[402,4])

    def test_cross_step_ids_never_ground_a_field(self):
        cited, checked = checked_ids(["T1-1","T2-1","T2-1",3],{"T2-1":"real thought"})
        self.assertEqual(cited,[{"id":"T2-1","text":"real thought"}])
        self.assertEqual(checked["invalid_ids"],["T1-1",3])

    def test_claim_audit_uses_cited_text_and_document_prefix(self):
        text="However, Mira reported 1,234 results in 2008."
        keys=claim_keywords([text],"Who is Mira?")
        self.assertEqual(set(keys),{"1234","2008"})
        ref=[{"id":"N1","text":text}]
        audit=check_claim("a label",ref,"Who is Mira?",["archive has 1,234 results in 2009."])
        self.assertEqual(audit["status"],"无返回依据")
        self.assertEqual(audit["missing_keywords"],["2008"])
        self.assertEqual(check_claim("a label",[], "Who?", ["2008"])["status"],"无法判断")

    def test_whole_preserves_conclusion_and_gates_ops_by_current_thought(self):
        data={"question":"Find the painter. Where is the painting?","rings":[
            {"type":"start","thinking":"Search for Mira."},
            {"type":"call","stage":1,"thinking_before":"Search for Mira.",
             "thinking_after":"Mira painted it in 2008.","calls":[
                 {"query":"synthetic search","returned":[{"docid":"doc","snippet":"Mira painted it."}]}]},
            {"type":"final","thinking":"Mira painted it in 2008.","formal_answer":"Mira.",
             "termination_reason":None}]}
        conditions=[{"id":"c1","text":"Find the painter."}]
        value={"start":{"plan":"Search","plan_ids":["S1"]},"steps":[{
            "step":1,"conclusion":"keep text","conclusion_ids":["T2-1"],
            "main_candidate":{"name":"Wrong","ids":["S1"]},
            "other_candidates":[{"name":"Mira","ids":["T1-1"]}],
            "condition_checks":[{"id":"c1","confirmed":True,"ids":["T1-1"]}],
            "new_facts":[{"fact":"A painter","ids":["doc-1"]}],
            "claims":[{"claim":"A date stated","ids":["T1-1"]}]}],"final":{}}
        env=json.dumps({"choices":[{"finish_reason":"stop","message":{"content":json.dumps(value)}}]})
        cfg={"url":"http://127.0.0.1:8000/v1","model":"stub","temperature":0,
             "seed":1,"reasoning_effort":"medium","max_tokens":16384,"whole_max_tokens":32768,"timeout_seconds":1}
        with TemporaryDirectory() as base, patch("chain_extractor_v2.direct_post",return_value=(200,env)) as post:
            out=Path(base)
            result=run_case(data,conditions,{"W":"fixture"},cfg,out,"W")
            self.assertEqual(post.call_count,1)
            self.assertFalse(result["whole_failed"])
            view=[json.loads(x) for x in (out/"STATE.jsonl").read_bytes().splitlines()]
            self.assertEqual(view[1]["state"]["candidates"],[{"name":"Mira","status":"备选"}])
            self.assertEqual(view[1]["state"]["confirmed"],["c1"])
            self.assertIn("keep text",(out/"CHAIN.md").read_text(encoding="utf-8"))
            checks=[json.loads(x) for x in (out/"CLAIMS.jsonl").read_bytes().splitlines()]
            self.assertEqual(checks[0]["missing_keywords"],["2008"])
