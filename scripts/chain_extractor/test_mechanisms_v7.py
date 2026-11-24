import unittest

from mechanisms_v7 import derive, state_changed, agreed_events


def state(step, current=None, confirmed=(), checking=None, other=None, kind=None):
    candidates = [{"name":current, "status":"当前"}] if current else []
    if other:
        candidates.append({"name":other[0],"status":other[1]})
    return {"stage":step,"type":kind or ("start" if step==0 else "call"),
            "checking_object":checking,"state":{"candidates":candidates,"confirmed":list(confirmed),"open":[]}}


class MechanismTests(unittest.TestCase):
    def test_state_observes_candidate_roles_not_checking_object_or_alias_expansion(self):
        self.assertFalse(state_changed(state(0,"Jordan Field",checking="X"),
                                       state(1,"Jordan A. Field",checking="Y")))
        self.assertTrue(state_changed(state(0,"Jordan Field",other=("Sam Hollow","备选")),
                                      state(1,"Jordan Field",other=("Sam Hollow","已排除"))))

    def test_events_respect_steps_and_distinguish_two_gaps(self):
        answer = "Jordan A. Field"
        steps = [state(0),state(1,"Jordan Field",["c1"],"X"),state(2,"Jordan Field",["c1"]," x "),
                 state(3,"Jordan Field",["c1"],"X"),state(4,"Jordan Field",["c2"],"X"),
                 state(5,"Jordan Field",["c2"],kind="final")]
        steps[-1]["answer_kind"]="作答"
        data=derive(steps,["c1","c2"],{1:1,2:0,3:1,4:0},{2:["event2"]},{3:"不一致"},
                    {1:{"c1"},2:{"c2"}},{0:1,5:2},[answer],"MODEL_FINAL_STOP")
        self.assertEqual(data["trajectory_events"]["practical_sufficient_at"],1)
        self.assertIsNone(data["trajectory_events"]["strict_sufficient_at"])
        self.assertEqual(data["trajectory_events"]["stagnation_segments"],[{"start":2,"end":3,"length":2}])
        self.assertTrue(data["steps"][2]["gap_a"])
        self.assertTrue(data["steps"][2]["gap_b"])
        self.assertTrue(data["steps"][3]["gap_a"])
        self.assertFalse(data["steps"][3]["gap_b"])
        self.assertTrue(data["steps"][4]["correction"])
        self.assertEqual(data["trajectory_events"]["adoption"]["c2"]["delay"],2)
        self.assertEqual(data["steps"][0]["unsupported_claims"],1)
        self.assertEqual(data["steps"][-1]["unsupported_claims"],2)

    def test_agreement_intersects_step_ids_and_condition_ids(self):
        first = {"steps":[{"stage":1,"gap_a":True,"adoption":[{"id":"c1","delay":0}]},
                          {"stage":2,"gap_a":False}],"trajectory_events":
                 {"stagnation_segments":[],"answer_kind":"作答","strict_sufficient_at":None}}
        second = {"steps":[{"stage":1,"gap_a":True,"adoption":[{"id":"c2","delay":0}]},
                           {"stage":2,"gap_a":True}],"trajectory_events":
                  {"stagnation_segments":[],"answer_kind":"作答","strict_sufficient_at":1}}
        result=agreed_events(first,second)
        self.assertEqual(result["step_events"]["gap_a"],[1])
        self.assertNotIn("adoption",result["step_events"])
        self.assertEqual(result["trajectory_events"]["answer_kind"],"作答")
