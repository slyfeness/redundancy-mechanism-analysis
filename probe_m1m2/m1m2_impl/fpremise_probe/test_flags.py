import unittest

from flags import classify, mark


def search(stage, role, candidate, match):
    return {"stage_id": stage, "role": role, "candidate": candidate, "match": match}


class PremiseTest(unittest.TestCase):
    def test_transparent_rows_and_interleaved_roles_preserve_runs(self):
        data = [search(1, "A", "Aloïs North", "different"), search(2, "B", "June Vale", "different"),
                search(3, "A", None, "none"), search(4, "A", "ALOIS NORTH", "different"),
                search(5, "A", "Aloïs North", "different"), search(6, "A", "Cora Reed", "same")]
        events = mark(data, {"A": "Cora Reed", "B": "Vera West"})
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["stage_id"], events[0]["consecutive_queries"],
                          events[0]["correction_stage_id"]), (1, 3, 6))

    def test_interruption_one_credit_and_only_later_corrections(self):
        data = [search(1, "A", "Max Red", "different"), search(2, "A", "Una Ray", "different"),
                search(3, "A", "Max Red", "different"), search(4, "A", "Max Red", "different"),
                search(5, "A", "Una Ray", "different"), search(6, "A", "Una Ray", "different"),
                search(7, "A", "Cora Reed", "same"), search(8, "A", "Max Red", "different"),
                search(9, "A", "Max Red", "different"), search(10, "A", "Cora Reed", "same")]
        events = mark(data, {"A": "Cora Reed"})
        self.assertEqual([(e["stage_id"], e["correction_stage_id"]) for e in events], [(3, 7), (5, 7)])

    def test_invalid_query_cannot_bridge_a_streak(self):
        data = [search(1, "A", "Max Red", "different"), search(2, None, None, "invalid"),
                search(3, "A", "Max Red", "different")]
        self.assertEqual(mark(data, {"A": "Cora Reed"}), [])

    def test_candidates_must_come_from_original_queries(self):
        queries = [{"id": 1, "text": "Aloïs North book"}, {"id": 2, "text": "publishers by century"}]
        raw = {"verdicts": [{"id": 1, "role": "A", "candidate": "Alois North", "match": "different"},
                            {"id": 2, "role": "A", "candidate": "Alois North", "match": "different"}]}
        self.assertEqual(set(classify(raw, queries, {"A": "Cora Reed"})), {1})


    def test_exact_table_name_cannot_be_a_different_candidate(self):
        query = [{"id": 1, "text": "Cora Reed book"}]
        item = {"id": 1, "role": "A", "candidate": "Cora Reed", "match": "different"}
        self.assertEqual(classify({"verdicts": [item]}, query, {"A": "Cora Reed"}), {})
