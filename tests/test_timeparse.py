import unittest
from datetime import datetime, timedelta, timezone

from ordo import timeparse as tp


class DurationTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(tp.parse_duration("3d"), timedelta(days=3))
        self.assertEqual(tp.parse_duration("12h"), timedelta(hours=12))
        self.assertEqual(tp.parse_duration("30m"), timedelta(minutes=30))
        self.assertEqual(tp.parse_duration("2w"), timedelta(weeks=2))
        self.assertEqual(tp.parse_duration("in 2 weeks"), timedelta(weeks=2))
        self.assertEqual(tp.parse_duration("+1 day"), timedelta(days=1))

    def test_garbage(self):
        with self.assertRaises(tp.TimeParseError):
            tp.parse_duration("soonish")


class WhenTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def test_relative(self):
        self.assertEqual(tp.parse_when("3d", now=self.now), self.now + timedelta(days=3))

    def test_iso_date_bumps_to_due_time(self):
        parsed = tp.parse_when("2026-11-30", now=self.now, tz=timezone.utc, due_time="18:00")
        self.assertEqual(parsed, datetime(2026, 11, 30, 18, 0, tzinfo=timezone.utc))

    def test_date_with_clock(self):
        parsed = tp.parse_when("2026-11-30 09:15", now=self.now, tz=timezone.utc)
        self.assertEqual(parsed, datetime(2026, 11, 30, 9, 15, tzinfo=timezone.utc))

    def test_tomorrow_with_clock(self):
        parsed = tp.parse_when("tomorrow 07:00", now=self.now, tz=timezone.utc)
        self.assertEqual(parsed, datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc))

    def test_now(self):
        self.assertEqual(tp.parse_when("now", now=self.now), self.now)

    def test_empty(self):
        self.assertIsNone(tp.parse_when("", now=self.now))

    def test_garbage_raises(self):
        with self.assertRaises(tp.TimeParseError):
            tp.parse_when("banana", now=self.now)


class StorageTest(unittest.TestCase):
    def test_roundtrip(self):
        original = datetime(2026, 5, 4, 14, 30, tzinfo=timezone.utc)
        stored = tp.to_storage(original)
        self.assertEqual(stored, "2026-05-04T14:30:00Z")
        self.assertEqual(tp.from_storage(stored), original)

    def test_none(self):
        self.assertIsNone(tp.to_storage(None))
        self.assertIsNone(tp.from_storage(None))


if __name__ == "__main__":
    unittest.main()
