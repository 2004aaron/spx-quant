"""VIX term-structure regime classifier (US-02) and stand-down gate (US-04).

Regime = (term-structure state, volatility bucket).
  state  : contango | flat | backwardation, from slope = (VIX3M - VIX) / VIX
  bucket : crushed | low | normal | elevated | panic, from spot VIX
VIX and VIX3M are required; VIX9D and VIX6M are shown when present. A missing
required point yields "unknown" and names the point, never a guess (US-02-AC3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import clock
from .params import Params, load_params

STATES = ("contango", "flat", "backwardation", "unknown")
BUCKETS = ("crushed", "low", "normal", "elevated", "panic", "unknown")
REQUIRED = ("vix", "vix3m")
SHOWN = ("vix9d", "vix", "vix3m", "vix6m")


@dataclass(frozen=True)
class Regime:
    state: str
    bucket: str
    slope: float | None
    inputs: dict[str, float | None] = field(default_factory=dict)
    reason: str = ""
    asof: datetime | None = None

    @property
    def known(self) -> bool:
        return self.state != "unknown" and self.bucket != "unknown"

    def as_dict(self) -> dict:
        return {"state": self.state, "bucket": self.bucket, "slope": self.slope, "inputs": self.inputs,
                "reason": self.reason, "asof": self.asof.isoformat() if self.asof else None}

    def __str__(self) -> str:
        stamp = f"  asof {clock.fmt(self.asof)}" if self.asof else ""
        if not self.known:
            return f"regime: unknown ({self.reason}){stamp}"
        vals = " ".join(f"{k.upper()}={v:.2f}" for k, v in self.inputs.items() if v is not None)
        return f"regime: {self.state} / {self.bucket}  slope={self.slope:+.3f}  {vals}{stamp}"


def classify(curve: dict[str, float | None], params: Params | None = None, asof: datetime | None = None) -> Regime:
    p = params or load_params()
    shown = {k: curve.get(k) for k in SHOWN}
    missing = [k for k in REQUIRED if curve.get(k) is None]
    if missing:
        return Regime("unknown", "unknown", None, shown, f"{', '.join(k.upper() for k in missing)} missing", asof)
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
    return Regime(state, bucket, round(slope, 4), shown, "", asof)


def gate(regime: Regime, params: Params | None = None) -> tuple[bool, list[str]]:
    """Alpha default: stand down in backwardation and outside the volatility floor/ceiling.

    The historical evidence in docs/backtest-findings.md contradicts the backwardation
    rule; it stays as the Alpha default and is tagged "tested, not supported".
    """
    p = params or load_params()
    if not regime.known:
        return False, [f"regime could not be identified: {regime.reason}"]
    reasons: list[str] = []
    vix = regime.inputs["vix"]
    b = p.vol_buckets
    if regime.state == "backwardation":
        reasons.append(f"VIX term structure inverted (backwardation): slope {regime.slope:+.3f}")
    if regime.bucket == "crushed":
        reasons.append(f"VIX {vix:.1f} below the {b['crushed_below']:g} floor: premium too thin to be worth the risk")
    if regime.bucket == "panic":
        where = "above" if vix > b["elevated_below"] else "at"
        reasons.append(f"VIX {vix:.1f} {where} the {b['elevated_below']:g} ceiling: panic-level volatility")
    return not reasons, reasons
