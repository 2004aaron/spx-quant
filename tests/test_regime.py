import itertools
import unittest

from spx_quant.regime import classify, gate


class RegimeTest(unittest.TestCase):
    def test_contango_normal(self):
        r = classify({"vix9d": 15.6, "vix": 16.5, "vix3m": 18.9, "vix6m": 19.6})
        self.assertEqual((r.state, r.bucket), ("contango", "normal"))
        self.assertAlmostEqual(r.slope, 0.1455, places=3)
        self.assertIn("VIX3M=18.90", str(r))

    def test_backwardation(self):
        r = classify({"vix9d": 34.0, "vix": 30.1, "vix3m": 26.4})
        self.assertEqual(r.state, "backwardation")
        self.assertEqual(r.bucket, "panic")
        self.assertAlmostEqual(r.slope, -0.1229, places=3)

    def test_missing_input_is_unknown_not_a_guess(self):
        r = classify({"vix9d": 15.6, "vix": 16.5, "vix3m": None})
        self.assertEqual(r.state, "unknown")
        self.assertFalse(r.known)
        self.assertEqual(str(r), "regime: unknown (VIX3M missing)")
        ok, reasons = gate(r)
        self.assertFalse(ok)

    def test_gate_sweep(self):
        curves = {
            "contango": (15.0, 16.0, 18.0),
            "flat": (16.0, 16.0, 16.2),
            "backwardation": (20.0, 18.0, 17.0),
        }
        spots = {"crushed": 11.0, "low": 14.0, "normal": 17.0, "elevated": 24.0, "panic": 45.0}
        for (state, (a, b, c)), (bucket, vix) in itertools.product(curves.items(), spots.items()):
            scale = vix / b
            r = classify({"vix9d": a * scale, "vix": vix, "vix3m": c * scale})
            self.assertEqual((r.state, r.bucket), (state, bucket))
            ok, reasons = gate(r)
            expect_go = state != "backwardation" and bucket not in ("crushed", "panic")
            self.assertEqual(ok, expect_go, f"{state}/{bucket}: {reasons}")


if __name__ == "__main__":
    unittest.main()
