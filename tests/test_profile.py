import tempfile
import unittest
from pathlib import Path

from spx_quant import profile as prof


class ProfileTest(unittest.TestCase):
    def test_valid_profile_and_tier(self):
        p = prof.validate(150_000, "portfolio", 0.08, 2)
        self.assertEqual(p.tier, "small")
        self.assertEqual(p.bp_cap_dollars, 12_000)
        self.assertEqual(prof.validate(2_500_000, "portfolio").tier, "large")

    def test_invalid_values_rejected(self):
        for kwargs in (
            dict(net_liq=-5000, margin_type="portfolio"),
            dict(net_liq="abc", margin_type="portfolio"),
            dict(net_liq=1000, margin_type="xyz"),
            dict(net_liq=1000, margin_type="reg_t", bp_cap_pct=1.5),
            dict(net_liq=1000, margin_type="reg_t", delta_theta_limit=0),
        ):
            with self.assertRaises(prof.ProfileError, msg=kwargs):
                prof.validate(**kwargs)

    def test_save_load_and_previous_kept_on_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            prof.save(prof.validate(150_000, "portfolio"), path)
            with self.assertRaises(prof.ProfileError):
                prof.validate(-5000, "portfolio")
            self.assertEqual(prof.load(path).net_liq, 150_000)


if __name__ == "__main__":
    unittest.main()
