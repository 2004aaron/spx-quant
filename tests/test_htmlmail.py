"""HTML email bodies (US-07, US-11): same content as the plain text, laid out in tables."""
import unittest
from datetime import date, timedelta

from spx_quant import htmlmail as h, mark, outbox, pipeline, report
from spx_quant.profile import validate
from tests.helpers import EOD, MARK_TIME, PARAMS, PatchedSource, memdb, replay

GMAIL = validate(150_000, "portfolio", notify_channel="gmail", email_to="me@example.com")


def scan(conn, source):
    return pipeline.scan(conn, source, GMAIL, PARAMS, "13:25", sleep=lambda s: None).alert


class HtmlMailTest(unittest.TestCase):
    def test_escapes_text_but_keeps_raw_markup(self):
        self.assertEqual(h.e("<b>&"), "&lt;b&gt;&amp;")
        self.assertEqual(h.e(h.b("x<y")), "<strong>x&lt;y</strong>")
        self.assertIn("color:#cf222e", h.money(-5))
        self.assertEqual(h.money(1234.5), "$1,234")

    def test_proposal_html_carries_the_numbers_in_the_text(self):
        a = scan(memdb(), replay())
        html, text = a["html"], a["text"]
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertNotIn("<script", html.lower())
        self.assertEqual(html.lower().count("<style"), 1)          # one block, in the head
        self.assertLess(html.index("<style"), html.index("<body"))
        self.assertLess(len(html), 16_000)                           # small enough for the task to pass to Gmail
        for heading in ("At a glance", "The trade", "Account limits", "Market", "Ranking", "Your decision"):
            self.assertIn(heading, html)
        self.assertIn(a["alert_id"], html)
        for leg in a["legs"]:
            self.assertIn(leg["sym"], html)
            self.assertIn(leg["sym"], text)
        self.assertIn(f"${a['credit']:,.0f}", html)
        self.assertIn(f"${a['bp_total']:,.2f}", html)

    def test_stand_down_and_no_advice_list_the_reasons(self):
        sd = scan(memdb(), PatchedSource(EOD, curve={"VIX": 31.0, "VIX9D": 33.0, "VIX3M": 29.0, "VIX6M": 27.0}))
        self.assertEqual(sd["kind"], "stand_down")
        self.assertIn("STAND DOWN", sd["html"])
        na = scan(memdb(), replay(EOD + timedelta(hours=2)))
        self.assertIn("NO ADVICE", na["html"])
        for a in (sd, na):
            for r in a["reasons"]:
                self.assertIn(h.e(r), a["html"])

    def test_repeat_gets_a_no_change_html_body(self):
        conn = memdb()
        a = scan(conn, replay())
        outbox.record(conn, PARAMS, a["alert_id"], EOD + timedelta(minutes=1), ref="m1")
        b = scan(conn, replay(EOD + timedelta(minutes=2)))
        self.assertEqual(b["repeat_of"], a["alert_id"])
        self.assertIn("NO CHANGE", b["html"])
        self.assertIn(a["alert_id"], b["html"])

    def test_outbox_hands_the_task_both_bodies(self):
        conn = memdb()
        a = scan(conn, replay())
        msg = outbox.pending(conn, PARAMS)[0]
        self.assertEqual(msg["body"], a["text"])
        self.assertEqual(msg["html"], a["html"])

    def test_weekly_html_matches_the_text_report(self):
        conn = memdb()
        a = scan(conn, replay())
        outbox.record(conn, PARAMS, a["alert_id"], EOD + timedelta(minutes=1), ref="m1")
        mark.run(conn, replay(MARK_TIME), PARAMS)
        end = date(2026, 10, 2)
        html, text = report.weekly_html(conn, PARAMS, end), report.weekly(conn, PARAMS, end)
        self.assertEqual(html, report.weekly_html(conn, PARAMS, end))
        w = report.week(conn, PARAMS, end)
        pnl = f"${abs(w.adv_pnl):,.0f}"
        self.assertIn(pnl, text)
        self.assertIn(pnl, html)
        self.assertIn(a["alert_id"], html)
        for heading in ("Summary", "Positions", "Worst case predicted vs realized", "Failures and anomalies"):
            self.assertIn(heading, html)
        self.assertIn("missed scan", html)


if __name__ == "__main__":
    unittest.main()
