"""HTML bodies for every StormGlass email (US-07): alerts, the Monday outlook, the Friday close.

The plain-text body stays the logged record and travels as the text alternative; the HTML
carries the same facts laid out as a card: headline, four key numbers, tables. Mail clients
drop <style> blocks and class names, so every style is inline and layout is tables.
"""
from __future__ import annotations

import re
from datetime import datetime
from html import escape

from . import clock
from .alert import (CURVE_ORDER, KIND_TITLE, _money, email_notes, ranked_first, risk_rows, sizing_notes,
                    sizing_rows)
from .analytics import assumptions_text
from .engine import ScanResult

INK, MUTED, LINE, SHADE, PAGE = "#1f2328", "#59636e", "#d8dee4", "#f6f8fa", "#eef1f5"
NAVY, AMBER, RED, GREEN, BLUE, GOLD = "#13203a", "#d08a52", "#cf222e", "#1a7f37", "#0969da", "#9a6700"
BADGE = {"PROPOSAL": GREEN, "STAND DOWN": GOLD, "NO ADVICE": MUTED, "NO CHANGE": BLUE}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,Menlo,Consolas,monospace"
CAPS = f"font-size:11px;font-weight:600;color:{MUTED};text-transform:uppercase;letter-spacing:.6px"
DISCLAIMER = "Model estimates with tagged assumptions, not investment advice. The engine never places orders."


class Raw(str):
    """Markup that is already escaped."""


def e(x) -> str:
    return x if isinstance(x, Raw) else escape(str(x))


def red(text: str) -> Raw:
    """Escape, then colour every negative dollar amount."""
    return Raw(re.sub(r"-\$[\d,.]*\d", lambda m: f'<span style="color:{RED}">{m[0]}</span>', escape(text)))


def money(v: float | None, signed: bool = False) -> Raw:
    return red(_money(v, signed))


def pill(text: str, colour: str) -> Raw:
    return Raw(f'<span style="display:inline-block;padding:2px 9px;border-radius:10px;background-color:{colour};'
               f'color:#ffffff;font-size:11px;font-weight:600;letter-spacing:.4px">{e(text)}</span>')


def section(title: str) -> Raw:
    return Raw(f'<div style="{CAPS};margin:22px 0 8px 0">{e(title)}</div>')


def tiles(items: list[tuple[str, object, str]]) -> Raw:
    """A row of key numbers: (label, value, small note under it)."""
    w = 100 // len(items)
    cells = "".join(
        f'<td width="{w}%" valign="top" style="padding:12px 10px;border:1px solid {LINE};background-color:{SHADE}">'
        f'<div style="{CAPS};font-size:10px">{e(label)}</div>'
        f'<div style="font-size:19px;font-weight:700;line-height:26px">{e(value)}</div>'
        f'<div style="font-size:11px;color:{MUTED}">{e(note)}</div></td>' for label, value, note in items)
    return Raw(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
               f'style="border-collapse:collapse;margin:16px 0 0 0"><tr>{cells}</tr></table>')


def table(head: list[str], rows: list[list], right: tuple[int, ...] = (), foot: list | None = None, pad: int = 8) -> Raw:
    """`pad` is the space left and right of each cell; a table with many number columns takes less to fit a phone."""
    def cell(tag, i, c, extra=""):
        align = "right" if i in right else "left"
        return f'<{tag} align="{align}" style="padding:7px {pad}px;{extra}">{e(c)}</{tag}>'
    out = [f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;color:{INK}">',
           "<tr>" + "".join(cell("th", i, h, f"{CAPS};font-size:10px;border-bottom:2px solid {LINE}")
                            for i, h in enumerate(head)) + "</tr>"]
    for n, r in enumerate(rows):
        shade = f' bgcolor="{SHADE}"' if n % 2 else ""
        out.append(f"<tr{shade}>" + "".join(cell("td", i, c, f"border-bottom:1px solid {LINE}") for i, c in enumerate(r)) + "</tr>")
    if foot:
        out.append("<tr>" + "".join(cell("td", i, c, "font-weight:700") for i, c in enumerate(foot)) + "</tr>")
    return Raw("".join(out) + "</table>")


