import unittest
from datetime import date, datetime, timedelta, timezone

from spx_quant import clock


class ClockTest(unittest.TestCase):
    def test_dst_offsets(self):
        self.assertEqual(clock.offset("ET", datetime(2026, 7, 1, 12, tzinfo=timezone.utc)), timedelta(hours=-4))
        self.assertEqual(clock.offset("ET", datetime(2026, 12, 1, 12, tzinfo=timezone.utc)), timedelta(hours=-5))
        self.assertEqual(clock.offset("PT", datetime(2026, 10, 5, 17, tzinfo=timezone.utc)), timedelta(hours=-7))
        self.assertEqual(clock.offset("PT", datetime(2026, 11, 16, 17, tzinfo=timezone.utc)), timedelta(hours=-8))

    def test_dst_boundaries_2026(self):
        # starts Sunday March 8 at 07:00 UTC for ET, ends Sunday November 1 at 06:00 UTC
        self.assertEqual(clock.offset("ET", datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)), timedelta(hours=-5))
        self.assertEqual(clock.offset("ET", datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)), timedelta(hours=-4))
        self.assertEqual(clock.offset("ET", datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc)), timedelta(hours=-4))
        self.assertEqual(clock.offset("ET", datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)), timedelta(hours=-5))

    def test_wall_time_round_trip(self):
        utc = clock.local_to_utc("ET", datetime(2026, 9, 28, 16, 14, 59))
        self.assertEqual(utc, datetime(2026, 9, 28, 20, 14, 59, tzinfo=timezone.utc))
        self.assertEqual(clock.fmt(utc), "2026-09-28 13:14 PT")
        self.assertEqual(clock.local_to_utc("PT", datetime(2026, 12, 1, 10, 30)), datetime(2026, 12, 1, 18, 30, tzinfo=timezone.utc))

    def test_trading_calendar(self):
        self.assertTrue(clock.trading_day(date(2026, 10, 5)))
        self.assertFalse(clock.trading_day(date(2026, 10, 3)))    # Saturday
        self.assertFalse(clock.trading_day(date(2026, 11, 26)))   # Thanksgiving
        self.assertTrue(clock.trading_day(date(2026, 11, 11)))    # Veterans Day, market open

    def test_options_close_including_early_closes(self):
        self.assertEqual(clock.options_close(date(2026, 10, 5)), datetime(2026, 10, 5, 20, 15, tzinfo=timezone.utc))
        self.assertEqual(clock.options_close(date(2026, 11, 27)), datetime(2026, 11, 27, 18, 15, tzinfo=timezone.utc))

    def test_market_date_uses_eastern_time(self):
        # 6 PM Pacific on Monday is already Tuesday UTC but still Monday's session in Eastern time
        self.assertEqual(clock.market_date(datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc)), date(2026, 9, 28))


if __name__ == "__main__":
    unittest.main()
