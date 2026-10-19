import itertools
import unittest
from datetime import datetime, timezone

from dataclasses import replace

from spx_quant.params import load_params
from spx_quant.regime import advisories, classify, gate

ASOF = datetime(2026, 10, 5, 17, 15, tzinfo=timezone.utc)


class RegimeTest(unittest.TestCase):
    def test_us02_ac1_normal_market_reads_contango_with_values_and_timestamp(self):
        r = classify({"vix": 16.0, "vix3m": 18.5}, asof=ASOF)
        self.assertEqual((r.state, r.bucket), ("contango", "normal"))
        text = str(r)
        self.assertIn("VIX=16.00", text)
        self.assertIn("VIX3M=18.50", text)
        self.assertIn("asof 2026-10-05 10:15 PT", text)

    def test_us02_ac2_stressed_market_reads_backwardation(self):
        r = classify({"vix9d": 41.0, "vix": 38.0, "vix3m": 30.0}, asof=ASOF)
        self.assertEqual(r.state, "backwardation")
        self.assertAlmostEqual(r.slope, -0.2105, places=3)
        self.assertIn("asof", str(r))

    def test_us02_ac3_missing_point_is_unknown_and_named(self):
        for missing in ("vix", "vix3m"):
            curve = {"vix9d": 15.6, "vix": 16.5, "vix3m": 18.9}
            curve[missing] = None
            r = classify(curve)
            self.assertFalse(r.known)
            self.assertIn(missing.upper(), r.reason)
            ok, reasons = gate(r)
            self.assertFalse(ok)
            self.assertIn(f"could not be identified: {missing.upper()} missing", reasons[0])

    def test_optional_points_do_not_block(self):
        self.assertTrue(classify({"vix": 16.0, "vix3m": 18.5, "vix9d": None, "vix6m": None}).known)

    def test_us04_ac1_panic_names_the_ceiling(self):
        ok, reasons = gate(classify({"vix": 35.0, "vix3m": 36.0}))
        self.assertFalse(ok)
        self.assertIn("VIX 35.0 above the 28 ceiling", reasons[0])

    def test_us04_ac2_crushed_names_the_floor(self):
        ok, reasons = gate(classify({"vix": 12.0, "vix3m": 14.0}))
        self.assertFalse(ok)
        self.assertIn("VIX 12.0 below the 13 floor", reasons[0])
        self.assertIn("premium too thin", reasons[0])

    def test_gate_sweep(self):
        curves = {"contango": (15.0, 16.0, 18.0), "flat": (16.0, 16.0, 16.2), "backwardation": (20.0, 18.0, 17.0)}
        spots = {"crushed": 11.0, "low": 14.0, "normal": 17.0, "elevated": 24.0, "panic": 45.0}
        for (state, (a, b, c)), (bucket, vix) in itertools.product(curves.items(), spots.items()):
            scale = vix / b
            r = classify({"vix9d": a * scale, "vix": vix, "vix3m": c * scale})
            self.assertEqual((r.state, r.bucket), (state, bucket))
            ok, reasons = gate(r)
            self.assertEqual(ok, bucket not in ("crushed", "panic"), f"{state}/{bucket}: {reasons}")
            self.assertEqual(any("backwardation" in n for n in advisories(r)), state == "backwardation")

    def test_backwardation_is_information_not_a_stand_down(self):
        r = classify({"vix9d": 24.0, "vix": 22.0, "vix3m": 20.5})
        self.assertEqual((r.state, r.bucket), ("backwardation", "elevated"))
        ok, reasons = gate(r)
        self.assertTrue(ok, reasons)
        notes = advisories(r)
        self.assertEqual(len(notes), 1)
        self.assertIn("inverted (backwardation)", notes[0])
        self.assertIn("information only", notes[0])

    def test_stand_down_rules_come_from_config(self):
        p = load_params()
        strict = replace(p, sections={**p.sections, "gate": {"stand_down_on": ["backwardation", "vol_floor", "vol_ceiling"]}})
        r = classify({"vix": 22.0, "vix3m": 20.5})
        ok, reasons = gate(r, strict)
        self.assertFalse(ok)
        self.assertIn("backwardation", reasons[0])
        self.assertEqual(advisories(r, strict), [])
        loose = replace(p, sections={**p.sections, "gate": {"stand_down_on": []}})
        ok, _ = gate(classify({"vix": 35.0, "vix3m": 36.0}), loose)
        self.assertTrue(ok)

    def test_unknown_rule_in_config_is_an_error(self):
        p = load_params()
        bad = replace(p, sections={**p.sections, "gate": {"stand_down_on": ["vol_flor"]}})
        with self.assertRaises(ValueError):
            gate(classify({"vix": 16.0, "vix3m": 18.5}), bad)

    def test_shipped_default_is_floor_and_ceiling_only(self):
        self.assertEqual(load_params().gate["stand_down_on"], ["vol_floor", "vol_ceiling"])


if __name__ == "__main__":
    unittest.main()
