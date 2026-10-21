"""Put vertical wing width x short delta sweep at 60 DTE (docs/results/rules-v2.md, evidence 5).

    python research/spx-replay/vertical_sweep.py SPX_DATA

Production builder and close-cost logic from all_strategies.py; 50% profit target read on the mid.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "spx-replay"))
import all_strategies as al  # noqa: E402
from spx_quant.params import load_params  # noqa: E402
from spx_quant.strategies import build  # noqa: E402

WIDTHS = (0.0075, 0.015, 0.025, 0.035, 0.05)
SHORTS = (0.16, 0.25)


def main() -> None:
    base = al.params_for(load_params(), 60)
    plist = {}
    for w in WIDTHS:
        for sd in SHORTS:
            secs = dict(base.sections)
            secs["put_vertical"] = {**secs["put_vertical"], "width_pct": w, "short_delta": sd}
            plist[(w, sd)] = replace(base, sections=secs)
    trades, open_, n, last = [], [], 0, None
    for d, spot, rows in al.sessions(Path(sys.argv[1])):
        quotes = {(r["exp"], r["strike"], r["right"]): (r["bid"], r["ask"]) for r in rows}
        for t in list(open_):
            pos = t["pos"]
            if d >= pos.exp:
                s = spot if d == pos.exp else last
                t.setdefault("out", (pos.payoff(s) - pos.credit + t["credit"], pos.payoff(s)))
                open_.remove(t)
            elif "out" not in t:
                c = al.close_cost(pos, quotes)
                if c and c[0] <= t["credit_mid"] / 100 * (1 - al.TARGET):
                    t["out"] = (t["credit"] - c[1] * 100, t["credit_mid"] - c[0] * 100)
        if n % 3 == 0:
            for key, p in plist.items():
                pos = build("put_vertical", "_SPX", spot, rows, d, p)
                if pos:
                    trades.append({"key": key, "year": d.year, "pos": pos, "credit": pos.credit_range[0], "credit_mid": pos.credit})
                    open_.append(trades[-1])
        n += 1
        last = spot
    g = defaultdict(list)
    for t in trades:
        if "out" in t:
            g[t["key"]].append(t)
    roc = lambda ts, i, c: sum(t["out"][i] for t in ts) / sum(t[c] for t in ts) if ts else float("nan")
    print("| Wings | Short delta | n | Bid/ask | Mid | Median fill cost | Bid/ask, fill cost <= 25% | 2010-2018 bid/ask | 2019-2023 bid/ask |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (w, sd), ts in sorted(g.items()):
        fc = sorted((t["credit_mid"] - t["credit"]) / t["credit_mid"] for t in ts)
        guard = [t for t in ts if (t["credit_mid"] - t["credit"]) / t["credit_mid"] <= 0.25]
        a, b = [t for t in ts if t["year"] < 2019], [t for t in ts if t["year"] >= 2019]
        print(f"| {w:.2%} | {sd:.2f} | {len(ts)} | {roc(ts, 0, 'credit'):.1%} | {roc(ts, 1, 'credit_mid'):.1%} | "
              f"{fc[len(fc) // 2]:.0%} | {roc(guard, 0, 'credit'):.1%} | {roc(a, 0, 'credit'):.1%} | {roc(b, 0, 'credit'):.1%} |")


if __name__ == "__main__":
    main()
