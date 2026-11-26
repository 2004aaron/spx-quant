"""Cboe volatility-index method (the VIX white paper) applied to an SPX option board.

    index(rows, now, rate, days) -> (value, notes)

rows: dicts with root, exp (date), right (C/P), strike, bid, ask. The two expirations that bracket
`days` are priced as variance swaps and interpolated to a constant `days` maturity: 30 is VIX,
93 is VIX3M, 9 is VIX9D, 182 is VIX6M. Steps, as Cboe documents them:
  1. time to settlement in minutes (AM-settled SPX at 9:30 ET, PM-settled SPXW at 16:00 ET)
  2. forward F from the strike where call and put mids are closest: F = K + e^(RT) (C - P)
  3. K0 is the first strike at or below F
  4. out-of-the-money puts below K0 and calls above it, each side stopping after two consecutive
     zero bids; K0 takes the average of its put and call mid
  5. sigma^2 = 2/T * sum(dK/K^2 * e^(RT) * Q(K)) - 1/T * (F/K0 - 1)^2
  6. interpolate the two total variances to `days`, annualize, square root, times 100
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from .. import clock
from ..strategies import expiry_utc

MIN_YEAR = 525_600


def _minutes(root: str, exp: date, now: datetime) -> float:
    return (expiry_utc(root, exp) - now).total_seconds() / 60


def term(rows: list[dict], t_years: float, rate: float) -> tuple[float, dict]:
    """Variance (sigma^2) of one expiration, plus the forward and K0 it used."""
    by_k: dict[float, dict] = {}
    for r in rows:
        mid = (r["bid"] + r["ask"]) / 2 if r["ask"] > 0 else 0.0
        by_k.setdefault(r["strike"], {})[r["right"]] = (r["bid"], mid)
    both = [(k, v["C"][1], v["P"][1]) for k, v in by_k.items() if "C" in v and "P" in v and v["C"][1] > 0 and v["P"][1] > 0]
    if not both:
        raise ValueError("no strike with both a call and a put quote")
    k_star, c, p = min(both, key=lambda x: abs(x[1] - x[2]))
    growth = math.exp(rate * t_years)
    fwd = k_star + growth * (c - p)
    strikes = sorted(by_k)
    below = [k for k in strikes if k <= fwd]
    if not below:
        raise ValueError("no strike at or below the forward")
    k0 = below[-1]

    def side(ks, right):
        out, zeros = [], 0
        for k in ks:
            bid, mid = by_k[k].get(right, (0.0, 0.0))
            if bid <= 0:
                zeros += 1
                if zeros == 2:
                    break
                continue
            zeros = 0
            out.append((k, mid))
        return out

    puts = side([k for k in reversed(strikes) if k < k0], "P")
    calls = side([k for k in strikes if k > k0], "C")
    at = [by_k[k0][x][1] for x in ("C", "P") if x in by_k[k0]]
    used = sorted(puts + [(k0, sum(at) / len(at))] + calls)
    if len(used) < 3:
        raise ValueError("fewer than three usable strikes")
    ks = [k for k, _ in used]
    total = 0.0
    for i, (k, q) in enumerate(used):
        dk = (ks[1] - ks[0]) if i == 0 else (ks[-1] - ks[-2]) if i == len(ks) - 1 else (ks[i + 1] - ks[i - 1]) / 2
        total += dk / k ** 2 * growth * q
    var = 2 / t_years * total - (fwd / k0 - 1) ** 2 / t_years
    zero = sum(1 for v in by_k.values() for b, _ in v.values() if b <= 0)
    return var, {"forward": round(fwd, 2), "k0": k0, "strikes": len(used), "lo": ks[0], "hi": ks[-1],
                 "quoted": sum(len(v) for v in by_k.values()), "zero_bids": zero, "vol": round(100 * math.sqrt(max(var, 0)), 2)}


def weekly(exp: date) -> bool:
    """Cboe uses Friday expirations only, or the Thursday before a Friday holiday."""
    return exp.weekday() == 4 or (exp.weekday() == 3 and not clock.trading_day(exp + timedelta(days=1)))


def bracket(rows: list[dict], now: datetime, days: float) -> tuple[tuple, tuple]:
    """The (root, exp) just before and just after the target, by minutes to settlement, among Friday
    expirations; on a third Friday the standard AM-settled SPX series is the one Cboe uses."""
    seen: dict[tuple, float] = {}
    for r in rows:
        key = (r["root"], r["exp"])
        if key not in seen:
            seen[key] = _minutes(r["root"], r["exp"], now)
    by_date: dict[date, tuple] = {}
    for (root, exp), m in seen.items():
        if m > 0 and weekly(exp) and (exp not in by_date or root == "SPX"):
            by_date[exp] = (root, exp, m)
    target = days * 1440
    near = [x for x in by_date.values() if x[2] <= target]
    far = [x for x in by_date.values() if x[2] > target]
    if not near or not far:
        raise ValueError(f"no expirations bracket {days:g} days")
    return max(near, key=lambda x: x[2]), min(far, key=lambda x: x[2])


def index(rows: list[dict], now: datetime, rate: float, days: float) -> tuple[float, dict]:
    (r1, e1, m1), (r2, e2, m2) = bracket(rows, now, days)
    v1, i1 = term([r for r in rows if r["root"] == r1 and r["exp"] == e1], m1 / MIN_YEAR, rate)
    v2, i2 = term([r for r in rows if r["root"] == r2 and r["exp"] == e2], m2 / MIN_YEAR, rate)
    target = days * 1440
    t1, t2 = m1 / MIN_YEAR, m2 / MIN_YEAR
    w = (m2 - target) / (m2 - m1)
    var = (t1 * v1 * w + t2 * v2 * (1 - w)) * MIN_YEAR / target
    if var <= 0:
        raise ValueError("non-positive variance")
    return round(100 * math.sqrt(var), 2), {"near": f"{r1} {e1}", "far": f"{r2} {e2}", **{f"near_{k}": v for k, v in i1.items()},
                                            **{f"far_{k}": v for k, v in i2.items()}}
