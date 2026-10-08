import unittest
from datetime import date, datetime, timedelta, timezone

from spx_quant import clock
from spx_quant.data.cboe import ReplaySource, fetch_chain, fetch_curve, parse_chain, probe_payload, quote_time
from tests.helpers import EOD, REPLAY, replay

NOW = datetime(2026, 10, 5, 17, 30, tzinfo=timezone.utc)   # 10:30 PT


def et(dt_utc):
    return clock.to_local("ET", dt_utc).replace(tzinfo=None).isoformat(timespec="seconds")


def row(exp, right, strike, bid, ask, delta, oi=500, vol=100, iv=0.18):
    return {"option": f"SPXW{exp:%y%m%d}{right}{int(strike * 1000):08d}", "bid": bid, "ask": ask, "iv": iv,
            "delta": delta, "open_interest": oi, "volume": vol}


def payload(quote_age_min=15, options=None, cdn_ts=NOW):
    return {"timestamp": cdn_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "data": {"current_price": 6500.0, "last_trade_time": et(NOW - timedelta(minutes=quote_age_min)),
                     "options": options or [row(date(2026, 11, 20), "P", 6000, 20.0, 21.0, -0.16),
                                            row(date(2026, 11, 20), "C", 6900, 15.0, 16.0, 0.16)]}}


class ProbeTest(unittest.TestCase):
    def test_us06_ac1_healthy_payload_passes(self):
        res = probe_payload(payload(), 30, now=NOW)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.strikes, 2)
        self.assertAlmostEqual(res.quote_age_min, 15.0)

    def test_us06_ac2_stale_by_one_minute_fails(self):
        res = probe_payload(payload(quote_age_min=31), 30, now=NOW)
        self.assertFalse(res.ok)
        self.assertEqual(res.kind, "stale_data")
        self.assertTrue(any("31 min old" in f for f in res.failures), res)

    def test_us06_ac2_missing_field_fails(self):
        bad = payload()
        for o in bad["data"]["options"]:
            del o["iv"]
        res = probe_payload(bad, 30, now=NOW)
        self.assertFalse(res.ok)
        self.assertEqual(res.kind, "feed_failure")
        self.assertTrue(any("field 'iv' missing at path data.options[0]" in f for f in res.failures), res)

    def test_us06_ac3_exactly_thirty_minutes_passes(self):
        self.assertTrue(probe_payload(payload(quote_age_min=30), 30, now=NOW).ok)

    def test_fresh_cdn_timestamp_does_not_hide_old_quotes(self):
        # the CDN rebuilds the file constantly; three hours after the close its timestamp is still "now"
        res = probe_payload(payload(quote_age_min=180, cdn_ts=NOW), 30, now=NOW)
        self.assertFalse(res.ok)

    def test_size_check(self):
        res = probe_payload(payload(), 30, now=NOW, min_rows=1000)
        self.assertFalse(res.ok)
        self.assertTrue(any("expected at least 1000" in f for f in res.failures))

    def test_missing_options_fails(self):
        self.assertFalse(probe_payload({"data": {}}, 30, now=NOW).ok)

    def test_quote_time_is_eastern_wall_time(self):
        raw = {"data": {"last_trade_time": "2026-09-28T16:14:59"}}
        self.assertEqual(quote_time(raw), datetime(2026, 9, 28, 20, 14, 59, tzinfo=timezone.utc))


class ReplayTest(unittest.TestCase):
    def test_recorded_close_is_fresh_ten_minutes_later(self):
        chain, res = fetch_chain(replay(), "_SPX", 30, 1000)
        self.assertTrue(res.ok, res)
        self.assertAlmostEqual(chain.spot, 7683.69, places=2)
        self.assertLess(res.quote_age_min, 11)

    def test_replay_at_recording_time_is_stale(self):
        chain, res = fetch_chain(ReplaySource(REPLAY), "_SPX", 30, 1000)   # recorded 23:27 UTC, 3 hours after close
        self.assertIsNone(chain)
        self.assertEqual(res.kind, "stale_data")

    def test_curve(self):
        curve, stale = fetch_curve(replay(), 30)
        self.assertEqual(stale, [])
        self.assertEqual(curve.values, {"vix9d": 14.39, "vix": 16.07, "vix3m": 18.23, "vix6m": 20.25})
        self.assertEqual(clock.fmt(curve.asof), "2026-09-28 13:15 PT")

    def test_stale_required_curve_point_is_reported(self):
        _, stale = fetch_curve(replay(EOD + timedelta(minutes=40)), 30)
        self.assertTrue(any("VIX is" in s for s in stale), stale)

    def test_parse_chain_keeps_roots_apart(self):
        _, rows = parse_chain(replay().chain_payload("_SPX"))
        self.assertEqual({r["root"] for r in rows}, {"SPX", "SPXW"})


if __name__ == "__main__":
    unittest.main()


class RetryTest(unittest.TestCase):
    def test_rate_limits_are_retried_then_succeed(self):
        import io
        import urllib.error
        from unittest import mock
        from spx_quant.data import cboe
        calls, waits = [], []

        def fake(req, timeout=None, context=None):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return io.BytesIO(b'{"data": {"current_price": 16.2}}')
        with mock.patch("urllib.request.urlopen", fake), mock.patch.object(cboe, "_sleep", waits.append):
            self.assertEqual(cboe.fetch_json("https://x/quotes/_VIX.json")["data"]["current_price"], 16.2)
        self.assertEqual((len(calls), waits), (3, [2, 5]))

    def test_gives_up_after_three_retries_and_does_not_retry_a_404(self):
        import urllib.error
        from unittest import mock
        from spx_quant.data import cboe
        waits = []

        def always(code):
            def f(req, timeout=None, context=None):
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
            return f
        with mock.patch("urllib.request.urlopen", always(429)), mock.patch.object(cboe, "_sleep", waits.append):
            with self.assertRaises(urllib.error.HTTPError):
                cboe.fetch_json("https://x")
        self.assertEqual(waits, [2, 5, 10])
        waits.clear()
        with mock.patch("urllib.request.urlopen", always(404)), mock.patch.object(cboe, "_sleep", waits.append):
            with self.assertRaises(urllib.error.HTTPError):
                cboe.fetch_json("https://x")
        self.assertEqual(waits, [])
