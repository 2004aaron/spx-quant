"""Key-result checks (proposal section 6). Each prints a markdown table meant to be committed.

  a1  A-KR1  days on which every scheduled scan produced a complete proposal or stand-down
  a2  A-KR2  proposals that fail an entry check; --plant proves each check catches a bad row
  a3  A-KR3  24 sizing cases (4 account sizes x 2 margin types x 3 regimes), zero violations
  b1  B-KR1  delivered messages within 5 minutes of scan completion
  b2  B-KR2  scheduled scans that produced a delivered message
  b3  B-KR3  delivered alerts that carry their quotes, data timestamp and output timestamp
"""
from __future__ import annotations

import copy
import sqlite3
from datetime import date, datetime, timedelta

from . import clock, margin, store
from .engine import run_scan
from .greeks import bs
from .params import Params
from .profile import validate
from .sizing import cents, delta_theta_ok
from .strategies import MULTIPLIER, NOTIONAL, years_to
from .synthetic import SyntheticSource

CHECKS = ("a1", "a2", "a3", "b1", "b2", "b3")
WINDOWS = {"a": (date(2026, 10, 5), date(2026, 10, 16)), "b": (date(2026, 10, 30), date(2026, 11, 13))}
A3_SIZES = (25_000, 75_000, 150_000, 1_500_000)
A3_MARGINS = ("reg_t", "portfolio")
A3_REGIMES = (("low", 14.5), ("normal", 17.5), ("elevated", 24.0))


def trading_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1) if clock.trading_day(start + timedelta(days=i))]


def _ts(s: str | None) -> datetime | None:
    return clock.parse_utc(s) if s else None


def _table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ---------------------------------------------------------------- A-KR1

def complete(alert: dict | None) -> bool:
    if not alert:
        return False
    if alert["kind"] == "proposal":
        r = alert.get("risk") or {}
        return bool(alert.get("legs")) and (alert.get("contracts") or 0) > 0 and alert.get("credit") is not None \
            and alert.get("bp_total") is not None and all(r.get(k) is not None for k in ("pop", "ev", "worst_case"))
    if alert["kind"] == "stand_down":
        return bool(alert.get("reasons"))
    return False


def a1(conn, params: Params, start: date, end: date) -> tuple[str, bool]:
    slots = list(params.schedule["slots"])
    rows, good = [], 0
    days = trading_days(start, end)
    for d in days:
        cells = []
        for s in slots:
            scans = store.rows(conn, "SELECT alert_id FROM scan WHERE slot = ? AND market_date = ?", (s, d.isoformat()))
            cells.append(any(complete(store.get_alert(conn, x["alert_id"])) for x in scans if x["alert_id"]))
        ok = all(cells)
        good += ok
        rows.append([d.isoformat()] + ["yes" if c else "no" for c in cells] + ["**yes**" if ok else "no"])
    text = f"### A-KR1 complete proposal or stand-down at every scheduled scan, {start} to {end}\n\n"
    text += _table(["date"] + [f"{s} PT" for s in slots] + ["qualifies"], rows)
    text += f"\n\n**{good} of {len(days)} trading days qualify** (target {len(days)} of {len(days)})."
    return text, good == len(days) and len(days) > 0


# ---------------------------------------------------------------- A-KR2

def _liquid(leg: dict, liq: dict) -> bool:
    mid = leg["mid"]
    return leg["bid"] > 0 and leg["ask"] > 0 and mid >= liq["min_mid"] and (leg["ask"] - leg["bid"]) / mid <= liq["max_spread_pct"] \
        and (leg["oi"] >= liq["min_open_interest"] or leg["vol"] >= liq["min_volume"])


def _credit_range(legs: list[dict]) -> tuple[float, float]:
    lo = -sum(l["qty"] * (l["bid"] if l["qty"] < 0 else l["ask"]) for l in legs) * MULTIPLIER
    hi = -sum(l["qty"] * (l["ask"] if l["qty"] < 0 else l["bid"]) for l in legs) * MULTIPLIER
    return lo, hi


