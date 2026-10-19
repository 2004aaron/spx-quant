"""Daily marking job (US-09): value every logged proposal as if it had been opened.

Runs once after the close. Each open proposal gets one mark row per trading day at
that day's closing quotes: cost to close at mid, P/L against the logged credit, and
the first management rule that would have fired (informational; marking continues).
On or after expiration the position settles at intrinsic value against the index
level the feed shows. SPXW and XSP settle on the close, so a same-day mark is exact;
SPX standard monthlies settle on the morning's opening print, which the delayed
feed does not carry, so those settlements are flagged as approximate.
"""
from __future__ import annotations

from datetime import date, datetime

from . import clock, store
from .data import cboe
from .strategies import AM_SETTLED_ROOTS, MULTIPLIER


def intrinsic(leg: dict, s: float) -> float:
    return max(0.0, s - leg["strike"]) if leg["right"] == "C" else max(0.0, leg["strike"] - s)


def exit_signal(pnl_lot: float, cost_lot: float, credit_lot: float, dte: int, legs: list[dict],
                board: dict, m: dict) -> str | None:
    if credit_lot > 0 and pnl_lot >= m["profit_target"] * credit_lot:
        return f"profit target ({pnl_lot / credit_lot:.0%} of credit)"
    if credit_lot > 0 and cost_lot >= m["loss_multiple"] * credit_lot:
        return f"loss stop (cost to close {cost_lot / credit_lot:.1f}x credit)"
    if dte <= m["defensive_dte"]:
        return f"defensive exit at {dte} DTE"
    shorts = [abs(board[l["sym"]]["delta"]) for l in legs if l["qty"] < 0 and l["sym"] in board]
    if shorts and max(shorts) >= m["tested_delta"]:
        return f"short strike tested ({max(shorts):.2f} delta)"
    return None


def mark_one(alert: dict, spot: float, board: dict, today: date, now: datetime, params) -> dict:
    legs, k = alert["legs"], alert["contracts"]
    credit_lot = alert["credit_per_lot"]
    exp = date.fromisoformat(legs[0]["exp"])
    root = cboe.OCC.match(legs[0]["sym"])["root"]
    dte = (exp - today).days
    row = dict(alert_id=alert["alert_id"], market_date=today, ts=now, dte=dte, spot=spot)
    if today >= exp:
        cost_lot = sum(-l["qty"] * intrinsic(l, spot) for l in legs) * MULTIPLIER
        basis = "settled at intrinsic vs index close"
        if root in AM_SETTLED_ROOTS:
            basis = "settled at intrinsic vs index close (approximate: AM-settled, opening print not in feed)"
        if today > exp:
            basis += f"; late: expired {exp.isoformat()}, settled on {today.isoformat()}"
        pnl_lot = credit_lot - cost_lot
        row.update(mid=round(cost_lot, 2), pnl=round(pnl_lot * k, 2), settled=1, basis=basis,
                   pnl_pct_credit=round(pnl_lot / credit_lot, 4) if credit_lot else None,
                   legs=[{"sym": l["sym"], "intrinsic": intrinsic(l, spot)} for l in legs])
        return row
    missing = [l["sym"] for l in legs if l["sym"] not in board]
    if missing:
        raise LookupError(f"no quote for {', '.join(missing)}")
    cost_lot = sum(-l["qty"] * board[l["sym"]]["mid"] for l in legs) * MULTIPLIER
    pnl_lot = credit_lot - cost_lot
    row.update(mid=round(cost_lot, 2), pnl=round(pnl_lot * k, 2), settled=0, basis="mid of closing quotes",
               pnl_pct_credit=round(pnl_lot / credit_lot, 4) if credit_lot else None,
               exit_signal=exit_signal(pnl_lot, cost_lot, credit_lot, dte, legs, board, params.management),
               legs=[{"sym": l["sym"], **{f: board[l["sym"]][f] for f in ("bid", "ask", "mid", "delta")}} for l in legs])
    return row


def run(conn, source, params, now: datetime | None = None) -> list[dict]:
    now = now or source.now()
    today = clock.market_date(now)
    if not clock.trading_day(today):
        store.event(conn, now, "mark_skipped", f"market closed on {today.isoformat()}")
        return []
    todo = [a for a in store.open_proposals(conn) if not store.marked_on(conn, a["alert_id"], today)]
    by_ticker: dict[str, list[dict]] = {}
    for a in todo:
        by_ticker.setdefault(a["ticker"], []).append(a)
    feed, out = params.feed, []
    # Closing quotes stay valid after the close: accept a board last updated within 20 minutes of
    # today's options close even if the job runs late or it was an early-close day.
    limit = feed["stale_after_minutes"]
    close = clock.options_close(today)
    if now > close:
        limit = max(limit, (now - close).total_seconds() / 60 + 20)
    for ticker, alerts in by_ticker.items():
        chain, probe = cboe.fetch_chain(source, ticker, limit, feed.get("min_rows", 1), now)
        if chain is None:
            store.event(conn, now, "mark_skipped", f"{ticker}: {'; '.join(probe.failures)}")
            continue
        board = {r["sym"]: r for r in chain.rows}
        for a in alerts:
            try:
                row = mark_one(a, chain.spot, board, today, now, params)
            except LookupError as e:
                store.event(conn, now, "mark_missing_quote", str(e), a["alert_id"])
                continue
            store.insert(conn, "mark", **row)
            out.append(row)
    return out
