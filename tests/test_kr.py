"""Key-result scripts (A-KR1, A-KR2, B-KR1 to B-KR3) run against small logs."""
import copy
import unittest
from datetime import date, datetime

from spx_quant import clock, kr, pipeline
from spx_quant.profile import validate
from spx_quant.synthetic import SyntheticSource
from tests.helpers import PARAMS, PatchedSource, memdb, pm150, replay
from tests.test_notify import FakeChannel

PROFILE = validate(150_000, "portfolio", 0.08, 2, "email", "me@example.com")


def run_day(conn, day, channel, vix=35.0):
    for slot in PARAMS.schedule["slots"]:
        hh, mm = (int(x) for x in slot.split(":"))
        now = clock.local_to_utc("PT", datetime(day.year, day.month, day.day, hh, mm))
        pipeline.scan(conn, SyntheticSource(vix, "flat", now=now), PROFILE, PARAMS, slot, channel=channel,
                      sleep=lambda s: None)


class AlphaKRTest(unittest.TestCase):
    def test_a_kr1_counts_days_with_both_scans_complete(self):
        conn = memdb()
        run_day(conn, date(2026, 10, 5), FakeChannel())
        run_day(conn, date(2026, 10, 6), FakeChannel())
        text, ok = kr.a1(conn, PARAMS, date(2026, 10, 5), date(2026, 10, 6))
        self.assertTrue(ok, text)
        self.assertIn("2 of 2 trading days qualify", text)
        text, ok = kr.a1(conn, PARAMS, date(2026, 10, 5), date(2026, 10, 7))
        self.assertFalse(ok)
        self.assertIn("2 of 3", text)

    def test_a_kr2_real_proposal_passes_and_every_planted_row_is_caught(self):
        conn = memdb()
        pipeline.scan(conn, replay(), pm150(), PARAMS, "10:30", send=False)
        text, ok = kr.a2(conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28), plant=True)
        self.assertIn("0 of 1 proposals fail a check", text)
        self.assertIn("8 of 8 planted rows caught", text)
        self.assertFalse(ok)   # fewer than the 10 proposals the target needs
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0], 1)   # real log untouched

    def test_a_kr2_end_of_day_proposal_waits_for_the_next_morning(self):
        conn = memdb()
        pipeline.scan(conn, replay(), pm150(), PARAMS, "13:25", send=False)
        text, _ = kr.a2(conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28))
        self.assertIn("1 pending", text)


class NextMorningTest(unittest.TestCase):
    def test_friday_xsp_proposal_is_requoted_on_a_monday_stand_down_morning(self):
        conn = memdb()
        fri = PatchedSource(clock.local_to_utc("PT", datetime(2026, 10, 2, 13, 25)), quote_et="2026-10-02T16:14:59")
        xsp_only = copy.deepcopy(PARAMS)
        xsp_only.sections["feed"]["tickers"] = ["_XSP"]
        a = pipeline.scan(conn, fri, pm150(), xsp_only, "13:25", send=False).alert
        self.assertEqual((a["kind"], a["ticker"]), ("proposal", "_XSP"))
        mon = PatchedSource(clock.local_to_utc("PT", datetime(2026, 10, 5, 10, 30)), quote_et="2026-10-05T13:15:00",
                            curve={"VIX": 35.0, "VIX3M": 33.0})
        rec = pipeline.scan(conn, mon, pm150(), PARAMS, "10:30", send=False)
        self.assertEqual(rec.result.outcome, "stand_down")   # the engine never needed the XSP board
        text, _ = kr.a2(conn, PARAMS, date(2026, 10, 2), date(2026, 10, 2))
        self.assertIn("0 of 1 proposals fail a check**; 0 pending", text)


class BetaKRTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = memdb()
        ch = FakeChannel()
        run_day(cls.conn, date(2026, 10, 30), ch, vix=35.0)
        run_day(cls.conn, date(2026, 11, 2), ch, vix=12.0)

    def test_b_kr1_on_time(self):
        text, ok = kr.b1(self.conn, PARAMS, date(2026, 10, 30), date(2026, 11, 2))
        self.assertIn("100%", text)
        self.assertTrue(ok)

    def test_b_kr2_every_scheduled_scan_sends_something(self):
        text, ok = kr.b2(self.conn, PARAMS, date(2026, 10, 30), date(2026, 11, 2))
        self.assertIn("4 of 4 scheduled scans sent a message", text)
        self.assertTrue(ok)

    def test_b_kr2_suppress_policy_would_miss_repeats(self):
        conn, p = memdb(), copy.deepcopy(PARAMS)
        p.sections["notify"]["repeat_policy"] = "suppress"
        for slot in p.schedule["slots"]:
            hh, mm = (int(x) for x in slot.split(":"))
            now = clock.local_to_utc("PT", datetime(2026, 10, 30, hh, mm))
            pipeline.scan(conn, SyntheticSource(35.0, "flat", now=now), PROFILE, p, slot, channel=FakeChannel(),
                          sleep=lambda s: None)
        text, ok = kr.b2(conn, p, date(2026, 10, 30), date(2026, 10, 30))
        self.assertIn("1 of 2 scheduled scans sent a message", text)
        self.assertFalse(ok)

    def test_b_kr3_short_no_change_messages_still_carry_quotes_and_timestamps(self):
        text, ok = kr.b3(self.conn, PARAMS, date(2026, 10, 30), date(2026, 11, 2))
        self.assertTrue(ok, text)
        self.assertIn("4 of 4 complete", text)


if __name__ == "__main__":
    unittest.main()