def _next_morning(conn, alert: dict, first_slot: str) -> tuple[list[dict] | None, float | None, str]:
    """Legs re-quoted by the next trading day's first scheduled scan, with that scan's quote age."""
    d = date.fromisoformat(alert["market_date"]) + timedelta(days=1)
    while not clock.trading_day(d):
        d += timedelta(days=1)
    scans = store.rows(conn, "SELECT * FROM scan WHERE slot = ? AND market_date = ? ORDER BY id", (first_slot, d.isoformat()))
    for s in scans:
        q = (s.get("leg_quotes") or {}).get(alert["alert_id"])
        if q is not None:
            legs = []
            for l in alert["legs"]:
                now = q.get(l["sym"])
                if now is None:
                    return None, s["quote_age_min"], f"{l['sym']} not listed at {first_slot} on {d}"
                legs.append(dict(l, **now))
            return legs, s["quote_age_min"], f"{first_slot} scan on {d}"
    if scans:
        return None, None, f"{first_slot} scan on {d} ({scans[-1]['outcome']}) has no quotes for these legs"
    return None, None, f"pending: no {first_slot} scan on {d} yet"


def a2_checks(conn, alert: dict, params: Params) -> dict[str, str]:
    """'ok', 'FAIL: why' or 'pending: why' per check.

    Account limits and the credit are checked against the quotes the proposal was built on.
    Listing, bids, liquidity and quote age are checked where the trade would be entered: at
    proposal time, or for an end-of-day proposal at the next morning's first scan (A-KR2).
    The credit is not re-checked overnight: one night of theta moves a strangle's price by more
    than its bid-ask width, so that version of the check could never pass."""
    prof = alert["profile"]
    cap = prof["net_liq"] * prof["bp_cap_pct"]
    out = {"bp_cap": "ok" if cents(alert["bp_total"]) <= cents(cap) else f"FAIL: ${alert['bp_total']:,.2f} > ${cap:,.2f}",
           "delta_theta": "ok" if delta_theta_ok(alert["delta_per_lot"], alert["theta_per_lot"], prof["delta_theta_limit"])
           else f"FAIL: delta {alert['delta_per_lot']} vs theta {alert['theta_per_lot']} at 1:{prof['delta_theta_limit']:g}"}
    limit = prof["net_liq"] * prof.get("max_worst_case_pct", 0.10)
    worst = -(alert.get("risk") or {}).get("worst_case", 0.0)
    slack = 0.01 * max(alert.get("contracts") or 1, 1)   # per-lot cents rounding in the sizer
    out["worst_case"] = "ok" if worst <= limit + slack else f"FAIL: worst case -${worst:,.2f} beyond the ${limit:,.2f} limit"
    lo, hi = _credit_range(alert["legs"])
    c = alert["credit_per_lot"]
    out["credit"] = "ok" if lo - 0.005 <= c <= hi + 0.005 else f"FAIL: credit ${c:,.2f} outside ${lo:,.2f} to ${hi:,.2f}"
    legs, age = alert["legs"], (_ts(alert["created_ts"]) - _ts(alert["data_ts"])).total_seconds() / 60 if alert["data_ts"] else None
    source = "at proposal"
    if alert["slot"] == params.schedule["eod_slot"]:
        legs, age, source = _next_morning(conn, alert, params.schedule["slots"][0])
        if legs is None:
            state = source if source.startswith("pending") else f"FAIL: {source}"
            for k in ("bids", "liquidity", "fresh"):
                out[k] = state
            return out
    liq, stale = params.liquidity, params.feed["stale_after_minutes"]
    out["bids"] = "ok" if all(l["bid"] > 0 for l in legs) else f"FAIL: a leg has no bid ({source})"
    out["liquidity"] = "ok" if all(_liquid(l, liq) for l in legs) else f"FAIL: a leg fails the liquidity filter ({source})"
    out["fresh"] = "ok" if age is not None and age <= stale else f"FAIL: quotes {age} min old ({source})"
    return out