def pairs(rows: list[tuple[str, str]]) -> Raw:
    """Label on the left, value on the right."""
    body = "".join(f'<tr><td valign="top" style="padding:6px 12px 6px 0;color:{MUTED};border-bottom:1px solid {LINE}" width="42%">'
                   f'{e(k)}</td><td valign="top" style="padding:6px 0;border-bottom:1px solid {LINE}">{red(v)}</td></tr>'
                   for k, v in rows)
    return Raw(f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px">{body}</table>')


def bullets(items: list[str], small: bool = False) -> Raw:
    style = f"font-size:12px;color:{MUTED}" if small else "font-size:13px"
    return Raw(f'<ul style="margin:0;padding:0 0 0 18px;{style}">'
               + "".join(f'<li style="margin:0 0 4px 0">{red(x)}</li>' for x in items) + "</ul>")


def note(text) -> Raw:
    return Raw(f'<p style="margin:10px 0 0 0;font-size:13px">{e(text)}</p>')


def small(text) -> Raw:
    return Raw(f'<p style="margin:6px 0 0 0;font-size:12px;line-height:17px;color:{MUTED}">{e(text)}</p>')


def callout(text) -> Raw:
    return Raw(f'<div style="margin:18px 0 0 0;padding:12px 14px;border-left:4px solid {AMBER};background-color:#fdf6ee;'
               f'font-size:13px;line-height:19px">{e(text)}</div>')


def page(badge: str, colour: str, ref: str, title: str, sub: str, parts: list, footer: list[str]) -> str:
    """The card every email shares: navy band, headline, body, small print."""
    foot = "".join(f'<div style="margin:0 0 3px 0">{e(x)}</div>' for x in footer)
    return (
        f'<!DOCTYPE html><html><body style="margin:0;padding:0;background-color:{PAGE}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}"><tr>'
        f'<td align="center" style="padding:24px 10px">'
        f'<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;'
        f'background-color:#ffffff;border:1px solid {LINE};font-family:{FONT};color:{INK};font-size:14px;line-height:20px">'
        f'<tr><td bgcolor="{NAVY}" style="padding:14px 24px"><table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0"><tr><td style="color:#ffffff;font-size:13px;font-weight:700;letter-spacing:3px">STORMGLASS</td>'
        f'<td align="right">{pill(badge, colour)}</td></tr></table></td></tr>'
        f'<tr><td style="padding:22px 24px 24px 24px">'
        f'<div style="font-size:22px;line-height:28px;font-weight:700">{e(title)}</div>'
        f'<div style="margin:4px 0 0 0;font-size:14px;color:{MUTED}">{e(sub)}</div>'
        + "".join(e(x) for x in parts) +
        f'</td></tr><tr><td style="padding:14px 24px;border-top:1px solid {LINE};background-color:{SHADE};font-size:11px;'
        f'line-height:16px;color:{MUTED}"><div style="margin:0 0 3px 0;font-family:{MONO}">{e(ref)}</div>{foot}</td></tr>'
        f'</table></td></tr></table></body></html>')


# ---- alerts ----

def _stamps(res: ScanResult, created_ts: datetime) -> list[str]:
    age = f"{res.quote_age_min:.0f} min old, " if res.quote_age_min is not None else ""
    data = f"{clock.fmt(res.data_ts)} ({age}{res.source})" if res.data_ts is not None else f"n/a ({res.source})"
    return [f"Output: {clock.fmt(created_ts)}", f"Data as of: {data}"]


def _market(res: ScanResult) -> list:
    if res.spot is None and res.regime is None:
        return []
    rows = []
    if res.spot is not None:
        rows.append(((res.market_ticker or "_SPX").lstrip("_"), f"{res.spot:,.2f}"))
        vals = "   ".join(f"{name} {res.curve[k]:.2f}" for k, name in CURVE_ORDER if res.curve.get(k) is not None)
        if vals:
            rows.append(("Volatility curve", vals))
    if res.regime is not None:
        r = res.regime
        slope = f" (slope {r.slope:+.3f})" if r.slope is not None else ""
        rows.append(("Regime", f"{r.state} / {r.bucket}{slope}" if r.known else f"unknown ({r.reason})"))
    if res.trend is not None:
        rows.append(("Trend", str(res.trend)))
    return [section("Market"), pairs(rows)]


def _legs(c) -> Raw:
    rows = []
    for l in sorted(c.position.legs, key=lambda l: (l.right, l.strike)):
        sell = l.qty < 0
        rows.append([Raw(f'<strong style="color:{RED if sell else GREEN}">{"SELL" if sell else "BUY"}</strong>'),
                     abs(l.qty) * c.sized.contracts, Raw(f'<span style="font-family:{MONO};font-size:12px">{e(l.sym)}</span>'),
                     f"{l.strike:g} {'put' if l.right == 'P' else 'call'}", f"{l.bid:.2f}", f"{l.ask:.2f}",
                     Raw(f"<strong>{l.mid:.2f}</strong>"), f"{l.iv:.1%}", f"{l.delta:+.3f}"])
    return table(["Side", "Qty", "Contract", "Strike", "Bid", "Ask", "Mid", "IV", "Delta"], rows, right=(1, 4, 5, 6, 7, 8))


def _tail(res: ScanResult) -> list:
    out = []
    if res.rejected:
        out += [section("Considered, not proposed"),
                bullets([f"{c.position.label()} {c.position.ticker.lstrip('_')} {c.position.exp:%m/%d} "
                         f"{c.position.legs_text()}: {'; '.join(c.reasons)}" for c in res.rejected], small=True)]
    if email_notes(res):
        out += [section("Notes"), bullets(email_notes(res))]
    return out


def alert_html(res: ScanResult, aid: str, created_ts: datetime, prev: dict | None = None) -> str:
    """The HTML twin of alert.render (prev=None) or alert.render_unchanged (prev = the alert repeated)."""
    footer = _stamps(res, created_ts) + [res.params_summary, DISCLAIMER]
    reply = Raw("Reply to this email with <strong>ACCEPTED</strong>, <strong>DECLINED</strong> or "
                "<strong>MODIFIED 2</strong> (the contracts you took) as the first word. "
                "Later, reply <strong>CLOSED</strong> if you exit early.")
    if res.kind != "proposal":
        what = KIND_TITLE.get(res.kind, "SCAN")
        title = "Do not enter today" if res.kind == "stand_down" else f"No advice ({res.outcome.replace('_', ' ')})"
        badge = "NO CHANGE" if prev else what
        sub = f"Unchanged since {prev['alert_id']}" if prev else "Nothing to act on from this scan"
        return page(badge, BADGE.get(badge, MUTED), aid, title, sub,
                    [section("Why"), bullets(res.reasons)] + _market(res) + ([] if prev else _tail(res)), footer)

    c = res.best
    p, s, r, prof = c.position, c.sized, c.risk, res.profile
    lots = f"{s.contracts} lot{'' if s.contracts == 1 else 's'}"
    title = f"Sell {lots} of the {p.ticker.lstrip('_')} {p.label()}"
    sub = f"Expires {p.exp:%a %b} {p.exp.day}, {p.exp.year} ({p.dte} days)  ·  {p.legs_text()}"
    numbers = tiles([
        ("Credit", money(p.credit * s.contracts), f"${p.credit:,.2f} per lot at mid"),
        ("Chance of profit", f"{r.pop:.0%}", "model estimate"),
        ("Worst case", money(r.worst_case), f"{abs(r.worst_case) / prof.net_liq:.0%} of net liq, stress test"),
        ("Buying power", f"${s.bp_total:,.0f}", f"cap ${s.cap:,.0f}"),
    ])
    if prev:
        return page("NO CHANGE", BLUE, aid, f"Still stands: {title[0].lower()}{title[1:]}",
                    f"Same proposal as {prev['alert_id']}  ·  {sub}",
                    [numbers, section("Order, at current quotes"), _legs(c), callout(reply)] + _market(res), footer)
    stress = table([f"{mv:+.0%}" for mv, _ in r.stress], [[money(v, True) for _, v in r.stress]],
                   right=tuple(range(len(r.stress))))
    risk = [(k, v) for k, v in risk_rows(c, prof) if not k.startswith("Stress")]
    parts = [numbers, section("Order"), _legs(c), callout(reply),
             section("Sizing"), pairs(sizing_rows(c, prof))] + [note(n) for n in sizing_notes(s)]
    parts += [section(f"Risk, model estimates for {'1 lot' if s.contracts == 1 else f'all {s.contracts} lots'}"), pairs(risk),
              section("If the index moved right now"), stress]
    parts += _market(res)
    parts += [section("Why this trade"), note(ranked_first(res))]
    if len(res.ranked) > 1:
        parts.append(table(["#", "Candidate", "Return on BP", "EV", "Chance", "Worst case"],
                           [[i, f"{x.position.label()} {x.position.ticker.lstrip('_')} {x.position.exp:%m/%d} "
                                f"{x.position.legs_text()} x{x.sized.contracts}", f"{x.risk.ann_return_bp:.1f}%/yr",
                             money(x.risk.ev), f"{x.risk.pop:.0%}", money(x.risk.worst_case)]
                            for i, x in enumerate(res.ranked, 1)], right=(2, 3, 4, 5)))
    parts += _tail(res) + [section("Assumptions"), small(assumptions_text(r.assumptions))]
    return page("PROPOSAL", GREEN, aid, title, sub, parts, footer)
