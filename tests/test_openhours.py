import unittest
from datetime import datetime

import openhours

# 2026-08-31 is a Monday, 2026-09-05 a Saturday, 2026-09-06 a Sunday.
HOURS = {
    "mon": [["09:00", "15:00"]],
    "tue": [["09:00", "13:00"], ["14:00", "17:00"]],
    "wed": [],
    "thu": [["09:00", "15:00"]],
    "fri": [["09:00", "15:00"]],
    "sat": [["10:00", "13:00"]],
    # no "sun" key -> closed
}


class IsOpenTests(unittest.TestCase):
    def test_open_during_a_listed_interval(self):
        self.assertTrue(openhours.is_open(HOURS, datetime(2026, 8, 31, 11, 30)))

    def test_closed_before_opening(self):
        self.assertFalse(openhours.is_open(HOURS, datetime(2026, 8, 31, 8, 59)))

    def test_open_exactly_at_the_opening_minute(self):
        self.assertTrue(openhours.is_open(HOURS, datetime(2026, 8, 31, 9, 0)))

    def test_closed_exactly_at_the_closing_minute(self):
        self.assertFalse(openhours.is_open(HOURS, datetime(2026, 8, 31, 15, 0)))

    def test_closed_on_an_empty_list_day(self):
        # Wednesday, 2026-09-02
        self.assertFalse(openhours.is_open(HOURS, datetime(2026, 9, 2, 11, 0)))

    def test_closed_on_a_missing_day_key(self):
        # Sunday, 2026-09-06
        self.assertFalse(openhours.is_open(HOURS, datetime(2026, 9, 6, 11, 0)))

    def test_multiple_intervals_closed_in_the_gap(self):
        # Tuesday, 2026-09-01, 13:30 is between the two intervals
        self.assertFalse(openhours.is_open(HOURS, datetime(2026, 9, 1, 13, 30)))

    def test_multiple_intervals_open_in_the_second(self):
        self.assertTrue(openhours.is_open(HOURS, datetime(2026, 9, 1, 15, 0)))

    def test_saturday_slot(self):
        self.assertTrue(openhours.is_open(HOURS, datetime(2026, 9, 5, 12, 0)))
        self.assertFalse(openhours.is_open(HOURS, datetime(2026, 9, 5, 14, 0)))

    def test_none_hours_returns_none(self):
        self.assertIsNone(openhours.is_open(None, datetime(2026, 8, 31, 11, 30)))


if __name__ == "__main__":
    unittest.main()
