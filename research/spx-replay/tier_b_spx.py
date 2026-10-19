"""Tier B on SPX: short-strangle replay on OptionsDX end-of-day chains (2010 to 2023).

    python research/spx-replay/tier_b_spx.py DATA [--every 3] [--delta 0.16] [--dte 45]
                                             [--cboe-cache .cache/cboe] [--json out.json]

DATA is a folder, zip or file of OptionsDX SPX EOD monthly files (.txt or .csv, zipped or not).
Replays the September Tier B study on SPX instead of SPY, with every mark taken from a real
quote instead of a model: open a 1-lot strangle every N sessions at the expiry nearest the
target DTE (within expiry.dte_min..dte_max), strikes nearest the target delta, then exit
either at expiration (cash settled at that day's underlying close) or at the 50% profit target.

Two fill modes bracket execution: "bidask" sells the bid and buys back at the ask, "mid" uses
mids both ways. If --cboe-cache holds VIX/VIX3M/VIX9D histories (research/rules-pivot/tier_a.py
downloads them there), results are also split by the regime read the day before entry.

Limits: the standard monthly SPX contract settles on the Friday open (SOQ), not the close; this
uses the close for every expiry. No commissions, no early assignment (SPX is European).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics as st
import sys
import zipfile
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from spx_quant.params import load_params  # noqa: E402

MULT = 100
TARGET = 0.50
VARIANTS = [(fill, exit_) for fill in ("bidask", "mid") for exit_ in ("hold", "pt50")]


# ---------- loading ----------

def _num(s: str) -> float | None:
    s = s.strip()
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _rows(text: io.TextIOBase):
    reader = csv.reader(text)
    head = [h.strip().strip("[]") for h in next(reader)]
    for r in reader:
        if len(r) >= len(head):
            yield dict(zip(head, r))


def month_files(path: Path):
    """Yield (sort_key, opener) for every data file under path, sorted by name (OptionsDX names sort by month)."""
    found = []
    paths = sorted(path.rglob("*")) if path.is_dir() else [path]
    for p in paths:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for m in z.namelist():
                    if m.lower().endswith((".txt", ".csv")):
                        found.append((Path(m).name, lambda p=p, m=m: io.TextIOWrapper(zipfile.ZipFile(p).open(m), "utf-8")))
        elif p.suffix.lower() in (".txt", ".csv"):
            found.append((p.name, lambda p=p: p.open(newline="")))
    return sorted(found, key=lambda x: x[0])


@dataclass
class Board:
    spot: float
    # chains[expiry][strike] = {"P": (bid, ask, delta), "C": (bid, ask, delta)}
    chains: dict = field(default_factory=lambda: defaultdict(dict))


def boards(path: Path):
    """Yield (date, Board) in date order, one month file in memory at a time."""
    for _, opener in month_files(path):
        days: dict[date, Board] = {}
        with opener() as f:
            for r in _rows(f):
                spot, k = _num(r["UNDERLYING_LAST"]), _num(r["STRIKE"])
                if spot is None or k is None:
                    continue
                d = date.fromisoformat(r["QUOTE_DATE"].strip())
                exp = date.fromisoformat(r["EXPIRE_DATE"].strip())
                b = days.setdefault(d, Board(spot))
                b.chains[exp][k] = {
                    "P": (_num(r["P_BID"]), _num(r["P_ASK"]), _num(r["P_DELTA"])),
                    "C": (_num(r["C_BID"]), _num(r["C_ASK"]), _num(r["C_DELTA"])),
                }
        yield from sorted(days.items())


# ---------- replay ----------

@dataclass
class Trade:
    opened: date
    exp: date
    put_k: float
    call_k: float
    quotes: dict           # fill -> credit per share
    regime: str = "n/a"
    closed: dict = field(default_factory=dict)   # variant -> (date, pnl $)


def _mid(q):
    return (q[0] + q[1]) / 2 if q[0] is not None and q[1] is not None else None


def _nearest(strikes: dict, right: str, target: float):
    best = None
    for k, legs in strikes.items():
        bid, ask, dlt = legs[right]
        if not bid or not ask or dlt is None or bid <= 0:
            continue
        gap = abs(abs(dlt) - target)
        if best is None or gap < best[0]:
            best = (gap, k)
    return best[1] if best and best[0] < 0.05 else None


def open_trade(d: date, b: Board, delta: float, dte: int, lo: int, hi: int) -> Trade | None:
    exps = [e for e in b.chains if lo <= (e - d).days <= hi]
    if not exps:
        return None
    exp = min(exps, key=lambda e: (abs((e - d).days - dte), e))
    ch = b.chains[exp]
    pk, ck = _nearest(ch, "P", delta), _nearest(ch, "C", delta)
    if pk is None or ck is None:
        return None
    p, c = ch[pk]["P"], ch[ck]["C"]
    return Trade(d, exp, pk, ck, {"bidask": p[0] + c[0], "mid": _mid(p) + _mid(c)})


def cost(t: Trade, b: Board, fill: str) -> float | None:
    ch = b.chains.get(t.exp, {})
    if t.put_k not in ch or t.call_k not in ch:
        return None
    p, c = ch[t.put_k]["P"], ch[t.call_k]["C"]
    if fill == "bidask":
        return p[1] + c[1] if p[1] is not None and c[1] is not None else None
    mp, mc = _mid(p), _mid(c)
    return mp + mc if mp is not None and mc is not None else None


def settle(t: Trade, spot: float) -> float:
    return max(t.put_k - spot, 0) + max(spot - t.call_k, 0)


def replay(path: Path, every: int, delta: float, dte: int, lo: int, hi: int, regime_of=None) -> list[Trade]:
    trades, open_, n, last_spot = [], [], 0, None
    for d, b in boards(path):
        for t in list(open_):
            if d >= t.exp:
                spot = b.spot if d == t.exp else last_spot
                for v in VARIANTS:
                    if v not in t.closed:
                        t.closed[v] = (t.exp, (t.quotes[v[0]] - settle(t, spot)) * MULT)
                open_.remove(t)
                continue
            for fill in ("bidask", "mid"):
                v = (fill, "pt50")
                if v in t.closed:
                    continue
                c = cost(t, b, fill)
                trigger = cost(t, b, "mid")      # target is read on the mid in both modes
                if c is not None and trigger is not None and trigger <= t.quotes["mid"] * (1 - TARGET):
                    t.closed[v] = (d, (t.quotes[fill] - c) * MULT)
        if n % every == 0:
            t = open_trade(d, b, delta, dte, lo, hi)
            if t:
                t.regime = regime_of(d) if regime_of else "n/a"
                trades.append(t)
                open_.append(t)
        n += 1
        last_spot = b.spot
    return [t for t in trades if len(t.closed) == len(VARIANTS)]


# ---------- reporting ----------

def summary(trades: list[Trade], v) -> dict:
    pnl = [t.closed[v][1] for t in trades]
    if not pnl:
        return {"n": 0}
    credit = sum(t.quotes[v[0]] for t in trades) * MULT
    days = [(t.closed[v][0] - t.opened).days for t in trades]
    srt = sorted(pnl)
    k = max(1, len(pnl) // 20)
    return {"n": len(pnl), "win": sum(x > 0 for x in pnl) / len(pnl), "avg": st.mean(pnl),
            "roc": sum(pnl) / credit if credit else 0, "worst": srt[0], "p5": srt[int(0.05 * (len(srt) - 1))],
            "sd": st.pstdev(pnl), "days": st.mean(days), "worst5_sum": sum(srt[:k]),
            "gains_sum": sum(x for x in pnl if x > 0)}


def table(rows: list[tuple[str, dict]]) -> str:
    out = ["| | n | win % | avg P/L | return on credit | worst | 5th pct | sd | avg days |",
           "|---|---|---|---|---|---|---|---|---|"]
    for name, s in rows:
        if s["n"] == 0:
            out.append(f"| {name} | 0 | | | | | | | |")
            continue
        out.append(f"| {name} | {s['n']} | {s['win']:.1%} | ${s['avg']:,.0f} | {s['roc']:.1%} | ${s['worst']:,.0f} | "
                   f"${s['p5']:,.0f} | ${s['sd']:,.0f} | {s['days']:.1f} |")
    return "\n".join(out)


def regime_lookup(cache: Path, params):
    from spx_quant.regime import classify
    sys.path.insert(0, str(ROOT / "research" / "rules-pivot"))
    from tier_a import series  # noqa: E402
    vix, v3m, v9d = (series(cache, t, 4) for t in ("VIX", "VIX3M", "VIX9D"))
    days = sorted(d for d in vix if d in v3m)

    def lookup(d: date) -> str:
        i = bisect_left(days, d)
        if i == 0:
            return "unknown"
        p = days[i - 1]
        return classify({"vix": vix[p], "vix3m": v3m[p], "vix9d": v9d.get(p)}, params).state
    return lookup


def report(trades: list[Trade], delta: float, dte: int) -> tuple[str, dict]:
    res = {f"{f}/{e}": summary(trades, (f, e)) for f, e in VARIANTS}
    fills = {"bidask": "bid/ask", "mid": "mid"}
    lines = [f"## SPX short strangle, {delta:.0%} delta, ~{dte} DTE, 1 lot",
             f"{trades[0].opened} to {trades[-1].opened}" if trades else "no trades", "",
             table([(f"{'Hold to expiry' if e == 'hold' else '50% profit target'}, {fills[f]} fills", res[f"{f}/{e}"])
                    for f, e in VARIANTS])]
    base = res["bidask/hold"]
    if base["n"]:
        lines += ["", f"Concentration (hold, bid/ask): worst 5% of trades ${base['worst5_sum']:,.0f} "
                      f"against total gains ${base['gains_sum']:,.0f}."]
    for label, key in (("year", lambda t: str(t.opened.year)), ("regime the day before entry", lambda t: t.regime)):
        groups = defaultdict(list)
        for t in trades:
            groups[key(t)].append(t)
        if len(groups) < 2:
            continue
        rows = [(g, summary(ts, ("bidask", "pt50"))) for g, ts in sorted(groups.items())]
        res[f"by_{label.split()[0]}"] = dict(rows)
        lines += ["", f"### 50% profit target, bid/ask fills, by {label}", "", table(rows)]
    return "\n".join(lines), res


def main() -> None:
    p = load_params()
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--delta", type=float, default=p.strangle["target_delta"])
    ap.add_argument("--dte", type=int, default=p.expiry["target_dte"])
    ap.add_argument("--cboe-cache", type=Path, default=ROOT / ".cache" / "cboe")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    lookup = regime_lookup(a.cboe_cache, p) if (a.cboe_cache / "VIX3M.csv").exists() else None
    trades = replay(a.data, a.every, a.delta, a.dte, p.expiry["dte_min"], p.expiry["dte_max"], lookup)
    text, res = report(trades, a.delta, a.dte)
    print(text)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
