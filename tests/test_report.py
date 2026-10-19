"""Weekly report (US-11, US-12) and the RC / stretch key-result scripts."""
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from spx_quant import clock, decisions, kr, mark, outbox, pipeline, report, store
from spx_quant.profile import validate
from tests.helpers import EOD, MARK_TIME, PARAMS, PatchedSource, memdb, pm150, replay

GMAIL = validate(150_000, "portfolio", notify_channel="gmail", email_to="me@example.com")


def pt(y, m, d, hh=13, mm=35):
    return clock.local_to_utc("PT", datetime(y, m, d, hh, mm))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.alert = pipeline.scan(self.conn, replay(), GMAIL, PARAMS, "13:25", sleep=lambda s: None).alert
        self.aid = self.alert["alert_id"]
        outbox.record(self.conn, PARAMS, self.aid, EOD + timedelta(minutes=1), ref="m1")
        mark.run(self.conn, replay(MARK_TIME), PARAMS)
        put = next(l["sym"] for l in self.alert["legs"] if l["right"] == "P")
        mark.run(self.conn, PatchedSource(pt(2026, 9, 29), quote_et="2026-09-29T16:14:59", mids={put: 45.0}), PARAMS)

    def test_us11_ac1_same_log_same_report_and_later_rows_do_not_change_it(self):
        a = report.weekly(self.conn, PARAMS, date(2026, 9, 29))
        self.assertEqual(a, report.weekly(self.conn, PARAMS, date(2026, 9, 29)))
        mark.run(self.conn, PatchedSource(pt(2026, 9, 30), quote_et="2026-09-30T16:14:59"), PARAMS)
        decisions.record(self.conn, self.aid, "declined", pt(2026, 9, 30))
        self.assertEqual(a, report.weekly(self.conn, PARAMS, date(2026, 9, 29)))
        self.assertIn(self.aid, a)
        self.assertIn("Advisor book (every proposal, followed in full): 1 position", a)

    def test_us11_ac3_worst_case_predicted_against_realized(self):
        p = report.positions(self.conn, date(2026, 9, 29))[0]
        self.assertLess(p.worst_mark, p.predicted)
        self.assertTrue(p.hit)
        self.assertIn("1 of 1 marked positions reached their stated worst case", report.weekly(self.conn, PARAMS, date(2026, 9, 29)))

    def test_your_book_scales_to_the_size_taken(self):
        decisions.record(self.conn, self.aid, "modified", EOD + timedelta(minutes=5), contracts=3)
        p = report.positions(self.conn, date(2026, 9, 29))[0]
        self.assertEqual(p.taken, 3)
        self.assertAlmostEqual(p.user_pnl, p.pnl * 3, places=2)
        self.assertTrue(p.active)
        text = report.weekly(self.conn, PARAMS, date(2026, 9, 29))
        self.assertIn("Your book (proposals you took): 1 position", text)
        self.assertIn("modified x3", text)

    def test_us11_ac2_quiet_week_still_tracks_open_positions(self):
        text = report.weekly(self.conn, PARAMS, date(2026, 10, 9))
        self.assertIn("0 scans", text)
        self.assertIn(self.aid, text)

    def test_us12_ac1_failures_listed_with_time_type_and_reason(self):
        pipeline.scan(self.conn, replay(EOD + timedelta(hours=2)), GMAIL, PARAMS, "13:25", sleep=lambda s: None)
        text = report.weekly(self.conn, PARAMS, date(2026, 9, 28), days=1)
        self.assertIn("| stale data |", text)
        self.assertIn("| missed scan | no 10:30 scan was logged for 2026-09-28", text)
        self.assertIn("| not delivered |", text)

    def test_us12_ac2_clean_week_says_so(self):
        conn = memdb()
        for d in range(28, 33):
            day = date(2026, 9, d) if d <= 30 else date(2026, 10, d - 30)
            for slot in ("10:30", "13:25"):
                store.insert(conn, "scan", slot=slot, outcome="stand_down", market_date=day.isoformat())
        text = report.weekly(conn, PARAMS, date(2026, 10, 2), days=5)
        self.assertIn("No anomalies this week: all 10 scheduled scans ran", text)


class RcKrTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.alert = pipeline.scan(self.conn, replay(), GMAIL, PARAMS, "13:25", sleep=lambda s: None).alert
        self.aid = self.alert["alert_id"]
        outbox.record(self.conn, PARAMS, self.aid, EOD + timedelta(minutes=1), ref="m1")
        mark.run(self.conn, replay(MARK_TIME), PARAMS)

    def test_rc1_needs_twenty_marked_proposals(self):
        text, ok = kr.rc1(self.conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28))
        self.assertIn("**0 of 1 marked proposals (0%)**", text)
        self.assertFalse(ok)

    def test_rc3_counts_missing_decisions_and_checks_the_report_agrees(self):
        text, ok = kr.rc3(self.conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28))
        self.assertIn("**1 missing decisions, 0 mismatches", text)
        self.assertTrue(ok)        # at most 1 missing is allowed
        decisions.record(self.conn, self.aid, "accepted", EOD + timedelta(minutes=3), source="email", ref="r1")
        text, ok = kr.rc3(self.conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28))
        self.assertIn("**0 missing decisions, 0 mismatches", text)

    def test_rc2_compares_engine_marks_with_broker_marks(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "marks.csv"
            f.write_text(f"alert_id,market_date,broker_pnl\n{self.aid},2026-09-28,-20\n")
            text, ok = kr.rc2(self.conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28), str(f))
        self.assertIn("mean error 2.8% over 1 comparisons", text)
        self.assertTrue(ok)
        self.assertFalse(kr.rc2(self.conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28), None)[1])

    def test_s1_flags_a_proposal_over_remaining_buying_power(self):
        decisions.record(self.conn, self.aid, "modified", EOD + timedelta(minutes=2), contracts=24)
        row = dict(store.get_alert(self.conn, self.aid))
        for k in ("id", "alert_id", "created_ts", "repeat_of"):
            row.pop(k)
        store.insert(self.conn, "alert", alert_id="planted-over", created_ts=EOD + timedelta(hours=1), **row)
        text, ok = kr.s1(self.conn, PARAMS, date(2026, 9, 28), date(2026, 9, 28))
        self.assertIn("| planted-over |", text)
        self.assertIn("OVER", text)
        self.assertIn("**1 of 2 proposals over**", text)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
