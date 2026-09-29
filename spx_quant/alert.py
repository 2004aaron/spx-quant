"""Alert identity and plain-text rendering (US-03 to US-05, QR-6, B-KR3).

Every field is plain text; nothing is carried by colour or layout. Every message
carries the quotes it was built on, the data timestamp and the output timestamp.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from datetime import datetime

from . import clock
from .analytics import assumptions_text
from .engine import Candidate, ScanResult

KIND_TITLE = {"proposal": "PROPOSAL", "stand_down": "STAND DOWN", "no_advice": "NO ADVICE"}
CURVE_ORDER = (("vix9d", "VIX9D"), ("vix", "VIX"), ("vix3m", "VIX3M"), ("vix6m", "VIX6M"))


def fingerprint(res: ScanResult) -> str:
    """Same conditions and same proposal -> same fingerprint (US-07-AC2). Numbers that drift every
    scan (VIX to the cent, credit) are left out; the decision and the contracts are in."""
    body = {"kind": res.kind, "codes": sorted(res.codes)}
    if res.regime is not None:
        body["regime"] = [res.regime.state, res.regime.bucket]
    if res.best:
        p = res.best.position
        body["trade"] = [p.strategy, p.ticker, sorted(l.sym for l in p.legs), res.best.sized.contracts]
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()


def alert_id(res: ScanResult, day) -> str:
    """User flow diagram format: scan date plus expiry for a proposal (2026-11-03-2026-12-18),
    2026-11-12-standdown, 2026-11-12-noadvice. A second alert the same day gets -2, -3."""
    if res.kind == "proposal" and res.best:
        return f"{day.isoformat()}-{res.best.position.exp.isoformat()}"
    return f"{day.isoformat()}-{'standdown' if res.kind == 'stand_down' else 'noadvice'}"


def _money(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    s = f"${abs(x):,.0f}"
    return ("-" if x < 0 else "+" if signed and x > 0 else "") + s


def _leg_line(c: Candidate, leg) -> str:
    p = c.position
    side = "SELL" if leg.qty < 0 else "BUY"
    n = abs(leg.qty) * c.sized.contracts
    kind = "put" if leg.right == "P" else "call"
    return (f"  {side} {n} {leg.sym}  {kind} {leg.strike:g}  bid {leg.bid:.2f}  ask {leg.ask:.2f}  "
            f"mid {leg.mid:.2f}  IV {leg.iv:.1%}  delta {leg.delta:+.3f}")


def _market_lines(res: ScanResult) -> list[str]:
    out = []
    if res.spot is not None:
        vals = "   ".join(f"{name} {res.curve[k]:.2f}" for k, name in CURVE_ORDER if res.curve.get(k) is not None)
        out.append(f"  {(res.market_ticker or '_SPX').lstrip('_')} {res.spot:,.2f}   {vals}".rstrip())
    if res.regime is not None:
        r = res.regime
        slope = f" (slope {r.slope:+.3f})" if r.slope is not None else ""
        out.append(f"  Regime: {r.state} / {r.bucket}{slope}" if r.known else f"  Regime: unknown ({r.reason})")
    return out


def _candidate_summary(i: int, c: Candidate) -> str:
    p, r = c.position, c.risk
    return (f"  {i}. {p.label()} {p.ticker.lstrip('_')} {p.exp:%m/%d} {p.legs_text()} x{c.sized.contracts}: "
            f"{r.ann_return_bp:.1f}%/yr on BP, EV {_money(r.ev)}, POP {r.pop:.0%}, worst case {_money(r.worst_case)}")


def _header(res: ScanResult, title: str, aid: str, created_ts: datetime) -> list[str]:
    lines = [f"SPX QUANT | {title} | {aid}", f"Output: {clock.fmt(created_ts)}"]
    if res.data_ts is not None:
        age = f"{res.quote_age_min:.0f} min old, " if res.quote_age_min is not None else ""
        lines.append(f"Data as of: {clock.fmt(res.data_ts)} ({age}{res.source})")
    else:
        lines.append(f"Data as of: n/a ({res.source})")
    mk = _market_lines(res)
    return lines + (["", "MARKET"] + mk if mk else [])


def render_unchanged(res: ScanResult, aid: str, created_ts: datetime, prev: dict) -> tuple[str, str]:
    """Short message for a scan that repeats the last delivered decision. It still carries the
    quotes and both timestamps (B-KR3); the full detail stays in the log under this alert ID."""
    since = f"{prev['alert_id']} ({clock.fmt(clock.parse_utc(prev['created_ts']))})"
    lines = _header(res, "NO CHANGE", aid, created_ts) + [""]
    if res.kind == "proposal":
        c = res.best
        p, s = c.position, c.sized
        subject = f"[SPX Quant {aid}] NO CHANGE: {p.label()} {p.ticker.lstrip('_')} {p.exp:%m/%d} x{s.contracts} still stands"
        lines.append(f"NO CHANGE since {since}: same proposal, {p.label()} on {p.ticker.lstrip('_')} x{s.contracts}.")
        lines += [_leg_line(c, l) for l in sorted(p.legs, key=lambda l: (l.right, l.strike))]
        lines.append(f"  Credit now ${p.credit:,.2f} per lot at mid; worst case {_money(c.risk.worst_case)}.")
    else:
        what = "still STAND DOWN" if res.kind == "stand_down" else "still NO ADVICE"
        subject = f"[SPX Quant {aid}] NO CHANGE: {what.lower()}"
        lines.append(f"NO CHANGE since {since}: {what}.")
        lines += [f"  - {x}" for x in res.reasons]
    lines += ["", f"Full detail: python -m spx_quant log --full --from {clock.market_date(created_ts)}",
              "Model estimates with tagged assumptions, not investment advice. The engine never places orders."]
    return subject[:200], "\n".join(lines)


def render(res: ScanResult, aid: str, created_ts: datetime) -> tuple[str, str]:
    lines = _header(res, KIND_TITLE.get(res.kind, "SCAN"), aid, created_ts)

    if res.kind == "proposal":
        c = res.best
        p, s, r = c.position, c.sized, c.risk
        prof = res.profile
        lo, hi = p.credit_range
        subject = f"[SPX Quant {aid}] PROPOSAL: {p.label()} {p.ticker.lstrip('_')} {p.exp:%m/%d} x{s.contracts}"
        lines += ["", f"PROPOSAL: {p.label()} on {p.ticker.lstrip('_')}, expires {p.exp.isoformat()} ({p.dte} DTE)"]
        lines += [_leg_line(c, l) for l in sorted(p.legs, key=lambda l: (l.right, l.strike))]
        lines += [
            f"  Credit: {_money(p.credit * s.contracts)} total ({s.contracts} x ${p.credit:,.2f} per lot at mid; "
            f"natural ${lo:,.2f}, far ${hi:,.2f})",
            f"  Buying power: ${s.bp_total:,.2f} of ${s.cap:,.2f} cap ({s.contracts} x ${s.bp_per_lot:,.2f}, "
            f"{prof.margin_type.replace('_', '-')} margin)",
            f"  Delta:theta: {s.dt_text()} within the 1:{s.dt_limit:g} limit (delta {s.delta_per_lot:+.2f} SPX-eq sh, "
            f"theta ${s.theta_per_lot:,.2f}/day per lot)",
            f"  Worst-case limit: ${s.worst_total:,.2f} of ${s.worst_limit:,.2f} ({prof.max_worst_case_pct:.0%} of net liq; "
            f"{s.contracts} x ${s.worst_per_lot:,.2f} stress loss per lot)",
        ]
        if s.limited_by == "worst case" and s.bp_contracts > s.contracts:
            lines.append(f"  Sized down from {s.bp_contracts} to {s.contracts} lots so the worst case stays inside the limit; "
                         f"buying power alone would allow {s.bp_contracts}.")
        lines += [
            "",
            f"RISK (model estimates for all {s.contracts} lots)",
            f"  Probability of profit: {r.pop:.1%}",
            f"  Expected value: {_money(r.ev)}",
            f"  Expected annual return on buying power: {r.ann_return_bp:.1f}%",
            f"  Worst case (stress: index {r.assumptions['worst_case_move']:+.0%}, volatility "
            f"+{r.assumptions['worst_case_vol_points']:g} points): {_money(r.worst_case)}"
            f" = {abs(r.worst_case) / prof.net_liq:.0%} of net liquidation",
            f"  Average of the worst 5% (CVaR 5%): {_money(r.cvar5)}",
            f"  Average of the worst 1% (CVaR 1%): {_money(r.cvar1)}",
            f"  Max profit: {_money(r.max_profit)}",
            f"  Max loss: {_money(-r.max_loss) if r.max_loss is not None else 'unlimited (naked short option)'}",
            f"  Breakevens at expiration: {' / '.join(f'{b:,.2f}' for b in r.breakevens) or 'n/a'}",
            "  Stress, instant index move: " + " | ".join(f"{mv:+.0%} {_money(v, True)}" for mv, v in r.stress),
            "  Implied crash rate: " + (f"{r.implied_crash_per_year:g} per year"
                                        if r.implied_crash_per_year is not None else "over 50 per year")
            + " (the crash frequency this premium pays for, before any volatility risk premium)",
            "",
            "ASSUMPTIONS",
        ]
        lines += textwrap.wrap(assumptions_text(r.assumptions), 96, initial_indent="  ", subsequent_indent="  ")
        lines += ["", "RANKING (expected annual return on buying power; best first)"]
        lines += [_candidate_summary(i, x) for i, x in enumerate(res.ranked, 1)]
        why = f"  Ranked first because it has the highest expected annual return on buying power ({r.ann_return_bp:.1f}%)"
        lines.append(why + ("." if len(res.ranked) == 1 else f" of {len(res.ranked)} candidates that fit."))
    elif res.kind == "stand_down":
        subject = f"[SPX Quant {aid}] STAND DOWN: {res.reasons[0] if res.reasons else 'no trade'}"
        lines += ["", "DO NOT ENTER"] + [f"  - {x}" for x in res.reasons]
    else:
        subject = f"[SPX Quant {aid}] NO ADVICE: {res.reasons[0] if res.reasons else res.outcome}"
        lines += ["", f"NO ADVICE ({res.outcome.replace('_', ' ')})"] + [f"  - {x}" for x in res.reasons]

    if res.rejected:
        lines += ["", "CONSIDERED, NOT PROPOSED"]
        for c in res.rejected:
            p = c.position
            lines.append(f"  - {p.label()} {p.ticker.lstrip('_')} {p.exp:%m/%d} {p.legs_text()}: {'; '.join(c.reasons)}")
    if res.notes:
        lines += ["", "NOTES"] + [f"  - {n}" for n in res.notes]
    lines += ["", res.params_summary,
              "Model estimates with tagged assumptions, not investment advice. The engine never places orders."]
    return subject[:200], "\n".join(lines)
