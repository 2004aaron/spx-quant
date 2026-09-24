"""Account profile (US-01): size, margin type, and risk caps that drive every proposal's sizing."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PATH = Path.home() / ".spx-quant" / "profile.json"
MARGIN_TYPES = ("reg_t", "portfolio")
LARGE_TIER_ABOVE = 1_000_000.0  # [UNVALIDATED] mentor: "millions" is the large tier


@dataclass(frozen=True)
class Profile:
    net_liq: float
    margin_type: str
    bp_cap_pct: float = 0.08
    delta_theta_limit: float = 2.0

    @property
    def tier(self) -> str:
        return "large" if self.net_liq >= LARGE_TIER_ABOVE else "small"

    @property
    def bp_cap_dollars(self) -> float:
        return self.net_liq * self.bp_cap_pct

    def __str__(self) -> str:
        return (f"net liq ${self.net_liq:,.0f}  margin {self.margin_type}  tier {self.tier}  "
                f"per-position BP cap {self.bp_cap_pct:.0%} (${self.bp_cap_dollars:,.0f})  "
                f"delta:theta limit 1:{self.delta_theta_limit:g}")


class ProfileError(ValueError):
    pass


def validate(net_liq, margin_type, bp_cap_pct=0.08, delta_theta_limit=2.0) -> Profile:
    try:
        net_liq = float(net_liq)
    except (TypeError, ValueError):
        raise ProfileError(f"net_liq: {net_liq!r} is not a number")
    if net_liq <= 0:
        raise ProfileError(f"net_liq: {net_liq:g} must be positive")
    if margin_type not in MARGIN_TYPES:
        raise ProfileError(f"margin_type: {margin_type!r} must be one of {MARGIN_TYPES}")
    bp_cap_pct = float(bp_cap_pct)
    if not 0 < bp_cap_pct <= 1:
        raise ProfileError(f"bp_cap_pct: {bp_cap_pct:g} must be in (0, 1]")
    delta_theta_limit = float(delta_theta_limit)
    if delta_theta_limit <= 0:
        raise ProfileError(f"delta_theta_limit: {delta_theta_limit:g} must be positive")
    return Profile(net_liq, margin_type, bp_cap_pct, delta_theta_limit)


def save(profile: Profile, path: Path = DEFAULT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(profile), indent=2) + "\n")
    return path


def load(path: Path = DEFAULT_PATH) -> Profile | None:
    if not path.exists():
        return None
    return validate(**json.loads(path.read_text()))
