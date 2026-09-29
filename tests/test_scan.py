"""End-to-end scans: engine, alert text, and the log (US-02 to US-06, US-08)."""
import sqlite3
import unittest
from datetime import date, datetime

from spx_quant import clock, pipeline, store
from spx_quant.engine import run_scan
from spx_quant.profile import validate
from spx_quant.synthetic import SyntheticSource
from tests.helpers import EOD, PARAMS, memdb, params_without, pm150, replay


class ProposalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = memdb()
        cls.rec = pipeline.scan(cls.conn, replay(), pm150(), PARAMS, slot="13:25", send=False)
        cls.alert = cls.rec.alert

    def test_us03_ac1_recorded_contango_session_gives_a_full_proposal(self):
        r = self.rec.result
        self.assertEqual((r.regime.state, r.regime.bucket), ("contango", "normal"))
        self.assertAlmostEqual(r.curve["vix"], 16.07)
        a = self.alert
        self.assertEqual(a["kind"], "proposal")
        for k in ("legs", "contracts", "credit", "credit_per_lot", "bp_per_lot", "bp_total", "delta_per_lot",
                  "theta_per_lot", "risk", "data_ts", "created_ts", "quotes", "strategy", "ticker"):
            self.assertIsNotNone(a[k], k)
        self.assertGreater(a["contracts"], 0)
        self.assertNotIn("n/a", a["text"])

    def test_us01_ac1_proposal_respects_the_profile(self):
        a = self.alert
        self.assertLessEqual(a["bp_total"], 12_000)
        self.assertLessEqual(abs(a["delta_per_lot"]) * 2, a["theta_per_lot"])
        self.assertEqual(a["profile"]["net_liq"], 150_000)

    def test_worst_case_limit_cuts_the_size(self):
        a = self.alert
        s = next(c["sized"] for c in a["candidates"] if c["strategy"] == a["strategy"] and c["ticker"] == a["ticker"])
        self.assertEqual((s["bp_contracts"], s["contracts"], s["limited_by"]), (5, 3, "worst case"))
        self.assertLessEqual(-a["risk"]["worst_case"], 15_000 + 0.03)
        self.assertIn("Sized down from 5 to 3 lots so the worst case stays inside the limit", a["text"])
        self.assertIn("Worst-case limit: $", a["text"])

    def test_us03_ac2_ranked_by_annual_return_on_bp_and_runner_up_shown(self):
        ranked = self.rec.result.ranked
        self.assertGreaterEqual(len(ranked), 2)
        rets = [c.risk.ann_return_bp for c in ranked]
        self.assertEqual(rets, sorted(rets, reverse=True))
        text = self.alert["text"]
        self.assertIn("RANKING", text)
        self.assertIn("  2. ", text)
        self.assertIn("Ranked first because it has the highest expected annual return on buying power", text)

    def test_us05_ac1_ac2_risk_block_labeled_with_units_and_assumptions(self):
        text = self.alert["text"]
        for label in ("Probability of profit: ", "%", "Expected value: $", "Worst case (stress: index -10%, volatility +10 points)",
                      "of net liquidation", "(CVaR 5%): ", "(CVaR 1%): ", "Breakevens at expiration: ", "ASSUMPTIONS",
                      "held to expiration"):
            self.assertIn(label, text)

    def test_b_kr3_quotes_and_both_timestamps_in_the_message(self):
        text = self.alert["text"]
        self.assertIn("Output: 2026-09-28 13:25 PT", text)
        self.assertIn("Data as of: 2026-09-28 13:14 PT", text)
        for s in ("SPX 7,683.69", "VIX9D 14.39", "VIX 16.07", "VIX3M 18.23"):
            self.assertIn(s, text)
        for leg in self.alert["legs"]:
            line = next(l for l in text.splitlines() if leg["sym"] in l)
            self.assertIn(f"bid {leg['bid']:.2f}", line)
            self.assertIn(f"ask {leg['ask']:.2f}", line)

    def test_us08_ac1_one_complete_row_per_scan(self):
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0], 1)
        scan = store.rows(self.conn, "SELECT * FROM scan")[0]
        self.assertEqual((scan["outcome"], scan["slot"], scan["alert_id"]), ("proposal", "13:25", self.alert["alert_id"]))
        self.assertAlmostEqual(scan["quote_age_min"], 10.0, delta=0.5)
        self.assertEqual(len(self.alert["candidates"]), len(self.rec.result.ranked) + len(self.rec.result.rejected))


