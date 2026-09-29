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


def alert_id(slot_ts: datetime, fp: str) -> str:
    return f"{clock.to_local('PT', slot_ts):%Y%m%d-%H%M}-{fp[:6]}"


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


def render(res: ScanResult, aid: str, created_ts: datetime) -> tuple[str, str]:
    title = KIND_TITLE.get(res.kind, "SCAN")
    lines = [f"SPX QUANT | {title} | {aid}", f"Output: {clock.fmt(created_ts)}"]
    if res.data_ts is not None:
        age = f"{res.quote_age_min:.0f} min old, " if res.quote_age_min is not None else ""
        lines.append(f"Data as of: {clock.fmt(res.data_ts)} ({age}{res.source})")
    else:
        lines.append(f"Data as of: n/a ({res.source})")
    mk = _market_lines(res)
    if mk:
        lines += ["", "MARKET"] + mk

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
            "",
            f"RISK (model estimates for all {s.contracts} lots)",
            f"  Probability of profit: {r.pop:.1%}",
            f"  Expected value: {_money(r.ev)}",
            f"  Expected annual return on buying power: {r.ann_return_bp:.1f}%",
            f"  Worst case (CVaR 1%, average of the worst 1% of outcomes): {_money(r.worst_case)}"
            f" = {abs(r.worst_case) / prof.net_liq:.0%} of net liquidation",
            f"  CVaR 5%: {_money(r.cvar5)}",
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
