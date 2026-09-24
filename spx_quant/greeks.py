"""Black-Scholes pricing and greeks for European index options. Stdlib only."""
from __future__ import annotations

import math
from dataclasses import dataclass


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float  # per 1 vol point (0.01)


def bs(spot: float, strike: float, t_years: float, vol: float, right: str, rate: float = 0.0) -> Greeks:
    if t_years <= 0 or vol <= 0:
        intrinsic = max(0.0, spot - strike) if right == "C" else max(0.0, strike - spot)
        return Greeks(intrinsic, 0.0, 0.0, 0.0, 0.0)
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = math.exp(-rate * t_years)
    if right == "C":
        price = spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (-spot * _norm_pdf(d1) * vol / (2 * sqrt_t) - rate * strike * disc * _norm_cdf(d2)) / 365.0
    elif right == "P":
        price = strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta = (-spot * _norm_pdf(d1) * vol / (2 * sqrt_t) + rate * strike * disc * _norm_cdf(-d2)) / 365.0
    else:
        raise ValueError(f"right must be 'C' or 'P', got {right!r}")
    gamma = _norm_pdf(d1) / (spot * vol * sqrt_t)
    vega = spot * _norm_pdf(d1) * sqrt_t / 100.0
    return Greeks(price, delta, gamma, theta, vega)


def implied_vol(price: float, spot: float, strike: float, t_years: float, right: str, rate: float = 0.0) -> float | None:
    """Bisection on vol in [0.1%, 500%]. Returns None when price is outside the no-arbitrage band."""
    lo, hi = 0.001, 5.0
    if price < bs(spot, strike, t_years, lo, right, rate).price or price > bs(spot, strike, t_years, hi, right, rate).price:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs(spot, strike, t_years, mid, right, rate).price < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)
