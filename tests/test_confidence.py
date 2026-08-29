import unittest

import confidence

HOUR = 3600
DAY = 24 * HOUR


class FreshReportTests(unittest.TestCase):
    def test_zero_age_is_full_confidence(self):
        for kind in ("pantry", "shelter", "wifi"):
            self.assertEqual(confidence.confidence(kind, 0), 1.0)

    def test_a_few_seconds_old_is_near_one(self):
        self.assertGreaterEqual(confidence.confidence("shelter", 30), 0.99)
        self.assertGreaterEqual(confidence.confidence("pantry", 30), 0.99)

    def test_negative_age_clamps_to_one(self):
        self.assertEqual(confidence.confidence("shelter", -500), 1.0)


class HalfLifeTests(unittest.TestCase):
    def test_one_half_life_is_exactly_half(self):
        self.assertAlmostEqual(confidence.confidence("shelter", 1 * HOUR), 0.5)
        self.assertAlmostEqual(confidence.confidence("pantry", 2 * HOUR), 0.5)
        self.assertAlmostEqual(confidence.confidence("wifi", 7 * DAY), 0.5)

    def test_two_half_lives_is_a_quarter(self):
        self.assertAlmostEqual(confidence.confidence("shelter", 2 * HOUR), 0.25)


class VeryOldReportTests(unittest.TestCase):
    def test_old_report_approaches_zero(self):
        self.assertLess(confidence.confidence("shelter", 1 * DAY), 0.001)
        self.assertLess(confidence.confidence("pantry", 2 * DAY), 0.001)
        self.assertLess(confidence.confidence("wifi", 365 * DAY), 0.001)

    def test_confidence_never_goes_negative(self):
        self.assertGreater(confidence.confidence("shelter", 10 * DAY), 0.0)


class PerTypeRateTests(unittest.TestCase):
    def test_each_kind_decays_at_its_own_rate(self):
        # At one hour old, shelter has lost half its confidence, pantry a bit,
        # wifi almost none.
        age = 1 * HOUR
        shelter = confidence.confidence("shelter", age)
        pantry = confidence.confidence("pantry", age)
        wifi = confidence.confidence("wifi", age)

        self.assertAlmostEqual(shelter, 0.5)
        self.assertAlmostEqual(pantry, 0.5 ** 0.5, places=6)  # ~0.707
        self.assertGreater(wifi, 0.99)
        self.assertGreater(wifi, pantry)
        self.assertGreater(pantry, shelter)

    def test_unknown_kind_falls_back_to_default_half_life(self):
        self.assertAlmostEqual(
            confidence.confidence("mystery", confidence.DEFAULT_HALF_LIFE_SECONDS),
            0.5,
        )


if __name__ == "__main__":
    unittest.main()
