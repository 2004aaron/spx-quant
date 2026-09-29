"""Buying-power models for Reg-T and portfolio margin, per one lot.

Reg-T follows the Cboe rule for broad-based index options. Portfolio margin is the
regulatory TIMS-style floor: worst loss over ten equidistant index moves from -8%
to +6%, legs repriced at their own IV. Broker house requirements run higher, so
pm_house_multiplier exists to calibrate against a real broker quote (A-KR2).
"""
from __future__ import annotations

from datetime import datetime

from .params import Params, load_params
from .strategies import MULTIPLIER, Position


def _regt_naked(leg, spot: float, m: dict) -> float:
    k = leg.strike
    if leg.right == "P":
        otm = max(0.0, spot - k)
        floor = m["regt_min_pct"] * k
    else:
        otm = max(0.0, k - spot)
        floor = m["regt_min_pct"] * spot
    return (leg.mid + max(m["regt_index_pct"] * spot - otm, floor)) * MULTIPLIER


def regt(pos: Position, spot: float, params: Params) -> float:
    m = params.margin
    if pos.defined_risk:
        return max(pos.width * MULTIPLIER - pos.credit, 0.0)
    shorts = [l for l in pos.legs if l.qty < 0]
    reqs = [(_regt_naked(l, spot, m), l.mid * MULTIPLIER) for l in shorts]
    if len(reqs) == 1:
        return reqs[0][0]
    worst = max(range(len(reqs)), key=lambda i: reqs[i][0])
    return reqs[worst][0] + sum(prem for i, (_, prem) in enumerate(reqs) if i != worst)


def pm_scenarios(pos: Position, spot: float, now: datetime, params: Params) -> list[tuple[float, float]]:
    """(index move, P/L per lot) at each TIMS valuation point."""
    m, rate = params.margin, params.risk.get("rate", 0.0)
    n = int(m["pm_points"])
    moves = [m["pm_down"] + i * (m["pm_up"] - m["pm_down"]) / (n - 1) for i in range(n)]
    base = pos.value(spot, now, rate)
    return [(round(mv, 4), round(pos.value(spot * (1 + mv), now, rate) - base, 2)) for mv in moves]


def portfolio(pos: Position, spot: float, now: datetime, params: Params) -> float:
    m = params.margin
    worst = -min(pnl for _, pnl in pm_scenarios(pos, spot, now, params))
    floor = m["pm_min_per_contract"] * sum(1 for l in pos.legs if l.qty < 0)
    req = max(worst, floor) * m["pm_house_multiplier"]
    if pos.defined_risk:
        req = min(req, max(pos.width * MULTIPLIER - pos.credit, floor))
    return req


def bp_per_lot(pos: Position, spot: float, margin_type: str, now: datetime, params: Params | None = None) -> float:
    p = params or load_params()
    if margin_type == "reg_t":
        return round(regt(pos, spot, p), 2)
    if margin_type == "portfolio":
        return round(portfolio(pos, spot, now, p), 2)
    raise ValueError(f"unknown margin type {margin_type!r}")
