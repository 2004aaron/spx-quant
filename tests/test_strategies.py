import unittest
from datetime import date

from spx_quant import clock
from spx_quant.data.cboe import fetch_chain, parse_chain
from spx_quant.strategies import BUILDERS, build, liquid
from tests.helpers import EOD, PARAMS, replay
from tests.test_feed import payload, row


class SyntheticBoardTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 23)
        board = date(2026, 11, 20)  # 58 DTE; a request for 60 must snap here
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
        self.assertEqual(len(liquid(rows, PARAMS)), 6)
        t = build("strangle", "_SPX", 6450.0, rows, self.today, PARAMS)
        self.assertEqual(t.dte, 58)
        self.assertEqual(sorted(l.strike for l in t.legs), [6000.0, 6900.0])
        self.assertAlmostEqual(t.credit, 3600.0)
        self.assertAlmostEqual(t.net_delta, 0.0)

    def test_no_liquid_strikes_means_no_candidate(self):
        for o in self.raw["data"]["options"]:
            o["open_interest"] = o["volume"] = 0
        _, rows = parse_chain(self.raw)
        self.assertIsNone(build("strangle", "_SPX", 6450.0, rows, self.today, PARAMS))


class RecordedBoardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain, _ = fetch_chain(replay(), "_SPX", 30, 1000)
        cls.xsp, _ = fetch_chain(replay(), "_XSP", 30, 1000)
        cls.today = clock.market_date(EOD)

    def build(self, name, chain=None):
        c = chain or self.chain
        return build(name, c.ticker, c.spot, c.rows, self.today, PARAMS)

    def test_every_builder_produces_a_single_root_single_expiry_position(self):
        for name in BUILDERS:
            p = self.build(name)
            self.assertIsNotNone(p, name)
            self.assertEqual(len({l.exp for l in p.legs}), 1)
            self.assertEqual(len({l.root for l in p.legs}), 1)
            self.assertTrue(PARAMS.expiry["dte_min"] <= p.dte <= PARAMS.expiry["dte_max"])
            self.assertGreater(p.credit, 0)
            lo, hi = p.credit_range
            self.assertLessEqual(lo, p.credit)
            self.assertLessEqual(p.credit, hi)

    def test_expiry_snaps_to_nearest_listed_and_prefers_close_settled(self):
        p = self.build("strangle")
        self.assertEqual((p.root, p.exp, p.dte), ("SPXW", date(2026, 11, 30), 63))   # 11/20 is 53 DTE, 11/30 is 63

    def test_strangle_is_delta_matched(self):
        p = self.build("strangle")
        put, call = sorted(p.legs, key=lambda l: l.right, reverse=True)
        self.assertLessEqual(abs(abs(put.delta) - abs(call.delta)), 0.02)
        self.assertLess(abs(p.net_delta), 30)   # SPY deltas on an SPX lot

    def test_put_vertical_wing_sits_below_the_short_put(self):
        v = self.build("put_vertical")
        by = {l.qty: l.strike for l in v.legs}
        self.assertLess(by[1], by[-1])
        self.assertTrue(v.defined_risk)
        self.assertEqual(v.width, max(l.strike for l in v.legs) - min(l.strike for l in v.legs))

    def test_xsp_delta_counts_one_tenth(self):
        spx, xsp = self.build("naked_put"), self.build("naked_put", self.xsp)
        self.assertAlmostEqual(xsp.net_delta * 10, spx.net_delta, delta=abs(spx.net_delta) * 0.02)
        self.assertAlmostEqual(xsp.credit * 10, spx.credit, delta=spx.credit * 0.05)


if __name__ == "__main__":
    unittest.main()
