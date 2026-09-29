"""Candidate structure builders (US-03): strangle, naked put, put vertical, iron condor.

Lessons from the prototype, kept here on purpose:
  * Filter the chain for liquidity BEFORE selecting by delta. On a dense board the
    exact 16-delta strike is often a thin odd strike next to a heavily traded one.
  * Snap to the nearest listed expiration. Asking for exactly 45 DTE returns nothing.
  * "Delta neutral" means matching deltas on both sides, not 16-delta put / 10-delta call.
All quantities are per one lot; sizing multiplies later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from . import clock
from .greeks import bs
from .params import Params, load_params

MULTIPLIER = 100
NOTIONAL = {"_SPX": 1.0, "_XSP": 0.1}  # delta is reported in SPX-equivalent shares so 10 XSP lots == 1 SPX lot
AM_SETTLED_ROOTS = {"SPX"}  # SPX standard monthlies settle on the open; SPXW and XSP settle on the close
BUILDERS = ("strangle", "naked_put", "put_vertical", "iron_condor")
DEFINED_RISK = {"put_vertical", "iron_condor"}


@dataclass(frozen=True)
class Leg:
    row: dict
    qty: int  # -1 short, +1 long, per lot

    def __getattr__(self, name):
        row = self.__dict__.get("row", {})
        if name.startswith("__") or name not in row:
            raise AttributeError(name)
        return row[name]

    def as_dict(self) -> dict:
        r = self.row
        return {"sym": r["sym"], "right": r["right"], "strike": r["strike"], "exp": r["exp"].isoformat(),
                "qty": self.qty, "bid": r["bid"], "ask": r["ask"], "mid": r["mid"], "iv": r["iv"],
                "delta": r["delta"], "oi": r["oi"], "vol": r["vol"]}


def expiry_utc(root: str, exp: date) -> datetime:
    t = time(9, 30) if root in AM_SETTLED_ROOTS else time(16, 0)
    return clock.local_to_utc("ET", datetime.combine(exp, t))


def years_to(root: str, exp: date, now: datetime) -> float:
    return max((expiry_utc(root, exp) - now).total_seconds() / (365.0 * 86400), 1 / (365.0 * 24))


@dataclass
class Position:
    strategy: str
    ticker: str
    root: str
    exp: date
    dte: int
    legs: list[Leg]
    width: float = 0.0  # strike distance of the widest spread, defined-risk structures only

    @property
    def credit(self) -> float:
        """Per-lot credit at mid, dollars."""
        return round(-sum(l.qty * l.mid for l in self.legs) * MULTIPLIER, 2)

    @property
    def credit_range(self) -> tuple[float, float]:
        """(natural, far) per-lot credit: sell at bid and buy at ask, vs sell at ask and buy at bid."""
        lo = -sum(l.qty * (l.bid if l.qty < 0 else l.ask) for l in self.legs) * MULTIPLIER
        hi = -sum(l.qty * (l.ask if l.qty < 0 else l.bid) for l in self.legs) * MULTIPLIER
        return round(lo, 2), round(hi, 2)

    @property
    def notional(self) -> float:
        return NOTIONAL.get(self.ticker, 1.0)

    @property
    def net_delta(self) -> float:
        """SPX-equivalent shares per lot, from exchange deltas (XSP counts one tenth)."""
        return round(sum(l.qty * l.delta for l in self.legs) * MULTIPLIER * self.notional, 3)

    @property
    def defined_risk(self) -> bool:
        return self.strategy in DEFINED_RISK

    def theta(self, spot: float, now: datetime, rate: float) -> float:
        """Dollars per calendar day per lot (positive for a net seller), Black-Scholes on each leg's IV."""
        t = years_to(self.root, self.exp, now)
        return round(sum(l.qty * bs(spot, l.strike, t, l.iv, l.right, rate).theta for l in self.legs) * MULTIPLIER, 2)

    def value(self, spot: float, now: datetime, rate: float, iv_shift: float = 0.0) -> float:
        """Model value per lot (negative for a net short), each leg at its own IV plus iv_shift."""
        t = years_to(self.root, self.exp, now)
        return sum(l.qty * bs(spot, l.strike, t, max(l.iv + iv_shift, 1e-4), l.right, rate).price
                   for l in self.legs) * MULTIPLIER

    def payoff(self, s_t: float) -> float:
        """P/L per lot if held to expiration and settled at s_t."""
        intrinsic = sum(l.qty * (max(0.0, s_t - l.strike) if l.right == "C" else max(0.0, l.strike - s_t))
                        for l in self.legs)
        return self.credit + intrinsic * MULTIPLIER

    def label(self) -> str:
        return self.strategy.replace("_", " ")

    def legs_text(self) -> str:
        parts = []
        for l in sorted(self.legs, key=lambda l: (l.right, l.strike)):
            parts.append(f"{'-' if l.qty < 0 else '+'}{l.strike:g}{l.right}")
        return " ".join(parts)

    def __str__(self) -> str:
        return (f"{self.label()} {self.ticker.lstrip('_')} {self.exp.isoformat()} ({self.dte} DTE)  {self.legs_text()}  "
                f"credit ${self.credit:,.0f}/lot  net delta {self.net_delta:+.1f}")


