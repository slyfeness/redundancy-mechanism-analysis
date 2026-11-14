"""Literal diagnostic fixtures with the archived result verdict left separate."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))


class SavedSubmissionTests(unittest.TestCase):
    def test_only_unambiguous_exact_field_or_whole_submission_matches(self):
        from audit_saved_submissions import lexical_signals

        fixtures = (
            ('Ada Lovelace', True, ('whole_match', True, True)),
            ('Analysis\n**Exact Answer:** Ada LOVELACE\nOther detail.', True, ('explicit_match', True, True)),
            ('Ada Lovelace is ruled out.', True, ('no_explicit_answer', False, True)),
            ('Exact Answer: Ada Lovelace\nExact Answer: Grace Hopper', True, ('conflicting_answers', False, True)),
            ('Exact Answer: Grace Hopper\nAda Lovelace is ruled out.', True, ('explicit_mismatch', False, True)),
            ('Ada Lovelaceman', True, ('no_explicit_answer', False, False)),
            ('Exact Answer: Ada Lovelace', False, ('terminal_failure', False, False)),
        )
        for text, complete, expected in fixtures:
            with self.subTest(text=text, complete=complete):
                self.assertEqual(lexical_signals(text, 'Ada Lovelace', complete=complete), expected)


if __name__ == '__main__':
    unittest.main()
