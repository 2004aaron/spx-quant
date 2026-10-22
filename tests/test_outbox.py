"""Gmail route (US-07): queue in the log, send outside, record the result."""
import sqlite3
import unittest
from datetime import timedelta

from spx_quant import kr, outbox, pipeline, store
from spx_quant.profile import validate
from tests.helpers import EOD, PARAMS, memdb, replay

GMAIL = validate(150_000, "portfolio", notify_channel="gmail", email_to="me@example.com")


def scan(conn):
    return pipeline.scan(conn, replay(), GMAIL, PARAMS, "13:25", sleep=lambda s: None)


class OutboxTest(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        self.rec = scan(self.conn)
        self.aid = self.rec.alert["alert_id"]

    def test_scan_queues_instead_of_sending(self):
        self.assertEqual(self.rec.delivery, "queued")
        box = outbox.pending(self.conn, PARAMS)
        self.assertEqual([m["alert_id"] for m in box], [self.aid])
        self.assertEqual(box[0]["to"], "me@example.com")
        self.assertIn("PROPOSAL", box[0]["subject"])
        self.assertIn("reply with ACCEPTED, DECLINED or MODIFIED", box[0]["body"])

    def test_delivered_leaves_the_outbox_and_counts_for_b_kr1(self):
        self.assertEqual(outbox.record(self.conn, PARAMS, self.aid, EOD + timedelta(minutes=2), ref="m1"), "delivered")
        self.assertEqual(outbox.pending(self.conn, PARAMS), [])
        text, _ = kr.b1(self.conn, PARAMS, EOD.date(), EOD.date())
        self.assertIn("**1 of 1 on time (100%)**", text)
        with self.assertRaises(outbox.OutboxError):
            outbox.record(self.conn, PARAMS, self.aid, EOD + timedelta(minutes=3))

    def test_next_identical_scan_is_a_short_no_change_note(self):
        outbox.record(self.conn, PARAMS, self.aid, EOD + timedelta(minutes=1), ref="m1")
        again = scan(self.conn)
        self.assertIn("NO CHANGE", again.alert["subject"])
        self.assertEqual(again.alert["repeat_of"], self.aid)

    def test_three_failures_give_up_and_raise_an_event(self):
        for i, want in enumerate(("failed", "failed", "gave_up"), 1):
            self.assertEqual(outbox.record(self.conn, PARAMS, self.aid, EOD + timedelta(minutes=i), error="429 rate limited"), want)
        self.assertEqual(outbox.pending(self.conn, PARAMS), [])
        ev = store.rows(self.conn, "SELECT kind, detail FROM event WHERE kind = 'delivery_failed'")
        self.assertIn("3 attempts", ev[0]["detail"])

    def test_late_delivery_is_flagged(self):
        outbox.record(self.conn, PARAMS, self.aid, EOD + timedelta(minutes=45), ref="m1")
        self.assertEqual(len(store.rows(self.conn, "SELECT 1 FROM event WHERE kind = 'delivery_late'")), 1)

    def test_unknown_or_unqueued_alerts_are_rejected(self):
        with self.assertRaises(outbox.OutboxError):
            outbox.record(self.conn, PARAMS, "no-such-alert", EOD)
        conn = memdb()
        rec = pipeline.scan(conn, replay(), validate(150_000, "portfolio"), PARAMS, "13:25")
        with self.assertRaises(outbox.OutboxError):
            outbox.record(conn, PARAMS, rec.alert["alert_id"], EOD)


class MigrationTest(unittest.TestCase):
    def test_a_log_from_an_older_version_gains_the_new_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id TEXT NOT NULL, "
                     "received_ts TEXT, decision TEXT, reason TEXT)")
        conn.execute("INSERT INTO feedback (alert_id, decision) VALUES ('old', 'declined')")
        conn.commit()
        from spx_quant import store as s
        orig = s.sqlite3.connect
        s.sqlite3.connect = lambda *_a, **_k: conn
        try:
            c = s.connect(":memory:")
        finally:
            s.sqlite3.connect = orig
        cols = {r[1] for r in c.execute("PRAGMA table_info(feedback)")}
        self.assertTrue({"contracts", "source", "ref"} <= cols)
        self.assertEqual(c.execute("SELECT decision FROM feedback").fetchone()[0], "declined")


if __name__ == "__main__":
    unittest.main()