def liquid(rows: list[dict], params: Params | None = None) -> list[dict]:
    p = (params or load_params()).liquidity
    out = []
    for r in rows:
        if r["bid"] <= 0 or r["ask"] <= 0 or r["mid"] < p["min_mid"]:
            continue
        if (r["ask"] - r["bid"]) / r["mid"] > p["max_spread_pct"]:
            continue
        if r["oi"] >= p["min_open_interest"] or r["vol"] >= p["min_volume"]:
            out.append(r)
    return out


def expiries(rows: list[dict], today: date, params: Params) -> list[tuple[str, date, list[dict]]]:
    """Liquid rows in the DTE window grouped by (root, expiration), nearest the target first.
    Ties go to close-settled roots, which mark and settle on the same index close the engine sees."""
    e = params.expiry
    groups: dict[tuple[str, date], list[dict]] = {}
    for r in liquid(rows, params):
        d = (r["exp"] - today).days
        if e["dte_min"] <= d <= e["dte_max"] and r["delta"]:
            groups.setdefault((r["root"], r["exp"]), []).append(r)
    keys = sorted(groups, key=lambda k: (abs((k[1] - today).days - e["target_dte"]), k[0] in AM_SETTLED_ROOTS, k[1]))
    return [(root, exp, groups[(root, exp)]) for root, exp in keys]


def _nearest_delta(rows: list[dict], target: float) -> dict | None:
    return min(rows, key=lambda r: (abs(abs(r["delta"]) - target), r["strike"])) if rows else None


def _wing(rows: list[dict], short: dict, width: float) -> dict | None:
    if short["right"] == "P":
        pool = [r for r in rows if r["strike"] < short["strike"]]
        target = short["strike"] - width
    else:
        pool = [r for r in rows if r["strike"] > short["strike"]]
        target = short["strike"] + width
    return min(pool, key=lambda r: (abs(r["strike"] - target), r["strike"])) if pool else None


def build(strategy: str, ticker: str, spot: float, rows: list[dict], today: date,
          params: Params | None = None) -> Position | None:
    """First expiration (nearest the target DTE) on which the structure can be built from liquid strikes."""
    p = params or load_params()
    for root, exp, group in expiries(rows, today, p):
        puts = [r for r in group if r["right"] == "P"]
        calls = [r for r in group if r["right"] == "C"]
        legs, width = _legs(strategy, spot, puts, calls, p)
        if legs:
            return Position(strategy, ticker, root, exp, (exp - today).days, legs, width)
    return None


def _legs(strategy: str, spot: float, puts: list[dict], calls: list[dict], p: Params) -> tuple[list[Leg] | None, float]:
    if strategy == "strangle":
        put = _nearest_delta(puts, p.strangle["target_delta"])
        call = _nearest_delta(calls, abs(put["delta"])) if put else None
        return ([Leg(put, -1), Leg(call, -1)], 0.0) if put and call else (None, 0.0)
    if strategy == "naked_put":
        put = _nearest_delta(puts, p.naked_put["target_delta"])
        return ([Leg(put, -1)], 0.0) if put else (None, 0.0)
    if strategy == "put_vertical":
        c = p.put_vertical
        short = _nearest_delta(puts, c["short_delta"])
        long = _wing(puts, short, c["width_pct"] * spot) if short else None
        if not (short and long):
            return None, 0.0
        return [Leg(short, -1), Leg(long, 1)], short["strike"] - long["strike"]
    if strategy == "iron_condor":
        c = p.iron_condor
        sp = _nearest_delta(puts, c["short_delta"])
        sc = _nearest_delta(calls, abs(sp["delta"])) if sp else None
        if not (sp and sc):
            return None, 0.0
        lp, lc = _wing(puts, sp, c["width_pct"] * spot), _wing(calls, sc, c["width_pct"] * spot)
        if not (lp and lc):
            return None, 0.0
        width = max(sp["strike"] - lp["strike"], lc["strike"] - sc["strike"])
        return [Leg(sp, -1), Leg(lp, 1), Leg(sc, -1), Leg(lc, 1)], width
    raise ValueError(f"unknown strategy {strategy!r}; expected one of {BUILDERS}")


def pick_strangle(rows: list[dict], today: date, params: Params | None = None,
                  ticker: str = "_SPX", spot: float = 0.0) -> Position | None:
    return build("strangle", ticker, spot, rows, today, params)
