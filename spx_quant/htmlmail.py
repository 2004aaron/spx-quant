"""HTML email bodies for alerts and the weekly report (US-07, US-11).

The plain-text body stays the logged record and the plain-text alternative; the HTML
body carries the same content with bold headings and tables. The Gmail connector the
scheduled tasks send through strips <style> blocks, class attributes and the
`background` shorthand, so every style here is inline, backgrounds are
`background-color` or `bgcolor`, and padding comes from `cellpadding` to keep the
message small enough for the task to pass along.
"""
from __future__ import annotations

from html import escape

INK, MUTED, LINE, SHADE = "#1f2328", "#59636e", "#d1d9e0", "#f6f8fa"
NAVY, ACCENT, RED, GREEN, PALE = "#13203a", "#d08a52", "#cf222e", "#1a7f37", "#b9c3d4"
BADGE = {"PROPOSAL": GREEN, "STAND DOWN": "#9a6700", "NO ADVICE": MUTED, "NO CHANGE": "#0969da",
         "WEEKLY REPORT": ACCENT}
FONT = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "Menlo,Consolas,monospace"
CAPS = "text-transform:uppercase;letter-spacing:.5px"


class Raw(str):
    """Markup that is already escaped."""


def e(x) -> str:
    return x if isinstance(x, Raw) else escape(str(x))


def money(v: float | None, signed: bool = False, cents: bool = False) -> Raw:
    if v is None:
        return Raw("n/a")
    s = f"${abs(v):,.2f}" if cents else f"${abs(v):,.0f}"
    if v < 0:
        return Raw(f'<span style="color:{RED}">-{s}</span>')
    return Raw(("+" if signed and v > 0 else "") + s)


def b(x) -> Raw:
    return Raw(f"<strong>{e(x)}</strong>")


def mono(x, small: bool = False) -> Raw:
    style = f"font-size:11px;color:{MUTED}" if small else "font-size:12px;white-space:nowrap"
    return Raw(f'<span style="font-family:{MONO};{style}">{e(x)}</span>')


def table(head: list[str] | None, rows: list[list], right: tuple[int, ...] = (), nowrap: tuple[int, ...] = ()) -> Raw:
    """Striped rows instead of per-cell borders: the stripe is one attribute per row."""
    th = f"border-bottom:1px solid {LINE};color:{MUTED};font-size:11px;font-weight:600;{CAPS}"

    def cell(tag, i, c):
        align = ' align="right"' if i in right else (' align="left"' if tag == "th" else "")
        style = (th + (";white-space:nowrap" if i in nowrap else "") if tag == "th"
                 else ("white-space:nowrap" if i in nowrap else ""))
        return f'<{tag}{align}{f" style={chr(34)}{style}{chr(34)}" if style else ""}>{e(c)}</{tag}>'
    out = [f'<table cellpadding="6" cellspacing="0" width="100%" style="border-collapse:collapse;border:1px solid {LINE};'
           f'margin:0 0 4px 0;font-size:13px;color:{INK}">']
    if head:
        out.append(f'<tr bgcolor="{SHADE}">' + "".join(cell("th", i, x) for i, x in enumerate(head)) + "</tr>")
    for n, r in enumerate(rows):
        stripe = f' bgcolor="{SHADE}"' if n % 2 == (0 if not head else 1) else ""
        out.append(f'<tr valign="top"{stripe}>' + "".join(cell("td", i, c) for i, c in enumerate(r)) + "</tr>")
    return Raw("".join(out) + "</table>")


def kv(pairs: list[tuple]) -> Raw:
    return table(None, [[b(k), v] for k, v in pairs])


def tiles(items: list[tuple]) -> Raw:
    """Headline numbers, (label, value, small print) each. Inline blocks, so four fit across a
    desktop window and they wrap two by two on a phone."""
    return Raw("<div>" + "".join(
        f'<div style="display:inline-block;vertical-align:top;width:128px;margin:0 6px 6px 0;padding:8px 10px;'
        f'border:1px solid {LINE}"><div style="font-size:11px;color:{MUTED};{CAPS}">{e(label)}</div>'
        f'<div style="font-size:20px;font-weight:700;color:{INK};padding-top:2px">{e(value)}</div>'
        f'<div style="font-size:12px;color:{MUTED};padding-top:2px">{e(sub)}</div></div>' for label, value, sub in items)
        + "</div>")


def bullets(items: list) -> Raw:
    return Raw(f'<ul style="margin:0;padding-left:20px;font-size:13px">'
               + "".join(f'<li style="margin:0 0 4px 0">{e(x)}</li>' for x in items) + "</ul>")


def para(x, small: bool = False) -> Raw:
    style = f"font-size:12px;color:{MUTED}" if small else "font-size:14px"
    return Raw(f'<p style="margin:0 0 6px 0;line-height:1.45;{style}">{e(x)}</p>')


def callout(x, ok: bool = False) -> Raw:
    return Raw(f'<div style="border-left:4px solid {GREEN if ok else ACCENT};background-color:{SHADE};'
               f'padding:10px 12px;font-size:13px;margin:4px 0">{e(x)}</div>')


def section(title: str, *parts) -> Raw:
    return Raw(f'<tr><td style="padding:14px 16px 4px 16px"><div style="font-size:13px;font-weight:700;color:{NAVY};'
               f'{CAPS};padding-bottom:6px">{e(title)}</div>' + "".join(e(p) for p in parts) + "</td></tr>")


def page(title: str, ident: str, meta: list[str], headline, sections: list[Raw], footer: list[str]) -> str:
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{SHADE}" style="background-color:{SHADE};'
        f'font-family:{FONT};color:{INK}"><tr><td align="center" style="padding:16px 8px">'
        f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#ffffff" style="max-width:680px;'
        f'background-color:#ffffff;border:1px solid {LINE};font-family:{FONT};color:{INK}">'
        f'<tr><td bgcolor="{NAVY}" style="background-color:{NAVY};padding:16px">'
        f'<div style="font-size:12px;font-weight:700;letter-spacing:2px;color:{ACCENT}">STORMGLASS</div>'
        f'<div style="padding-top:8px"><span style="background-color:{BADGE.get(title, MUTED)};color:#ffffff;font-size:12px;'
        f'font-weight:700;letter-spacing:1px;padding:3px 8px;border-radius:3px">{e(title)}</span>'
        f'<span style="font-family:{MONO};font-size:12px;color:{PALE};padding-left:8px">{e(ident)}</span></div>'
        + "".join(f'<div style="font-size:12px;color:{PALE};padding-top:2px;word-break:break-word">{e(m)}</div>' for m in meta)
        + f'</td></tr><tr><td style="padding:16px 16px 0 16px;font-size:17px;font-weight:700;line-height:1.35">{e(headline)}'
        "</td></tr>" + "".join(sections)
        + f'<tr><td style="padding:16px 16px 18px 16px;font-size:11px;color:{MUTED};border-top:1px solid {LINE}">'
        + "".join(f'<div style="padding-top:4px">{e(f)}</div>' for f in footer) + "</td></tr></table></td></tr></table>")
