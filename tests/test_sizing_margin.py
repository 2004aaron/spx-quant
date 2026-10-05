import copy
import unittest
from datetime import date, datetime, timezone

from spx_quant import margin
from spx_quant.profile import validate
from spx_quant.sizing import delta_theta_ok, size
from spx_quant.strategies import Leg, Position
from tests.helpers import PARAMS

NOW = datetime(2026, 10, 5, 17, 30, tzinfo=timezone.utc)
EXP = date(2026, 11, 20)


def leg(right, strike, mid, qty, delta, iv=0.18):
    return Leg({"sym": f"SPXW261120{right}{int(strike * 1000):08d}", "root": "SPXW", "exp": EXP, "right": right,
                "strike": float(strike), "bid": mid - 0.2, "ask": mid + 0.2, "mid": mid, "iv": iv, "delta": delta,
                "oi": 500, "vol": 100}, qty)


def pos(strategy, legs, width=0.0):
    return Position(strategy, "_SPX", "SPXW", EXP, 46, legs, width)


class RegTTest(unittest.TestCase):
    def test_naked_put_uses_the_ten_percent_floor_when_far_out(self):
        p = pos("naked_put", [leg("P", 6500, 20.0, -1, -0.10)])
        self.assertEqual(margin.bp_per_lot(p, 7000, "reg_t", NOW, PARAMS), 67_000.00)

    def test_strangle_is_worse_side_plus_other_premium(self):
        p = pos("strangle", [leg("P", 6500, 20.0, -1, -0.10), leg("C", 7500, 15.0, -1, 0.10)])
        self.assertEqual(margin.bp_per_lot(p, 7000, "reg_t", NOW, PARAMS), 73_500.00)

    def test_defined_risk_is_width_less_credit(self):
        p = pos("put_vertical", [leg("P", 6800, 30.0, -1, -0.25), leg("P", 6750, 22.0, 1, -0.21)], width=50)
        self.assertEqual(margin.bp_per_lot(p, 7000, "reg_t", NOW, PARAMS), 4_200.00)


class PortfolioMarginTest(unittest.TestCase):
    def test_worst_scenario_is_the_down_move_for_a_short_put(self):
        p = pos("naked_put", [leg("P", 6500, 20.0, -1, -0.10)])
        scen = margin.pm_scenarios(p, 7000, NOW, PARAMS)
        self.assertEqual(len(scen), 10)
        self.assertEqual(min(scen, key=lambda s: s[1])[0], -0.15)
        self.assertLess(margin.bp_per_lot(p, 7000, "portfolio", NOW, PARAMS), margin.bp_per_lot(p, 7000, "reg_t", NOW, PARAMS))

    def test_house_multiplier_scales(self):
        p = pos("naked_put", [leg("P", 6500, 20.0, -1, -0.10)])
        base = margin.bp_per_lot(p, 7000, "portfolio", NOW, PARAMS)
        q = copy.deepcopy(PARAMS)
        q.sections["margin"]["pm_house_multiplier"] = 1.5
        self.assertAlmostEqual(margin.bp_per_lot(p, 7000, "portfolio", NOW, q), base * 1.5, places=1)

    def test_defined_risk_never_exceeds_max_loss(self):
        p = pos("put_vertical", [leg("P", 6800, 30.0, -1, -0.25), leg("P", 6750, 22.0, 1, -0.21)], width=50)
        self.assertLessEqual(margin.bp_per_lot(p, 7000, "portfolio", NOW, PARAMS), 4_200.00)


class SizingTest(unittest.TestCase):
    def setUp(self):
        self.prof = validate(150_000, "portfolio", 0.08, 2)

    def test_us03_ac4_candidate_exactly_at_the_cap_is_allowed(self):
        s = size(self.prof, 12_000.00, 0.0, 100.0)
        self.assertTrue(s.ok, s.reasons)
        self.assertEqual((s.contracts, s.bp_total), (1, 12_000.00))

    def test_one_cent_over_the_cap_is_refused(self):
        s = size(self.prof, 12_000.01, 0.0, 100.0)
        self.assertFalse(s.ok)
        self.assertEqual(s.codes, ["over_cap"])
        self.assertIn("cap is $12,000.00", s.reasons[0])

    def test_contracts_fill_up_to_the_cap(self):
        s = size(self.prof, 3_300.00, 1.0, 100.0)
        self.assertEqual((s.contracts, s.bp_total), (3, 9_900.00))

    def test_float_noise_cannot_break_the_inclusive_cap(self):
        prof = validate(0.1 + 0.2, "reg_t", 1.0, 2)   # 0.30000000000000004
        self.assertEqual(size(prof, 0.30, 0.0, 1.0).contracts, 1)

    def test_delta_theta_limit_boundary(self):
        self.assertTrue(delta_theta_ok(50.0, 100.0, 2.0))      # exactly 1:2
        self.assertFalse(delta_theta_ok(50.01, 100.0, 2.0))
        self.assertTrue(delta_theta_ok(-50.0, 100.0, 2.0))     # direction does not matter
        s = size(self.prof, 1_000.0, 60.0, 100.0)
        self.assertEqual(s.codes, ["delta_theta"])
        self.assertIn("breaks the 1:2 limit", s.reasons[0])

    def test_non_positive_theta_is_not_a_premium_sale(self):
        self.assertEqual(size(self.prof, 1_000.0, 0.0, -5.0).codes, ["theta"])


class WorstCaseSizingTest(unittest.TestCase):
    def setUp(self):
        self.prof = validate(150_000, "portfolio", 0.08, 2)   # worst-case limit 10% = $15,000

    def test_sized_down_when_the_worst_case_binds_before_buying_power(self):
        s = size(self.prof, 2_000.00, 0.0, 100.0, worst_per_lot=4_000.00)
        self.assertTrue(s.ok, s.reasons)
        self.assertEqual((s.bp_contracts, s.contracts, s.limited_by), (6, 3, "worst case"))
        self.assertEqual((s.worst_total, s.worst_limit, s.bp_total), (12_000.00, 15_000.00, 6_000.00))

    def test_worst_case_exactly_at_the_limit_is_allowed(self):
        s = size(self.prof, 1_000.00, 0.0, 100.0, worst_per_lot=5_000.00)
        self.assertEqual((s.contracts, s.worst_total), (3, 15_000.00))

    def test_one_lot_over_the_limit_is_refused(self):
        s = size(self.prof, 1_000.00, 0.0, 100.0, worst_per_lot=15_000.01)
        self.assertFalse(s.ok)
        self.assertEqual(s.codes, ["over_worst_case"])
        self.assertIn("over the $15,000.00 limit (10% of $150,000)", s.reasons[0])

    def test_buying_power_still_binds_when_it_is_tighter(self):
        s = size(self.prof, 5_000.00, 0.0, 100.0, worst_per_lot=1_000.00)
        self.assertEqual((s.contracts, s.limited_by), (2, "buying power"))

    def test_no_stress_loss_means_no_worst_case_constraint(self):
        self.assertEqual(size(self.prof, 1_000.00, 0.0, 100.0, worst_per_lot=0.0).contracts, 12)

    def test_the_limit_follows_the_profile(self):
        tight = validate(150_000, "portfolio", 0.08, 2, max_worst_case_pct=0.05)
        self.assertEqual(size(tight, 1_000.00, 0.0, 100.0, worst_per_lot=4_000.00).contracts, 1)


if __name__ == "__main__":
    unittest.main()
