import unittest

import capacity


class OverallCapacityTests(unittest.TestCase):
    def test_equal_thirds_mean_of_three_values(self):
        self.assertEqual(capacity.overall_capacity(30, 60, 90), 60.0)

    def test_all_equal_returns_that_value(self):
        self.assertEqual(capacity.overall_capacity(50, 50, 50), 50.0)

    def test_missing_one_category_averages_the_rest(self):
        self.assertEqual(capacity.overall_capacity(40, 80, None), 60.0)

    def test_missing_two_categories_returns_the_remaining_one(self):
        self.assertEqual(capacity.overall_capacity(None, 25, None), 25.0)

    def test_all_missing_returns_none(self):
        self.assertIsNone(capacity.overall_capacity(None, None, None))

    def test_result_rounds_to_one_decimal(self):
        # (10 + 20 + 25) / 3 = 18.333...
        self.assertEqual(capacity.overall_capacity(10, 20, 25), 18.3)

    def test_stays_within_bounds(self):
        self.assertEqual(capacity.overall_capacity(0, 0, 0), 0.0)
        self.assertEqual(capacity.overall_capacity(100, 100, 100), 100.0)


if __name__ == "__main__":
    unittest.main()
