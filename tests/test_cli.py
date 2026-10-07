import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from spx_quant.__main__ import main
from tests.helpers import REPLAY

EOD = "2026-09-28T20:25:00+00:00"
MARK = "2026-09-28T20:35:00+00:00"


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--profile", str(self.profile), "--db", str(self.db), *args])
        return code, out.getvalue()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self.tmp.name) / "profile.json"
        self.db = Path(self.tmp.name) / "quant.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_day_on_a_recorded_session(self):
        code, out = self.run_cli("profile", "set", "--net-liq", "150000", "--margin", "portfolio")
        self.assertEqual(code, 0, out)
        code, out = self.run_cli("profile", "set", "--net-liq", "-5", "--margin", "portfolio")
        self.assertEqual(code, 2)
        self.assertIn("previous profile unchanged: net liq $150,000", out)

        code, out = self.run_cli("regime", "--replay", str(REPLAY), "--now", EOD)
        self.assertIn("regime: contango / normal", out)
        self.assertIn("gate: GO", out)

        code, out = self.run_cli("scan", "--slot", "13:25", "--no-send", "--replay", str(REPLAY), "--now", EOD)
        self.assertEqual(code, 0, out)
        self.assertIn("SPX QUANT | PROPOSAL", out)

        code, out = self.run_cli("log", "--from", "2026-09-28", "--to", "2026-09-28")
        self.assertIn("1 alert(s)", out)

        code, out = self.run_cli("mark", "--replay", str(REPLAY), "--now", MARK)
        self.assertIn("1 position(s) marked", out)

        code, out = self.run_cli("kr", "a2", "--from", "2026-09-28", "--to", "2026-09-28", "--plant")
        self.assertIn("8 of 8 planted rows caught", out)
        self.assertEqual(code, 1)   # fewer than 10 proposals

    def test_margin_check_sets_the_house_multiplier(self):
        import shutil
        from spx_quant.params import DEFAULT_PATH, load_params
        params = Path(self.tmp.name) / "params.toml"
        shutil.copy(DEFAULT_PATH, params)
        self.run_cli("profile", "set", "--net-liq", "150000", "--margin", "portfolio")
        code, out = self.run_cli("margin-check")
        self.assertEqual(code, 1)
        self.assertIn("no proposals", out)
        self.run_cli("scan", "--slot", "13:25", "--no-send", "--replay", str(REPLAY), "--now", EOD)
        code, out = self.run_cli("margin-check")
        self.assertIn("SELL 1 XSP261113P00725000", out)
        self.assertIn("SELL 1 XSP261113C00805000", out)
        self.assertIn("Engine buying power: $6,243.18", out)
        self.assertIn("--broker-bp", out)
        code, out = self.run_cli("--params", str(params), "margin-check", "--broker-bp", "7803.98", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("Set margin.pm_house_multiplier = 1.250", out)
        q = load_params(params)
        self.assertEqual(q.margin["pm_house_multiplier"], 1.25)
        self.assertEqual(q.provenance["margin.pm_house_multiplier"]["tag"], "unvalidated: partially supported")
        self.assertIn("broker $7,803.98 vs engine $6,243.18", q.provenance["margin.pm_house_multiplier"]["source"])
        code, out = self.run_cli("--params", str(params), "margin-check", "--broker-bp", "-1")
        self.assertEqual(code, 2)

    def test_stale_replay_refuses_to_advise(self):
        self.run_cli("profile", "set", "--net-liq", "150000", "--margin", "portfolio")
        code, out = self.run_cli("scan", "--no-send", "--replay", str(REPLAY))
        self.assertIn("NO ADVICE (stale data)", out)

    def test_scan_without_a_profile_exits_with_instructions(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_cli("scan", "--no-send", "--replay", str(REPLAY), "--now", EOD)
        self.assertIn("profile set", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
