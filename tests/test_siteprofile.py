"""Runner side of the settings site: the saved DynamoDB row becomes the run's profile file."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from spx_quant import profile as prof

spec = importlib.util.spec_from_file_location("siteprofile", Path(__file__).parents[1] / "deploy" / "cloud" / "siteprofile.py")
siteprofile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(siteprofile)

ROW = {"email": {"S": "me@example.com"}, "net_liq": {"N": "150000"}, "margin_type": {"S": "portfolio"},
       "bp_cap_pct": {"N": "0.06"}, "delta_theta_limit": {"N": "2"}, "max_worst_case_pct": {"N": "0.04"},
       "alerts": {"BOOL": True}, "monday_email": {"BOOL": False}, "digest_book": {"S": "paper"},
       "updated_at": {"S": "2026-11-16T20:00:00+00:00"}}


class SiteProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "pilot.json"
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, item, *flags, email="Me@Example.com"):
        def aws(*args):
            self.calls.append(args)
            if isinstance(item, Exception):
                raise item
            return json.dumps({"Item": item} if item else {})
        with contextlib.redirect_stdout(io.StringIO()) as self.said:
            return siteprofile.main([email, str(self.out), *flags], aws)

    def test_saved_row_becomes_the_profile(self):
        self.assertEqual(self.run_with(ROW), 0)
        p = prof.load(self.out)
        self.assertEqual((p.net_liq, p.margin_type, p.bp_cap_pct, p.delta_theta_limit, p.max_worst_case_pct),
                         (150000.0, "portfolio", 0.06, 2.0, 0.04))
        self.assertEqual((p.notify_channel, p.email_to), ("email", "Me@Example.com"))

    def test_the_row_is_looked_up_by_the_lowercased_email(self):
        self.run_with(ROW)
        args = self.calls[0]
        self.assertEqual(args[:2], ("dynamodb", "get-item"))
        self.assertEqual(json.loads(args[args.index("--key") + 1]), {"email": {"S": "me@example.com"}})

    def test_alerts_switched_off_or_no_email_means_no_channel(self):
        self.run_with({**ROW, "alerts": {"BOOL": False}})
        self.assertEqual(prof.load(self.out).notify_channel, "none")
        self.run_with(ROW, "--no-email")
        self.assertEqual((prof.load(self.out).notify_channel, prof.load(self.out).email_to), ("none", ""))

    def test_missing_limit_takes_the_tier_default(self):
        self.run_with({k: v for k, v in ROW.items() if k != "delta_theta_limit"} | {"net_liq": {"N": "2000000"}})
        self.assertEqual(prof.load(self.out).delta_theta_limit, 7.0)

    def test_no_row_bad_row_or_no_access_leaves_the_file_alone(self):
        self.out.write_text("kept", encoding="utf-8")
        bad = {**ROW, "net_liq": {"N": "50000"}}   # portfolio margin under $100,000
        for item in (None, bad, RuntimeError("Unable to locate credentials")):
            self.assertEqual(self.run_with(item), 1)
            self.assertEqual(self.out.read_text(encoding="utf-8"), "kept")
            self.assertIn("using the runner's secrets", self.said.getvalue())


if __name__ == "__main__":
    unittest.main()
