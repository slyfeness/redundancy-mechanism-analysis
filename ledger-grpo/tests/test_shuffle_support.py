import unittest

from audit_shuffle_support import width_support


class ShuffleSupportTest(unittest.TestCase):
    def test_identical_width_support_and_movement(self):
        result = width_support([2,2,2,3,4,4], [2,2,3])
        self.assertEqual(result['exact_width_subsets'], 3)
        self.assertEqual(result['maximum_relocated_events'], 1)
        self.assertAlmostEqual(result['expected_relocated_events'], 2/3)

    def test_unique_width_strata_force_original_positions(self):
        self.assertEqual(width_support([2,3,4], [2,4])['maximum_relocated_events'], 0)
