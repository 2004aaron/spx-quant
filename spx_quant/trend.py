"""Market trend from the SPX daily close: 50-day vs 200-day simple moving average.

The trend decides one thing: whether the bullish structures (naked put, put vertical) may be proposed. A naked put is a long-delta
bet. In the 2010-2023 OptionsDX replay it beat the strangle when the 50-day sat above the
200-day, and in the 2007-2009 death-cross months Cboe's put-write indices lost money
(docs/results/rules-v2.md). Short dips below the 200-day are NOT a reason to skip it: those were
the naked put's best entries. So "up" needs the 50-day above the 200-day, and anything else,
including history that is missing or stale, falls back to the strategies that don't need it.
"""
from __future__ import annotations

import csv
import io
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime

from . import clock
from .params import Params

HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv"


@dataclass(frozen=True)
class Trend:
    state: str                       # up | down | unknown
    fast: float | None = None
    slow: float | None = None
    close: float | None = None
    asof: date | None = None
    reason: str = ""

    @property
    def up(self) -> bool:
        return self.state == "up"

    def __str__(self) -> str:
        if self.state == "unknown":
            return f"unknown ({self.reason})"
        rel = "above" if self.up else "below"
        return (f"{self.state} (SPX 50-day {self.fast:,.0f} {rel} 200-day {self.slow:,.0f}, "
                f"close {self.close:,.2f} on {self.asof:%m/%d})")

    def as_dict(self) -> dict:
        return {"state": self.state, "fast": self.fast, "slow": self.slow, "close": self.close,
                "asof": self.asof.isoformat() if self.asof else None, "reason": self.reason}


def parse_history(text: str) -> list[tuple[date, float]]:
    out = []
    for row in csv.reader(io.StringIO(text)):
        try:
            out.append((datetime.strptime(row[0].strip(), "%m/%d/%Y").date(), float(row[-1])))
        except (ValueError, IndexError):
            continue
    return sorted(out)


def classify(closes: list[tuple[date, float]], params: Params, today: date) -> Trend:
    t = params.trend
    fast_n, slow_n = int(t["fast_sma"]), int(t["slow_sma"])
    closes = [(d, c) for d, c in closes if d <= today]
    if len(closes) < slow_n:
        return Trend("unknown", reason=f"{len(closes)} daily closes, {slow_n} needed")
    asof, close = closes[-1]
    age = (today - asof).days
    if age > t["max_age_days"]:
        return Trend("unknown", asof=asof, reason=f"last close is {age} days old (limit {t['max_age_days']:g})")
    px = [c for _, c in closes]
    fast, slow = sum(px[-fast_n:]) / fast_n, sum(px[-slow_n:]) / slow_n
    return Trend("up" if fast > slow else "down", round(fast, 2), round(slow, 2), close, asof)


def fetch(source, params: Params, now: datetime) -> Trend:
    """Trend from the source's daily SPX history; unknown when the source has none or it fails."""
    get = getattr(source, "history_text", None)
    if get is None:
        return Trend("unknown", reason=f"{getattr(source, 'name', 'source')} has no price history")
    try:
        text = get()
    except Exception as e:  # network or file failure must never block a scan
        return Trend("unknown", reason=f"price history unavailable: {e}")
    return classify(parse_history(text), params, clock.market_date(now))


def fetch_text(url: str = HISTORY_URL, timeout: float = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "spx-quant/0.5"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read().decode("utf-8")


def allowed(strategies: list[str], trend: Trend, params: Params) -> tuple[list[str], list[str]]:
    """(kept, dropped): strategies listed in trend.up_only are dropped unless the trend is up."""
    up_only = set(params.trend["up_only"])
    if trend.up:
        return list(strategies), []
    return [s for s in strategies if s not in up_only], [s for s in strategies if s in up_only]


def delta_theta_override(strategy: str, trend: Trend, params: Params, profile_limit: float) -> float | None:
    """The looser delta:theta limit for a bullish structure in an uptrend, or None to keep the profile's."""
    key = f"{strategy}_delta_theta"
    if not trend.up or key not in params.trend:
        return None
    n = float(params.trend[key])
    return n if n < profile_limit else None


def notes(trend: Trend, dropped: list[str], params: Params) -> list[str]:
    out = []
    names = ", ".join(s.replace("_", " ") for s in dropped)
    if dropped and trend.state == "down":
        out.append(f"{names.capitalize()} not offered: the 50-day is below the 200-day. In the 2007-2009 bear market "
                   "put selling lost money while the 50-day sat below the 200-day.")
    elif dropped:
        out.append(f"{names.capitalize()} not offered: the trend could not be read ({trend.reason}).")
    elif trend.up:
        out.append("Naked put and put vertical eligible: the 50-day is above the 200-day. Both are long-delta positions; "
                   "in 2010-2023 uptrends the naked put beat the strangle on return per buying power, but that sample "
                   "was a bull market.")
    return out
