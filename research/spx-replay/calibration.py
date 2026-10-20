"""How accurate are the engine's own numbers? Calibration on OptionsDX SPX chains, 2010 to 2023.

    python research/spx-replay/calibration.py SPX_DATA [--every 3] [--csv out.csv]

For every entry the engine's risk block (spx_quant.analytics.compute) is run exactly as in a live
scan: production builder, current params, ATM IV from that day's chain, one lot. Each prediction is
then checked against what the real quotes did:
  * probability of profit vs the realized win rate, held to expiry (the model's own assumption)
  * expected value vs realized P/L at mid fills, held to expiry
  * the stress-test worst case (index -10%, vol +10 points) vs the realized loss
  * CVaR 5% vs the mean of the realized worst 5%
"""
from __future__ import annotations

import argparse
import csv
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "spx-replay"))
import all_strategies as al  # noqa: E402
from spx_quant import analytics, clock  # noqa: E402
from spx_quant.margin import bp_per_lot  # noqa: E402
from spx_quant.params import load_params  # noqa: E402
from spx_quant.strategies import build  # noqa: E402

STRATEGIES = ("strangle", "naked_put", "put_vertical")
BUCKETS = ((0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.85), (0.85, 0.9), (0.9, 0.95), (0.95, 1.01))


def replay(path: Path, every: int) -> list[dict]:
    p = load_params()
    out, open_, n, last = [], [], 0, None
    for d, spot, rows in al.sessions(path):
        for t in list(open_):
            if d >= t["pos"].exp:
                t["pnl"] = t["pos"].payoff(spot if d == t["pos"].exp else last)
                open_.remove(t)
        if n % every == 0:
            now = clock.local_to_utc("ET", datetime(d.year, d.month, d.day, 16, 0))
            for s in STRATEGIES:
                pos = build(s, "_SPX", spot, rows, d, p)
                iv = analytics.atm_iv(rows, pos.root, pos.exp, spot) if pos else None
                if pos is None or iv is None:
                    continue
                bp = bp_per_lot(pos, spot, "portfolio", now, p)
                r = analytics.compute(pos, 1, bp, spot, iv, now, p)
                t = {"strategy": s, "opened": d, "pos": pos, "pop": r.pop, "ev": r.ev, "cvar5": r.cvar5,
                     "stress": analytics.stress_loss_per_lot(pos, spot, now, p)}
                out.append(t)
                open_.append(t)
        n += 1
        last = spot
    return [t for t in out if "pnl" in t]


def report(ts: list[dict]) -> str:
    lines = []
    for s in STRATEGIES:
        g = [t for t in ts if t["strategy"] == s]
        if not g:
            continue
        win = [t["pnl"] > 0 for t in g]
        brier = st.mean((t["pop"] - w) ** 2 for t, w in zip(g, win))
        base = st.mean(win)
        pnl = sorted(t["pnl"] for t in g)
        k = max(1, len(pnl) // 20)
        lines += [f"## {s.replace('_', ' ')} ({len(g)} entries, held to expiry, mid credit)", "",
                  "| | Predicted | Realized |", "|---|---|---|",
                  f"| Win rate | {st.mean(t['pop'] for t in g):.1%} | {base:.1%} |",
                  f"| Average P/L per lot | ${st.mean(t['ev'] for t in g):,.0f} | ${st.mean(pnl):,.0f} |",
                  f"| Average of worst 5% (CVaR 5%) | ${st.mean(t['cvar5'] for t in g):,.0f} | ${st.mean(pnl[:k]):,.0f} |",
                  f"| Losses bigger than the stress-test worst case | | {sum(t['pnl'] < -t['stress'] for t in g)} of {len(g)} |",
                  f"| Brier score (lower is better; always guessing the base rate scores {base * (1 - base):.3f}) | {brier:.3f} | |",
                  "", "| Predicted POP | n | Realized win rate |", "|---|---|---|"]
        for lo, hi in BUCKETS:
            b = [t for t in g if lo <= t["pop"] < hi]
            if b:
                lines.append(f"| {lo:.0%} to {min(hi, 1):.0%} | {len(b)} | {st.mean(t['pnl'] > 0 for t in b):.1%} |")
        ev_hi = [t for t in g if t["ev"] >= st.median(x["ev"] for x in g)]
        ev_lo = [t for t in g if t["ev"] < st.median(x["ev"] for x in g)]
        lines += ["", f"Ranking check: entries with above-median predicted EV made ${st.mean(t['pnl'] for t in ev_hi):,.0f} "
                      f"a lot on average; below-median made ${st.mean(t['pnl'] for t in ev_lo):,.0f}.", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--csv", type=Path)
    a = ap.parse_args()
    ts = replay(a.data, a.every)
    print(report(ts))
    if a.csv:
        with a.csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["strategy", "opened", "exp", "legs", "pop", "ev", "cvar5", "stress_loss", "pnl_hold_mid"])
            for t in ts:
                w.writerow([t["strategy"], t["opened"], t["pos"].exp, t["pos"].legs_text(), round(t["pop"], 4),
                            round(t["ev"], 2), round(t["cvar5"], 2), round(t["stress"], 2), round(t["pnl"], 2)])


if __name__ == "__main__":
    main()
