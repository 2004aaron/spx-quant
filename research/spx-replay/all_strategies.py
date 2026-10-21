"""Replay all four StormGlass builders on OptionsDX SPX end-of-day chains.

    python research/spx-replay/all_strategies.py SPX_DATA [--every 3] [--dte 45 60] [--json out.json]

Strikes are chosen by the production code (spx_quant.strategies.build) on each session's real
chain, so every trade is the one the engine would have proposed that day. Buying power comes from
spx_quant.margin (portfolio margin and Reg-T). Each trade is marked every session from real
quotes and exits either at the 50% profit target (read on the mid) or at expiration, settled at
that day's close. Two fill modes bracket execution: bid/ask (sell the bid, buy the ask, on every
leg) and mid.

OptionsDX has no open interest, so the open-interest/volume part of the liquidity filter is
skipped; the spread and minimum-mid checks still apply. Every expiry is treated as close-settled.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "spx-replay"))
from spx_quant import clock  # noqa: E402
from spx_quant.margin import bp_per_lot  # noqa: E402
from spx_quant.params import load_params  # noqa: E402
from spx_quant.strategies import BUILDERS, MULTIPLIER, build  # noqa: E402
from tier_b_spx import _num, _rows, month_files  # noqa: E402

TARGET = 0.50
MAX_DTE = 75


def sessions(path: Path):
    """Yield (date, spot, rows) per session; rows in the engine's chain format, DTE <= MAX_DTE."""
    for _, opener in month_files(path):
        days: dict[date, list] = defaultdict(list)
        spots: dict[date, float] = {}
        with opener() as f:
            for r in _rows(f):
                spot, k = _num(r["UNDERLYING_LAST"]), _num(r["STRIKE"])
                if spot is None or k is None:
                    continue
                d = date.fromisoformat(r["QUOTE_DATE"].strip())
                exp = date.fromisoformat(r["EXPIRE_DATE"].strip())
                if (exp - d).days > MAX_DTE:
                    continue
                spots[d] = spot
                for right in ("P", "C"):
                    bid, ask = _num(r[f"{right}_BID"]), _num(r[f"{right}_ASK"])
                    dlt, iv = _num(r[f"{right}_DELTA"]), _num(r[f"{right}_IV"])
                    if bid is None or ask is None or ask < bid:
                        continue
                    days[d].append({"sym": f"SPXW{exp:%y%m%d}{right}{int(round(k * 1000)):08d}", "root": "SPXW",
                                    "exp": exp, "right": right, "strike": k, "bid": bid, "ask": ask,
                                    "mid": (bid + ask) / 2, "iv": iv or 0.0, "delta": dlt or 0.0,
                                    "oi": 10 ** 6, "vol": _num(r[f"{right}_VOLUME"]) or 0})
        for d in sorted(days):
            yield d, spots[d], days[d]


def params_for(base, dte: int):
    secs = dict(base.sections)
    secs["expiry"] = {**secs["expiry"], "target_dte": dte, "dte_min": dte - 15, "dte_max": dte + 15}
    return replace(base, sections=secs)


def close_cost(pos, quotes: dict) -> tuple[float, float] | None:
    """(mid, natural) cost per share to close: buy shorts at the ask, sell longs at the bid."""
    mid = nat = 0.0
    for l in pos.legs:
        q = quotes.get((l.exp, l.strike, l.right))
        if q is None:
            return None
        mid += -l.qty * (q[0] + q[1]) / 2
        nat += -l.qty * (q[1] if l.qty < 0 else q[0])
    return mid, nat


def replay(path: Path, every: int, dtes: list[int]):
    base = load_params()
    plist = {dte: params_for(base, dte) for dte in dtes}
    trades, open_, n, last_spot = [], [], 0, None
    for d, spot, rows in sessions(path):
        quotes = {(r["exp"], r["strike"], r["right"]): (r["bid"], r["ask"]) for r in rows}
        for t in list(open_):
            pos = t["pos"]
            if d >= pos.exp:
                s = spot if d == pos.exp else last_spot
                pnl = pos.payoff(s) - pos.credit + t["credit"]
                t["out"].setdefault("pt50", (pos.exp, pnl, pos.payoff(s)))
                t["out"]["hold"] = (pos.exp, pnl, pos.payoff(s))
                open_.remove(t)
                continue
            if "pt50" not in t["out"]:
                c = close_cost(pos, quotes)
                if c and c[0] <= t["credit_mid"] / MULTIPLIER * (1 - TARGET):
                    t["out"]["pt50"] = (d, t["credit"] - c[1] * MULTIPLIER, t["credit_mid"] - c[0] * MULTIPLIER)
        if n % every == 0:
            now = clock.local_to_utc("ET", datetime(d.year, d.month, d.day, 16, 0))
            for dte, p in plist.items():
                for s in BUILDERS:
                    pos = build(s, "_SPX", spot, rows, d, p)
                    if pos is None:
                        continue
                    trades.append({"strategy": s, "dte": dte, "opened": d, "pos": pos, "credit": pos.credit_range[0],
                                   "credit_mid": pos.credit, "out": {},
                                   "bp_pm": bp_per_lot(pos, spot, "portfolio", now, p),
                                   "bp_regt": bp_per_lot(pos, spot, "reg_t", now, p)})
                    open_.append(trades[-1])
        n += 1
        last_spot = spot
    return [t for t in trades if len(t["out"]) == 2]


