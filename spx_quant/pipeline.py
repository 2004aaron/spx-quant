"""The scan process (Figure 3): run the engine, log everything, send, exit.

Order matters for the evidence: the alert row and the scan row are written before
the send, so a crash during delivery still leaves a logged outcome (QR-3), and the
delivery rows record the time the message was accepted (QR-2).
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from . import clock, notify, store
from .data import cboe
from .alert import alert_id, fingerprint, render
from .engine import ScanResult, run_scan
from .params import Params
from .profile import Profile


@dataclass
class ScanRecord:
    result: ScanResult | None
    alert: dict | None
    delivery: str | None


def slot_time(slot: str | None, now: datetime) -> tuple[str, datetime]:
    """'10:30' -> that Pacific wall time on today's market date; None -> 'manual' at now."""
    if not slot:
        return "manual", now.replace(second=0, microsecond=0)
    hh, mm = (int(x) for x in slot.split(":"))
    day = clock.to_local("PT", now).date()
    return slot, clock.local_to_utc("PT", datetime.combine(day, time(hh, mm)))


def previous_trading_day(d):
    d -= timedelta(days=1)
    while not clock.trading_day(d):
        d -= timedelta(days=1)
    return d


def leg_quotes(conn, res: ScanResult, now: datetime, source=None, params: Params | None = None) -> dict:
    """Current quotes for the legs of proposals logged since the previous trading day, so an
    end-of-day proposal can be checked against the next morning's board (A-KR2). Boards the
    engine did not need (an XSP proposal on a stand-down morning) are fetched here."""
    since = previous_trading_day(clock.market_date(now)).isoformat()
    recent = store.rows(conn, "SELECT alert_id, ticker, legs FROM alert WHERE kind='proposal' AND market_date >= ?", (since,))
    if source is not None and params is not None:
        f = params.feed
        for t in sorted({a["ticker"] for a in recent} - set(res.boards)):
            chain, _ = cboe.fetch_chain(source, t, f["stale_after_minutes"], f.get("min_rows", 1), now)
            if chain is not None:
                res.boards[t] = {r["sym"]: r for r in chain.rows}
    out = {}
    for a in recent:
        board = res.boards.get(a["ticker"])
        if not board:
            continue
        out[a["alert_id"]] = {l["sym"]: ({k: board[l["sym"]][k] for k in ("bid", "ask", "mid", "oi", "vol")}
                                         if l["sym"] in board else None) for l in a["legs"]}
    return out


def alert_row(res: ScanResult, aid: str, slot: str, slot_ts: datetime, created: datetime,
              fp: str, subject: str, text: str) -> dict:
    row = dict(alert_id=aid, slot=slot, slot_ts=slot_ts, created_ts=created, data_ts=res.data_ts,
               market_date=clock.market_date(created), kind=res.kind, outcome=res.outcome, ticker=res.ticker,
               regime=res.regime.as_dict() if res.regime else None, reasons=res.reasons, codes=res.codes,
               quotes=res.quotes(), profile=res.profile.__dict__ if res.profile else None,
               candidates=[c.as_dict() for c in res.ranked + res.rejected], fingerprint=fp, subject=subject, text=text)
    if res.best:
        c = res.best
        p, s = c.position, c.sized
        row.update(strategy=p.strategy, legs=[l.as_dict() for l in p.legs], contracts=s.contracts,
                   credit=round(p.credit * s.contracts, 2), credit_per_lot=p.credit, bp_per_lot=s.bp_per_lot,
                   bp_total=s.bp_total, delta_per_lot=s.delta_per_lot, theta_per_lot=s.theta_per_lot,
                   risk=c.risk.as_dict())
    return row


def scan(conn, source, profile: Profile, params: Params, slot: str | None = None,
         send: bool = True, channel=None, sleep=None) -> ScanRecord:
    started = source.now()
    label, slot_ts = slot_time(slot, started)
    try:
        res = run_scan(source, profile, params, started)
    except Exception as e:
        finished = source.now()
        store.insert(conn, "scan", slot=label, slot_ts=slot_ts, started_ts=started, finished_ts=finished,
                     outcome="error", market_date=clock.market_date(started), source=getattr(source, "name", ""),
                     detail={"error": f"{type(e).__name__}: {e}"})
        store.event(conn, finished, "scan_error", traceback.format_exc(limit=4))
        raise

    if res.kind is None:
        store.insert(conn, "scan", slot=label, slot_ts=slot_ts, started_ts=started, finished_ts=source.now(),
                     outcome=res.outcome, market_date=clock.market_date(started), source=res.source,
                     detail={"reasons": res.reasons})
        return ScanRecord(res, None, None)

    late = (started - slot_ts).total_seconds() / 60
    if label != "manual" and late > 30:
        res.notes.append(f"late run: started {clock.fmt(started)}, {late:.0f} min after the {label} slot")
    created = source.now()
    fp = fingerprint(res)
    aid = store.unique_alert_id(conn, alert_id(slot_ts, fp))
    subject, text = render(res, aid, created)
    row = alert_row(res, aid, label, slot_ts, created, fp, subject, text)
    store.insert(conn, "alert", **row)
    finished = source.now()
    store.insert(conn, "scan", slot=label, slot_ts=slot_ts, started_ts=started, finished_ts=finished,
                 outcome=res.outcome, quote_age_min=res.quote_age_min, data_ts=res.data_ts, alert_id=aid,
                 market_date=clock.market_date(started), source=res.source,
                 detail={"reasons": res.reasons, "codes": res.codes, "notes": res.notes},
                 leg_quotes=leg_quotes(conn, res, started, source if label == params.schedule["slots"][0] else None, params))
    if res.outcome in ("stale_data", "feed_failure", "error"):
        store.event(conn, finished, res.outcome, "; ".join(res.reasons), aid)
    if label != "manual" and late > 30:
        store.event(conn, finished, "scan_late", f"{late:.0f} min after the {label} slot", aid)
    status = None
    if send:
        extra = {"sleep": sleep} if sleep else {}
        status = notify.deliver(conn, store.get_alert(conn, aid), finished, profile, params, channel, now=source.now, **extra)
    return ScanRecord(res, store.get_alert(conn, aid), status)
