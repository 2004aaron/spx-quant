"""Risk block (US-05): probability of profit, expected value, CVaR, breakevens, stress rows.

Model, stated in every alert:
  * The position is held to expiration and settles at intrinsic value.
  * The index follows a lognormal path at realized vol = ATM IV x (1 - vrp_haircut),
    drifting at the risk-free rate, plus a one-time crash of crash_size that arrives
    with annual probability crash_prob_annual (Poisson).
Under risk-neutral pricing every option has EV = 0, so any positive EV comes from
those two knobs. Set the crash probability to zero and the model collects skew for
free. That is why implied_crash_per_year is reported: with vrp_haircut held at zero,
it is the crash rate that makes EV exactly zero, i.e. how much tail the market is
paying for. The required knobs are never defaulted (US-05-AC3).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime

from .params import Params, load_params
from .strategies import Position, years_to

REQUIRED = ("risk.vrp_haircut", "risk.crash_prob_annual", "risk.crash_size", "risk.rate")
STRESS = ("risk.worst_case_move", "risk.worst_case_vol_points")


@dataclass
class Risk:
    pop: float                  # probability, 0..1
    ev: float                   # dollars, all contracts
    cvar5: float                # dollars, average of the worst 5% of outcomes (negative = loss)
    cvar1: float                # dollars, average of the worst 1% of outcomes
    breakevens: list[float]     # index levels at expiration
    max_profit: float           # dollars, credit at mid
    max_loss: float | None      # dollars, defined-risk structures only
    stress: list[tuple[float, float]]  # (instant index move, dollars)
    ann_return_bp: float        # percent: EV / buying power, annualized over DTE
    implied_crash_per_year: float | None
    assumptions: dict
    worst_case_stress: float = 0.0  # dollars: instant index move plus a volatility jump (user flow screen 8)

    @property
    def worst_case(self) -> float:
        return self.worst_case_stress

    def as_dict(self) -> dict:
        d = asdict(self)
        d["worst_case"] = self.worst_case
        return d


def atm_iv(rows: list[dict], root: str, exp: date, spot: float) -> float | None:
    """Mean IV of the put and call struck nearest spot on that expiration."""
    same = [r for r in rows if r["root"] == root and r["exp"] == exp and r["iv"] > 0]
    vals = []
    for right in ("P", "C"):
        side = [r for r in same if r["right"] == right]
        if side:
            vals.append(min(side, key=lambda r: abs(r["strike"] - spot))["iv"])
    return sum(vals) / len(vals) if vals else None


def _grid(spot: float, t: float, sigma: float, lam: float, jump: float, rate: float, n: int):
    """Terminal index levels and their probabilities for the diffusion + crash mixture."""
    s = sigma * math.sqrt(t)
    m = (rate - 0.5 * sigma * sigma) * t
    c = math.log(1 + jump)
    pc = 1 - math.exp(-lam * t)
    lo, hi = m + min(c, 0.0) - 8 * s, m + max(c, 0.0) + 8 * s
    dx = (hi - lo) / (n - 1)
    xs = [lo + i * dx for i in range(n)]
    ws = [(1 - pc) * math.exp(-0.5 * ((x - m) / s) ** 2) + pc * math.exp(-0.5 * ((x - m - c) / s) ** 2) for x in xs]
    total = sum(ws)
    return [spot * math.exp(x) for x in xs], [w / total for w in ws]


def _ev(pos: Position, levels, probs) -> float:
    return sum(p * pos.payoff(s) for s, p in zip(levels, probs))


def _cvar(outcomes: list[tuple[float, float]], alpha: float) -> float:
    acc = tail = 0.0
    for pnl, p in sorted(outcomes):
        take = min(p, alpha - acc)
        if take <= 0:
            break
        tail += take * pnl
        acc += take
    return tail / alpha


def _breakevens(levels, pnls) -> list[float]:
    out = []
    for i in range(1, len(levels)):
        a, b = pnls[i - 1], pnls[i]
        if (a <= 0 < b) or (a > 0 >= b):
            s0, s1 = levels[i - 1], levels[i]
            out.append(round(s0 + (s1 - s0) * (0 - a) / (b - a), 2))
    return out


def implied_crash(pos: Position, spot: float, t: float, sigma: float, jump: float, rate: float,
                  n: int = 401, hi: float = 50.0) -> float | None:
    """Crash rate per year that zeroes EV with vrp_haircut = 0. 0.0 if the premium pays for no tail at all."""
    def ev(lam):
        return _ev(pos, *_grid(spot, t, sigma, lam, jump, rate, n))
    if ev(0.0) <= 0:
        return 0.0
    if ev(hi) > 0:
        return None
    lo = 0.0
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if ev(mid) > 0 else (lo, mid)
    return round(0.5 * (lo + hi), 3)


def compute(pos: Position, contracts: int, bp_total: float, spot: float, sigma_atm: float,
            now: datetime, params: Params | None = None) -> Risk:
    p = params or load_params()
    vrp, lam, jump, rate = (p.need(*k.split(".")) for k in REQUIRED)
    wc_move, wc_vol = (p.need(*k.split(".")) for k in STRESS)
    n = int(p.risk.get("grid_points", 2001))
    t = years_to(pos.root, pos.exp, now)
    sigma = sigma_atm * (1 - vrp)
    levels, probs = _grid(spot, t, sigma, lam, jump, rate, n)
    per_lot = [pos.payoff(s) for s in levels]
    k = contracts
    outcomes = [(v * k, pr) for v, pr in zip(per_lot, probs)]
    ev = sum(v * pr for v, pr in outcomes)
    pop = sum(pr for v, pr in outcomes if v > 0)
    base = pos.value(spot, now, rate)
    stress = [(mv, round((pos.value(spot * (1 + mv), now, rate) - base) * k, 2)) for mv in p.risk.get("stress_moves", [])]
    max_loss = round((pos.width * 100 - pos.credit) * k, 2) if pos.defined_risk else None
    worst = (pos.value(spot * (1 + wc_move), now, rate, wc_vol / 100) - base) * k
    ann = ev / bp_total * 365 / max(pos.dte, 1) * 100 if bp_total > 0 else 0.0
    assumptions = {
        "hold": "held to expiration, settled at intrinsic value",
        "atm_iv": round(sigma_atm, 4), "realized_vol": round(sigma, 4), "vrp_haircut": vrp,
        "crash_prob_annual": lam, "crash_size": jump, "rate": rate, "years_to_expiry": round(t, 4),
        "worst_case_move": wc_move, "worst_case_vol_points": wc_vol,
        "tags": {k2: p.tag(k2) for k2 in REQUIRED + STRESS},
    }
    return Risk(
        pop=round(pop, 4), ev=round(ev, 2), cvar5=round(_cvar(outcomes, 0.05), 2), cvar1=round(_cvar(outcomes, 0.01), 2),
        breakevens=_breakevens(levels, per_lot), max_profit=round(pos.credit * k, 2), max_loss=max_loss,
        stress=stress, ann_return_bp=round(ann, 2),
        implied_crash_per_year=implied_crash(pos, spot, t, sigma_atm, jump, rate),
        assumptions=assumptions, worst_case_stress=round(worst, 2),
    )


def assumptions_text(a: dict) -> str:
    return (f"Model estimates, {a['hold']}. Index lognormal at realized vol {a['realized_vol']:.1%} "
            f"(ATM IV {a['atm_iv']:.1%} less a {a['vrp_haircut']:.0%} volatility risk premium), drift {a['rate']:.1%}/yr, "
            f"plus a {a['crash_size']:.0%} crash arriving {a['crash_prob_annual']:g} times per year. "
            f"Worst case is a stress test: index {a['worst_case_move']:+.0%} at once with volatility up "
            f"{a['worst_case_vol_points']:g} points. "
            f"Input tags: " + ", ".join(f"{k.split('.')[1]} {v}" for k, v in a["tags"].items()) + ".")
