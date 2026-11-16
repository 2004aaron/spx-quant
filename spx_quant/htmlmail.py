"""HTML bodies for every StormGlass email (US-07): alerts, the Monday outlook, the Friday close.

The plain-text body stays the logged record and travels as the text alternative; the HTML
carries the same facts laid out as a card: headline, four key numbers, tables. Mail clients
drop <style> blocks and class names, so every style is inline and layout is tables.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from html import escape
from urllib.parse import quote

from . import clock
from .alert import CURVE_ORDER, KIND_TITLE, _money
from .engine import BOOK_NOTE, ScanResult
from .takeprofit import limit_price

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


def page(badge: str, colour: str, ref: str, title: str, sub: str, parts: list, footer: list[str], preheader: str = "") -> str:
    """The card every email shares: navy band, headline, body, small print. `preheader` is the inbox preview line."""
    foot = "".join(f'<div style="margin:0 0 3px 0">{e(x)}</div>' for x in footer)
    return (
        f'<!DOCTYPE html><html><body style="margin:0;padding:0;background-color:{PAGE}">'
        + (f'<div style="display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;color:{PAGE}">'
           f'{e(preheader)}</div>' if preheader else "") +
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
# The alert card keeps only what a person needs to decide: the trade, what it pays, the odds, where the
# index has to stay, the downside, and one tap to answer. Risk tables, ranking, assumptions and rejected
# candidates stay in the plain-text body and the log, which remain the full record.

def _fine_print(res: ScanResult, created_ts: datetime) -> list[str]:
    age = f"{res.quote_age_min:.0f} min old, " if res.quote_age_min is not None else ""
    data = f"{clock.fmt(res.data_ts)} ({age}{res.source})" if res.data_ts is not None else f"n/a ({res.source})"
    out = [f"Output: {clock.fmt(created_ts)}", f"Data as of: {data}"]
    if res.spot is not None:
        curve = "  ".join(f"{name} {res.curve[k]:.2f}" for k, name in CURVE_ORDER if res.curve.get(k) is not None)
        out.append(f"{(res.market_ticker or '_SPX').lstrip('_')} {res.spot:,.2f}  {curve}".rstrip())
    return out + ["Full detail (risk, sizing, assumptions) is in the log under the ID above.", DISCLAIMER]


def _order(c) -> Raw:
    """One line per leg: what to do, then the contract and its quotes in small print."""
    rows = []
    for l in sorted(c.position.legs, key=lambda l: (l.right, l.strike)):
        sell = l.qty < 0
        what = (f'<strong style="color:{RED if sell else GREEN}">{"Sell" if sell else "Buy"}</strong> '
                f'{abs(l.qty) * c.sized.contracts} &times; {l.strike:g} {"put" if l.right == "P" else "call"}')
        quote = f'<span style="font-family:{MONO}">{e(l.sym)}</span>&nbsp; bid {l.bid:.2f} / ask {l.ask:.2f}'
        rows.append(f'<tr><td style="padding:12px 0;border-bottom:1px solid {LINE};font-size:16px">{what}'
                    f'<div style="margin:3px 0 0 0;font-size:11px;color:{MUTED}">{quote}</div></td>'
                    f'<td align="right" valign="top" style="padding:12px 0;border-bottom:1px solid {LINE};font-size:16px">'
                    f'<strong>{l.mid:.2f}</strong><div style="font-size:11px;color:{MUTED}">price</div></td></tr>')
    return Raw(f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{"".join(rows)}</table>')


def _underlying(res: ScanResult) -> float | None:
    """The proposal's own index level: XSP is a tenth of SPX."""
    if res.spot is None:
        return None
    return res.spot / 10 if res.best.position.ticker == "_XSP" else res.spot