def summary(ts: list[dict], exit_: str, fill: str = "natural") -> dict:
    pnl = [t["out"][exit_][1 if fill == "natural" else 2] for t in ts]
    days = [max((t["out"][exit_][0] - t["opened"]).days, 1) for t in ts]
    s = sorted(pnl)
    bp_days = lambda key: sum(t[key] * dd for t, dd in zip(ts, days)) / 365
    return {"n": len(ts), "win": sum(x > 0 for x in pnl) / len(ts), "avg": st.mean(pnl),
            "roc": sum(pnl) / sum(t["credit" if fill == "natural" else "credit_mid"] for t in ts), "worst": s[0], "p5": s[int(0.05 * (len(s) - 1))],
            "days": st.mean(days), "bp_pm": st.mean(t["bp_pm"] for t in ts), "bp_regt": st.mean(t["bp_regt"] for t in ts),
            "ann_pm": sum(pnl) / bp_days("bp_pm"), "ann_regt": sum(pnl) / bp_days("bp_regt")}


def table(rows) -> str:
    out = ["| | n | win % | avg P/L | return on credit | 5th pct | worst | avg days | avg BP (PM) | annual return on BP (PM) | annual return on BP (Reg-T) |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in rows:
        out.append(f"| {name} | {s['n']} | {s['win']:.1%} | ${s['avg']:,.0f} | {s['roc']:.1%} | ${s['p5']:,.0f} | ${s['worst']:,.0f} | "
                   f"{s['days']:.1f} | ${s['bp_pm']:,.0f} | {s['ann_pm']:.1%} | {s['ann_regt']:.1%} |")
    return "\n".join(out)


def report(trades: list[dict]) -> tuple[str, dict]:
    res, lines = {}, []
    groups = defaultdict(list)
    for t in trades:
        groups[(t["dte"], t["strategy"])].append(t)
    for dte in sorted({k[0] for k in groups}):
        for exit_ in ("pt50", "hold"):
            for fill in ("natural", "mid"):
                rows = [(s.replace("_", " "), summary(groups[(dte, s)], exit_, fill)) for s in BUILDERS if groups[(dte, s)]]
                res[f"{dte}/{exit_}/{fill}"] = dict(rows)
                lines += [f"### Target {dte} DTE, {'50% profit target' if exit_ == 'pt50' else 'hold to expiry'}, "
                          f"{'bid/ask' if fill == 'natural' else 'mid'} fills", "", table(rows), ""]
        rows = []
        for half, f in (("2010-2018", lambda t: t["opened"].year < 2019), ("2019-2023", lambda t: t["opened"].year >= 2019)):
            for s in BUILDERS:
                sub = [t for t in groups[(dte, s)] if f(t)]
                if sub:
                    for fill in ("natural", "mid"):
                        rows.append((f"{s.replace('_', ' ')}, {half}, {'bid/ask' if fill == 'natural' else 'mid'}",
                                     summary(sub, "pt50", fill)))
        res[f"{dte}/halves"] = dict(rows)
        lines += [f"### Target {dte} DTE, 50% profit target, by half", "", table(rows), ""]
    return "\n".join(lines), res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--dte", type=int, nargs="+", default=[45])
    ap.add_argument("--json", type=Path)
    ap.add_argument("--trades", type=Path, help="write one CSV row per trade")
    a = ap.parse_args()
    trades = replay(a.data, a.every, a.dte)
    text, res = report(trades)
    print(text)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str))
    if a.trades:
        with a.trades.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["strategy", "target_dte", "opened", "exp", "legs", "credit", "bp_pm", "bp_regt",
                        "pt50_closed", "pt50_pnl", "hold_pnl", "credit_mid", "pt50_pnl_mid", "hold_pnl_mid"])
            for t in trades:
                w.writerow([t["strategy"], t["dte"], t["opened"], t["pos"].exp, t["pos"].legs_text(), round(t["credit"], 2),
                            t["bp_pm"], t["bp_regt"], t["out"]["pt50"][0], round(t["out"]["pt50"][1], 2),
                            round(t["out"]["hold"][1], 2), t["credit_mid"], round(t["out"]["pt50"][2], 2),
                            round(t["out"]["hold"][2], 2)])


if __name__ == "__main__":
    main()
