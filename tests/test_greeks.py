import unittest

from spx_quant.greeks import bs, implied_vol


class GreeksTest(unittest.TestCase):
    def test_put_call_parity(self):
        c = bs(6500, 6500, 45 / 365, 0.15, "C").price
        p = bs(6500, 6500, 45 / 365, 0.15, "P").price
        self.assertAlmostEqual(c - p, 0.0, places=6)

    def test_atm_delta_near_half(self):
        self.assertAlmostEqual(bs(6500, 6500, 45 / 365, 0.15, "C").delta, 0.51, delta=0.02)
        self.assertAlmostEqual(bs(6500, 6500, 45 / 365, 0.15, "P").delta, -0.49, delta=0.02)

    def test_otm_put_delta_and_theta_sign(self):
        g = bs(6500, 6000, 45 / 365, 0.18, "P")
        self.assertTrue(-0.25 < g.delta < 0)
        self.assertLess(g.theta, 0)
        self.assertGreater(g.vega, 0)

    def test_implied_vol_round_trip(self):
        price = bs(6500, 6200, 45 / 365, 0.22, "P").price
        self.assertAlmostEqual(implied_vol(price, 6500, 6200, 45 / 365, "P"), 0.22, places=4)

    def test_implied_vol_rejects_arbitrage(self):
        self.assertIsNone(implied_vol(-1.0, 6500, 6200, 45 / 365, "P"))

    def test_bad_right(self):
        with self.assertRaises(ValueError):
            bs(100, 100, 0.1, 0.2, "X")


if __name__ == "__main__":
    unittest.main()