def _zone(res: ScanResult) -> list:
    """Where the index has to finish for the trade to make money, as a sentence and a coloured bar."""
    p, r = res.best.position, res.best.risk
    now, be = _underlying(res), sorted(r.breakevens)
    if now is None or not be or len(be) > 2:
        return []
    name, day = p.ticker.lstrip("_"), f"{p.exp:%b} {p.exp.day}"
    if len(be) == 2:
        zones = [(be[0], False), (be[1], True), (None, False)]
        text = (f"You profit if {name} finishes between <strong>{be[0]:,.0f}</strong> and <strong>{be[1]:,.0f}</strong> "
                f"on {day}. Today it is {now:,.0f}: it can fall {(now - be[0]) / now:.1%} or rise "
                f"{(be[1] - now) / now:.1%} before you lose money.")
    else:
        up = now > be[0]
        zones = [(be[0], not up), (None, up)]
        text = (f"You profit if {name} finishes {'above' if up else 'below'} <strong>{be[0]:,.0f}</strong> on {day}. "
                f"Today it is {now:,.0f}: it can {'fall' if up else 'rise'} {abs(now - be[0]) / now:.1%} "
                f"before you lose money.")
    lo, hi = min(be + [now]) * 0.97, max(be + [now]) * 1.03
    pct = lambda x: max(1, round((x - lo) / (hi - lo) * 100))
    cells, edge, marks = [], lo, []
    for stop, good in zones:
        end = hi if stop is None else stop
        cells.append(f'<td width="{pct(end) - pct(edge)}%" height="10" bgcolor="{GREEN if good else "#f2c4c4"}" '
                     f'style="font-size:1px;line-height:1px">&nbsp;</td>')
        edge = end
    at = pct(now)
    label = f'<span style="font-size:12px;font-weight:600;color:{INK}">&#9650; today {now:,.0f}</span>'
    marker = (f'<td width="{at}%"></td><td align="left">{label}</td>' if at < 60
              else f'<td width="{at}%" align="right">{label}</td><td></td>')
    bar = (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:12px 0 0 0">'
           f'<tr>{"".join(cells)}</tr></table>'
           f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:4px 0 0 0"><tr>{marker}</tr></table>')
    return [section(f"Where {name} needs to be"), Raw(f'<p style="margin:0;font-size:15px;line-height:22px">{text}</p>'), Raw(bar)]


def _button(label: str, href: str, solid: bool) -> str:
    style = (f"background-color:{GREEN};color:#ffffff;border:1px solid {GREEN}" if solid
             else f"background-color:#ffffff;color:{INK};border:1px solid #b6bec8")
    return (f'<td style="padding:0 8px 8px 0"><a href="{e(href)}" style="display:inline-block;padding:10px 14px;white-space:nowrap;'
            f'border-radius:6px;font-size:15px;font-weight:600;text-decoration:none;{style}">{e(label)}</a></td>')


def _answer(aid: str, reply_to: str | None) -> list:
    """One-tap answers: each button opens a reply whose subject carries the alert ID and whose first line
    is the decision, which is what the reply reader looks for. Text instructions only when there is no sender address."""
    how = Raw("Or just reply with <strong>ACCEPTED</strong>, <strong>DECLINED</strong> or <strong>MODIFIED 2</strong> "
              "(the lots you took), with your fill price if you like: <strong>ACCEPTED @ 7.05</strong>. "
              "Reply <strong>CLOSED</strong> later if you exit early.")
    if not reply_to:
        return [callout(how)]
    subj = quote(f"Re: [StormGlass {aid}]")
    href = lambda body: f"mailto:{reply_to}?subject={subj}&body={quote(body)}"
    buttons = (_button("I took it", href("ACCEPTED"), True) + _button("I passed", href("DECLINED"), False)
               + _button("Took fewer", href("MODIFIED "), False))
    return [Raw(f'<table cellpadding="0" cellspacing="0" style="margin:22px 0 0 0"><tr>{buttons}</tr></table>')]


def _why(res: ScanResult) -> str:
    p, r = res.best.position, res.best.risk
    if p.strategy in res.preferred and len(res.ranked) > 1:
        return f"The market is trending up, which favors the {p.label()}."
    if len(res.ranked) == 1:
        return f"The only trade that fit your limits today ({r.ann_return_bp:.1f}% a year expected on buying power)."
    return (f"Best expected return of the {len(res.ranked)} trades that fit your limits "
            f"({r.ann_return_bp:.1f}% a year on buying power).")


def reply_address(env=os.environ) -> str | None:
    return env.get("SPX_QUANT_SMTP_FROM") or env.get("SPX_QUANT_SMTP_USER") or None


def alert_html(res: ScanResult, aid: str, created_ts: datetime, prev: dict | None = None,
               reply_to: str | None = None) -> str:
    """The HTML twin of alert.render (prev=None) or alert.render_unchanged (prev = the alert repeated)."""
    footer = _fine_print(res, created_ts)
    if res.kind != "proposal":
        what = KIND_TITLE.get(res.kind, "SCAN")
        title = "Do not enter today" if res.kind == "stand_down" else "No trade today"
        badge = "NO CHANGE" if prev else what
        sub = f"Unchanged since {prev['alert_id']}" if prev else "Sit this one out. Here is why:"
        return page(badge, BADGE.get(badge, MUTED), aid, title, sub, [Raw('<div style="height:12px"></div>'),
                    bullets(res.reasons)], footer, preheader=res.reasons[0] if res.reasons else "")

    c = res.best
    p, s, r = c.position, c.sized, c.risk
    lots = f"{s.contracts} lot{'' if s.contracts == 1 else 's'}"
    title = f"Sell {lots} of the {p.ticker.lstrip('_')} {p.label()}"
    sub = f"Expires {p.exp:%a %b} {p.exp.day} ({p.dte} days)"
    move = r.assumptions.get("worst_case_move")
    numbers = tiles([
        ("You collect", money(p.credit * s.contracts), f"${p.credit:,.0f} per lot" if s.contracts > 1 else "up front"),
        ("Profit odds", f"{r.pop:.0%}", "model estimate"),
        ("Worst case", money(r.worst_case), f"if the index drops {abs(move):.0%} fast" if move else "stress test"),
    ])
    why = {"worst case": "stay inside your worst-case limit", BOOK_NOTE: "fit your remaining buying power"}
    cut = ""
    if s.bp_contracts > s.contracts and s.limited_by in why:
        cut = f" Cut from {s.bp_contracts} to {s.contracts} lot{'' if s.contracts == 1 else 's'} to {why[s.limited_by]}."
    uses = small(f"Uses ${s.bp_total:,.0f} of your ${s.cap:,.0f} buying power.{cut}")
    gtc = callout(Raw(f"<strong>Then set your take-profit:</strong> a GTC buy-to-close for the whole order at "
                      f"<strong>${limit_price({'credit_per_lot': p.credit}):.2f}</strong>, half the credit. Your broker closes it "
                      f"at the 50% target and StormGlass asks after the close whether it filled. Filled at a different price? "
                      f"Use half of what you got, and add it to your answer: <strong>ACCEPTED @ 7.05</strong>."))
    preview = f"Collect {_money(p.credit * s.contracts)}, {r.pop:.0%} odds, worst case {_money(r.worst_case)}"
    reply_to = reply_to if reply_to is not None else reply_address()
    if prev:
        return page("NO CHANGE", BLUE, aid, f"Still stands: {title[0].lower()}{title[1:]}",
                    f"Same proposal as {prev['alert_id']}  ·  {sub}",
                    [numbers, section("The order"), _order(c), uses, gtc] + _answer(aid, reply_to), footer, preheader=preview)
    parts = [numbers] + _zone(res) + [section("The order"), _order(c), uses, gtc] + _answer(aid, reply_to)
    parts += [section("Why this trade"), note(_why(res))]
    return page("PROPOSAL", GREEN, aid, title, sub, parts, footer, preheader=preview)
