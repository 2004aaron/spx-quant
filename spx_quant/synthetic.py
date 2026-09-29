"""Synthetic Cboe-shaped boards for tests and the A-KR3 matrix.

Prices come from Black-Scholes with a put skew, IV(K) = ATM x (1 - 5x + 20x^2),
x = ln(K/S), which gives roughly the 16-delta put / ATM / 16-delta call IV ratios seen
on the live SPX board (about 1.4 / 1.0 / 0.85). Quotes are timestamped like the live
feed: underlying last_trade_time in US Eastern wall time.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from . import clock
from .greeks import bs
from .strategies import years_to

SHAPES = {"contango": 1.12, "flat": 1.02, "backwardation": 0.85}


def iv_at(atm: float, spot: float, strike: float) -> float:
    x = math.log(strike / spot)
    return max(atm * (1 - 5 * x + 20 * x * x), 0.4 * atm)


def _et(dt_utc: datetime) -> str:
    return clock.to_local("ET", dt_utc).replace(tzinfo=None).isoformat(timespec="seconds")


def board(ticker: str, spot: float, atm: float, now: datetime, quote_ts: datetime,
          dte_range=(21, 70), rate: float = 0.04) -> dict:
    root, step = ("SPXW", 5.0) if ticker == "_SPX" else ("XSP", 1.0)
    today = clock.market_date(now)
    exps = [today + timedelta(days=d) for d in range(dte_range[0], dte_range[1] + 1)
            if (today + timedelta(days=d)).weekday() == 4]
    lo, hi = math.floor(spot * 0.75 / step) * step, math.ceil(spot * 1.15 / step) * step
    opts = []
    for exp in exps:
        t = years_to(root, exp, now)
        k = lo
        while k <= hi:
            iv = iv_at(atm, spot, k)
            for right in ("P", "C"):
                g = bs(spot, k, t, iv, right, rate)
                if g.price < 0.05 or abs(g.delta) > 0.75:
                    continue
                half = max(0.05 * (step / 5), 0.015 * g.price)
                opts.append({"option": f"{root}{exp:%y%m%d}{right}{int(round(k * 1000)):08d}",
                             "bid": round(max(g.price - half, 0.05), 2), "ask": round(g.price + half, 2),
                             "iv": round(iv, 4), "delta": round(g.delta, 4), "open_interest": 1500, "volume": 300})
            k += step
    return {"timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "data": {"current_price": spot, "close": spot, "last_trade_time": _et(quote_ts), "options": opts}}


def curve(vix: float, shape: str, quote_ts: datetime) -> dict:
    back = SHAPES[shape]
    vals = {"VIX9D": vix / back ** 0.5, "VIX": vix, "VIX3M": vix * back, "VIX6M": vix * back ** 1.3}
    return {sym: {"data": {"current_price": round(v, 2), "last_trade_time": _et(quote_ts)}} for sym, v in vals.items()}


class SyntheticSource:
    name = "synthetic"

    def __init__(self, vix: float, shape: str = "contango", spot: float = 7600.0, now: datetime | None = None,
                 age_minutes: float = 15, tickers=("_SPX", "_XSP"), missing: tuple = ()):
        self._now = now or clock.local_to_utc("PT", datetime(2026, 10, 7, 10, 30))
        q = self._now - timedelta(minutes=age_minutes)
        atm = vix / 100 * 0.9
        self.chains = {t: board(t, spot if t == "_SPX" else spot / 10, atm, self._now, q) for t in tickers}
        self.curve = {k: v for k, v in curve(vix, shape, q).items() if k not in missing}

    def chain_payload(self, ticker: str) -> dict:
        if ticker not in self.chains:
            raise LookupError(f"{ticker} not in synthetic source")
        return self.chains[ticker]

    def quote_payload(self, symbol: str) -> dict:
        if symbol not in self.curve:
            raise LookupError(f"{symbol} missing")
        return self.curve[symbol]

    def now(self) -> datetime:
        return self._now
