"""VIX term-structure regime classifier (US-02).

Regime = (term-structure state, volatility bucket).
  state  : contango | flat | backwardation, from slope = (VIX3M - VIX) / VIX
  bucket : crushed | low | normal | elevated | panic, from spot VIX
A missing input yields state "unknown" and never a guess (US-02-AC3).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .params import Params, load_params

STATES = ("contango", "flat", "backwardation", "unknown")
BUCKETS = ("crushed", "low", "normal", "elevated", "panic", "unknown")
REQUIRED = ("vix9d", "vix", "vix3m")


@dataclass(frozen=True)
class Regime:
    state: str
    bucket: str
    slope: float | None
    inputs: dict[str, float | None] = field(default_factory=dict)
    reason: str = ""

    @property
    def known(self) -> bool:
        return self.state != "unknown" and self.bucket != "unknown"

    def __str__(self) -> str:
        if not self.known:
            return f"regime: unknown ({self.reason})"
        vals = " ".join(f"{k.upper()}={v:.2f}" for k, v in self.inputs.items() if v is not None)
        return f"regime: {self.state} / {self.bucket}  slope={self.slope:+.3f}  {vals}"


def classify(curve: dict[str, float | None], params: Params | None = None) -> Regime:
    p = params or load_params()
    missing = [k for k in REQUIRED if curve.get(k) is None]
    if missing:
        return Regime("unknown", "unknown", None, dict(curve), f"{', '.join(k.upper() for k in missing)} missing")
    vix, vix3m = float(curve["vix"]), float(curve["vix3m"])
    slope = (vix3m - vix) / vix
    r = p.regime
    if slope >= r["contango_slope"]:
        state = "contango"
    elif slope <= r["backwardation_slope"]:
        state = "backwardation"
    else:
        state = "flat"
    b = p.vol_buckets
    if vix < b["crushed_below"]:
        bucket = "crushed"
    elif vix < b["low_below"]:
        bucket = "low"
    elif vix < b["normal_below"]:
        bucket = "normal"
    elif vix < b["elevated_below"]:
        bucket = "elevated"
    else:
        bucket = "panic"
    return Regime(state, bucket, round(slope, 4), {k: curve.get(k) for k in ("vix9d", "vix", "vix3m", "vix6m")})


def gate(regime: Regime, params: Params | None = None) -> tuple[bool, list[str]]:
    """Alpha default: stand down in backwardation and in crushed/panic buckets (US-04).

    The historical evidence in docs/backtest-findings.md contradicts the backwardation
    rule; it stays as the Alpha default and US-13 is the planned replacement.
    """
    p = params or load_params()
    reasons: list[str] = []
    if not regime.known:
        return False, [f"regime unknown: {regime.reason}"]
    if regime.state == "backwardation":
        reasons.append(f"VIX term structure inverted: slope {regime.slope:+.3f}")
    if regime.bucket == "crushed":
        reasons.append(f"VIX {regime.inputs['vix']:.1f} below floor {p.vol_buckets['crushed_below']:.1f}: premium too thin for the tail")
    if regime.bucket == "panic":
        reasons.append(f"VIX {regime.inputs['vix']:.1f} in panic bucket: sample too small to support any rule")
    return not reasons, reasons