def _plant_rows(conn, params: Params, day: date) -> dict[str, str]:
    """Insert one bad proposal per check into a copy of the log; returns {alert_id: check it must fail}."""
    liq = params.liquidity
    base_legs = [
        {"sym": "SPXW261120P06900000", "right": "P", "strike": 6900.0, "exp": "2026-11-20", "qty": -1,
         "bid": 20.0, "ask": 20.6, "mid": 20.3, "iv": 0.19, "delta": -0.16, "oi": 900, "vol": 150},
        {"sym": "SPXW261120C07900000", "right": "C", "strike": 7900.0, "exp": "2026-11-20", "qty": -1,
         "bid": 14.0, "ask": 14.6, "mid": 14.3, "iv": 0.12, "delta": 0.16, "oi": 900, "vol": 150},
    ]
    t0 = clock.local_to_utc("PT", datetime.combine(day, datetime.min.time()).replace(hour=10, minute=30))
    base = dict(slot=params.schedule["slots"][0], slot_ts=t0, created_ts=t0, data_ts=t0 - timedelta(minutes=15),
                market_date=day, kind="proposal", outcome="proposal", ticker="_SPX", strategy="strangle",
                legs=base_legs, contracts=1, credit=3460.0, credit_per_lot=3460.0, bp_per_lot=10000.0, bp_total=10000.0,
                delta_per_lot=0.0, theta_per_lot=150.0, risk={"pop": 0.8, "ev": 100.0, "worst_case": -10000.0},
                reasons=[], codes=[], profile={"net_liq": 150000.0, "bp_cap_pct": 0.08, "delta_theta_limit": 2.0,
                                               "max_worst_case_pct": 0.10},
                fingerprint="plant", subject="planted", text="planted")
    bad = {
        "bp_cap": {"bp_per_lot": 12000.01, "bp_total": 12000.01},
        "delta_theta": {"delta_per_lot": 80.0},
        "bids": {"legs": [dict(base_legs[0], bid=0.0), base_legs[1]]},
        "liquidity": {"legs": [dict(base_legs[0], oi=0, vol=0), base_legs[1]]},
        "fresh": {"data_ts": t0 - timedelta(minutes=31)},
        "credit": {"credit_per_lot": 3600.0, "credit": 3600.0},
        "worst_case": {"risk": {"pop": 0.8, "ev": 100.0, "worst_case": -15000.02}},
    }
    planted = {}
    for check, change in bad.items():
        row = copy.deepcopy(base)
        row.update(change, alert_id=f"PLANT-{check}")
        store.insert(conn, "alert", **row)
        planted[row["alert_id"]] = check
    eod = copy.deepcopy(base)
    eod.update(alert_id="PLANT-next_morning", slot=params.schedule["eod_slot"])
    store.insert(conn, "alert", **eod)
    nxt = day + timedelta(days=1)
    while not clock.trading_day(nxt):
        nxt += timedelta(days=1)
    store.insert(conn, "scan", slot=params.schedule["slots"][0], market_date=nxt, outcome="proposal", quote_age_min=15,
                 leg_quotes={"PLANT-next_morning": {
                     base_legs[0]["sym"]: {"bid": 0.0, "ask": 20.6, "mid": 10.3, "oi": 900, "vol": 150},
                     base_legs[1]["sym"]: {k: base_legs[1][k] for k in ("bid", "ask", "mid", "oi", "vol")}}})
    planted["PLANT-next_morning"] = "bids"
    return planted


def a2(conn, params: Params, start: date, end: date, plant: bool = False) -> tuple[str, bool]:
    cols = ("bp_cap", "delta_theta", "worst_case", "bids", "liquidity", "fresh", "credit")
    real = [a for a in store.alerts_between(conn, start, end, "proposal") if not a["alert_id"].startswith("PLANT-")]
    rows, failed, pending = [], 0, 0
    for a in real:
        res = a2_checks(conn, a, params)
        f = [k for k in cols if res.get(k, "").startswith("FAIL")]
        p = [k for k in cols if res.get(k, "").startswith("pending")]
        failed += bool(f)
        pending += bool(p) and not f
        rows.append([a["alert_id"], a["slot"]] + [("ok" if res.get(k) == "ok" else res.get(k, "")[:60]) for k in cols])
    text = f"### A-KR2 proposals that fail an entry check, {start} to {end}\n\n"
    text += _table(["alert", "slot"] + list(cols), rows) if rows else "_no proposals in the window_"
    text += f"\n\n**{failed} of {len(real)} proposals fail a check**; {pending} pending the next morning's scan " \
            f"(target 0 failures across at least 10)."
    passed = failed == 0 and pending == 0 and len(real) >= 10
    if plant:
        mem = sqlite3.connect(":memory:")
        conn.backup(mem)
        mem.row_factory = sqlite3.Row
        planted = _plant_rows(mem, params, start)
        caught = []
        for aid, check in planted.items():
            res = a2_checks(mem, store.get_alert(mem, aid), params)
            hit = res.get(check, "").startswith("FAIL")
            caught.append([aid, check, "caught" if hit else "**MISSED**", res.get(check, "")[:70]])
        n = sum(r[2] == "caught" for r in caught)
        text += "\n\n#### Planted rows (in a copy of the log; the real log is untouched)\n\n"
        text += _table(["planted alert", "check", "result", "detail"], caught)
        text += f"\n\n**{n} of {len(caught)} planted rows caught.**"
        passed = passed and n == len(caught)
    return text, passed


