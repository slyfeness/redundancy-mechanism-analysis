import unittest

from chain_extractor_v7 import candidate_equivalent, check_groups


class V7Tests(unittest.TestCase):
    def test_name_expansion_keeps_surname_and_all_short_tokens(self):
        self.assertTrue(candidate_equivalent("Jordan Field", "Jordan A. Field"))
        self.assertFalse(candidate_equivalent("Jordan Field", "Jordan Fields"))
        self.assertFalse(candidate_equivalent("Jordan A. Field", "Jordan B. Field"))
        self.assertTrue(candidate_equivalent("Blue Bird", "Blue Bird (Season 2)"))

    def test_condition_minimum_does_not_count_ignored_or_asked(self):
        clauses = [{"id": f"Q{i}", "text": "A short clause."} for i in range(1, 7)]
        question = " ".join(row["text"] for row in clauses)
        groups = {"answer_type":"person", "ignored":["Q5"], "conditions":[
            {"id":"c1","clauses":["Q1","Q2"]},{"id":"c2","clauses":["Q3"]},
            {"id":"c3","clauses":["Q4"]},{"id":"c4","clauses":["Q6"],"asked":True}]}
        self.assertFalse(check_groups(question, clauses, groups)["valid"])
        groups["conditions"][0]["clauses"]=["Q1"]
        groups["conditions"].insert(1, {"id":"c5","clauses":["Q2"]})
        self.assertTrue(check_groups(question, clauses, groups)["valid"])
