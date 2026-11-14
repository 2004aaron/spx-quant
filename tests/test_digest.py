"""Monday outlook (issue #63): the two books, the two tables, one send per date."""
import contextlib
import io
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from spx_quant import clock, decisions, digest, mark, pipeline, store
from spx_quant.__main__ import main
from spx_quant.profile import save, validate
from tests.helpers import EOD, MARK_TIME, PARAMS, PatchedSource, memdb, pm150, replay
from tests.test_htmlmail import HtmlChannel

EMAIL = validate(150_000, "portfolio", 0.08, 2, "email", "me@example.com")
D28, D29, D30 = date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)


def pt(d, hh=13, mm=35):
    return clock.local_to_utc("PT", datetime(2026, 9, d, hh, mm))


def clone(conn, a, n, exp, worst, pnl=None, signal=None):
    """A second proposal in the log: the recorded one with another id, expiry and stated worst case."""
    row = {k: v for k, v in a.items() if k != "id"}
    row.update(alert_id=f"{a['alert_id']}-c{n}", legs=[dict(l, exp=exp) for l in a["legs"]], risk=dict(a["risk"], worst_case=worst))
    store.insert(conn, "alert", **row)
    if pnl is not None:
        store.insert(conn, "mark", alert_id=row["alert_id"], market_date=D28, ts=MARK_TIME, dte=30, spot=768.37, mid=0.0,
                     pnl=pnl, pnl_pct_credit=round(pnl / a["credit"], 4), settled=0, exit_signal=signal)
    return row["alert_id"]


class Failing:
    name, html = "fake", True

    def __init__(self):
        self.tries = 0

    def send(self, *message):
        self.tries += 1
        raise OSError("smtp down")


class BookTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.alert = pipeline.scan(self.conn, replay(), pm150(), PARAMS, "13:25", send=False).alert
        self.aid = self.alert["alert_id"]
        mark.run(self.conn, replay(MARK_TIME), PARAMS)
        self.put, self.call = (next(l for l in self.alert["legs"] if l["right"] == r) for r in "PC")

    def next_day(self, d, **mids):
        legs = {"put": self.put["sym"], "call": self.call["sym"]}
        mark.run(self.conn, PatchedSource(pt(d), quote_et=f"2026-09-{d}T16:14:59", mids={legs[k]: v for k, v in mids.items()}), PARAMS)

    def test_paper_book_holds_every_proposal_at_full_size(self):
        p, = digest.book(self.conn, D28, "paper")
        a = self.alert
        self.assertEqual((p.lots, p.entered, p.expires, p.dte, p.credit), (a["contracts"], "2026-09-28", "2026-11-30", 63, a["credit"]))
        self.assertEqual((p.pnl, p.pct, p.marked, p.closed), (0.0, 0.0, "2026-09-28", None))
        self.assertEqual((p.worst, p.bp), (a["risk"]["worst_case"], a["bp_total"]))
        self.assertAlmostEqual(p.away, min(768.37 - self.put["strike"], self.call["strike"] - 768.37) / 768.37)
        self.assertEqual((p.name, p.strikes), ("strangle XSP", "717P/811C"))

    def test_paper_book_closes_at_the_first_mark_that_flags_the_target(self):
        self.next_day(29, put=2.0, call=1.0)          # 300 to close against 817 collected: past the 50% target
        self.next_day(30, put=5.0, call=3.0)
        p, = digest.book(self.conn, D30, "paper")
        self.assertEqual((p.closed, p.how, p.pnl), ("2026-09-29", "profit target", 517.0))
        self.assertIn("0 open positions", digest.monday(self.conn, D30, "paper")[0])
        self.assertIsNone(digest.book(self.conn, D28, "paper")[0].closed)   # a digest for an earlier date ignores later marks

    def test_a_repeat_is_not_a_second_paper_position(self):
        store.insert(self.conn, "alert", **{k: v for k, v in self.alert.items() if k != "id"} | {"alert_id": "again", "repeat_of": self.aid})
        self.assertEqual(len(digest.book(self.conn, D28, "paper")), 1)

    def test_taken_book_is_what_the_investor_took_at_the_lots_taken(self):
        self.assertEqual(digest.book(self.conn, D28), [])
        decisions.record(self.conn, self.aid, "modified", EOD + timedelta(minutes=1), contracts=2)
        self.next_day(29, put=4.0, call=2.0)
        p, = digest.book(self.conn, D29)
        a = self.alert
        self.assertEqual((p.lots, p.credit, p.pnl), (2, 2 * a["credit"], 2 * 217.0))
        self.assertEqual((p.worst, p.bp), (round(2 * a["risk"]["worst_case"], 2), round(2 * a["bp_per_lot"], 2)))

    def test_taken_position_at_the_target_stays_open_until_closed_and_gets_a_pill(self):
        decisions.record(self.conn, self.aid, "accepted", EOD + timedelta(minutes=1))
        self.next_day(29, put=2.0, call=1.0)
        p, = digest.book(self.conn, D29)
        self.assertTrue(p.at_target and not p.closed)
        subject, text, html = digest.monday(self.conn, D29)
        self.assertIn("1 open position, unrealized +$517", subject)
        self.assertIn("strangle XSP [at target]", text)
        self.assertIn("AT\u00a0TARGET</span>", html)
        decisions.record(self.conn, self.aid, "closed", pt(30, 9))
        p, = digest.book(self.conn, D30)
        self.assertEqual((p.closed, p.how, p.pnl), ("2026-09-30", "closed by you", 517.0))
        self.assertIsNone(digest.book(self.conn, D29)[0].closed)

    def test_declined_is_not_in_the_taken_book_and_expiry_closes_a_taken_one(self):
        decisions.record(self.conn, self.aid, "declined", EOD + timedelta(minutes=1))
        self.assertEqual(digest.book(self.conn, D28), [])
        decisions.record(self.conn, self.aid, "accepted", EOD + timedelta(minutes=2))
        store.insert(self.conn, "mark", alert_id=self.aid, market_date="2026-11-30", ts=MARK_TIME, dte=0, spot=768.0, mid=0.0,
                     pnl=817.0, pnl_pct_credit=1.0, settled=1)
        p, = digest.book(self.conn, date(2026, 11, 30))
        self.assertEqual((p.closed, p.how, p.pnl), ("2026-11-30", "expired", 817.0))


class MondayTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.alert = a = pipeline.scan(self.conn, replay(), pm150(), PARAMS, "13:25", send=False).alert
        mark.run(self.conn, replay(MARK_TIME), PARAMS)
        self.ids = [clone(self.conn, a, n, f"2026-10-{n:02d}", -1000.0 * n, pnl=10.0 * n) for n in range(1, 12)]

    def test_four_numbers_and_two_tables_of_ten(self):
        subject, text, html = digest.monday(self.conn, D28, "paper")
        a = self.alert
        self.assertEqual(subject, "[StormGlass] Monday outlook 2026-09-28: 12 open positions, unrealized +$660")
        for s in ("Open positions       12 (5 expire within 7 days)", f"Credit open          ${12 * a['credit']:,.0f}",
                  "Unrealized P/L       +$660 (marks of Sep 28)", f"Buying power in use  ${12 * a['bp_total']:,.0f}",
                  "CLOSEST TO EXPIRY (10 OF 12)", "MOST AT RISK, BY STATED WORST CASE (10 OF 12)"):
            self.assertIn(s, text)
        soon, risky = text.split("CLOSEST TO EXPIRY")[1].split("MOST AT RISK")
        self.assertEqual([l.split()[6:8] for l in soon.splitlines()[2:12]], [["Oct", str(n)] for n in range(1, 11)])
        self.assertEqual([l.split()[6] for l in risky.splitlines()[2:12]], [f"-${n},000" for n in range(11, 3, -1)] + ["-$3,762", "-$3,000"])
        self.assertIn("Oct 1 (3d)", html)
        self.assertNotIn("Nov 30 (63d)", html.split("Most at risk")[0])    # the recorded one expires last: cut from the top 10
        self.assertEqual(html.count("entered Sep 28"), 20)

    def test_html_carries_the_same_numbers_with_inline_styles_only(self):
        _, text, html = digest.monday(self.conn, D28, "paper")
        for s in ("MONDAY OUTLOOK", "12 open positions", "+$660", "-$11,000", "$9,804", "never places orders", "digest-monday-2026-09-28"):
            self.assertIn(s, html)
        for banned in ("<style", "class=", "<script", "background:"):
            self.assertNotIn(banned, html)
        self.assertIn("never places orders", text)

    def test_same_log_and_date_give_the_same_email_and_later_rows_do_not_change_it(self):
        before = digest.monday(self.conn, D28, "paper")
        clone(self.conn, dict(self.alert, market_date="2026-09-29"), 99, "2026-10-01", -99000.0)
        decisions.record(self.conn, self.ids[0], "accepted", pt(29))
        self.assertEqual(before, digest.monday(self.conn, D28, "paper"))

    def test_an_empty_book_says_so(self):
        subject, text, html = digest.monday(self.conn, D28, "taken")
        self.assertEqual(subject, "[StormGlass] Monday outlook 2026-09-28: 0 open positions")
        for body in (text, html):
            self.assertIn("No open positions in this book.", body)


class SendTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        pipeline.scan(self.conn, replay(), pm150(), PARAMS, "13:25", send=False)
        self.msg = digest.monday(self.conn, D28, "paper")

    def events(self):
        return [(e["kind"], e["detail"]) for e in store.rows(self.conn, "SELECT kind, detail FROM event ORDER BY id")]

    def test_one_send_per_date_recorded_as_an_event(self):
        ch = HtmlChannel()
        self.assertEqual(digest.send(self.conn, EMAIL, PARAMS, "monday", D28, self.msg, ch), "sent")
        self.assertEqual(digest.send(self.conn, EMAIL, PARAMS, "monday", D28, self.msg, ch), "already_sent")
        self.assertEqual(ch.sent, [self.msg])
        self.assertEqual(self.events(), [("digest_monday", "2026-09-28")])
        self.assertEqual(digest.send(self.conn, EMAIL, PARAMS, "monday", D29, self.msg, ch), "sent")

    def test_a_failed_send_is_retried_flagged_and_can_run_again(self):
        ch = Failing()
        self.assertEqual(digest.send(self.conn, EMAIL, PARAMS, "monday", D28, self.msg, ch, sleep=lambda s: None), "failed")
        self.assertEqual(ch.tries, 3)
        self.assertEqual(self.events(), [("delivery_failed", "monday digest 2026-09-28: 3 attempts; last error OSError: smtp down")])
        self.assertEqual(digest.send(self.conn, EMAIL, PARAMS, "monday", D28, self.msg, HtmlChannel()), "sent")

    def test_no_email_channel_sends_nothing(self):
        self.assertEqual(digest.send(self.conn, pm150(), PARAMS, "monday", D28, self.msg), "no_channel")
        self.assertEqual(digest.send(self.conn, EMAIL, PARAMS, "monday", D28, self.msg), "failed")   # SMTP variables not set
        self.assertEqual([k for k, _ in self.events()], ["delivery_failed"])


class DigestCliTest(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--profile", str(self.profile), "--db", str(self.db), *args])
        return code, out.getvalue()

    def test_digest_monday_prints_writes_files_and_refuses_to_send_without_a_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.profile, self.db = Path(tmp) / "profile.json", Path(tmp) / "quant.db"
            save(pm150(), self.profile)
            conn = store.connect(self.db)
            pipeline.scan(conn, replay(), pm150(), PARAMS, "13:25", send=False)
            conn.close()
            code, out = self.run_cli("digest", "monday", "--date", "2026-09-28", "--book", "paper")
            self.assertEqual(code, 0)
            self.assertIn("STORMGLASS | MONDAY OUTLOOK | 2026-09-28 | paper book", out)
            txt, html = Path(tmp) / "m.txt", Path(tmp) / "m.html"
            code, out = self.run_cli("digest", "monday", "--date", "2026-09-28", "--book", "paper", "--out", str(txt), "--html", str(html))
            self.assertEqual((code, out.count("wrote ")), (0, 2))
            self.assertIn("1 open position", html.read_text(encoding="utf-8"))
            self.assertTrue(txt.read_text(encoding="utf-8").startswith("STORMGLASS | MONDAY OUTLOOK"))
            code, out = self.run_cli("digest", "monday", "--date", "2026-09-28", "--send")
            self.assertEqual(code, 1)
            self.assertIn("monday digest for 2026-09-28: no channel", out)


if __name__ == "__main__":
    unittest.main()
