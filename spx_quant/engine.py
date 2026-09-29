"""One scan (Figure 2): check feed -> classify -> gate -> build -> size -> risk -> rank.

Pure with respect to storage and delivery: run_scan returns a ScanResult and the
CLI decides what to log and send. Outcomes follow proposal 4.2:
proposal | stand_down | stale_data | feed_failure | market_closed, plus error for
configuration problems (a missing risk assumption, US-05-AC3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import analytics, clock, margin, sizing
from .data import cboe
from .params import MissingParam, Params
from .profile import Profile
from .regime import Regime, classify, gate
from .strategies import BUILDERS, Position, build


def usd(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


@dataclass
class Candidate:
    position: Position
    sized: sizing.Sized
    risk: analytics.Risk | None = None
    reasons: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons

    def as_dict(self) -> dict:
        p = self.position
        lo, hi = p.credit_range
        return {"strategy": p.strategy, "ticker": p.ticker, "root": p.root, "exp": p.exp.isoformat(), "dte": p.dte,
                "legs": [l.as_dict() for l in p.legs], "width": p.width, "credit_per_lot": p.credit,
                "credit_range_per_lot": [lo, hi], "net_delta_per_lot": p.net_delta, "notional": p.notional,
                "sized": self.sized.as_dict(), "risk": self.risk.as_dict() if self.risk else None,
                "reasons": self.reasons, "codes": self.codes}


@dataclass
class ScanResult:
    outcome: str
    now: datetime
    kind: str | None = None           # proposal | stand_down | no_advice | None when the market is closed
    regime: Regime | None = None
    spot: float | None = None
    ticker: str | None = None          # the proposal's ticker once one is chosen
    market_ticker: str | None = None   # the board the regime read and spot came from
    data_ts: datetime | None = None
    quote_age_min: float | None = None
    curve: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    ranked: list[Candidate] = field(default_factory=list)
    rejected: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    source: str = ""
    params_summary: str = ""
    profile: Profile | None = None
    boards: dict = field(default_factory=dict, repr=False)  # ticker -> {occ symbol: row}, for re-checking earlier legs

    @property
    def best(self) -> Candidate | None:
        return self.ranked[0] if self.ranked else None

    def quotes(self) -> dict:
        q = {"spot": self.spot, "spot_ticker": self.market_ticker}
        q.update(self.curve)
        return q


def _no_advice(res: ScanResult, outcome: str, reasons: list[str], code: str) -> ScanResult:
    res.outcome, res.kind, res.reasons, res.codes = outcome, "no_advice", reasons, [code]
    return res


def evaluate(chain: cboe.Chain, profile: Profile, strategies: list[str], now: datetime, params: Params) -> list[Candidate]:
    today = clock.market_date(now)
    rate = params.need("risk", "rate")
    out = []
    for name in strategies:
        pos = build(name, chain.ticker, chain.spot, chain.rows, today, params)
        if pos is None:
            continue
        bp = margin.bp_per_lot(pos, chain.spot, profile.margin_type, now, params)
        theta = pos.theta(chain.spot, now, rate)
        sz = sizing.size(profile, bp, pos.net_delta, theta)
        cand = Candidate(pos, sz, reasons=list(sz.reasons), codes=list(sz.codes))
        if sz.ok:
            iv = analytics.atm_iv(chain.rows, pos.root, pos.exp, chain.spot)
            if iv is None:
                cand.reasons.append("no ATM implied volatility on this expiration")
                cand.codes.append("no_atm_iv")
            else:
                cand.risk = analytics.compute(pos, sz.contracts, sz.bp_total, chain.spot, iv, now, params)
                r, min_pop = cand.risk, params.risk.get("min_pop", 0.0)
                if r.ev <= 0:
                    cand.reasons.append(f"expected value {usd(r.ev)} is not positive under the stated assumptions")
                    cand.codes.append("negative_ev")
                if r.pop < min_pop:
                    cand.reasons.append(f"probability of profit {r.pop:.0%} is below the {min_pop:.0%} minimum")
                    cand.codes.append("low_pop")
        out.append(cand)
    return out


def run_scan(source, profile: Profile, params: Params, now: datetime | None = None) -> ScanResult:
    now = now or source.now()
    res = ScanResult("error", now, source=getattr(source, "name", ""), params_summary=params.summary(), profile=profile)
    day = clock.market_date(now)
    if not clock.trading_day(day):
        res.outcome, res.kind = "market_closed", None
        res.reasons, res.codes = [f"US markets closed on {day.isoformat()} (weekend or exchange holiday)"], ["market_closed"]
        return res

    feed = params.feed
    tickers = list(feed.get("tickers", ["_SPX"]))
    chain, probe = cboe.fetch_chain(source, tickers[0], feed["stale_after_minutes"], feed.get("min_rows", 1), now)
    res.quote_age_min = probe.quote_age_min
    if chain is None:
        return _no_advice(res, probe.kind or "feed_failure", probe.failures, probe.kind or "feed_failure")
    res.spot, res.ticker, res.market_ticker, res.data_ts = chain.spot, chain.ticker, chain.ticker, chain.quote_ts
    res.boards[chain.ticker] = {r["sym"]: r for r in chain.rows}

    curve, stale = cboe.fetch_curve(source, feed["stale_after_minutes"], now)
    res.curve = dict(curve.values)
    res.notes += curve.notes
    if stale:
        return _no_advice(res, "stale_data", stale, "stale_data")

    res.regime = classify(curve.values, params, asof=curve.asof)
    ok, why = gate(res.regime, params)
    if not ok:
        res.outcome, res.kind, res.reasons = "stand_down", "stand_down", why
        res.codes = _gate_codes(res.regime)
        return res

    allowed = list(params.playbook.get(res.regime.bucket, []))
    if not allowed:
        res.outcome, res.kind = "stand_down", "stand_down"
        res.reasons, res.codes = [f"no strategies are permitted in the {res.regime.bucket} bucket"], ["no_strategies"]
        return res
    unknown = [s for s in allowed if s not in BUILDERS]
    if unknown:
        return _no_advice(res, "error", [f"playbook names unknown strategies: {', '.join(unknown)}"], "config")

    try:
        cands = evaluate(chain, profile, allowed, now, params)
        for t in tickers[1:]:
            if any(c.ok for c in cands):
                break
            extra, p2 = cboe.fetch_chain(source, t, feed["stale_after_minutes"], feed.get("min_rows", 1), now)
            if extra is None:
                res.notes.append(f"{t} unavailable: {'; '.join(p2.failures)}")
                continue
            res.boards[extra.ticker] = {r["sym"]: r for r in extra.rows}
            cands += evaluate(extra, profile, allowed, now, params)
    except MissingParam as e:
        return _no_advice(res, "error", [f"risk block cannot be computed: {e}"], "missing_param")

    res.ranked = sorted((c for c in cands if c.ok), key=lambda c: -c.risk.ann_return_bp)
    res.rejected = [c for c in cands if not c.ok]
    if res.ranked:
        best = res.best.position
        res.outcome, res.kind = "proposal", "proposal"
        res.ticker = best.ticker
        if best.ticker != chain.ticker:
            res.notes.append(f"{chain.ticker.lstrip('_')} could not be sized for this account; using {best.ticker.lstrip('_')}")
        return res

    res.outcome, res.kind = "stand_down", "stand_down"
    if not cands:
        res.reasons, res.codes = ["no candidate could be built from liquid strikes in the DTE window"], ["no_candidates"]
    elif all(set(c.codes) & {"over_cap", "delta_theta", "theta", "bp_unknown"} for c in cands):
        res.reasons = [f"no proposal could be sized for this account ({profile.margin_type}, "
                       f"${profile.bp_cap_dollars:,.0f} per-position cap, delta:theta 1:{profile.delta_theta_limit:g})"]
        res.codes = ["no_fit"]
    else:
        res.reasons = ["no candidate passed the risk checks"]
        res.codes = sorted({code for c in cands for code in c.codes})
    return res


def _gate_codes(r: Regime) -> list[str]:
    if not r.known:
        return ["regime_unknown"]
    codes = []
    if r.state == "backwardation":
        codes.append("backwardation")
    if r.bucket == "crushed":
        codes.append("vol_floor")
    if r.bucket == "panic":
        codes.append("vol_ceiling")
    return codes
