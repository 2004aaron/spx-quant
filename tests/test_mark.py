"""Daily marking (US-09)."""
import unittest
from datetime import date, datetime

from spx_quant import clock, mark, pipeline, store
from tests.helpers import MARK_TIME, PARAMS, PatchedSource, TrendReplay, memdb, pm150_loose, replay


def pt(y, m, d, hh=13, mm=35):
    return clock.local_to_utc("PT", datetime(y, m, d, hh, mm))


class MarkTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.alert = pipeline.scan(self.conn, TrendReplay(), pm150_loose(), PARAMS, "13:25", send=False).alert
        self.assertEqual((self.alert["kind"], self.alert["strategy"]), ("proposal", "naked_put"))
        self.leg = self.alert["legs"][0]["sym"]
        self.exp = date.fromisoformat(self.alert["legs"][0]["exp"])

    def test_us09_ac1_daily_mark_as_if_opened(self):
        rows = mark.run(self.conn, replay(MARK_TIME), PARAMS)
        self.assertEqual(len(rows), 1)
        m = store.marks_for(self.conn, self.alert["alert_id"])[0]
        self.assertEqual((m["market_date"], m["settled"], m["dte"]), ("2026-09-28", 0, (self.exp - date(2026, 9, 28)).days))
        self.assertAlmostEqual(m["pnl"], 0.0, places=2)   # same quotes it was proposed on
        self.assertEqual(mark.run(self.conn, replay(MARK_TIME), PARAMS), [])   # once per day

    def test_exit_signal_is_recorded_but_marking_continues(self):
        src = PatchedSource(pt(2026, 9, 29), quote_et="2026-09-29T16:14:59", mids={self.leg: 2.0})
        m = mark.run(self.conn, src, PARAMS)[0]
        self.assertIn("profit target", m["exit_signal"])
        self.assertEqual(m["settled"], 0)
        self.assertEqual(len(store.open_proposals(self.conn)), 1)

    def test_profit_target_is_the_only_exit(self):
        m = PARAMS.management
        self.assertIsNone(mark.exit_signal(-900.0, 1000.0, m))   # a loss is never an exit signal
        self.assertIsNone(mark.exit_signal(499.0, 1000.0, m))
        self.assertIn("profit target", mark.exit_signal(500.0, 1000.0, m))

    def test_us09_ac2_settles_at_expiration(self):
        e = self.exp
        src = PatchedSource(pt(e.year, e.month, e.day), quote_et=f"{e.isoformat()}T16:14:59", spot=7000.0)
        m = mark.run(self.conn, src, PARAMS)[0]
        credit_lot = self.alert["credit_per_lot"]
        strike = self.alert["legs"][0]["strike"]
        expected = (credit_lot - max(0.0, strike - 700.0) * 100) * self.alert["contracts"]
        self.assertEqual(m["settled"], 1)
        self.assertAlmostEqual(m["pnl"], expected, places=2)
        self.assertIn("settled at intrinsic", m["basis"])
        self.assertEqual(store.open_proposals(self.conn), [])

    def test_missing_leg_quote_is_an_event_not_a_guess(self):
        src = PatchedSource(pt(2026, 9, 29), quote_et="2026-09-29T16:14:59", drop=(self.leg,))
        self.assertEqual(mark.run(self.conn, src, PARAMS), [])
        self.assertEqual(store.rows(self.conn, "SELECT kind FROM event")[0]["kind"], "mark_missing_quote")

    def test_late_mark_still_uses_that_days_closing_quotes(self):
        self.assertEqual(len(mark.run(self.conn, replay(pt(2026, 9, 28, 18, 0)), PARAMS)), 1)

    def test_yesterdays_board_skips_the_mark(self):
        src = PatchedSource(pt(2026, 9, 29), quote_et="2026-09-28T16:14:59")
        self.assertEqual(mark.run(self.conn, src, PARAMS), [])
        self.assertEqual(store.rows(self.conn, "SELECT kind FROM event")[0]["kind"], "mark_skipped")


if __name__ == "__main__":
    unittest.main()
