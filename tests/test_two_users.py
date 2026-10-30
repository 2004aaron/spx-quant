"""Two users on one host at the same time (proposal 4.5): one copy of the code, and a
profile and a log per user. Both scans start together on the same recorded board."""
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPLAY

ROOT = Path(__file__).resolve().parent.parent
NOW = "2026-09-28T20:25:00+00:00"
USERS = {"a": ("150000", "portfolio", "a@example.com"), "b": ("250000", "reg_t", "b@example.com")}


class TwoUsersAtOnce(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        for u, (net_liq, margin, to) in USERS.items():
            self.cli(u, "profile", "set", "--net-liq", net_liq, "--margin", margin, "--notify", "gmail", "--email-to", to)
        self.out = self.scan(*USERS)

    def args(self, u, *a):
        return [sys.executable, "-m", "spx_quant", "--profile", str(self.dir / f"{u}.json"), "--db", str(self.dir / f"{u}.db"), *a]

    def cli(self, u, *a):
        r = subprocess.run(self.args(u, *a), cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def scan(self, *users):
        """Start every user's scan before waiting on any of them."""
        procs = {u: subprocess.Popen(self.args(u, "scan", "--slot", "13:25", "--replay", str(REPLAY), "--now", NOW),
                                     cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for u in users}
        out = {u: p.communicate(timeout=120) for u, p in procs.items()}
        for u, p in procs.items():
            self.assertEqual(p.returncode, 0, out[u][1])
        return {u: o for u, (o, _) in out.items()}

    def rows(self, u, sql):
        conn = sqlite3.connect(self.dir / f"{u}.db")
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql)]

    def test_each_log_holds_only_its_own_scan(self):
        for u, (net_liq, margin, to) in USERS.items():
            self.assertEqual(len(self.rows(u, "SELECT * FROM scan")), 1)
            [alert] = self.rows(u, "SELECT profile FROM alert")
            p = json.loads(alert["profile"])
            self.assertEqual((p["net_liq"], p["margin_type"], p["email_to"]), (float(net_liq), margin, to))

    def test_same_board_sized_for_each_account(self):
        a = self.rows("a", "SELECT kind, ticker, strategy, contracts, bp_total FROM alert")[0]
        b = self.rows("b", "SELECT kind, ticker, strategy, contracts, bp_total FROM alert")[0]
        self.assertEqual((a["kind"], b["kind"]), ("proposal", "proposal"))
        self.assertEqual((a["contracts"], b["contracts"]), (1, 2))
        self.assertLessEqual(a["bp_total"], 0.08 * 150_000)
        self.assertLessEqual(b["bp_total"], 0.08 * 250_000)
        self.assertIn("SELL 1 XSP", self.out["a"])
        self.assertIn("SELL 2 XSP", self.out["b"])

    def test_alerts_go_only_to_their_own_user(self):
        for u, (_, _, to) in USERS.items():
            self.assertEqual([m["to"] for m in json.loads(self.cli(u, "outbox"))], [to])

    def test_alert_ids_are_counted_per_log(self):
        first = [self.rows(u, "SELECT alert_id FROM alert")[0]["alert_id"] for u in USERS]
        self.assertEqual(first[0], first[1])          # same ID in both logs: neither saw the other's alert
        self.scan("a")
        self.assertEqual([r["alert_id"] for r in self.rows("a", "SELECT alert_id FROM alert ORDER BY id")],
                         [first[0], first[0] + "-2"])
        self.assertEqual(len(self.rows("b", "SELECT * FROM alert")), 1)

    def test_side_by_side_table(self):
        r = subprocess.run([sys.executable, "deploy/cloud/side_by_side.py", str(self.dir / "a.db"), str(self.dir / "b.db"),
                            "--labels", "pilot", "demo"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| 2026-09-28 | 13:25 | 13:25:00 | PROPOSAL strangle XSP x1 | 13:25:00 | PROPOSAL strangle XSP x2 | 0 s |",
                      r.stdout)
        self.assertIn("1 slot in both logs", r.stdout)
        self.assertNotIn("150,000", r.stdout)
        self.assertNotIn("250000", r.stdout)


if __name__ == "__main__":
    unittest.main()