class StandDownTest(unittest.TestCase):
    def scan(self, source, profile=None, params=PARAMS):
        conn = memdb()
        return conn, pipeline.scan(conn, source, profile or pm150(), params, slot="10:30", send=False)

    def test_us04_ac1_ac3_panic_stands_down_and_is_logged(self):
        conn, rec = self.scan(SyntheticSource(35.0, "flat"))
        self.assertEqual(rec.result.outcome, "stand_down")
        self.assertIn("VIX 35.0 above the 28 ceiling", rec.alert["text"])
        a = rec.alert
        self.assertEqual(a["kind"], "stand_down")
        self.assertIsNotNone(a["created_ts"])
        self.assertEqual(a["regime"]["bucket"], "panic")
        self.assertTrue(a["reasons"])

    def test_us04_ac2_crushed_stands_down(self):
        _, rec = self.scan(SyntheticSource(12.0, "contango"))
        self.assertIn("VIX 12.0 below the 13 floor", rec.alert["reasons"][0])

    def test_us02_ac3_missing_vix3m_is_named_in_the_output(self):
        _, rec = self.scan(SyntheticSource(17.0, missing=("VIX3M",)))
        self.assertEqual(rec.result.outcome, "stand_down")
        self.assertIn("regime could not be identified: VIX3M missing", rec.alert["text"])

    def test_us03_ac3_nothing_fits_says_so(self):
        _, rec = self.scan(replay(EOD), validate(25_000, "reg_t", 0.01, 2))
        self.assertEqual(rec.result.outcome, "stand_down")
        self.assertIn("no proposal could be sized for this account", rec.alert["reasons"][0])
        self.assertEqual(rec.result.codes, ["no_fit"])

    def test_tight_worst_case_limit_means_nothing_fits(self):
        _, rec = self.scan(replay(EOD), validate(150_000, "portfolio", 0.08, 2, max_worst_case_pct=0.001))
        self.assertEqual(rec.result.codes, ["no_fit"])
        self.assertIn("worst case at most $150", rec.alert["reasons"][0])

    def test_us06_ac2_stale_data_gives_no_advice(self):
        conn, rec = self.scan(SyntheticSource(17.0, age_minutes=31))
        self.assertEqual(rec.result.outcome, "stale_data")
        self.assertEqual(rec.alert["kind"], "no_advice")
        self.assertIsNone(rec.alert["legs"])
        self.assertEqual(store.rows(conn, "SELECT kind FROM event")[0]["kind"], "stale_data")

    def test_us06_ac3_exactly_thirty_minutes_still_advises(self):
        _, rec = self.scan(SyntheticSource(17.5, age_minutes=30))
        self.assertIn(rec.result.outcome, ("proposal", "stand_down"))

    def test_us05_ac3_missing_assumption_blocks_the_risk_block(self):
        _, rec = self.scan(replay(EOD), params=params_without("risk", "crash_prob_annual"))
        self.assertEqual((rec.result.outcome, rec.alert["kind"]), ("error", "no_advice"))
        self.assertIn("risk.crash_prob_annual", rec.alert["text"])

    def test_market_closed_logs_a_scan_but_no_alert(self):
        sat = clock.local_to_utc("PT", datetime(2026, 10, 3, 10, 30))
        conn, rec = self.scan(SyntheticSource(17.0, now=sat))
        self.assertIsNone(rec.alert)
        self.assertEqual(store.rows(conn, "SELECT outcome FROM scan")[0]["outcome"], "market_closed")

    def test_feed_failure_is_logged(self):
        class Down(SyntheticSource):
            def chain_payload(self, ticker):
                raise TimeoutError("timed out")
        conn, rec = self.scan(Down(17.0))
        self.assertEqual(rec.result.outcome, "feed_failure")
        self.assertIn("timed out", rec.alert["text"])


class LogTest(unittest.TestCase):
    def test_us08_ac2_query_by_date_in_order(self):
        conn = memdb()
        for day, vix in ((5, 35.0), (6, 12.0), (7, 36.0), (8, 11.0)):
            now = clock.local_to_utc("PT", datetime(2026, 10, day, 10, 30))
            pipeline.scan(conn, SyntheticSource(vix, "flat", now=now), pm150(), PARAMS, "10:30", send=False)
        got = store.alerts_between(conn, date(2026, 10, 6), date(2026, 10, 7))
        self.assertEqual([a["market_date"] for a in got], ["2026-10-06", "2026-10-07"])
        self.assertEqual(len(store.alerts_between(conn, date(2026, 10, 1), date(2026, 10, 31))), 4)

    def test_log_is_append_only(self):
        conn = memdb()
        pipeline.scan(conn, SyntheticSource(35.0, "flat"), pm150(), PARAMS, "10:30", send=False)
        for sql in ("UPDATE alert SET kind = 'proposal'", "DELETE FROM alert", "DELETE FROM scan", "UPDATE scan SET outcome='x'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                conn.execute(sql)

    def test_same_slot_twice_gets_distinct_ids(self):
        conn = memdb()
        a = pipeline.scan(conn, SyntheticSource(35.0, "flat"), pm150(), PARAMS, "10:30", send=False).alert
        b = pipeline.scan(conn, SyntheticSource(35.0, "flat"), pm150(), PARAMS, "10:30", send=False).alert
        self.assertNotEqual(a["alert_id"], b["alert_id"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])

    def test_late_run_is_flagged(self):
        conn = memdb()
        noon = clock.local_to_utc("PT", datetime(2026, 10, 7, 12, 0))
        rec = pipeline.scan(conn, SyntheticSource(35.0, "flat", now=noon), pm150(), PARAMS, "10:30", send=False)
        self.assertIn("late run: started 2026-10-07 12:00 PT, 90 min after the 10:30 slot", rec.alert["text"])
        self.assertEqual(store.rows(conn, "SELECT kind FROM event")[0]["kind"], "scan_late")

    def test_engine_is_deterministic(self):
        a = run_scan(replay(EOD), pm150(), PARAMS)
        b = run_scan(replay(EOD), pm150(), PARAMS)
        self.assertEqual([c.as_dict() for c in a.ranked], [c.as_dict() for c in b.ranked])


if __name__ == "__main__":
    unittest.main()
