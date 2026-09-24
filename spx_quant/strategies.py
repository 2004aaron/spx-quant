"""Candidate structure builders. First increment: the delta-matched short strangle (US-03).

Two lessons baked in from the prototype:
  * Filter the chain for liquidity BEFORE selecting by delta. On a dense board the
    exact 16-delta strike is often a thin odd strike next to a heavily traded one.
  * Snap to the nearest listed expiration. Asking for exactly 45 DTE returns nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .params import Params, load_params

MULTIPLIER = 100


@dataclass(frozen=True)
class Strangle:
    exp: date
    dte: int
    put: dict
    call: dict

    @property
    def credit(self) -> float:
        return (self.put["mid"] + self.call["mid"]) * MULTIPLIER

    @property
    def net_delta(self) -> float:
        return (self.put["delta"] + self.call["delta"]) * MULTIPLIER

    def __str__(self) -> str:
        return (f"short strangle {self.exp.isoformat()} ({self.dte} DTE)  "
                f"{self.put['strike']:.0f}P ({self.put['delta']:+.2f}) / {self.call['strike']:.0f}C ({self.call['delta']:+.2f})  "
                f"credit ${self.credit:,.0f}  net delta {self.net_delta:+.1f}")


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


def pick_strangle(rows: list[dict], today: date, params: Params | None = None) -> Strangle | None:
    p = params or load_params()
    s = p.strangle
    cands = [r for r in liquid(rows, p) if s["dte_min"] <= (r["exp"] - today).days <= s["dte_max"]]
    if not cands:
        return None
    exp = min({r["exp"] for r in cands}, key=lambda e: abs((e - today).days - s["target_dte"]))
    leg = [r for r in cands if r["exp"] == exp and r["delta"]]
    puts = [r for r in leg if r["right"] == "P"]
    calls = [r for r in leg if r["right"] == "C"]
    if not puts or not calls:
        return None
    put = min(puts, key=lambda r: abs(abs(r["delta"]) - s["target_delta"]))
    call = min(calls, key=lambda r: abs(abs(r["delta"]) - abs(put["delta"])))
    return Strangle(exp, (exp - today).days, put, call)
