"""Sizing against the account profile (US-01, US-03) and the delta:theta guardrail.

The buying-power cap is inclusive: a candidate needing exactly the cap fits
(US-03-AC4). Money is compared in whole cents so float noise cannot flip that.
Delta:theta limit 1:N means |net delta| x N <= theta; delta in share-equivalents,
theta in dollars per day. The ratio does not change with contract count.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .profile import Profile


def cents(x: float) -> int:
    return int(round(x * 100))


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
                "dt_limit": self.dt_limit, "dt_ratio": self.dt_ratio, "reasons": self.reasons, "codes": self.codes}


def delta_theta_ok(delta: float, theta: float, limit: float) -> bool:
    return theta > 0 and abs(delta) * limit <= theta + 1e-9


def size(profile: Profile, bp_per_lot: float, delta_per_lot: float, theta_per_lot: float) -> Sized:
    cap = profile.bp_cap_dollars
    s = Sized(0, round(bp_per_lot, 2), 0.0, cap, delta_per_lot, theta_per_lot, profile.delta_theta_limit)
    if cents(bp_per_lot) <= 0:
        s.reasons.append("buying power could not be computed")
        s.codes.append("bp_unknown")
        return s
    n = cents(cap) // cents(bp_per_lot)
    if n == 0:
        s.reasons.append(f"needs ${bp_per_lot:,.2f} of buying power per lot; cap is ${cap:,.2f} "
                         f"({profile.bp_cap_pct:.0%} of ${profile.net_liq:,.0f}, {profile.margin_type})")
        s.codes.append("over_cap")
    if theta_per_lot <= 0:
        s.reasons.append(f"theta ${theta_per_lot:,.2f}/day is not positive; not a premium-selling position")
        s.codes.append("theta")
    elif not delta_theta_ok(delta_per_lot, theta_per_lot, profile.delta_theta_limit):
        s.reasons.append(f"delta:theta {s.dt_text()} breaks the 1:{profile.delta_theta_limit:g} limit "
                         f"(delta {delta_per_lot:+.2f} SPX-eq sh, theta ${theta_per_lot:,.2f}/day per lot)")
        s.codes.append("delta_theta")
    if s.ok:
        s.contracts = n
        s.bp_total = round(n * cents(bp_per_lot) / 100, 2)
    return s
