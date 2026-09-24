import copy
import unittest
from datetime import date, datetime, timedelta, timezone

from spx_quant.data.cboe import parse_chain, probe_payload
from spx_quant.params import load_params
from spx_quant.strategies import liquid, pick_strangle

NOW = datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc)


def occ(exp: date, right: str, strike: float) -> str:
    return f"SPXW{exp:%y%m%d}{right}{int(strike * 1000):08d}"


def row(exp, right, strike, bid, ask, delta, oi=500, vol=100, iv=0.18):
    return {"option": occ(exp, right, strike), "bid": bid, "ask": ask, "iv": iv, "delta": delta,
            "open_interest": oi, "volume": vol}


def payload(asof=NOW, options=None):
    return {"timestamp": asof.isoformat(), "data": {"current_price": 6500.0, "options": options or [
        row(date(2026, 11, 6), "P", 6000, 20.0, 21.0, -0.16),
        row(date(2026, 11, 6), "C", 6900, 15.0, 16.0, 0.16),
    ]}}


class ProbeTest(unittest.TestCase):
    def test_healthy_payload_passes(self):
        res = probe_payload(payload(), 30, now=NOW)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.strikes, 2)

    def test_shape_drift_fails_loudly(self):
        bad = payload()
        for o in bad["data"]["options"]:
            del o["iv"]
        res = probe_payload(bad, 30, now=NOW)
        self.assertFalse(res.ok)
        self.assertTrue(any("field 'iv' missing at path data.options[0]" in f for f in res.failures), res)

    def test_stale_data_fails(self):
        res = probe_payload(payload(asof=NOW - timedelta(minutes=45)), 30, now=NOW)
        self.assertFalse(res.ok)
        self.assertTrue(any("45 min old" in f for f in res.failures), res)

    def test_missing_options_fails(self):
        res = probe_payload({"data": {}}, 30, now=NOW)
        self.assertFalse(res.ok)


class StrangleTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 23)
        self.params = load_params()
        board = date(2026, 11, 6)  # 44 DTE; a request for 45 must snap here
        self.raw = payload(options=[
            row(board, "P", 6000, 20.0, 21.0, -0.16),
            row(board, "P", 6050, 24.0, 25.0, -0.19),
            row(board, "P", 5975, 18.0, 19.0, -0.15, oi=0, vol=0),   # thin odd strike: must be filtered first
            row(board, "C", 6900, 15.0, 16.0, 0.16),
            row(board, "C", 6950, 11.0, 12.0, 0.12),
            row(date(2026, 10, 2), "P", 6300, 10.0, 11.0, -0.16),     # 9 DTE, outside window
            row(date(2026, 10, 2), "C", 6700, 8.0, 9.0, 0.16),
        ])

    def test_liquidity_prefilter_then_delta_match(self):
        _, rows = parse_chain(self.raw)
        self.assertEqual(len(liquid(rows, self.params)), 6)
        t = pick_strangle(rows, self.today, self.params)
        self.assertIsNotNone(t)
        self.assertEqual(t.dte, 44)
        self.assertEqual((t.put["strike"], t.call["strike"]), (6000.0, 6900.0))
        self.assertLessEqual(abs(abs(t.put["delta"]) - abs(t.call["delta"])), 0.02)
        self.assertAlmostEqual(t.credit, 3600.0)
        self.assertAlmostEqual(t.net_delta, 0.0)

    def test_no_liquid_strikes_means_no_proposal(self):
        raw = copy.deepcopy(self.raw)
        for o in raw["data"]["options"]:
            o["open_interest"] = o["volume"] = 0
        _, rows = parse_chain(raw)
        self.assertIsNone(pick_strangle(rows, self.today, self.params))


class ParamsTest(unittest.TestCase):
    def test_every_parameter_is_tagged(self):
        p = load_params()
        self.assertIn("validated", p.summary())
        self.assertEqual(p.provenance["strangle.target_dte"]["tag"], "validated")


if __name__ == "__main__":
    unittest.main()
