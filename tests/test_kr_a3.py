"""A-KR3: 24 account type and size cases, zero violations of the BP cap or the delta:theta limit.

One test per case so the runner reports 24. Every ranked candidate is checked, not only the best.
`python -m spx_quant kr a3` prints the same matrix as a table for the results commit.
"""
import unittest

from spx_quant import kr
from tests.helpers import PARAMS


class AKR3Matrix(unittest.TestCase):
    pass


def _case(size, margin, regime, vix):
    def test(self):
        prof, res, violations = kr.a3_case(size, margin, regime, vix, PARAMS)
        self.assertIn(res.outcome, ("proposal", "stand_down"))
        self.assertEqual(violations, [])
        if res.best:
            self.assertLessEqual(res.best.sized.bp_total, prof.bp_cap_dollars)
    return test


for _size in kr.A3_SIZES:
    for _margin in kr.A3_MARGINS:
        for _regime, _vix in kr.A3_REGIMES:
            setattr(AKR3Matrix, f"test_{_size}_{_margin}_{_regime}", _case(_size, _margin, _regime, _vix))


if __name__ == "__main__":
    unittest.main()
