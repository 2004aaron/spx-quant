"""Decisions (US-10) and sizing against remaining buying power (US-13)."""
import unittest
from datetime import timedelta

from spx_quant import decisions, pipeline, store
from spx_quant.decisions import DecisionError, Held
from spx_quant.engine import run_scan
from spx_quant.profile import validate
from spx_quant.sizing import size
from spx_quant.synthetic import SyntheticSource
from tests.helpers import EOD, MARK_TIME, PARAMS, memdb, pm150, replay


class DecisionTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.aid = pipeline.scan(self.conn, replay(), pm150(), PARAMS, "13:25", send=False).alert["alert_id"]

    def test_us10_ac1_feedback_is_stored_with_the_alert(self):
        self.assertEqual(decisions.record(self.conn, self.aid, "declined", EOD, "too close to the FOMC"), "recorded")
        h = decisions.history(self.conn, self.aid)
        self.assertEqual((h[0]["decision"], h[0]["reason"], h[0]["source"]), ("declined", "too close to the FOMC", "cli"))

    def test_us10_ac2_unknown_identifier_is_rejected_and_nothing_stored(self):
        with self.assertRaises(DecisionError):
            decisions.record(self.conn, "2026-01-01-2026-02-13", "accepted", EOD)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)

    def test_stand_downs_cannot_be_accepted(self):
        conn = memdb()
        sd = pipeline.scan(conn, SyntheticSource(35.0, "contango"), pm150(), PARAMS, send=False).alert
        with self.assertRaises(DecisionError):
            decisions.record(conn, sd["alert_id"], "accepted", EOD)

    def test_modified_needs_a_size_and_closed_needs_a_taken_position(self):
        with self.assertRaises(DecisionError):
            decisions.record(self.conn, self.aid, "modified", EOD)
        with self.assertRaises(DecisionError):
            decisions.record(self.conn, self.aid, "closed", EOD)
        decisions.record(self.conn, self.aid, "modified", EOD, contracts=2)
        self.assertEqual(decisions.record(self.conn, self.aid, "closed", EOD + timedelta(days=3)), "recorded")
        self.assertEqual(decisions.latest(self.conn, self.aid)["decision"], "closed")

    def test_an_email_reply_is_recorded_once(self):
        d, n = decisions.parse_reply("Modified 3 - only had room for three")
        self.assertEqual((d, n), ("modified", 3))
        self.assertEqual(decisions.record(self.conn, self.aid, d, EOD, "x", n, "email", ref="gmail-1"), "recorded")
        self.assertEqual(decisions.record(self.conn, self.aid, d, EOD, "x", n, "email", ref="gmail-1"), "duplicate")
        self.assertIsNone(decisions.parse_reply("sounds good"))

    def test_held_positions_count_at_the_size_taken_until_closed_or_settled(self):
        decisions.record(self.conn, self.aid, "modified", EOD, contracts=2)
        a = store.get_alert(self.conn, self.aid)
        self.assertEqual(decisions.held(self.conn, EOD + timedelta(hours=1)), [Held(self.aid, 2, round(a["bp_per_lot"] * 2, 2))])
        self.assertEqual(decisions.held(self.conn, EOD - timedelta(hours=1)), [])
        decisions.record(self.conn, self.aid, "closed", EOD + timedelta(days=1))
        self.assertEqual(decisions.held(self.conn, EOD + timedelta(days=2)), [])


class RemainingBuyingPowerTest(unittest.TestCase):
    """US-13 acceptance criteria, with the proposal's own numbers."""

    def setUp(self):
        self.prof = validate(150_000, "portfolio", 0.08, 2)     # $12,000 cap allows 3 x $3,300

    def test_us13_ac2_sized_down_for_remaining_buying_power(self):
        s = size(self.prof, 3_300.00, 0.0, 100.0, available=9_000.00)
        self.assertEqual((s.bp_contracts, s.contracts, s.bp_total, s.limited_by), (3, 2, 6_600.00, "remaining buying power"))

    def test_us13_ac3_exactly_enough_is_allowed(self):
        self.assertEqual(size(self.prof, 3_300.00, 0.0, 100.0, available=3_300.00).contracts, 1)

    def test_us13_ac4_nothing_fits_gives_the_reason(self):
        s = size(self.prof, 3_300.00, 0.0, 100.0, available=2_000.00)
        self.assertFalse(s.ok)
        self.assertEqual(s.reasons, ["insufficient buying power: $2,000 available, $3,300 needed"])

    def test_us13_ac1_open_positions_reduce_what_is_available(self):
        held = [Held("2026-10-01-2026-11-13", 4, 60_000.00), Held("2026-10-05-2026-11-20", 2, 40_000.00)]
        res = run_scan(replay(), pm150(), PARAMS, EOD, held=held)
        note = next(n for n in res.notes if n.startswith("remaining buying power"))
        self.assertIn("$50,000 of $150,000 net liq after 2 open positions", note)
        self.assertIn("2026-10-01-2026-11-13 x4 ($60,000)", note)
        self.assertEqual(res.outcome, "proposal")

    def test_engine_stands_down_when_nothing_fits_what_is_left(self):
        res = run_scan(replay(), pm150(), PARAMS, EOD, held=[Held("x", 30, 148_000.00)])
        self.assertEqual(res.outcome, "stand_down")
        self.assertTrue(res.reasons[0].startswith("insufficient buying power: $2,000 available, $"), res.reasons)

    def test_pipeline_uses_decisions_on_file(self):
        conn = memdb()
        first = pipeline.scan(conn, replay(), pm150(), PARAMS, "13:25", send=False).alert
        decisions.record(conn, first["alert_id"], "accepted", EOD + timedelta(seconds=30))
        second = pipeline.scan(conn, replay(MARK_TIME), pm150(), PARAMS, "13:25", send=False)
        self.assertTrue(any(n.startswith("remaining buying power") for n in second.result.notes))


if __name__ == "__main__":
    unittest.main()
