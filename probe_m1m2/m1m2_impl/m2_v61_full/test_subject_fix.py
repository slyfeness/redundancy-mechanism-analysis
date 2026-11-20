import unittest

from rules import cleanup


class SubjectFixTest(unittest.TestCase):
    def test_answer_subject_is_retained_while_claim_and_duplicate_checks_survive(self):
        original = {"entities": [{"var": "P", "name": "Blue Finch"}],
                    "conditions": [{"id": "a", "subject": "P", "claim": "Was first recorded in winter."},
                                   {"id": "b", "subject": "P", "claim": "Met a Blue Finch."},
                                   {"id": "c", "subject": "P", "claim": "Was first recorded in winter."}]}
        kept, changes = cleanup("q", original, ["Blue Finch"], drop_answer_subject=False)
        self.assertEqual([row["id"] for row in kept["conditions"]], ["a"])
        self.assertEqual([row["reason"] for row in changes], ["answer_in_claim", "duplicate_claim"])
        self.assertEqual(cleanup("q", original, ["Blue Finch"])[0]["conditions"], [])


    def test_replay_does_not_replace_an_already_sealed_duplicate_verdict(self):
        from pathlib import Path
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m2_v61_fix"))
        from run_fix import cleanup_replayed

        first = {"id": "first", "subject": "P", "claim": "Was first recorded in winter."}
        sealed = {**first, "id": "sealed", "subject": "Q"}
        original = {"entities": [{"var": "P", "name": "Blue Finch"}, {"var": "Q", "name": "Calm Sparrow"}],
                    "conditions": [first, sealed]}
        question = {"answers": ["Blue Finch"]}
        previous, _ = cleanup("q", original, question["answers"])
        result, restored, blocked, _, _ = cleanup_replayed("q", question, original, previous)
        self.assertEqual(result["conditions"], [sealed])
        self.assertFalse(restored)
        self.assertEqual(blocked, {"first": "duplicate_claim"})