# ---------------------------------------------------------------- A-KR3

def a3_case(net_liq: float, margin_type: str, regime: str, vix: float, params: Params):
    """Run one case, then re-derive every ranked candidate's exposure from its legs and contract
    count rather than trusting the fields the sizer wrote."""
    prof = validate(net_liq, margin_type, 0.08, 2.0)
    src = SyntheticSource(vix, "contango")
    res = run_scan(src, prof, params)
    rate = params.risk["rate"]
    violations, worst = [], []
    for c in res.ranked:
        p, n = c.position, c.sized.contracts
        spot = src.chains[p.ticker]["data"]["current_price"]
        bp = n * margin.bp_per_lot(p, spot, prof.margin_type, res.now, params)
        delta = sum(l.qty * l.delta for l in p.legs) * MULTIPLIER * NOTIONAL[p.ticker]
        theta = sum(l.qty * bs(spot, l.strike, years_to(p.root, p.exp, res.now), l.iv, l.right, rate).theta
                    for l in p.legs) * MULTIPLIER
        if n < 1 or cents(bp) > cents(prof.bp_cap_dollars):
            violations.append(f"{p.strategy}: {n} lots use ${bp:,.2f} against a ${prof.bp_cap_dollars:,.2f} cap")
        if not (theta > 0 and abs(delta) * prof.delta_theta_limit <= theta + 1e-6):
            violations.append(f"{p.strategy}: delta {delta:+.2f} vs theta ${theta:,.2f}/day over 1:{prof.delta_theta_limit:g}")
        r = params.risk
        loss = -(p.value(spot * (1 + r["worst_case_move"]), res.now, rate, r["worst_case_vol_points"] / 100)
                 - p.value(spot, res.now, rate)) * n
        if loss > prof.worst_case_limit + 0.01 * n:
            worst.append(f"{p.strategy}: {n} lots lose ${loss:,.2f} in the stress test, limit ${prof.worst_case_limit:,.2f}")
    return prof, res, violations, worst


def a3(params: Params) -> tuple[str, bool]:
    rows, total_v, total_w = [], 0, 0
    for size in A3_SIZES:
        for margin in A3_MARGINS:
            for regime, vix in A3_REGIMES:
                prof, res, v, w = a3_case(size, margin, regime, vix, params)
                total_v += len(v)
                total_w += len(w)
                b = res.best
                what = (f"{b.position.label()} {b.position.ticker.lstrip('_')} x{b.sized.contracts}" if b
                        else "; ".join(res.reasons)[:60])
                bp = f"${b.sized.bp_total:,.0f}" if b else "-"
                dt = b.sized.dt_text() if b else "-"
                wc = f"${b.sized.worst_total:,.0f} of ${prof.worst_case_limit:,.0f}" if b else "-"
                if b and b.sized.limited_by == "worst case":
                    wc += f" (cut from {b.sized.bp_contracts})"
                rows.append([f"${size:,}", margin, f"{regime} (VIX {vix})", res.outcome, what, bp,
                             f"${prof.bp_cap_dollars:,.0f}", dt, wc, len(v)])
    text = "### A-KR3 sizing matrix: 4 account sizes x 2 margin types x 3 regimes\n\n"
    text += _table(["net liq", "margin", "regime", "outcome", "best candidate", "BP used", "cap", "delta:theta",
                    "worst case vs limit", "violations"], rows)
    text += f"\n\n**{len(rows)} cases, {total_v} violations** of the BP cap or delta:theta limit across every ranked " \
            f"candidate (target 24 cases, 0 violations). Worst-case limit breaches: {total_w} (not part of the KR as written)."
    return text, len(rows) == 24 and total_v == 0 and total_w == 0


# ---------------------------------------------------------------- Beta

