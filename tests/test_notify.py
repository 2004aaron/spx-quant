"""Delivery (US-07): latency, no repeats, retry and failure records."""
import copy
import os
import unittest
from datetime import timedelta
from unittest import mock

from spx_quant import notify, pipeline, store
from spx_quant.profile import validate
from spx_quant.synthetic import SyntheticSource
from tests.helpers import PARAMS, memdb, replay


class FakeChannel:
    name = "fake"

    def __init__(self, fail_times=0):
        self.sent, self.fail_times = [], fail_times

    def send(self, subject, body):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("smtp down")
        self.sent.append((subject, body))


PROFILE = validate(150_000, "portfolio", 0.08, 2, "email", "me@example.com")


def scan(conn, channel, vix=35.0, params=PARAMS):
    return pipeline.scan(conn, SyntheticSource(vix, "flat"), PROFILE, params, "10:30", send=True, channel=channel,
                         sleep=lambda s: None)


class DeliveryTest(unittest.TestCase):
    def test_us07_ac1_delivered_and_timed(self):
        conn, ch = memdb(), FakeChannel()
        rec = scan(conn, ch)
        self.assertEqual(rec.delivery, "delivered")
        subject, body = ch.sent[0]
        self.assertIn(rec.alert["alert_id"], subject)
        d = store.rows(conn, "SELECT * FROM delivery")[0]
        s = store.rows(conn, "SELECT * FROM scan")[0]
        self.assertEqual(d["status"], "delivered")
        self.assertLessEqual(d["delivered_ts"], (store._enc(rec.result.now + timedelta(minutes=20))))
        self.assertGreaterEqual(d["delivered_ts"], s["finished_ts"])

    def test_us07_ac2_unchanged_scan_sends_a_short_no_change_note_not_the_full_alert(self):
        conn, ch = memdb(), FakeChannel()
        first = scan(conn, ch)
        second = scan(conn, ch)
        self.assertEqual(second.delivery, "delivered")
        subject, body = ch.sent[1]
        self.assertIn("NO CHANGE: still stand down", subject)
        self.assertIn(f"NO CHANGE since {first.alert['alert_id']}", body)
        self.assertEqual(second.alert["repeat_of"], first.alert["alert_id"])
        self.assertEqual(second.alert["text"], body)   # the log holds exactly what was sent
        third = scan(conn, ch, vix=12.0)   # conditions changed: full alert again
        self.assertNotIn("NO CHANGE", ch.sent[2][0])

    def test_latency_is_measured_on_a_moving_clock(self):
        class Ticking(SyntheticSource):
            def __init__(self, step_min, *a, **k):
                super().__init__(*a, **k)
                self.base, self.step, self.calls = self._now, step_min, 0

            def now(self):
                self.calls += 1
                return self.base + timedelta(minutes=self.step * self.calls)

        from spx_quant import kr
        from datetime import date
        conn = memdb()
        pipeline.scan(conn, Ticking(3, 35.0, "flat"), PROFILE, PARAMS, "10:30", channel=FakeChannel(), sleep=lambda s: None)
        text, ok = kr.b1(conn, PARAMS, date(2026, 10, 7), date(2026, 10, 7))
        self.assertIn("| 6.00 | no |", text)   # two ticks between scan completion and delivery
        self.assertFalse(ok)

    def test_suppress_policy_sends_nothing_for_a_repeat(self):
        p = copy.deepcopy(PARAMS)
        p.sections["notify"]["repeat_policy"] = "suppress"
        conn, ch = memdb(), FakeChannel()
        scan(conn, ch, params=p)
        self.assertEqual(scan(conn, ch, params=p).delivery, "suppressed_repeat")
        self.assertEqual(len(ch.sent), 1)

    def test_no_change_note_for_a_proposal_keeps_the_legs_and_quotes(self):
        conn, ch = memdb(), FakeChannel()
        for _ in range(2):
            pipeline.scan(conn, replay(), PROFILE, PARAMS, "13:25", channel=ch, sleep=lambda s: None)
        subject, body = ch.sent[1]
        self.assertIn("still stands", subject)
        self.assertLess(len(body), len(ch.sent[0][1]) / 2)
        for s in ("Data as of: ", "VIX3M 18.23", "bid 4.24", "ask 4.49", "worst case -$"):
            self.assertIn(s, body)

    def test_us07_ac3_retried_then_delivered(self):
        conn, ch = memdb(), FakeChannel(fail_times=2)
        rec = scan(conn, ch)
        self.assertEqual(rec.delivery, "delivered")
        statuses = [d["status"] for d in store.rows(conn, "SELECT status FROM delivery ORDER BY id")]
        self.assertEqual(statuses, ["failed", "failed", "delivered"])

    def test_us07_ac3_final_failure_is_flagged(self):
        conn, ch = memdb(), FakeChannel(fail_times=99)
        rec = scan(conn, ch)
        self.assertEqual(rec.delivery, "failed")
        self.assertEqual(len(store.rows(conn, "SELECT * FROM delivery WHERE status='failed'")), 3)
        ev = store.rows(conn, "SELECT * FROM event WHERE kind='delivery_failed'")
        self.assertEqual(len(ev), 1)
        self.assertIn("smtp down", ev[0]["detail"])

    def test_missing_credentials_are_a_recorded_failure(self):
        conn = memdb()
        rec = pipeline.scan(conn, SyntheticSource(35.0, "flat"), PROFILE, PARAMS, "10:30", send=False)
        with mock.patch.dict(os.environ, {}, clear=True):
            status = notify.deliver(conn, rec.alert, rec.result.now, PROFILE, PARAMS, now=lambda: rec.result.now)
        self.assertEqual(status, "failed")   # no SPX_QUANT_SMTP_* variables in the test environment
        self.assertIn("SPX_QUANT_SMTP_HOST", store.rows(conn, "SELECT detail FROM event")[0]["detail"])

    def test_no_channel_configured(self):
        conn = memdb()
        rec = pipeline.scan(conn, SyntheticSource(35.0, "flat"), validate(150_000, "portfolio"), PARAMS, "10:30")
        self.assertEqual(rec.delivery, "no_channel")

    def test_discord_chunks_fit_the_limit(self):
        body = "\n".join(f"line {i} " + "x" * 80 for i in range(100))
        chunks = notify.DiscordChannel.chunks("[SPX Quant X] PROPOSAL: something", body)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 2000 for c in chunks))
        self.assertTrue(chunks[0].startswith("**[SPX Quant X]"))

    def test_email_channel_reads_the_environment(self):
        env = {"SPX_QUANT_SMTP_HOST": "smtp.example.com", "SPX_QUANT_SMTP_USER": "u", "SPX_QUANT_SMTP_PASSWORD": "p"}
        ch = notify.channel_for(PROFILE, env)
        self.assertEqual((ch.host, ch.port, ch.sender, ch.to), ("smtp.example.com", 587, "u", "me@example.com"))


if __name__ == "__main__":
    unittest.main()
