import unittest

from chain_state_v10 import action_errors, fact_errors, adoption_errors, materialize, derive, compare


def table(status="未确认", ids=()):
    return [{"condition":"c1","status":status,"evidence":list(ids)}]


def evidence(eid="E1@1"):
    return {"id":eid,"fact":"报告确认发现","ids":["doc-1"],"about":"对象","conditions":["c1"],
            "strength":"直接","quotes":[{"id":"doc-1","docid":"doc","text":"An explicit discovery."}]}


def verdict(eid="E1@1", val="采纳", **kw):
    return {"id":eid,"verdict":val,"reason":"","basis":"","basis_conditions":[],"valid":"","ids":["N1"],**kw}


class StateTests(unittest.TestCase):
    def test_action_rejects_future_or_unknown_ref_and_missing_target(self):
        op={"object":"x","kind":"条件","conditions":["c1"],"what":"","ids":["N1"]}
        raw={"targets":[op],"plan_ids":[],"plan_match":"一致","looking_for":"find","plan_note":""}
        self.assertTrue(action_errors(raw,{"c1"},{"P1"}))
        op["ids"]=["P1"]
        self.assertFalse(action_errors(raw,{"c1"},{"P1"}))
        raw["targets"]=[]
        self.assertTrue(action_errors(raw,{"c1"},{"P1"}))

    def test_facts_cite_new_documents_and_attach_original_text(self):
        raw={"facts":[{k:v for k,v in evidence().items() if k not in {"id","quotes"}}]}
        self.assertTrue(fact_errors(raw,{"c1"},{"other-1":("other","text")}))
        source={"doc-1":("doc","exact sentence")}
        self.assertFalse(fact_errors(raw,{"c1"},source))
        self.assertEqual(materialize(raw,source,2)[0]["quotes"][0]["text"],"exact sentence")

    def test_current_rejected_evidence_cannot_confirm(self):
        row={"evidence":[verdict(val="没理会",ids=[])],"earlier_adopted":[],
             "table":table("确认",["E1@1"]),"assertions":[]}
        self.assertTrue(adoption_errors(row,{"c1"},[evidence()],{},set(),{"N1"}))
        row["evidence"]=[verdict()]
        self.assertFalse(adoption_errors(row,{"c1"},[evidence()],{},set(),{"N1"}))

    def test_late_adoption_checks_pending_ids(self):
        row={"evidence":[],"earlier_adopted":[{"id":"E1@1","ids":["N1"]}],
             "table":table("确认",["E1@1"]),"assertions":[]}
        self.assertFalse(adoption_errors(row,{"c1"},[],{"E1@1":evidence()},set(),{"N1"}))
        self.assertTrue(adoption_errors(row,{"c1"},[],{},{"E1@1"},{"N1"}))

    def test_negative_requires_validity_and_no_duplicate_verdict(self):
        row={"evidence":[verdict(val="否定")],"earlier_adopted":[],
             "table":table(),"assertions":[]}
        self.assertTrue(adoption_errors(row,{"c1"},[evidence()],{},set(),{"N1"}))
        row["evidence"]=[verdict(val="否定",reason="年份不符",basis="题外",valid="不成立")]
        self.assertFalse(adoption_errors(row,{"c1"},[evidence()],{},set(),{"N1"}))
        row["evidence"]*=2
        self.assertTrue(adoption_errors(row,{"c1"},[evidence()],{},set(),{"N1"}))

    def test_progress_and_conflict_can_coexist_with_strict(self):
        step={"step":1,"before_table":table(),"table":table("冲突",["E1@1"]),
              "candidate_before":"x","candidate_after":"x","excluded_before":[],
              "action":{"targets":[],"plan_match":"一致"},"new_evidence":[evidence()],
              "verdicts":[verdict()],"earlier_adopted":[],"assertions":[],"strict":[1]}
        result=derive([step],["c1"],None,False,lambda _:False)
        self.assertEqual(result["steps"][0]["tier"],"有进展")
        self.assertTrue({"严格重复","冲突不改"}<=set(result["steps"][0]["mechanisms"]))
        self.assertIsNone(result["evidence_point"])

    def test_direct_evidence_separate_from_inferred(self):
        step={"step":1,"before_table":table(),"table":table("确认",["E1@1"]),
              "candidate_before":None,"candidate_after":"x","excluded_before":[],
              "action":None,"new_evidence":[{**evidence(),"strength":"推断"}],
              "verdicts":[verdict()],"earlier_adopted":[],"assertions":[],"strict":[]}
        result=derive([step],["c1"],1,False,lambda _:False)
        self.assertEqual(result["evidence_point"],1)
        self.assertIsNone(result["direct_evidence_point"])

    def test_stability_aligns_by_citation_not_evidence_number(self):
        row={"step":1,"table":table(),"action":None,"new_evidence":[evidence("E1@1")],
             "verdicts":[verdict("E1@1")],"tier":"有进展","mechanisms":[]}
        other={**row,"new_evidence":[evidence("E2@1")],"verdicts":[verdict("E2@1")]}
        score=compare([row],[other])
        self.assertEqual(score["evidence_verdict"],[1,1])
        self.assertEqual(score["targets"],[0,1])


if __name__=="__main__":
    unittest.main()
