import copy
import unittest

from spx_quant import analytics, clock
from spx_quant.data.cboe import fetch_chain
from spx_quant.params import MissingParam
from spx_quant.strategies import build
from tests.helpers import EOD, PARAMS, params_without, replay


class RiskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain, _ = fetch_chain(replay(), "_SPX", 30, 1000)
        today = clock.market_date(EOD)
        cls.strangle = build("strangle", "_SPX", cls.chain.spot, cls.chain.rows, today, PARAMS)
        cls.condor = build("iron_condor", "_SPX", cls.chain.spot, cls.chain.rows, today, PARAMS)
        cls.iv = analytics.atm_iv(cls.chain.rows, cls.strangle.root, cls.strangle.exp, cls.chain.spot)

    def risk(self, pos, params=PARAMS, k=2, bp=40_000):
        return analytics.compute(pos, k, bp, self.chain.spot, self.iv, EOD, params)

    def test_atm_iv_is_read_from_the_board(self):
        self.assertAlmostEqual(self.iv, 0.139, places=2)

    def test_us05_ac1_every_risk_field_is_present(self):
        r = self.risk(self.strangle)
        d = r.as_dict()
        for k in ("pop", "ev", "cvar5", "cvar1", "worst_case", "breakevens", "max_profit", "stress",
                  "ann_return_bp", "implied_crash_per_year", "assumptions"):
            self.assertIsNotNone(d[k], k)
        self.assertTrue(0 < r.pop < 1)
        self.assertLessEqual(r.cvar1, r.cvar5)
        self.assertLess(r.cvar5, 0)
        self.assertEqual(len(r.breakevens), 2)
        self.assertEqual(r.max_profit, round(self.strangle.credit * 2, 2))
        self.assertIsNone(r.max_loss)

    def test_us05_ac2_assumptions_are_stated(self):
        text = analytics.assumptions_text(self.risk(self.strangle).assumptions)
        for s in ("held to expiration", "realized vol", "volatility risk premium", "crash", "unvalidated"):
            self.assertIn(s, text)

    def test_us05_ac3_missing_assumption_is_named_not_defaulted(self):
        for key in ("vrp_haircut", "crash_prob_annual", "crash_size", "rate"):
            with self.assertRaises(MissingParam) as cm:
                self.risk(self.strangle, params_without("risk", key))
            self.assertIn(f"risk.{key}", str(cm.exception))

    def test_defined_risk_tail_is_capped_by_max_loss(self):
        r = self.risk(self.condor)
        self.assertIsNotNone(r.max_loss)
        self.assertGreaterEqual(r.cvar1, -r.max_loss - 0.01)

    def test_crash_knob_is_what_pays_for_the_tail(self):
        # With no crash risk and no VRP the model books skew as free money (engine-build-notes finding 5).
        free = copy.deepcopy(PARAMS)
        free.sections["risk"].update(vrp_haircut=0.0, crash_prob_annual=0.0)
        self.assertGreater(self.risk(self.strangle, free).ev, 0)
        heavy = copy.deepcopy(PARAMS)
        heavy.sections["risk"]["crash_prob_annual"] = 2.0
        self.assertLess(self.risk(self.strangle, heavy).ev, self.risk(self.strangle).ev)
        self.assertGreater(self.risk(self.strangle).implied_crash_per_year, 0)

    def test_annualized_return_on_buying_power(self):
        r = self.risk(self.strangle, k=1, bp=20_000)
        self.assertAlmostEqual(r.ann_return_bp, r.ev / 20_000 * 365 / self.strangle.dte * 100, places=1)


if __name__ == "__main__":
    unittest.main()