def _delivered(conn, start: date, end: date) -> list[dict]:
    return store.rows(conn, """SELECT d.*, a.kind, a.text, a.legs, a.slot, a.market_date, s.finished_ts
                               FROM delivery d JOIN alert a ON a.alert_id = d.alert_id
                               LEFT JOIN scan s ON s.alert_id = a.alert_id
                               WHERE d.status = 'delivered' AND a.market_date BETWEEN ? AND ? ORDER BY d.id""",
                      (start.isoformat(), end.isoformat()))


def b1(conn, params: Params, start: date, end: date, minutes: float = 5) -> tuple[str, bool]:
    rows, on_time = [], 0
    ds = _delivered(conn, start, end)
    for d in ds:
        lag = (_ts(d["delivered_ts"]) - _ts(d["finished_ts"])).total_seconds() / 60 if d["finished_ts"] else None
        ok = lag is not None and lag <= minutes
        on_time += ok
        rows.append([d["alert_id"], d["channel"], f"{lag:.2f}" if lag is not None else "n/a", "yes" if ok else "no"])
    pct = on_time / len(ds) if ds else 0.0
    text = f"### B-KR1 delivered within {minutes:g} minutes of scan completion, {start} to {end}\n\n"
    text += _table(["alert", "channel", "minutes", "on time"], rows) if rows else "_no deliveries in the window_"
    text += f"\n\n**{on_time} of {len(ds)} on time ({pct:.0%})** (target 95%)."
    return text, bool(ds) and pct >= 0.95


def b2(conn, params: Params, start: date, end: date) -> tuple[str, bool]:
    slots = list(params.schedule["slots"])
    rows, good, total = [], 0, 0
    for d in trading_days(start, end):
        for s in slots:
            total += 1
            got = store.rows(conn, """SELECT d.status FROM scan sc JOIN delivery d ON d.alert_id = sc.alert_id
                                      WHERE sc.slot = ? AND sc.market_date = ?""", (s, d.isoformat()))
            statuses = sorted({g["status"] for g in got})
            ok = "delivered" in statuses
            good += ok
            rows.append([d.isoformat(), s, ", ".join(statuses) or "no scan", "yes" if ok else "no"])
    text = f"### B-KR2 scheduled scans that sent a message, {start} to {end}\n\n"
    text += _table(["date", "slot PT", "delivery statuses", "message sent"], rows)
    text += f"\n\n**{good} of {total} scheduled scans sent a message** (target {total} of {total})."
    return text, good == total and total > 0


def b3_fields(d: dict) -> list[str]:
    t = d["text"] or ""
    missing = []
    for label in ("Output: ", "Data as of: "):
        line = next((l for l in t.splitlines() if l.startswith(label)), "")
        if not line or "n/a" in line[:len(label) + 4]:
            missing.append(label.strip(": "))
    for sym in ("SPX ", "VIX9D ", "VIX ", "VIX3M "):
        if sym not in t:
            missing.append(sym.strip())
    if d["kind"] == "proposal":
        for l in d["legs"] or []:
            line = next((x for x in t.splitlines() if l["sym"] in x), "")
            if "bid " not in line or "ask " not in line:
                missing.append(f"{l['sym']} bid/ask")
    return missing


def b3(conn, params: Params, start: date, end: date) -> tuple[str, bool]:
    rows, good = [], 0
    seen = set()
    for d in _delivered(conn, start, end):
        if d["alert_id"] in seen:
            continue
        seen.add(d["alert_id"])
        miss = b3_fields(d)
        good += not miss
        rows.append([d["alert_id"], d["kind"], "complete" if not miss else "missing " + ", ".join(miss)])
    n = len(rows)
    text = f"### B-KR3 alerts carrying quotes, data timestamp and output timestamp, {start} to {end}\n\n"
    text += _table(["alert", "kind", "fields"], rows) if rows else "_no delivered alerts in the window_"
    text += f"\n\n**{good} of {n} complete ({good / n:.0%})**" if n else "\n\n**0 alerts**"
    text += " (target 100%)."
    return text, n > 0 and good == n


def run(which: str, conn, params: Params, start: date | None, end: date | None, plant: bool = False) -> tuple[str, bool]:
    if which == "a3":
        return a3(params)
    s, e = WINDOWS[which[0]]
    start, end = start or s, end or e
    if which == "a1":
        return a1(conn, params, start, end)
    if which == "a2":
        return a2(conn, params, start, end, plant)
    return {"b1": b1, "b2": b2, "b3": b3}[which](conn, params, start, end)
