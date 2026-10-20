"""Trend readings and the end-to-end rule-set comparison behind docs/results/rules-v2.md.

    python research/spx-replay/rules_v2.py TRADES.csv [--cboe-cache .cache/cboe]

TRADES.csv is the --trades output of all_strategies.py run with --dte 45 60. Needs SPX, PUT and
PUTD histories in the Cboe cache (downloaded on first use).
"""
from __future__ import annotations

import argparse
import csv
import statistics as st
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "rules-pivot"))
from tier_a import series  # noqa: E402

READINGS = {
    "SPX above 200-day": lambda px, i: px[i] > sum(px[i - 199:i + 1]) / 200,
    "Up over 20 days": lambda px, i: px[i] > px[i - 20],
    "Within 5% of 52-week high": lambda px, i: px[i] >= 0.95 * max(px[i - 251:i + 1]),
    "50-day above 200-day": lambda px, i: sum(px[i - 49:i + 1]) / 50 > sum(px[i - 199:i + 1]) / 200,
}
GOLDEN = "50-day above 200-day"
RULES = {
    "Old: strangle, 45 DTE": lambda up: ("strangle", "45"),
    "Strangle, 60 DTE": lambda up: ("strangle", "60"),
    "New: 60 DTE, naked put in uptrend, else strangle": lambda up: ("naked_put" if up else "strangle", "60"),
    "Naked put always, 60 DTE": lambda up: ("naked_put", "60"),
}


def held(t) -> int:
    return max((date.fromisoformat(t["pt50_closed"]) - date.fromisoformat(t["opened"])).days, 1)


def ann_bp(ts) -> float:
    return sum(float(t["pt50_pnl"]) for t in ts) / (sum(float(t["bp_pm"]) * held(t) for t in ts) / 365)


def stats(ts) -> dict:
    pnl = [float(t["pt50_pnl"]) for t in ts]
    s = sorted(pnl)
    eq = peak = mdd = 0.0
    for _, p in sorted((t["pt50_closed"], p) for t, p in zip(ts, pnl)):
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return {"n": len(ts), "win": sum(p > 0 for p in pnl) / len(pnl), "ann": ann_bp(ts), "p5": s[int(0.05 * len(s))],
            "worst": s[0], "mdd": mdd}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trades", type=Path)
    ap.add_argument("--cboe-cache", type=Path, default=ROOT / ".cache" / "cboe")
    a = ap.parse_args()
    spx = series(a.cboe_cache, "SPX")
    days = sorted(spx)
    px = [spx[d] for d in days]
    prior = lambda d: bisect_left(days, d) - 1
    trades = list(csv.DictReader(a.trades.open()))
    for t in trades:
        i = prior(date.fromisoformat(t["opened"]))
        t["read"] = {k: f(px, i) for k, f in READINGS.items()}

    print("## Trend readings: naked put vs strangle, 45 DTE, annual return on PM buying power\n")
    print("| Reading | Period | NP up | Strangle up | NP down | Strangle down |\n|---|---|---|---|---|---|")
    for name in READINGS:
        for per, f in (("2010-2023", lambda y: True), ("2010-2018", lambda y: y < 2019), ("2019-2023", lambda y: y >= 2019)):
            cells = []
            for state in (True, False):
                for s in ("naked_put", "strangle"):
                    g = [t for t in trades if t["target_dte"] == "45" and t["strategy"] == s and t["read"][name] == state
                         and f(int(t["opened"][:4]))]
                    cells.append(f"{ann_bp(g):.1%}")
            print(f"| {name} | {per} | " + " | ".join(cells) + " |")

    print("\n## Cboe put-write indices by 50/200 cross, 21-session forward return\n")
    print("| Index | Period | Trend | Sessions | Annualized | 5th-pct month |\n|---|---|---|---|---|---|")
    idx = {d: i for i, d in enumerate(days)}
    for prog in ("PUT", "PUTD"):
        s = series(a.cboe_cache, prog)
        sd = sorted(d for d in s if d in idx and idx[d] >= 200)
        rows = [(sd[j], READINGS[GOLDEN](px, idx[sd[j - 1]]), s[sd[j + 21]] / s[sd[j]] - 1) for j in range(1, len(sd) - 21)]
        for per, f in (("2007-2009", lambda y: y <= 2009), ("2010-2023", lambda y: 2010 <= y <= 2023), ("all", lambda y: True)):
            for up in (True, False):
                x = sorted(r[2] for r in rows if r[1] == up and f(r[0].year))
                if x:
                    print(f"| {prog} | {per} | {'up' if up else 'down'} | {len(x)} | {st.mean(x) * 252 / 21:.1%} | {x[int(0.05 * len(x))]:.1%} |")

    by = defaultdict(dict)
    for t in trades:
        by[t["opened"]][(t["strategy"], t["target_dte"])] = t
    print("\n## Rule sets end to end (1 SPX lot per entry, 50% target, bid/ask)\n")
    print("| Rule set | Period | n | Win % | Annual return on BP | 5th pct | Worst | Max drawdown |\n|---|---|---|---|---|---|---|---|")
    for per, f in (("2010-2023", lambda y: True), ("2010-2018", lambda y: y < 2019), ("2019-2023", lambda y: y >= 2019),
                   ("2022", lambda y: y == 2022)):
        for name, pick in RULES.items():
            ts = []
            for d, row in sorted(by.items()):
                if f(int(d[:4])):
                    any_t = next(iter(row.values()))
                    t = row.get(pick(any_t["read"][GOLDEN]))
                    if t:
                        ts.append(t)
            s = stats(ts)
            print(f"| {name} | {per} | {s['n']} | {s['win']:.1%} | {s['ann']:.1%} | ${s['p5']:,.0f} | ${s['worst']:,.0f} | ${s['mdd']:,.0f} |")


if __name__ == "__main__":
    main()
