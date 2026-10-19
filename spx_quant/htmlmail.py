"""HTML email bodies for alerts and the weekly report (US-07, US-11).

The plain-text body stays the logged record and the plain-text alternative; the HTML
body carries the same content with bold headings and tables. Styling lives in one
<style> block in the head (Gmail, Apple Mail and Outlook read it) so the message stays
small enough for the scheduled task to pass through the Gmail connector. A client that
drops the block still gets real tables, bold labels and right-aligned numbers from the
markup itself.
"""
from __future__ import annotations

from html import escape

INK, MUTED, LINE, SHADE = "#1f2328", "#59636e", "#d1d9e0", "#f6f8fa"
NAVY, ACCENT, RED, GREEN = "#13203a", "#d08a52", "#cf222e", "#1a7f37"
BADGE = {"PROPOSAL": GREEN, "STAND DOWN": "#9a6700", "NO ADVICE": MUTED, "NO CHANGE": "#0969da",
         "WEEKLY REPORT": ACCENT}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

CSS = f"""body{{margin:0;padding:0;background:{SHADE};font-family:{FONT};color:{INK}}}
.w{{max-width:680px;background:#fff;border:1px solid {LINE}}}
.top{{background:{NAVY};padding:16px}}.brand{{font-size:12px;font-weight:700;letter-spacing:2px;color:{ACCENT}}}
.badge{{display:inline-block;color:#fff;font-size:12px;font-weight:700;letter-spacing:1px;padding:3px 8px;border-radius:3px}}
.id{{font-family:{MONO};font-size:12px;color:#b9c3d4;padding-left:8px}}
.meta{{font-size:12px;color:#b9c3d4;padding-top:2px;word-break:break-word}}
.hl{{padding:16px 16px 0;font-size:17px;font-weight:700;line-height:1.35}}
.s{{padding:14px 16px 4px}}.st{{font-size:13px;font-weight:700;color:{NAVY};text-transform:uppercase;letter-spacing:.6px;padding-bottom:6px}}
.t{{border-collapse:collapse;border:1px solid {LINE};margin:0 0 4px;font-size:13px;width:100%}}
.t td,.t th{{padding:6px 7px;border-bottom:1px solid {LINE};vertical-align:top;text-align:left}}
.t th{{background:{SHADE};color:{MUTED};font-size:11px;text-transform:uppercase;font-weight:600;vertical-align:bottom}}
.t .r{{text-align:right}}.nw{{white-space:nowrap}}.neg{{color:{RED}}}
.m{{font-family:{MONO};font-size:12px;white-space:nowrap}}.ms{{font-family:{MONO};font-size:11px;color:{MUTED}}}
.tile{{display:inline-block;vertical-align:top;width:128px;margin:0 6px 6px 0;padding:8px 10px;border:1px solid {LINE}}}
.tl{{font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:.5px}}.tv{{font-size:20px;font-weight:700;padding-top:2px}}
.ts{{font-size:12px;color:{MUTED};padding-top:2px}}
ul{{margin:0;padding-left:20px;font-size:13px}}li{{margin:0 0 4px}}
.p{{margin:0 0 6px;font-size:14px;line-height:1.45}}.ps{{margin:0 0 6px;font-size:12px;line-height:1.45;color:{MUTED}}}
.co{{border-left:4px solid {ACCENT};background:{SHADE};padding:10px 12px;font-size:13px;margin:4px 0}}.ok{{border-left-color:{GREEN}}}
.foot{{padding:16px 16px 18px;font-size:11px;color:{MUTED};border-top:1px solid {LINE}}}"""


class Raw(str):
    """Markup that is already escaped."""


def e(x) -> str:
    return x if isinstance(x, Raw) else escape(str(x))


def money(v: float | None, signed: bool = False, cents: bool = False) -> Raw:
    if v is None:
        return Raw("n/a")
    s = f"${abs(v):,.2f}" if cents else f"${abs(v):,.0f}"
    if v < 0:
        return Raw(f'<span class="neg" style="color:{RED}">-{s}</span>')
    return Raw(("+" if signed and v > 0 else "") + s)


def b(x) -> Raw:
    return Raw(f"<strong>{e(x)}</strong>")


def mono(x, small: bool = False) -> Raw:
    return Raw(f'<span class="{"ms" if small else "m"}">{e(x)}</span>')


def table(head: list[str] | None, rows: list[list], right: tuple[int, ...] = (), nowrap: tuple[int, ...] = ()) -> Raw:
    def cell(tag, i, c):
        cls = " ".join(x for x, on in (("r", i in right), ("nw", i in nowrap)) if on)
        return f'<{tag}{" align=right" if i in right else ""}{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{e(c)}</{tag}>'
    out = ['<table class="t" cellpadding="6" cellspacing="0" width="100%">']
    if head:
        out.append("<tr>" + "".join(cell("th", i, x) for i, x in enumerate(head)) + "</tr>")
    out += ["<tr>" + "".join(cell("td", i, c) for i, c in enumerate(r)) + "</tr>" for r in rows]
    return Raw("".join(out) + "</table>")


def kv(pairs: list[tuple]) -> Raw:
    return table(None, [[b(k), v] for k, v in pairs])


def tiles(items: list[tuple]) -> Raw:
    """Headline numbers, (label, value, small print) each. Inline blocks, so four fit across a
    desktop window and they wrap two by two on a phone."""
    return Raw('<div style="margin:4px 0 2px">' + "".join(
        f'<div class="tile"><div class="tl">{e(label)}</div><div class="tv">{e(value)}</div>'
        f'<div class="ts">{e(sub)}</div></div>' for label, value, sub in items) + "</div>")


def bullets(items: list) -> Raw:
    return Raw("<ul>" + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>")


def para(x, small: bool = False) -> Raw:
    return Raw(f'<p class="{"ps" if small else "p"}">{e(x)}</p>')


def callout(x, ok: bool = False) -> Raw:
    return Raw(f'<div class="co{" ok" if ok else ""}">{e(x)}</div>')


def section(title: str, *parts) -> Raw:
    return Raw(f'<tr><td class="s"><div class="st"><strong>{e(title)}</strong></div>' + "".join(e(p) for p in parts) + "</td></tr>")


def page(title: str, ident: str, meta: list[str], headline, sections: list[Raw], footer: list[str]) -> str:
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:16px 8px">'
        f'<table class="w" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td class="top" bgcolor="{NAVY}"><div class="brand" style="color:{ACCENT}">STORMGLASS</div>'
        f'<div style="padding-top:8px"><span class="badge" style="background:{BADGE.get(title, MUTED)};color:#fff">{e(title)}</span>'
        f'<span class="id" style="color:#b9c3d4">{e(ident)}</span></div>'
        + "".join(f'<div class="meta" style="color:#b9c3d4">{e(m)}</div>' for m in meta) + "</td></tr>"
        f'<tr><td class="hl">{e(headline)}</td></tr>' + "".join(sections)
        + '<tr><td class="foot">' + "".join(f"<div>{e(f)}</div>" for f in footer) + "</td></tr>"
        "</table></td></tr></table></body></html>")
