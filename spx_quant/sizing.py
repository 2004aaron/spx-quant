"""Sizing against the account profile (US-01, US-03) and the delta:theta guardrail.

The buying-power cap is inclusive: a candidate needing exactly the cap fits
(US-03-AC4). Money is compared in whole cents so float noise cannot flip that.
The worst-case limit works the same way on the stress-test loss: contracts are cut
until contracts x loss per lot fits inside max_worst_case_pct of net liquidation.
Buying power is what the broker holds; the worst case is what can actually be lost,
and for a naked option the second can be several times the first.
Remaining buying power (US-13) is a second cap: net liquidation minus what positions
already taken still hold. The per-position cap and the remaining amount both apply.
Delta:theta limit 1:N means |net delta| x N <= theta; delta in share-equivalents,
theta in dollars per day. The ratio does not change with contract count.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .profile import Profile


def cents(x: float) -> int:
    return int(round(x * 100))


def usd(x: float) -> str:
    """$3,300 for whole dollars, $3,312.50 otherwise (the US-13 messages quote whole dollars)."""
    return f"${x:,.0f}" if cents(x) % 100 == 0 else f"${x:,.2f}"


@dataclass
class Sized:
    contracts: int
    bp_per_lot: float
    bp_total: float
    cap: float
    delta_per_lot: float
    theta_per_lot: float
    dt_limit: float
    reasons: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    worst_per_lot: float = 0.0     # dollars lost per lot in the stress test (positive = loss)
    worst_total: float = 0.0
    worst_limit: float = 0.0
    bp_contracts: int = 0          # what the buying-power cap alone would allow
    limited_by: str = ""           # "buying power", "remaining buying power" or "worst case"
    available: float | None = None  # remaining buying power after taken positions (US-13); None = not tracked

    @property
    def ok(self) -> bool:
        return not self.reasons

    @property
    def dt_ratio(self) -> float | None:
        """theta / |delta|, the N in 1:N. None when delta is zero (perfectly flat)."""
        return None if abs(self.delta_per_lot) < 1e-9 else self.theta_per_lot / abs(self.delta_per_lot)

    def dt_text(self) -> str:
        r = self.dt_ratio
        return f"1:{r:.1f}" if r is not None else "1:inf (flat)"

    def as_dict(self) -> dict:
        return {"contracts": self.contracts, "bp_per_lot": self.bp_per_lot, "bp_total": self.bp_total,
                "cap": self.cap, "delta_per_lot": self.delta_per_lot, "theta_per_lot": self.theta_per_lot,
                "dt_limit": self.dt_limit, "dt_ratio": self.dt_ratio, "reasons": self.reasons, "codes": self.codes,
                "worst_per_lot": self.worst_per_lot, "worst_total": self.worst_total, "worst_limit": self.worst_limit,
                "bp_contracts": self.bp_contracts, "limited_by": self.limited_by, "available": self.available}


def delta_theta_ok(delta: float, theta: float, limit: float) -> bool:
    return theta > 0 and abs(delta) * limit <= theta + 1e-9


def size(profile: Profile, bp_per_lot: float, delta_per_lot: float, theta_per_lot: float,
         worst_per_lot: float = 0.0, available: float | None = None) -> Sized:
    cap = profile.bp_cap_dollars
    s = Sized(0, round(bp_per_lot, 2), 0.0, cap, delta_per_lot, theta_per_lot, profile.delta_theta_limit,
              worst_per_lot=round(max(worst_per_lot, 0.0), 2), worst_limit=profile.worst_case_limit)
    if cents(bp_per_lot) <= 0:
        s.reasons.append("buying power could not be computed")
        s.codes.append("bp_unknown")
        return s
    n = s.bp_contracts = cents(cap) // cents(bp_per_lot)
    s.limited_by = "buying power"
    if available is not None:
        s.available = round(available, 2)
        by_available = max(cents(available), 0) // cents(bp_per_lot)
        if by_available < n:
            n, s.limited_by = by_available, "remaining buying power"
        if by_available == 0 and s.bp_contracts > 0:
            s.reasons.append(f"insufficient buying power: {usd(max(available, 0))} available, {usd(bp_per_lot)} needed")
            s.codes.append("over_available")
    if cents(s.worst_per_lot) > 0:
        by_worst = cents(s.worst_limit) // cents(s.worst_per_lot)
        if by_worst < n:
            n, s.limited_by = by_worst, "worst case"
        if by_worst == 0:
            s.reasons.append(f"worst case ${s.worst_per_lot:,.2f} per lot is over the ${s.worst_limit:,.2f} limit "
                             f"({profile.max_worst_case_pct:.0%} of ${profile.net_liq:,.0f})")
            s.codes.append("over_worst_case")
    if s.bp_contracts == 0:
        s.reasons.append(f"needs ${bp_per_lot:,.2f} of buying power per lot; cap is ${cap:,.2f} "
                         f"({profile.bp_cap_pct:.0%} of ${profile.net_liq:,.0f}, {profile.margin_type})")
        s.codes.append("over_cap")
    if theta_per_lot <= 0:
        s.reasons.append(f"theta ${theta_per_lot:,.2f}/day is not positive; not a premium-selling position")
        s.codes.append("theta")
    elif not delta_theta_ok(delta_per_lot, theta_per_lot, profile.delta_theta_limit):
        s.reasons.append(f"delta:theta {s.dt_text()} breaks the 1:{profile.delta_theta_limit:g} limit "
                         f"(delta {delta_per_lot:+.2f} SPY deltas, theta ${theta_per_lot:,.2f}/day per lot)")
        s.codes.append("delta_theta")
    if s.ok:
        s.contracts = n
        s.bp_total = round(n * cents(bp_per_lot) / 100, 2)
        s.worst_total = round(n * cents(s.worst_per_lot) / 100, 2)
    return s
