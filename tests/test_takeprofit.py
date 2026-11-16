"""Take-profit by GTC order: the 30-minute check, the end-of-day question, the answers, the presumed close."""
import contextlib
import io
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from spx_quant import clock, decisions, digest, pipeline, store, takeprofit as tp
from spx_quant.__main__ import main
from tests.helpers import EOD, PARAMS, PatchedSource, memdb, pm150, replay

D28 = date(2026, 9, 28)


def pt(d, hh, mm=0, month=9):
    return clock.local_to_utc("PT", datetime(2026, month, d, hh, mm))


class TakeProfitTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.alert = pipeline.scan(self.conn, replay(), pm150(), PARAMS, "13:25", send=False).alert
        self.aid = self.alert["alert_id"]
        self.legs = {l["right"]: l["sym"] for l in self.alert["legs"]}
        self.limit = tp.limit_price(self.alert)

    def take(self, **kw):
        decisions.record(self.conn, self.aid, "accepted", EOD + timedelta(minutes=1), **kw)

    def at(self, d, hh, mm=0, put=1.0, call=1.0, month=9):
        """A check at that time with the put and call mids given (bid/ask a dime apart)."""
        when = pt(d, hh, mm, month)
        et = clock.to_local("ET", when - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
        src = PatchedSource(when, quote_et=et, mids={self.legs["P"]: put, self.legs["C"]: call})
        return tp.check(self.conn, src, PARAMS)

    def test_limit_is_half_the_credit_rounded_down_to_a_nickel(self):
        self.assertEqual(tp.limit_price({"credit_per_lot": 715.0}), 3.55)
        self.assertEqual(tp.limit_price({"credit_per_lot": 715.0}, fill=7.30), 3.65)
        self.assertEqual(tp.limit_price({"credit_per_lot": 700.0}), 3.50)

    def test_close_cost_buys_shorts_at_the_ask_and_sells_longs_at_the_bid(self):
        legs = [{"sym": "A", "qty": -1}, {"sym": "B", "qty": 1}]
        board = {"A": {"bid": 2.0, "ask": 2.2}, "B": {"bid": 0.5, "ask": 0.7}}
        self.assertEqual(tp.close_cost(legs, board), 1.7)
        self.assertIsNone(tp.close_cost(legs, {"A": {"bid": 0, "ask": 0}, "B": board["B"]}))

    def test_only_taken_positions_are_checked(self):
        self.assertEqual(self.at(29, 9), [])
        self.take()
        row, = self.at(29, 9, put=3.0, call=2.0)
        self.assertEqual((row["cost"], row["limit_price"], row["hit"]), (5.1, self.limit, 0))

    def test_a_touch_is_asked_about_at_the_end_of_the_day(self):
        self.take()
        self.at(29, 9, put=3.0, call=2.0)
        self.at(29, 11, 30, put=2.0, call=1.0)          # 3.10 to close, under the limit
        self.at(29, 12, put=3.0, call=2.0)              # bounced back before the close
        t, = tp.pending(self.conn, pt(29, 14))
        self.assertTrue(t.today)
        self.assertEqual((t.low["cost"], t.limit, t.lots), (3.1, self.limit, self.alert["contracts"]))
        subject, text, html = digest.eod(self.conn, date(2026, 9, 29), reply_to="me@example.com")
        self.assertIn("1 take-profit hit today", subject)
        self.assertIn("HIT YOUR TAKE-PROFIT TODAY", text)
        self.assertIn(f"mailto:me@example.com?subject=Re%3A%20%5BStormGlass%20{self.aid}%5D&amp;body=FILLED", html)
        self.assertIn("body=NOT%20FILLED", html)
        self.assertIn("11:15 AM PT", html)              # the quote time, 15 minutes before the check

    def test_filled_closes_at_the_limit_and_books_that_pnl(self):
        self.take()
        self.at(29, 11, put=2.0, call=1.0)
        self.assertEqual(tp.answer(self.conn, self.aid, "FILLED", pt(29, 14), ref="m1"), "recorded")
        self.assertEqual(tp.answer(self.conn, self.aid, "FILLED", pt(29, 14), ref="m1"), "duplicate")
        d = decisions.latest(self.conn, self.aid)
        self.assertEqual((d["decision"], d["price"]), ("closed", self.limit))
        self.assertEqual(tp.pending(self.conn, pt(29, 15)), [])
        p, = digest.book(self.conn, date(2026, 9, 29))
        self.assertEqual((p.closed, p.how), ("2026-09-29", "take-profit order"))
        self.assertEqual(p.pnl, round((self.alert["credit_per_lot"] - self.limit * 100) * self.alert["contracts"], 2))

    def test_not_filled_waits_for_the_next_touch(self):
        self.take()
        self.at(29, 11, put=2.0, call=1.0)
        self.assertEqual(tp.answer(self.conn, self.aid, "Not filled", pt(29, 14), ref="m2"), "recorded")
        self.assertEqual(tp.pending(self.conn, pt(29, 15)), [])
        self.assertEqual(decisions.latest(self.conn, self.aid)["decision"], "accepted")
        self.at(30, 10, put=2.0, call=1.0)
        self.assertEqual(len(tp.pending(self.conn, pt(30, 14))), 1)
        with self.assertRaises(decisions.DecisionError):
            tp.answer(memdb(), self.aid, "not filled", pt(30, 14))

    def test_an_unanswered_touch_is_closed_after_three_trading_days(self):
        self.take()
        self.at(30, 11, put=2.0, call=1.0)              # Wednesday
        t, = tp.pending(self.conn, pt(30, 14))
        self.assertEqual(t.presume_on(), date(2026, 10, 5))   # Thu, Fri, Mon
        self.assertEqual(tp.presume(self.conn, pt(2, 14, month=10)), [])
        self.assertEqual(tp.presume(self.conn, pt(5, 14, month=10)), [self.aid])
        d = decisions.latest(self.conn, self.aid)
        self.assertEqual((d["decision"], d["source"], d["price"]), ("closed", "presumed", self.limit))

    def test_the_fill_price_moves_the_limit(self):
        self.take(price=8.50)
        row, = self.at(29, 9, put=2.0, call=2.0)
        self.assertEqual((row["limit_price"], row["hit"]), (4.25, 1))

    def test_the_end_of_day_scan_asks_first(self):
        self.take()
        self.at(29, 11, put=2.0, call=1.0)
        src = PatchedSource(pt(29, 13, 25), quote_et="2026-09-29T16:14:59")
        a = pipeline.scan(self.conn, src, pm150(), PARAMS, "13:25", send=False).alert
        self.assertIn("1 take-profit to confirm", a["subject"])
        self.assertTrue(a["text"].startswith("STORMGLASS |"))
        self.assertIn("TAKE-PROFIT: DID IT FILL?", a["text"])
        self.assertLess(a["html"].index("Did your take-profit fill?"), a["html"].index("font-size:22px"))
        morning = pipeline.scan(self.conn, PatchedSource(pt(29, 10, 30), quote_et="2026-09-29T13:20:00"), pm150(), PARAMS,
                                "10:30", send=False).alert
        self.assertNotIn("take-profit", morning["subject"])

    def test_friday_close_lists_the_weeks_exits(self):
        self.take()
        self.at(29, 11, put=2.0, call=1.0)
        tp.answer(self.conn, self.aid, "FILLED", pt(29, 14))
        subject, text, html = digest.friday(self.conn, date(2026, 10, 2))
        profit = round((self.alert["credit_per_lot"] - self.limit * 100) * self.alert["contracts"])
        self.assertIn(f"1 closed, +${profit:,}", subject)
        self.assertIn("Take-profit order filled Tue Sep 29", html)
        self.assertIn("CLOSED THIS WEEK", text)
        self.assertIn("nothing closed", digest.friday(self.conn, date(2026, 10, 9))[0])

    def test_nothing_to_send_when_nothing_is_taken(self):
        self.assertIsNone(digest.eod(self.conn, date(2026, 9, 29)))

    def test_replies_go_through_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, prof = Path(tmp) / "q.db", Path(tmp) / "p.json"
            conn = store.connect(db)
            for t in ("alert",):
                for r in store.rows(self.conn, f"SELECT * FROM {t}"):
                    store.insert(conn, t, **{k: v for k, v in r.items() if k != "id"})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["--db", str(db), "--profile", str(prof), "reply", self.aid, "ACCEPTED @ 7.40", "--ref", "r1"])
                main(["--db", str(db), "--profile", str(prof), "reply", self.aid, "NOT FILLED", "--ref", "r2"])
            self.assertEqual(decisions.fill_price(conn, self.aid), 7.4)
            self.assertIn("no take-profit touch", out.getvalue())


if __name__ == "__main__":
    unittest.main()
