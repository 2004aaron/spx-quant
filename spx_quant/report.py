"""Weekly report (US-11, US-12): the advisor's full book against the investor's.

Built only from the log and an end date, never the wall clock, so regenerating it from
the same log gives the same text (US-11-AC1). Rows written after the end date are
ignored, which also makes old reports reproducible after the log has grown.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import clock, decisions, store
from . import htmlmail as h
from .params import Params

FAILURES = {"stale_data": "stale data", "feed_failure": "feed failure", "error": "engine error",
            "scan_error": "engine error", "scan_late": "late scan", "delivery_failed": "delivery failed",
            "delivery_late": "late delivery", "mark_skipped": "mark skipped", "mark_missing_quote": "mark missing quote"}


@dataclass
class Position:
    alert: dict
    entered: str
    expires: str
    contracts: int
    credit: float
    pnl: float | None            # advisor P/L at the latest mark on or before the end date
    mark_date: str | None
    settled: bool
    worst_mark: float | None     # most negative daily mark (US-11-AC3, RC-KR1)
    predicted: float | None      # worst case stated at proposal time (negative)
    decision: str | None
    taken: int | None            # contracts the investor took, None if never taken
    user_pnl: float | None
    repeat: bool

    @property
    def alert_id(self) -> str:
        return self.alert["alert_id"]

    @property
    def hit(self) -> bool:
        return self.worst_mark is not None and self.predicted is not None and self.worst_mark <= self.predicted

    @property
    def reached(self) -> float | None:
        if self.worst_mark is None or not self.predicted:
            return None
        return max(0.0, self.worst_mark / self.predicted)

    @property
    def active(self) -> bool:
        """Still held by the investor at the end date."""
        return self.taken is not None and self.decision in decisions.TAKEN and not self.settled


def end_of_day(d: date) -> datetime:
    return clock.local_to_utc("PT", datetime.combine(d, time(23, 59, 59)))


def positions(conn, end: date) -> list[Position]:
    """Every distinct proposal logged on or before `end`, plus any NO CHANGE repeat the
    investor actually took."""
    asof = end_of_day(end)
    out = []
    for a in store.rows(conn, """SELECT * FROM alert WHERE kind = 'proposal' AND market_date <= ?
                                 ORDER BY created_ts, id""", (end.isoformat(),)):
        d = decisions.latest(conn, a["alert_id"], asof)
        taken = decisions.taken_size(conn, a, asof)
        if a["repeat_of"] and taken is None:
            continue
        marks = [m for m in store.marks_for(conn, a["alert_id"]) if m["market_date"] <= end.isoformat()]
        last = marks[-1] if marks else None
        user_pnl = None
        if taken is not None and marks and a["contracts"]:
            stop = clock.market_date(clock.parse_utc(d["received_ts"])).isoformat() if d and d["decision"] == "closed" else end.isoformat()
            held = [m for m in marks if m["market_date"] <= stop] or marks[:1]
            user_pnl = round(held[-1]["pnl"] * taken / a["contracts"], 2)
        out.append(Position(
            alert=a, entered=a["market_date"], expires=(a["legs"] or [{}])[0].get("exp", "?"), contracts=a["contracts"] or 0,
            credit=a["credit"] or 0.0, pnl=last["pnl"] if last else None, mark_date=last["market_date"] if last else None,
            settled=bool(last and last["settled"]), worst_mark=min(m["pnl"] for m in marks) if marks else None,
            predicted=(a["risk"] or {}).get("worst_case"), decision=d["decision"] if d else None, taken=taken,
            user_pnl=user_pnl, repeat=bool(a["repeat_of"])))
    return out


def _money(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _cols(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return ["  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]


def failures(conn, params: Params, start: date, end: date) -> list[tuple[str, str, str]]:
    """(timestamp, failure type, reason) for every scan or alert that was skipped or failed."""
    out = []
    lo, hi = clock.local_to_utc("PT", datetime.combine(start, time())), end_of_day(end)
    for e in store.rows(conn, "SELECT * FROM event ORDER BY ts, id"):
        ts = clock.parse_utc(e["ts"])
        if lo <= ts <= hi and e["kind"] in FAILURES:
            reason = (e["detail"] or "").strip().splitlines()[-1] if e["detail"] else ""
            out.append((clock.fmt(ts), FAILURES[e["kind"]], (f"{e['alert_id']}: " if e["alert_id"] else "") + reason[:160]))
    d = start
    while d <= end:
        if clock.trading_day(d):
            for slot in params.schedule["slots"]:
                if not store.rows(conn, "SELECT 1 FROM scan WHERE market_date = ? AND slot = ?", (d.isoformat(), slot)):
                    out.append((f"{d.isoformat()} {slot} PT", "missed scan", f"no {slot} scan was logged for {d.isoformat()}"))
        d += timedelta(days=1)
    limit = int(params.notify.get("max_attempts", 3))
    for a in store.rows(conn, """SELECT DISTINCT a.alert_id, a.created_ts FROM alert a JOIN delivery q ON q.alert_id = a.alert_id
                                 WHERE q.status = 'queued' AND a.market_date BETWEEN ? AND ? ORDER BY a.created_ts""",
                        (start.isoformat(), end.isoformat())):
        rows = store.rows(conn, "SELECT status FROM delivery WHERE alert_id = ?", (a["alert_id"],))
        failed = sum(r["status"] == "failed" for r in rows)
        if not any(r["status"] == "delivered" for r in rows) and failed < limit:
            out.append((clock.fmt(clock.parse_utc(a["created_ts"])), "not delivered",
                        f"{a['alert_id']}: queued for Gmail and never sent"))
    return sorted(out)


@dataclass
class Week:
    start: date
    end: date
    advisor: list[Position]
    mine: list[Position]
    adv_pnl: float
    my_pnl: float
    scans: list[dict]
    delivered: list[dict]
    asked: list[str]
    missing: list[str]
    fails: list[tuple[str, str, str]]
    slots: int

    def count(self, *outcomes) -> int:
        return sum(s["outcome"] in outcomes for s in self.scans)


def week(conn, params: Params, end: date, days: int = 7) -> Week:
    start = end - timedelta(days=days - 1)
    pos = positions(conn, end)
    advisor = [p for p in pos if not p.repeat]
    mine = [p for p in pos if p.taken is not None]
    scans = store.rows(conn, "SELECT outcome, slot FROM scan WHERE market_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
    delivered = store.rows(conn, """SELECT DISTINCT d.alert_id, a.kind, a.repeat_of FROM delivery d JOIN alert a ON a.alert_id = d.alert_id
                                    WHERE d.status = 'delivered' AND a.market_date BETWEEN ? AND ?""", (start.isoformat(), end.isoformat()))
    asked = [r["alert_id"] for r in delivered if r["kind"] == "proposal" and not r["repeat_of"]]
    missing = [a for a in asked if decisions.latest(conn, a, end_of_day(end)) is None]
    slots = sum(clock.trading_day(start + timedelta(days=i)) for i in range(days)) * len(params.schedule["slots"])
    return Week(start, end, advisor, mine, round(sum(p.pnl or 0.0 for p in advisor), 2),
                round(sum(p.user_pnl or 0.0 for p in mine), 2), scans, delivered, asked, missing,
                failures(conn, params, start, end), slots)


def _status(p: Position) -> str:
    return "settled" if p.settled else ("open" if p.mark_date else "not marked yet")


def _decision(p: Position) -> str:
    return (p.decision or "none") + (f" x{p.taken}" if p.decision == "modified" else "")


def weekly(conn, params: Params, end: date, days: int = 7) -> str:
    w = week(conn, params, end, days)
    start, advisor, mine, adv_pnl, my_pnl = w.start, w.advisor, w.mine, w.adv_pnl, w.my_pnl
    scans, count, delivered, asked, missing = w.scans, w.count, w.delivered, w.asked, w.missing

    lines = [f"STORMGLASS | WEEKLY REPORT | week ending {end.isoformat()}",
             f"Window: {start.isoformat()} to {end.isoformat()} (market dates). Built only from the log; "
             "regenerating it from the same log gives the same report.", "",
             "SUMMARY",
             f"  Advisor book (every proposal, followed in full): {len(advisor)} position{'s' * (len(advisor) != 1)}, "
             f"P/L to date {_money(adv_pnl)}",
             f"  Your book (proposals you took): {len(mine)} position{'s' * (len(mine) != 1)}, P/L to date {_money(my_pnl)}",
             f"  You minus the advisor: {_money(round(my_pnl - adv_pnl, 2))}",
             f"  This week: {len(scans)} scans ({count('proposal')} proposals, {count('stand_down')} stand-downs, "
             f"{count('stale_data', 'feed_failure', 'error')} no advice), {len(delivered)} alert{'s' * (len(delivered) != 1)} delivered",
             f"  Decisions: {len(asked) - len(missing)} of {len(asked)} new proposals delivered this week have your decision"
             + (f"; missing: {', '.join(missing)}" if missing else "")]

    lines += ["", f"POSITIONS (advisor book; P/L at the latest mark on or before {end.isoformat()})"]
    if advisor:
        rows = [["alert", "structure", "entered", "expires", "lots", "credit", "P/L", "status", "your decision"]]
        for p in advisor:
            a = p.alert
            rows.append([p.alert_id, f"{a['strategy'].replace('_', ' ')} {a['ticker'].lstrip('_')}", p.entered, p.expires,
                         str(p.contracts), _money(p.credit), _money(p.pnl), _status(p), _decision(p)])
        lines += _cols(rows)
    else:
        lines.append("  No proposals logged yet.")

    lines += ["", "WORST CASE PREDICTED vs REALIZED (how close each position came to its stated worst case)"]
    marked = [p for p in advisor if p.worst_mark is not None]
    if marked:
        rows = [["alert", "predicted worst case", "worst daily mark", "reached", "hit"]]
        rows += [[p.alert_id, _money(p.predicted), _money(p.worst_mark),
                  f"{p.reached:.0%}" if p.reached is not None else "n/a", "YES" if p.hit else "no"] for p in marked]
        lines += _cols(rows)
        lines.append(f"  {sum(p.hit for p in marked)} of {len(marked)} marked positions reached their stated worst case.")
    else:
        lines.append("  No marks yet.")

    lines += ["", "YOUR BOOK (P/L scaled to the contracts you took)"]
    if mine:
        rows = [["alert", "lots taken", "P/L", "status"]]
        rows += [[p.alert_id, str(p.taken), _money(p.user_pnl),
                  "closed" if p.decision == "closed" else ("settled" if p.settled else "open")] for p in mine]
        lines += _cols(rows)
    else:
        lines.append("  No decisions recorded as taken yet.")

    lines += ["", "FAILURES AND ANOMALIES THIS WEEK"]
    if w.fails:
        lines += [f"  - {ts} | {kind} | {why}" for ts, kind, why in w.fails]
    else:
        lines.append(f"  No anomalies this week: all {w.slots} scheduled scans ran, nothing failed, and every alert was delivered.")
    lines += ["", "Paper P/L from the engine's own marks, not money earned. Model estimates, not investment advice."]
    return "\n".join(lines) + "\n"


def weekly_html(conn, params: Params, end: date, days: int = 7) -> str:
    """The weekly report as an HTML email body: the same numbers as weekly(), in tables."""
    w = week(conn, params, end, days)
    m = h.money
    sections = [h.section("Summary", h.tiles([
        ("Advisor book", m(w.adv_pnl), f"{len(w.advisor)} position{'s' * (len(w.advisor) != 1)}, every proposal"),
        ("Your book", m(w.my_pnl), f"{len(w.mine)} position{'s' * (len(w.mine) != 1)} you took"),
        ("You minus advisor", m(round(w.my_pnl - w.adv_pnl, 2)), "P/L to date"),
        ("Scans this week", len(w.scans), f"{w.count('proposal')} proposal{'s' * (w.count('proposal') != 1)}, "
                                          f"{w.count('stand_down')} stand-down{'s' * (w.count('stand_down') != 1)}")]),
        h.kv([("No advice", w.count("stale_data", "feed_failure", "error")),
              ("Alerts delivered", len(w.delivered)),
              ("Decisions recorded", f"{len(w.asked) - len(w.missing)} of {len(w.asked)} new proposals"
               + (f"; missing: {', '.join(w.missing)}" if w.missing else ""))]))]
    sections.append(h.section(f"Positions (advisor book, P/L at the latest mark on or before {end.isoformat()})",
        h.table(["position", "credit", "P/L", "status", "decision"],
                [[h.Raw(f"{h.b(p.alert['strategy'].replace('_', ' ') + ' ' + p.alert['ticker'].lstrip('_') + f' x{p.contracts}')}<br>"
                        f"{h.mono(p.alert_id, small=True)}<br>{h.e(f'{p.entered} to {p.expires}')}"),
                  m(p.credit), m(p.pnl), _status(p), _decision(p)] for p in w.advisor], right=(1, 2)) if w.advisor else h.para("No proposals logged yet.")))
    marked = [p for p in w.advisor if p.worst_mark is not None]
    sections.append(h.section("Worst case predicted vs realized",
        *([h.table(["alert", "predicted", "worst mark", "reached", "hit"],
                   [[h.mono(p.alert_id, small=True), m(p.predicted), m(p.worst_mark), f"{p.reached:.0%}" if p.reached is not None else "n/a",
                     h.b("YES") if p.hit else "no"] for p in marked], right=(1, 2, 3)),
           h.para(f"{sum(p.hit for p in marked)} of {len(marked)} marked positions reached their stated worst case.", small=True)]
          if marked else [h.para("No marks yet.")])))
    sections.append(h.section("Your book (P/L scaled to the contracts you took)",
        h.table(["alert", "lots", "P/L", "status"],
                [[h.mono(p.alert_id, small=True), p.taken, m(p.user_pnl), "closed" if p.decision == "closed" else ("settled" if p.settled else "open")]
                 for p in w.mine], right=(1, 2)) if w.mine else h.para("No decisions recorded as taken yet.")))
    sections.append(h.section("Failures and anomalies this week",
        h.table(["when", "type", "reason"], [[ts, h.b(kind), why] for ts, kind, why in w.fails]) if w.fails else
        h.callout(f"No anomalies this week: all {w.slots} scheduled scans ran, nothing failed, and every alert was delivered.",
                  ok=True)))
    return h.page("WEEKLY REPORT", f"week ending {end.isoformat()}",
                  [f"Window: {w.start.isoformat()} to {end.isoformat()} (market dates)",
                   "Built only from the log; regenerating it from the same log gives the same report."],
                  f"Week ending {end:%A, %B} {end.day}, {end.year}", sections,
                  ["Paper P/L from the engine's own marks, not money earned. Model estimates, not investment advice."])
