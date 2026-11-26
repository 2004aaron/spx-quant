"""Cboe volatility-index method on an SPX board (spx_quant.data.vixcalc)."""
import unittest
from datetime import date, datetime, timedelta, timezone

from spx_quant.data import vixcalc
from spx_quant.greeks import bs
from spx_quant.strategies import years_to

NOW = datetime(2026, 11, 23, 18, 30, tzinfo=timezone.utc)


def board(vol, days, spot=7000.0, rate=0.04, skew=0.0, root="SPXW"):
    rows = []
    for d in days:
        exp = (NOW + timedelta(days=d)).date()
        t = years_to(root, exp, NOW)
        for k in range(3000, 11001, 5):
            v = vol + skew * (spot - k) / spot
            for right in "CP":
                px = bs(spot, k, t, max(v, 0.05), right, rate).price
                rows.append({"root": root, "exp": exp, "right": right, "strike": float(k),
                             "bid": round(max(px - 0.05, 0), 2), "ask": round(px + 0.05, 2)})
    return rows


class VixCalcTest(unittest.TestCase):
    def test_flat_vol_comes_back(self):
        for near, far, target in ((25, 39, 30), (88, 102, 93)):   # Fridays, from a Monday NOW
            v, info = vixcalc.index(board(0.20, (near, far)), NOW, 0.04, target)
            self.assertAlmostEqual(v, 20.0, delta=0.4, msg=info)

    def test_skew_raises_the_index_above_atm_vol(self):
        flat, _ = vixcalc.index(board(0.18, (81, 109)), NOW, 0.04, 93)
        skewed, _ = vixcalc.index(board(0.18, (81, 109), skew=0.4), NOW, 0.04, 93)
        self.assertGreater(skewed, flat + 0.5)

    def test_bracket_uses_fridays_and_the_standard_series(self):
        third = date(2027, 2, 19)            # a third Friday: SPX (AM) and SPXW (PM) both list it
        rows = [{"root": "SPX", "exp": third}, {"root": "SPXW", "exp": third},
                {"root": "SPXW", "exp": date(2027, 3, 1)},   # a Monday: not used
                {"root": "SPXW", "exp": date(2027, 3, 5)}]
        (r1, e1, _), (r2, e2, _) = vixcalc.bracket(rows, NOW, 93)
        self.assertEqual((r1, e1, r2, e2), ("SPX", third, "SPXW", date(2027, 3, 5)))
        with self.assertRaises(ValueError):
            vixcalc.bracket(board(0.2, (60, 80)), NOW, 93)

    def test_forward_and_k0(self):
        _, info = vixcalc.index(board(0.2, (81, 109)), NOW, 0.04, 93)
        self.assertLessEqual(info["near_k0"], info["near_forward"])
        self.assertGreater(info["near_forward"], 7000)   # carry at 4%


if __name__ == "__main__":
    unittest.main()
