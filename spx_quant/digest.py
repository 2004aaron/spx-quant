"""Weekly digest emails (issue #63): the Monday outlook of open positions.

Built only from the log and a date, like the weekly report, so the same log and date give
the same email. A digest reads one of two books:

  taken   proposals the investor accepted or modified, at the lots taken; a position leaves
          the book on a CLOSED decision or a settled mark
  paper   every proposal that is not a NO CHANGE repeat, at full size; a position leaves the
          book at the first mark that flags the profit target or settles

The email goes out over the profile's email channel once per date: the send writes a
`digest_monday` event holding the date, and a second run for that date sends nothing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from . import clock, decisions, htmlmail as h, notify, store
from .alert import _money
from .report import _cols, end_of_day

BOOKS = ("taken", "paper")
KINDS = ("monday",)
TOP = 10
BOOK_NAME = {"taken": "your book", "paper": "paper book"}
BOOK_NOTE = {"taken": "Your book: the proposals you accepted or modified, at the lots you took.",
             "paper": "Paper book: every proposal at full size, closed at the profit target or at expiration."}
MARKS_NOTE = ("To short strike: how far the index was from the nearest short strike at the latest mark. "
              "P/L is paper P/L from the engine's closing mid marks, not money earned.")


HTML_NOTE = ("Cushion: how far the index is from your nearest short strike. Bars show progress to the 50% profit target. "
             "P/L is from the engine's closing marks, not money earned.")


@dataclass
class Position:
    alert: dict
    lots: int
    entered: str
    expires: str
    dte: int                 # calendar days from the digest date to expiration
    credit: float
    pnl: float | None        # at the latest mark, or at the mark that closed it
    pct: float | None        # share of the credit captured at that mark
    marked: str | None
    worst: float | None      # worst case stated in the proposal, scaled to the lots held (negative)
    bp: float                # buying power, scaled to the lots held
    away: float | None       # nearest short strike, as a fraction of the mark's index level
    at_target: bool
    closed: str | None       # market date it left the book
    how: str | None

    @property
    def name(self) -> str:
        return f"{self.alert['strategy'].replace('_', ' ')} {self.alert['ticker'].lstrip('_')}"

    @property
    def title(self) -> str:
        return f"{self.alert['ticker'].lstrip('_')} {self.alert['strategy'].replace('_', ' ')}"

    @property
    def strikes(self) -> str:
        return "/".join(f"{l['strike']:g}{l['right']}" for l in sorted(self.alert["legs"], key=lambda l: l["strike"]))


def _exit(marks: list[dict], kind: str, closed_on: str | None) -> tuple[dict | None, str | None, str | None]:
    """(the mark that fixes the P/L, date closed, how); the latest mark and no date while open."""
    if kind == "paper":
        m = next((m for m in marks if m["exit_signal"] or m["settled"]), None)
    else:
        m = next((m for m in marks if m["settled"]), None)
        if closed_on and (m is None or closed_on < m["market_date"]):
            held = [x for x in marks if x["market_date"] <= closed_on] or marks[:1]
            return (held[-1] if held else None), closed_on, "closed by you"
    if m:
        return m, m["market_date"], "expired" if m["settled"] else "profit target"
    return (marks[-1] if marks else None), None, None


def book(conn, asof: date, kind: str = "taken") -> list[Position]:
    """Every position that has been in the book on or before `asof`, open or closed, in entry order."""
    day, eod, out = asof.isoformat(), end_of_day(asof), []
    for a in store.rows(conn, "SELECT * FROM alert WHERE kind = 'proposal' AND market_date <= ? ORDER BY created_ts, id", (day,)):
        lots, closed_on = a["contracts"], None
        if kind == "paper":
            if a["repeat_of"]:
                continue
        else:
            lots, d = decisions.taken_size(conn, a, eod), decisions.latest(conn, a["alert_id"], eod)
            if lots is None or d["decision"] == "declined":
                continue
            if d["decision"] == "closed":
                closed_on = clock.market_date(clock.parse_utc(d["received_ts"])).isoformat()
        m, closed, how = _exit([m for m in store.marks_for(conn, a["alert_id"]) if m["market_date"] <= day], kind, closed_on)
        scale, exp = lots / (a["contracts"] or lots), a["legs"][0]["exp"]
        worst = (a["risk"] or {}).get("worst_case")
        shorts = [l["strike"] for l in a["legs"] if l["qty"] < 0]
        out.append(Position(
            alert=a, lots=lots, entered=a["market_date"], expires=exp, dte=(date.fromisoformat(exp) - asof).days,
            credit=round(a["credit_per_lot"] * lots, 2), pnl=round(m["pnl"] * scale, 2) if m else None,
            pct=m["pnl_pct_credit"] if m else None, marked=m["market_date"] if m else None,
            worst=round(worst * scale, 2) if worst is not None else None, bp=round((a["bp_per_lot"] or 0.0) * lots, 2),
            away=min(abs(k - m["spot"]) / m["spot"] for k in shorts) if m and m["spot"] and shorts else None,
            at_target=bool(m and m["exit_signal"] and not closed), closed=closed, how=how))
    return out


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def _pnl(p: Position) -> str:
    if p.pnl is None:
        return "n/a"
    return _money(p.pnl, True) + (f" ({p.pct:.0%})" if p.pct is not None else "")


def _row(p: Position, risk: bool) -> list[str]:
    """Four cells that name the position, then the numbers."""
    first = [_money(p.worst), f"${p.bp:,.0f}"] if risk else [f"{_day(p.expires)} ({p.dte}d)", _money(p.credit)]
    return ([p.name + " [at target]" * p.at_target, p.strikes, _day(p.entered), str(p.lots)] + first
            + [_pnl(p), f"{p.away:.1%}" if p.away is not None else "n/a"])


TARGET = 0.5   # the exit: half the credit captured


def _days(n: int) -> str:
    return "today" if n == 0 else f"in {n} day{'s' * (n != 1)}"


def _progress(p: Position) -> str:
    """A thin bar of the way to the profit target; red when the position is under water."""
    if p.pct is None:
        return ""
    fill = max(2, min(100, round(abs(p.pct) / TARGET * 100)))
    colour = h.GREEN if p.pct >= 0 else h.RED
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:8px 0 0 0"><tr>'
            f'<td width="{fill}%" height="4" bgcolor="{colour}" style="font-size:1px;line-height:1px">&nbsp;</td>'
            + (f'<td height="4" bgcolor="{h.LINE}" style="font-size:1px;line-height:1px">&nbsp;</td>' if fill < 100 else "")
            + "</tr></table>")


def _item(p: Position, risk: bool) -> str:
    """One position as a row: name and plain details on the left, the number that matters on the right."""
    tag = (" " + h.pill("AT\u00a0TARGET", h.GREEN)) * p.at_target
    cushion = f" · {p.away:.1%} cushion" if p.away is not None else ""
    detail = f"{p.strikes} · {p.lots} lot{'s' * (p.lots != 1)} · entered {_day(p.entered)}"
    when = f"Expires {_day(p.expires)} ({p.dte}d){cushion}"
    if risk:
        big, sub = h.money(p.worst), f"uses ${p.bp:,.0f}"
    else:
        big = h.money(p.pnl, True) if p.pnl is not None else "n/a"
        sub = f"{p.pct:.0%} of credit" if p.pct is not None else "not marked yet"
    return (f'<tr><td valign="top" style="padding:12px 12px 12px 0;border-bottom:1px solid {h.LINE}">'
            f'<div style="font-size:15px;font-weight:600">{h.e(p.title)}{tag}</div>'
            f'<div style="margin:2px 0 0 0;font-size:12px;color:{h.MUTED}">{h.e(when)}</div>'
            f'<div style="font-size:12px;color:{h.MUTED}">{h.e(detail)}</div></td>'
            f'<td align="right" valign="top" width="38%" style="padding:12px 0;border-bottom:1px solid {h.LINE}">'
            f'<div style="font-size:16px;font-weight:700">{h.e(big)}</div>'
            f'<div style="font-size:11px;color:{h.MUTED}">{h.e(sub)}</div>'
            + ("" if risk else _progress(p)) + "</td></tr>")


def _list(rows: list[Position], risk: bool) -> h.Raw:
    return h.Raw('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">'
                 + "".join(_item(p, risk) for p in rows) + "</table>")


def _tables(pos: list[Position]) -> list[tuple[str, list[str], list[Position], bool]]:
    """(title, number columns, positions, risk columns?) for the two Monday tables, up to TOP rows each."""
    count = f" ({TOP} of {len(pos)})" if len(pos) > TOP else ""
    soon = sorted(pos, key=lambda p: (p.expires, p.entered))[:TOP]
    risky = sorted(pos, key=lambda p: (p.worst is None, p.worst or 0.0))[:TOP]
    tail = ["P/L (of credit)", "To short strike"]
    return [(f"Closest to expiry{count}", ["Expires", "Credit"] + tail, soon, False),
            (f"Most at risk, by stated worst case{count}", ["Worst case", "Buying power"] + tail, risky, True)]


def monday(conn, asof: date, kind: str = "taken") -> tuple[str, str, str]:
    """(subject, plain text, HTML) of the Monday outlook: what is open, what expires first, what could lose most."""
    pos = [p for p in book(conn, asof, kind) if not p.closed]
    n, soon = len(pos), sum(p.dte <= 7 for p in pos)
    credit, bp = sum(p.credit for p in pos), sum(p.bp for p in pos)
    pnl, worst = sum(p.pnl or 0.0 for p in pos), sum(p.worst or 0.0 for p in pos)
    marked = max((p.marked for p in pos if p.marked), default=None)
    title = f"{n} open position{'s' * (n != 1)}"
    subject = f"[StormGlass] Monday outlook {asof.isoformat()}: {title}" + (f", unrealized {_money(pnl, True)}" if n else "")
    stats = [("Open positions", str(n), f"{soon} expire{'s' * (soon == 1)} within 7 days"),
             ("Credit open", _money(credit), "collected at entry"),
             ("Unrealized P/L", _money(pnl, True), f"marks of {_day(marked)}" if marked else "no marks yet"),
             ("Buying power in use", f"${bp:,.0f}", f"stated worst case {_money(worst)}")]
    text = [f"STORMGLASS | MONDAY OUTLOOK | {asof.isoformat()} | {BOOK_NAME[kind]}", BOOK_NOTE[kind], ""]
    parts: list = []
    if not pos:
        text.append("No open positions in this book.")
        parts.append(h.note("No open positions in this book."))
    else:
        text += _cols([[k, f"{v} ({note})"] for k, v, note in stats])
        parts.append(h.tiles([("Credit open", h.money(credit), "collected at entry"),
                              ("Buying power", f"${bp:,.0f}", "in use"),
                              ("Worst case", h.money(worst), "all positions, stress test")]))
        for name, head, rows, risk in _tables(pos):
            text += ["", name.upper()] + _cols([["Position", "Strikes", "Entered", "Lots"] + head] + [_row(p, risk) for p in rows])
            parts += [h.section(("Biggest downside" if risk else "Expiring soonest") + name[name.find(" ("):] * (" (" in name)),
                      _list(rows, risk)]
    text += ["", MARKS_NOTE, h.DISCLAIMER]
    d = f"{asof:%a %b} {asof.day}, {asof.year}"
    sub = (f"{_money(pnl, True)} unrealized  ·  {soon} expiring this week  ·  {BOOK_NAME[kind]}" if n
           else f"As of {d}  ·  {BOOK_NAME[kind]}")
    html = h.page("MONDAY OUTLOOK", h.BLUE, f"digest-monday-{asof.isoformat()}", title, sub, parts,
                  [f"As of {d}.", BOOK_NOTE[kind], HTML_NOTE, h.DISCLAIMER], preheader=subject.split(": ", 1)[-1])
    return subject, "\n".join(text) + "\n", html


def build(which: str, conn, asof: date, kind: str = "taken") -> tuple[str, str, str]:
    return {"monday": monday}[which](conn, asof, kind)


def send(conn, profile, params, which: str, asof: date, message: tuple[str, str, str], channel=None,
         now=clock.now_utc, sleep=time.sleep) -> str:
    """Email one digest, once per date. Returns sent, already_sent, no_channel or failed."""
    kind, day = f"digest_{which}", asof.isoformat()
    if store.rows(conn, "SELECT 1 FROM event WHERE kind = ? AND detail = ?", (kind, day)):
        return "already_sent"
    try:
        channel = channel or notify.channel_for(profile)
    except notify.ChannelError as e:
        store.event(conn, now(), "delivery_failed", f"{which} digest {day}: {e}")
        return "failed"
    if channel is None:
        return "no_channel"
    attempts, err = int(params.notify.get("max_attempts", 3)), ""
    for i in range(1, attempts + 1):
        try:
            channel.send(*(message if getattr(channel, "html", False) else message[:2]))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if i < attempts:
                sleep(float(params.notify.get("retry_wait_seconds", 5)) * i)
            continue
        store.event(conn, now(), kind, day)
        return "sent"
    store.event(conn, now(), "delivery_failed", f"{which} digest {day}: {attempts} attempts; last error {err}")
    return "failed"
