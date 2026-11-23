from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from chain_extractor_v2 import check_conditions, fallback_conditions, audit_quote, state_after, verified_facts, judge

class ProtocolTests(unittest.TestCase):
    def test_coverage_counts_union_and_normalizes(self):
        text="Some words. More useful words."
        repeat={"conditions":[{"id":"c1","text":"Some words."},{"id":"c2","text":"SOME WORDS.","asked":True}]}
        self.assertFalse(check_conditions(text,repeat)["valid"])
        self.assertTrue(check_conditions(text,fallback_conditions(text))["valid"])
        self.assertEqual(fallback_conditions("A 3.14 ratio; what value?")["conditions"][-1]["asked"],True)

    def test_only_current_new_returns_can_ground_facts(self):
        ring={"calls":[{"returned":[{"docid":"old","title":"a"},{"docid":"x","snippet":"This **exact text** is here."}]}]}
        result, audit = verified_facts({"new_facts":[{"fact":"f","quote":"EXACT  TEXT"},{"fact":"wrong","quote":"fake"}]},ring)
        self.assertEqual(result,[{"fact":"f","quote":"EXACT  TEXT","docid":"x"}])
        self.assertEqual([a["status"] for a in audit],["pass","reject"])

    def test_quote_fallback_is_contiguous_and_bounded(self):
        self.assertEqual(audit_quote("abc xyz","abc xyz")["status"],"pass")
        self.assertEqual(audit_quote("abcdefghij","abcdefghXj",fuzzy=True)["status"],"flag")
        self.assertEqual(audit_quote("abcdefghij","abcdXXefghXXij",fuzzy=True)["status"],"reject")

    def test_retains_candidates_and_applies_only_evidenced_operations(self):
        state={"candidates":[{"name":"One","status":"当前"}],"confirmed":[],"open":["c1","c2"]}
        changed=state_after(state,[{"op":"设为当前","name":"Two"},{"op":"排除","name":"Three"}],
                            [{"op":"确认","id":"c2"},{"op":"确认","id":"wrong"}],["c1","c2"])
        self.assertEqual(changed,{"candidates":[{"name":"One","status":"备选"},{"name":"Two","status":"当前"},{"name":"Three","status":"已排除"}],
                                  "confirmed":["c2"],"open":["c1"]})

    def test_requested_retry_limits(self):
        payloads=[]
        replies=iter([200,200,200,200])
        def fake(url,body):
            payloads.append(body)
            return next(replies),json.dumps({"choices":[{"message":{"content":"{","reasoning_content":"stub"}}]})
        with TemporaryDirectory() as d:
            out,error,attempts=judge(Path(d),"A","SYNTHETIC",{"number":5},{"url":"http://127.0.0.1:8000/v1",
                "model":"stub","temperature":0,"seed":42,"reasoning_effort":"medium","max_tokens":10},post=fake)
        self.assertIsNone(out)
        self.assertEqual(error,"json_parse_failed")
        self.assertEqual(len(attempts),4)
        self.assertTrue(all(x==payloads[0] for x in payloads))

if __name__=="__main__":
    unittest.main()
