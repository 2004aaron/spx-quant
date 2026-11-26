import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from spx_quant.data import cboe, tastytrade
from spx_quant.params import load_params

NOW = datetime(2026, 11, 23, 18, 30, tzinfo=timezone.utc)   # Monday 10:30 PT


def occ(root, d, right, k):
    return f"{root:<6}{d:%y%m%d}{right}{int(k * 1000):08d}"


def fake_get(path, query=None):
    today = NOW.date()
    if path.startswith("/option-chains/"):
        exps = [today + timedelta(days=n) for n in (10, 46, 59, 66, 90)]
        strikes = [{"strike-price": str(k), "call": occ("SPXW", d, "C", k), "put": occ("SPXW", d, "P", k)}
                   for d in exps for k in range(5000, 8501, 50)]
        return {"data": {"items": [{"root-symbol": "SPXW", "expirations": [
            {"expiration-date": d.isoformat(), "strikes": [s for s in strikes if s["call"][6:12] == f"{d:%y%m%d}"]}
            for d in exps]}]}}
    kind, syms = next(iter(query.items()))
    ts = (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    if kind == "index":
        return {"data": {"items": [{"symbol": s, "last": "7000" if s == "SPX" else "18", "updated-at": ts}
                                   for s in syms.split(",")]}}
    items = []
    for s in syms.split(","):
        k = int(s[-8:]) / 1000
        otm = max((k - 7000) if s[12] == "C" else (7000 - k), 0)
        px = max(150 - otm * 0.12, 0.5)
        items.append({"symbol": s, "bid": f"{px - 0.2:.2f}", "ask": f"{px + 0.2:.2f}",
                      "open-interest": "500", "volume": "50", "updated-at": ts})
    return {"data": {"items": items}}


class TastytradeSourceTest(unittest.TestCase):
    def setUp(self):
        self.src = tastytrade.TastytradeSource(load_params())
        self.src._get = fake_get
        self.src.now = lambda: NOW

    def test_chain_probes_and_parses_like_cboe(self):
        held = occ("SPXW", NOW.date() + timedelta(days=10), "P", 6500).replace(" ", "")
        self.src.want([held])
        chain, probe = cboe.fetch_chain(self.src, "_SPX", 30, 200, NOW)
        self.assertTrue(probe.ok, probe)
        exps = {r["exp"] for r in chain.rows}
        self.assertEqual(len(exps), 3)                       # two nearest 60 DTE plus the held one
        self.assertIn(held, {r["sym"] for r in chain.rows})
        put = min((r for r in chain.rows if r["right"] == "P" and r["exp"] == NOW.date() + timedelta(days=59)),
                  key=lambda r: abs(r["strike"] - 6500))
        self.assertGreater(put["iv"], 0)
        self.assertTrue(-1 < put["delta"] < 0)
        self.assertTrue(all(5600 <= r["strike"] <= 7840 for r in chain.rows if r["sym"] != held))

    def test_curve(self):
        curve, stale = cboe.fetch_curve(self.src, 30, NOW)
        self.assertEqual(stale, [])
        self.assertEqual(curve.values["vix"], 18.0)

    def test_available_needs_both_secrets(self):
        with mock.patch.dict(os.environ, {"TASTYTRADE_CLIENT_SECRET": "x"}, clear=True):
            self.assertFalse(tastytrade.available())
        with mock.patch.dict(os.environ, {"TASTYTRADE_CLIENT_SECRET": "x", "TASTYTRADE_REFRESH_TOKEN": "y"}):
            self.assertTrue(tastytrade.available())


if __name__ == "__main__":
    unittest.main()
