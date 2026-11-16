"""Take-profit by GTC order (Nov 16, 2026): the broker closes the trade, the engine logs it.

StormGlass never places orders, so the 50% exit lives at the investor's broker: a GTC
buy-to-close limit for the whole order at half the credit. The engine can't see that order,
so it watches the price and asks.

  check    every 30 minutes in market hours, and once on the closing quotes: price each taken
           position at what it costs to close (ask on short legs, bid on long legs) and log one
           tp_check row. A row at or below the limit is a touch: the order could have filled.
  pending  taken positions with a touch the investor hasn't answered yet.
  answer   FILLED records CLOSED at the limit; NOT FILLED keeps it open until the next touch.
  presume  no answer 3 trading days after the first touch: CLOSED at the limit, source presumed.

A touch is not a fill. Quotes are about 15 minutes delayed, a 30-minute check can miss a short
spike, and a limit can be touched without filling. That is why the investor confirms.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import clock, decisions, store
from .data import cboe
from .strategies import MULTIPLIER

TICK = 0.05
PRESUME_DAYS = 3
NOT_FILLED = re.compile(r"^\s*not[\s-]*filled\b", re.I)
FILLED = re.compile(r"^\s*filled\b", re.I)


def limit_price(alert: dict, fill: float | None = None, target: float = 0.5) -> float:
    """The GTC buy-to-close price per share: what is left after keeping `target` of the credit,
    rounded down to a nickel so a fill keeps at least that much."""
    credit = fill or alert["credit_per_lot"] / MULTIPLIER
    return round(math.floor(credit * (1 - target) / TICK + 1e-9) * TICK, 2)


def close_cost(legs: list[dict], board: dict) -> float | None:
    """Per share, to close every leg now: buy the shorts at the ask, sell the longs at the bid."""
    total = 0.0
    for l in legs:
        q = board.get(l["sym"])
        if q is None or (l["qty"] < 0 and q["ask"] <= 0):
            return None
        total += -l["qty"] * (q["ask"] if l["qty"] < 0 else q["bid"])
    return round(total, 2)


def _limit(conn, a: dict, params) -> float:
    return limit_price(a, decisions.fill_price(conn, a["alert_id"]), params.management["profit_target"])


def check(conn, source, params, now: datetime | None = None) -> list[dict]:
    """One tp_check row per taken position, from one chain fetch per ticker."""
    now = now or source.now()
    today = clock.market_date(now)
    if not clock.trading_day(today):
        return []
    held = [store.get_alert(conn, h.alert_id) for h in decisions.held(conn, now)]
    by_ticker: dict[str, list[dict]] = {}
    for a in held:
        if date.fromisoformat(a["legs"][0]["exp"]) > today:
            by_ticker.setdefault(a["ticker"], []).append(a)
    limit, close = params.feed["stale_after_minutes"], clock.options_close(today)
    if now > close:
        limit = max(limit, (now - close).total_seconds() / 60 + 20)   # the closing board, same rule as the mark
    out = []
    for ticker, alerts in by_ticker.items():
        chain, probe = cboe.fetch_chain(source, ticker, limit, params.feed.get("min_rows", 1), now)
        if chain is None:
            store.event(conn, now, "tp_check_skipped", f"{ticker}: {'; '.join(probe.failures)}")
            continue
        board = {r["sym"]: r for r in chain.rows}
        for a in alerts:
            cost = close_cost(a["legs"], board)
            if cost is None:
                store.event(conn, now, "tp_check_skipped", "no usable quote for a leg", a["alert_id"])
                continue
            lim = _limit(conn, a, params)
            row = dict(alert_id=a["alert_id"], market_date=today, ts=now, quote_ts=chain.quote_ts, cost=cost,
                       limit_price=lim, hit=int(cost <= lim))
            store.insert(conn, "tp_check", **row)
            out.append(row)
    return out


@dataclass
class Touch:
    alert: dict
    lots: int
    limit: float
    first: dict          # the first touching check since the last NOT FILLED
    low: dict            # the cheapest touching check
    today: bool          # touched on the day asked about

    @property
    def aid(self) -> str:
        return self.alert["alert_id"]

    @property
    def profit(self) -> float:
        """What a fill at the limit realizes on the lots held."""
        return round((self.alert["credit_per_lot"] - self.limit * MULTIPLIER) * self.lots, 2)

    def presume_on(self) -> date:
        d, n = date.fromisoformat(self.first["market_date"]), 0
        while n < PRESUME_DAYS:
            d += timedelta(days=1)
            n += clock.trading_day(d)
        return d


def pending(conn, now: datetime, day: date | None = None) -> list[Touch]:
    """Taken, still open, touched since the last NOT FILLED answer: the investor owes an answer.
    `today` on each touch means it touched on `day` (default: now's market date)."""
    day, out = (day or clock.market_date(now)).isoformat(), []
    for h in decisions.held(conn, now):
        last_no = store.rows(conn, "SELECT MAX(ts) t FROM event WHERE kind = 'tp_unfilled' AND alert_id = ? AND ts <= ?",
                             (h.alert_id, now.isoformat()))[0]["t"]
        hits = store.rows(conn, "SELECT * FROM tp_check WHERE alert_id = ? AND hit = 1 AND ts > ? AND ts <= ? ORDER BY ts, id",
                          (h.alert_id, last_no or "", now.isoformat()))
        if not hits:
            continue
        low = min(hits, key=lambda r: (r["cost"], r["ts"]))
        out.append(Touch(store.get_alert(conn, h.alert_id), h.contracts, hits[0]["limit_price"], hits[0], low,
                         any(r["market_date"] == day for r in hits)))
    return out


def answer(conn, alert_id: str, text: str, now: datetime, ref: str | None = None, source: str = "email") -> str | None:
    """FILLED / NOT FILLED from a reply. Returns recorded or duplicate, or None if the text is neither."""
    if NOT_FILLED.match(text or ""):
        if ref and store.rows(conn, "SELECT 1 FROM event WHERE kind = 'tp_unfilled' AND detail = ?", (ref,)):
            return "duplicate"
        if not any(t.aid == alert_id for t in pending(conn, now)):
            raise decisions.DecisionError(f"{alert_id} has no take-profit touch waiting for an answer")
        store.event(conn, now, "tp_unfilled", ref or f"{source} {now.isoformat()}", alert_id)
        return "recorded"
    if FILLED.match(text or ""):
        a = store.get_alert(conn, alert_id)
        if a is None:
            raise decisions.DecisionError(f"no logged alert with id {alert_id!r}; nothing stored")
        t = next((t for t in pending(conn, now) if t.aid == alert_id), None)
        lim = t.limit if t else limit_price(a, decisions.fill_price(conn, alert_id))
        return decisions.record(conn, alert_id, "closed", now, f"take-profit GTC filled at {lim:.2f}", None, source, ref, lim)
    return None


def presume(conn, now: datetime) -> list[str]:
    """Close, at the limit, every touch left unanswered for PRESUME_DAYS trading days."""
    today, out = clock.market_date(now), []
    for t in pending(conn, now):
        if today >= t.presume_on():
            decisions.record(conn, t.aid, "closed", now, f"presumed filled at {t.limit:.2f}: take-profit touched "
                             f"{t.first['market_date']}, no answer in {PRESUME_DAYS} trading days", None, "presumed", None, t.limit)
            out.append(t.aid)
    return out
