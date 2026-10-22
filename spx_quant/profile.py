"""Account profile (US-01): size, margin type, risk caps and notification address.

Three caps apply to every proposal: buying power per position (bp_cap_pct), the
delta:theta ratio, and the stress-test worst case (max_worst_case_pct of net
liquidation; see analytics.stress_loss_per_lot).

Account tiers (decided 2026-10-06, all [UNVALIDATED]; docs/operations.md has the reasoning):

  tier      net liq             margin                 delta:theta default
  starter   under $100,000      Reg-T only             1:2
  standard  $100,000 to $1M     Reg-T or portfolio     1:2
  large     $1,000,000 and up   Reg-T or portfolio     1:7

Delta in the ratio is SPY-weighted (see strategies.SPY_WEIGHT). Defaults for every
tier: 8% of net liq in buying power per position, 5% of net liq worst case.

Lives in a local JSON file that is never committed (QR-5). Each pilot user has
their own file; the path is passed to every command with --profile.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

HOME = Path(os.environ.get("SPX_QUANT_HOME", Path.home() / ".spx-quant"))
DEFAULT_PATH = HOME / "profile.json"
MARGIN_TYPES = ("reg_t", "portfolio")
CHANNELS = ("none", "email", "discord", "gmail")  # gmail: queued, sent by the scheduled task's Gmail connector
PM_MIN_NET_LIQ = 100_000.0      # tastytrade keeps portfolio margin active at $100,000+ ($125,000 to open)
LARGE_TIER_ABOVE = 1_000_000.0  # [UNVALIDATED] mentor call, Aug 2026: "millions" is where 1:2 becomes too directional
DT_LIMIT = {"starter": 2.0, "standard": 2.0, "large": 7.0}  # [UNVALIDATED] mentor call: 1:2 "is the limit"; millions "closer to 1:10, 1:7"
DEFAULT_BP_CAP = 0.08           # [UNVALIDATED] proposal US-01-AC1; about 3 to 6 positions inside 25-50% total buying power
DEFAULT_MAX_WORST_CASE = 0.05   # [UNVALIDATED] six positions at the cap lose at most ~30% in the stress test


def tier_for(net_liq: float) -> str:
    if net_liq >= LARGE_TIER_ABOVE:
        return "large"
    return "standard" if net_liq >= PM_MIN_NET_LIQ else "starter"


@dataclass(frozen=True)
class Profile:
    net_liq: float
    margin_type: str
    bp_cap_pct: float = DEFAULT_BP_CAP
    delta_theta_limit: float = 2.0
    notify_channel: str = "none"
    email_to: str = ""
    max_worst_case_pct: float = DEFAULT_MAX_WORST_CASE

    @property
    def tier(self) -> str:
        return tier_for(self.net_liq)

    @property
    def bp_cap_dollars(self) -> float:
        return round(self.net_liq * self.bp_cap_pct, 2)

    @property
    def worst_case_limit(self) -> float:
        """Most a proposal may lose in the stress test, in dollars."""
        return round(self.net_liq * self.max_worst_case_pct, 2)

    def __str__(self) -> str:
        note = f"  notify {self.notify_channel}" + (f" {self.email_to}" if self.email_to else "")
        return (f"net liq ${self.net_liq:,.0f}  margin {self.margin_type}  tier {self.tier}  "
                f"per-position BP cap {self.bp_cap_pct:.0%} (${self.bp_cap_dollars:,.0f})  "
                f"delta:theta limit 1:{self.delta_theta_limit:g}  "
                f"worst-case limit {self.max_worst_case_pct:.0%} (${self.worst_case_limit:,.0f}){note}")


class ProfileError(ValueError):
    pass


def _num(name, v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ProfileError(f"{name}: {v!r} is not a number") from None


def validate(net_liq, margin_type, bp_cap_pct=DEFAULT_BP_CAP, delta_theta_limit=None,
             notify_channel="none", email_to="", max_worst_case_pct=DEFAULT_MAX_WORST_CASE) -> Profile:
    """delta_theta_limit=None takes the tier default."""
    net_liq = _num("net_liq", net_liq)
    if net_liq <= 0:
        raise ProfileError(f"net_liq: {net_liq:g} must be positive")
    if margin_type not in MARGIN_TYPES:
        raise ProfileError(f"margin_type: {margin_type!r} must be one of {MARGIN_TYPES}")
    if margin_type == "portfolio" and net_liq < PM_MIN_NET_LIQ:
        raise ProfileError(f"margin_type: portfolio margin needs at least ${PM_MIN_NET_LIQ:,.0f} of net liq "
                           f"(tastytrade: $125,000 to open, $100,000 to keep); use reg_t")
    if delta_theta_limit is None:
        delta_theta_limit = DT_LIMIT[tier_for(net_liq)]
    bp_cap_pct = _num("bp_cap_pct", bp_cap_pct)
    if not 0 < bp_cap_pct <= 1:
        raise ProfileError(f"bp_cap_pct: {bp_cap_pct:g} must be in (0, 1]")
    delta_theta_limit = _num("delta_theta_limit", delta_theta_limit)
    if delta_theta_limit <= 0:
        raise ProfileError(f"delta_theta_limit: {delta_theta_limit:g} must be positive")
    if notify_channel not in CHANNELS:
        raise ProfileError(f"notify_channel: {notify_channel!r} must be one of {CHANNELS}")
    email_to = (email_to or "").strip()
    if notify_channel in ("email", "gmail") and "@" not in email_to:
        raise ProfileError(f"email_to: an address is required when notify_channel is {notify_channel}")
    max_worst_case_pct = _num("max_worst_case_pct", max_worst_case_pct)
    if not 0 < max_worst_case_pct <= 1:
        raise ProfileError(f"max_worst_case_pct: {max_worst_case_pct:g} must be in (0, 1]")
    return Profile(net_liq, margin_type, bp_cap_pct, delta_theta_limit, notify_channel, email_to, max_worst_case_pct)


def save(profile: Profile, path: Path = DEFAULT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(profile), indent=2) + "\n", encoding="utf-8")
    return path


def load(path: Path = DEFAULT_PATH) -> Profile | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate(**data)
    except (ValueError, TypeError) as e:
        if isinstance(e, ProfileError):
            raise
        raise ProfileError(f"{path}: {e}") from None
