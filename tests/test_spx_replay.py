"""research/spx-replay/tier_b_spx.py against OptionsDX-format files built from Black-Scholes."""
import importlib.util
import math
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

from spx_quant.greeks import bs

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tier_b_spx", ROOT / "research" / "spx-replay" / "tier_b_spx.py")
tb = importlib.util.module_from_spec(spec)
sys.modules["tier_b_spx"] = tb
spec.loader.exec_module(tb)

HEAD = ("QUOTE_UNIXTIME QUOTE_READTIME QUOTE_DATE QUOTE_TIME_HOURS UNDERLYING_LAST EXPIRE_DATE EXPIRE_UNIX DTE "
        "C_DELTA C_GAMMA C_VEGA C_THETA C_RHO C_IV C_VOLUME C_LAST C_SIZE C_BID C_ASK STRIKE P_BID P_ASK P_SIZE "
        "P_LAST P_DELTA P_GAMMA P_VEGA P_THETA P_RHO P_IV P_VOLUME STRIKE_DISTANCE STRIKE_DISTANCE_PCT").split()


def sessions(start: date, n: int):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def write_months(folder: Path, path: dict, vol=0.18):
    """path: {date: spot}. Writes one OptionsDX-style monthly .txt per month, padded and bracketed like the real files."""
    folder.mkdir(parents=True, exist_ok=True)
    months = {}
    for d, spot in path.items():
        exps = [d + timedelta(days=k) for k in range(0, 71) if (d + timedelta(days=k)).weekday() == 4]
        for e in exps:
            t = max((e - d).days, 0) / 365
            k = math.floor(spot * 0.85 / 10) * 10
            while k <= spot * 1.15:
                x = math.log(k / spot)
                iv = vol * (1 - 5 * x + 20 * x * x)
                p, c = bs(spot, k, t, iv, "P"), bs(spot, k, t, iv, "C")
                q = lambda g: (round(max(g.price - 0.1, 0.0), 2), round(g.price + 0.1, 2))
                (pb, pa), (cb, ca) = q(p), q(c)
                vals = {"QUOTE_DATE": d.isoformat(), "EXPIRE_DATE": e.isoformat(), "UNDERLYING_LAST": spot,
                        "STRIKE": float(k), "P_BID": pb, "P_ASK": pa, "C_BID": cb, "C_ASK": ca,
                        "P_DELTA": round(p.delta, 5), "C_DELTA": round(c.delta, 5), "DTE": (e - d).days}
                months.setdefault(d.strftime("%Y%m"), []).append(", ".join(f" {vals.get(h, '')}" for h in HEAD))
                k += 10
    for m, rows in months.items():
        (folder / f"spx_eod_{m}.txt").write_text(", ".join(f"[{h}]" for h in HEAD) + "\n" + "\n".join(rows) + "\n")


def run(folder):
    return tb.replay(folder, every=3, delta=0.16, dte=45, lo=30, hi=60)


class SpxReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        days = sessions(date(2015, 1, 5), 130)
        cls.flat = base / "flat"
        write_months(cls.flat, {d: 2000.0 for d in days})
        crash = {d: 2000.0 * (0.85 if i >= 40 else 1.0) for i, d in enumerate(days)}
        cls.crash = base / "crash"
        write_months(cls.crash, crash)
        cls.zip = base / "flat.zip"
        with zipfile.ZipFile(cls.zip, "w") as z:
            for f in sorted(cls.flat.iterdir()):
                z.write(f, f.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reads_padded_bracketed_files(self):
        d, b = next(tb.boards(self.flat))
        self.assertEqual(d, date(2015, 1, 5))
        self.assertEqual(b.spot, 2000.0)
        self.assertTrue(all(isinstance(k, float) for k in next(iter(b.chains.values()))))

    def test_zip_matches_folder(self):
        a, z = run(self.flat), run(self.zip)
        self.assertEqual([(t.opened, t.put_k, t.call_k) for t in a], [(t.opened, t.put_k, t.call_k) for t in z])

    def test_entries_hit_target_delta_and_dte(self):
        trades = run(self.flat)
        self.assertGreater(len(trades), 10)
        for t in trades:
            self.assertTrue(30 <= (t.exp - t.opened).days <= 60)
            self.assertLess(t.put_k, 2000)
            self.assertGreater(t.call_k, 2000)
            self.assertLess(t.quotes["bidask"], t.quotes["mid"])

    def test_flat_market_every_trade_wins(self):
        trades = run(self.flat)
        for v in tb.VARIANTS:
            self.assertTrue(all(t.closed[v][1] > 0 for t in trades), v)
        pt = tb.summary(trades, ("mid", "pt50"))
        hold = tb.summary(trades, ("mid", "hold"))
        self.assertLess(pt["days"], hold["days"])
        self.assertAlmostEqual(pt["roc"], 0.5, delta=0.05)

    def test_crash_produces_put_side_losses(self):
        trades = run(self.crash)
        hit = [t for t in trades if t.opened < date(2015, 2, 27) < t.exp]
        self.assertTrue(hit)
        self.assertTrue(all(t.closed[("bidask", "hold")][1] < 0 for t in hit))
        self.assertLess(tb.summary(trades, ("bidask", "hold"))["worst"], -5_000)

    def test_settlement_is_intrinsic(self):
        t = tb.Trade(date(2015, 1, 5), date(2015, 2, 20), 1900, 2100, {"bidask": 10, "mid": 11})
        self.assertEqual(tb.settle(t, 1850), 50)
        self.assertEqual(tb.settle(t, 2000), 0)
        self.assertEqual(tb.settle(t, 2130), 30)

    def test_report_renders(self):
        text, res = tb.report(run(self.flat), 0.16, 45)
        self.assertIn("50% profit target, bid/ask fills", text)
        self.assertEqual(res["bidask/hold"]["n"], len(run(self.flat)))


if __name__ == "__main__":
    unittest.main()
