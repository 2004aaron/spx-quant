import tempfile
import unittest
from pathlib import Path

from spx_quant import profile as prof


class ProfileTest(unittest.TestCase):
    def test_us01_ac1_valid_profile_saved_and_classified(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            prof.save(prof.validate(150_000, "portfolio", 0.08, 2), path)
            p = prof.load(path)
            self.assertEqual((p.net_liq, p.margin_type, p.bp_cap_pct, p.delta_theta_limit), (150_000, "portfolio", 0.08, 2))
            self.assertEqual(p.tier, "small")
            self.assertEqual(p.bp_cap_dollars, 12_000)
            self.assertEqual(prof.validate(2_500_000, "portfolio").tier, "large")

    def test_us01_ac2_invalid_or_missing_values_rejected(self):
        for kwargs in (
            dict(net_liq=-5000, margin_type="portfolio"),
            dict(net_liq="abc", margin_type="portfolio"),
            dict(net_liq=None, margin_type="portfolio"),
            dict(net_liq=1000, margin_type="xyz"),
            dict(net_liq=1000, margin_type=None),
            dict(net_liq=1000, margin_type="reg_t", bp_cap_pct=1.5),
            dict(net_liq=1000, margin_type="reg_t", bp_cap_pct=0),
            dict(net_liq=1000, margin_type="reg_t", delta_theta_limit=0),
            dict(net_liq=1000, margin_type="reg_t", notify_channel="sms"),
            dict(net_liq=1000, margin_type="reg_t", notify_channel="email", email_to=""),
        ):
            with self.assertRaises(prof.ProfileError, msg=kwargs):
                prof.validate(**kwargs)

    def test_us01_ac2_previous_profile_stays_in_use(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            prof.save(prof.validate(150_000, "portfolio"), path)
            with self.assertRaises(prof.ProfileError):
                prof.save(prof.validate(-5000, "portfolio"), path)
            self.assertEqual(prof.load(path).net_liq, 150_000)

    def test_worst_case_limit_defaults_to_ten_percent_and_is_validated(self):
        p = prof.validate(150_000, "portfolio")
        self.assertEqual((p.max_worst_case_pct, p.worst_case_limit), (0.10, 15_000))
        for bad in (0, -0.1, 1.5, "abc"):
            with self.assertRaises(prof.ProfileError, msg=bad):
                prof.validate(150_000, "portfolio", max_worst_case_pct=bad)

    def test_profile_saved_before_the_worst_case_limit_still_loads(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            path.write_text('{"net_liq": 150000, "margin_type": "portfolio", "bp_cap_pct": 0.08, '
                            '"delta_theta_limit": 2.0, "notify_channel": "none", "email_to": ""}')
            self.assertEqual(prof.load(path).max_worst_case_pct, 0.10)

    def test_notification_address_is_part_of_the_profile(self):
        p = prof.validate(150_000, "portfolio", notify_channel="email", email_to=" me@example.com ")
        self.assertEqual(p.email_to, "me@example.com")
        self.assertIn("notify email me@example.com", str(p))

    def test_missing_file_means_no_profile(self):
        self.assertIsNone(prof.load(Path(tempfile.gettempdir()) / "definitely-not-here.json"))


if __name__ == "__main__":
    unittest.main()
