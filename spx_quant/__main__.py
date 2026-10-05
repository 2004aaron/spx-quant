"""CLI: python -m spx_quant [--profile P] [--db D] [--params F] <command>

  profile set --net-liq N --margin reg_t|portfolio [--bp-cap 0.08] [--dt-limit 2]
              [--notify none|email|discord] [--email-to ADDR] [--max-worst-case 0.10]
  profile show
  probe   [--ticker _SPX]                       feed check: shape, size, quote age
  regime                                        VIX term structure -> regime and gate
  scan    [--slot HH:MM] [--no-send] [--replay FILE [--now ISO]]
  mark    [--replay FILE [--now ISO]]           daily marking job
  log     [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--kind K] [--full]
  record  --out FILE.json.gz                    save the current boards for replay
  kr      a1|a2|a3|b1|b2|b3 [--from D] [--to D] [--plant]
  notify-test                                   send a test message on the profile's channel
  margin-check [--alert ID] [--broker-bp N [--apply]]
                                                compare engine buying power with one broker ticket
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from . import __version__, calibrate, clock, kr, mark, notify, pipeline, store
from . import profile as prof
from .data import cboe
from .params import DEFAULT_PATH as PARAMS_PATH, load_params
from .regime import classify, gate


def _source(a, params):
    if getattr(a, "replay", None):
        return cboe.ReplaySource(a.replay, clock.parse_utc(a.now) if a.now else None)
    return cboe.LiveSource(params.feed["timeout_seconds"])


def _profile(a):
    try:
        p = prof.load(a.profile)
    except prof.ProfileError as e:
        sys.exit(f"profile at {a.profile} is invalid: {e}")
    if p is None:
        sys.exit(f"no profile at {a.profile}; run: python -m spx_quant profile set --net-liq N --margin reg_t|portfolio")
    return p


def _profile_or_none(a):
    try:
        return prof.load(a.profile)
    except prof.ProfileError as e:
        print(f"saved profile at {a.profile} is invalid: {e}")
        return None


def cmd_profile(a, params) -> int:
    if a.action == "show":
        p = _profile_or_none(a)
        print(p if p else "no profile saved; run: python -m spx_quant profile set --net-liq N --margin reg_t|portfolio")
        return 0
    try:
        p = prof.validate(a.net_liq, a.margin, a.bp_cap, a.dt_limit, a.notify, a.email_to, a.max_worst_case)
    except prof.ProfileError as e:
        prev = _profile_or_none(a)
        print(f"rejected: {e}")
        print(f"previous profile unchanged: {prev}" if prev else "no profile saved")
        return 2
    print(f"saved {prof.save(p, a.profile)}\n{p}")
    return 0


def cmd_probe(a, params) -> int:
    f = params.feed
    _, res = cboe.fetch_chain(_source(a, params), a.ticker, f["stale_after_minutes"], f.get("min_rows", 1))
    print(res)
    return 0 if res.ok else 1


def cmd_regime(a, params) -> int:
    src = _source(a, params)
    curve, stale = cboe.fetch_curve(src, params.feed["stale_after_minutes"])
    r = classify(curve.values, params, asof=curve.asof)
    print(r)
    for s in curve.notes:
        print(f"  note: {s}")
    ok, reasons = gate(r, params)
    print("gate: GO" if ok and not stale else "gate: STAND DOWN\n  " + "\n  ".join(reasons + stale))
    return 0


def cmd_scan(a, params) -> int:
    p = _profile(a)
    conn = store.connect(a.db)
    rec = pipeline.scan(conn, _source(a, params), p, params, a.slot, send=not a.no_send)
    if rec.alert is None:
        print(f"{rec.result.outcome}: {'; '.join(rec.result.reasons)}")
        return 0
    print(rec.alert["text"])
    print(f"\nlogged {rec.alert['alert_id']} to {a.db}; delivery: {rec.delivery or 'not sent (--no-send)'}")
    return 0


def cmd_mark(a, params) -> int:
    conn = store.connect(a.db)
    rows = mark.run(conn, _source(a, params), params)
    for r in rows:
        tail = f"  SETTLED ({r['basis']})" if r["settled"] else (f"  exit signal: {r['exit_signal']}" if r.get("exit_signal") else "")
        pct = f"{r['pnl_pct_credit']:.1%} of credit" if r.get("pnl_pct_credit") is not None else "no credit"
        print(f"{r['alert_id']}  {r['market_date']}  DTE {r['dte']}  P/L ${r['pnl']:,.2f} ({pct}){tail}")
    print(f"{len(rows)} position(s) marked")
    return 0


def cmd_log(a, params) -> int:
    conn = store.connect(a.db)
    start = date.fromisoformat(a.start) if a.start else date(2000, 1, 1)
    end = date.fromisoformat(a.end) if a.end else date(2100, 1, 1)
    rows = store.alerts_between(conn, start, end, a.kind)
    for r in rows:
        if a.full:
            print(r["text"] + "\n" + "-" * 72)
        else:
            print(f"{r['alert_id']}  {clock.fmt(clock.parse_utc(r['created_ts']))}  {r['kind']:<10} {r['subject']}")
    print(f"{len(rows)} alert(s)")
    return 0


def cmd_record(a, params) -> int:
    path = cboe.record(cboe.LiveSource(params.feed["timeout_seconds"]), list(params.feed["tickers"]), a.out)
    print(f"recorded {path}")
    return 0


def cmd_kr(a, params) -> int:
    conn = store.connect(a.db) if a.which != "a3" else None
    start = date.fromisoformat(a.start) if a.start else None
    end = date.fromisoformat(a.end) if a.end else None
    text, passed = kr.run(a.which, conn, params, start, end, plant=a.plant)
    print(text)
    return 0 if passed else 1


def cmd_notify_test(a, params) -> int:
    p = _profile(a)
    try:
        ch = notify.channel_for(p)
        if ch is None:
            print("profile notify channel is 'none'")
            return 1
        ch.send("[SPX Quant] test message", f"Test from spx-quant {__version__} at {clock.fmt(clock.now_utc())}.")
    except Exception as e:
        print(f"failed: {type(e).__name__}: {e}")
        return 1
    print(f"sent via {ch.name}")
    return 0


def cmd_margin_check(a, params) -> int:
    conn = store.connect(a.db)
    alert = store.get_alert(conn, a.alert) if a.alert else calibrate.latest_proposal(conn)
    if alert is None or alert["kind"] != "proposal":
        print(f"no proposal {a.alert} in {a.db}" if a.alert else f"no proposals in {a.db}; run a scan first")
        return 1
    try:
        text, ratio = calibrate.report(alert, params, a.broker_bp)
    except ValueError as e:
        print(f"rejected: {e}")
        return 2
    print(text)
    if a.apply and ratio is not None:
        calibrate.apply(a.params, ratio, alert, a.broker_bp, calibrate.engine_bp(alert, params), date.today())
        print(f"wrote pm_house_multiplier = {ratio} to {a.params}")
    elif a.apply:
        print("nothing written")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spx_quant", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"spx-quant {__version__}")
    ap.add_argument("--profile", type=Path, default=Path(os.environ.get("SPX_QUANT_PROFILE", prof.DEFAULT_PATH)))
    ap.add_argument("--db", type=Path, default=Path(os.environ.get("SPX_QUANT_DB", store.DEFAULT_PATH)))
    ap.add_argument("--params", type=Path, default=PARAMS_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile")
    p.add_argument("action", choices=["set", "show"])
    p.add_argument("--net-liq", type=float)
    p.add_argument("--margin", choices=prof.MARGIN_TYPES)
    p.add_argument("--bp-cap", type=float, default=0.08)
    p.add_argument("--dt-limit", type=float, default=2.0)
    p.add_argument("--notify", choices=prof.CHANNELS, default="none")
    p.add_argument("--email-to", default="")
    p.add_argument("--max-worst-case", type=float, default=0.10,
                   help="largest stress-test loss allowed per proposal, as a fraction of net liq (default 0.10)")
    p.set_defaults(fn=cmd_profile)

    def replayable(q):
        q.add_argument("--replay", help="recorded .json.gz session instead of the live feed")
        q.add_argument("--now", help="ISO time to evaluate a replay at (default: when it was recorded)")

    q = sub.add_parser("probe")
    q.add_argument("--ticker", default="_SPX")
    replayable(q)
    q.set_defaults(fn=cmd_probe)

    q = sub.add_parser("regime")
    replayable(q)
    q.set_defaults(fn=cmd_regime)

    q = sub.add_parser("scan")
    q.add_argument("--slot", help="scheduled slot in Pacific time, e.g. 10:30")
    q.add_argument("--no-send", action="store_true")
    replayable(q)
    q.set_defaults(fn=cmd_scan)

    q = sub.add_parser("mark")
    replayable(q)
    q.set_defaults(fn=cmd_mark)

    q = sub.add_parser("log")
    q.add_argument("--from", dest="start")
    q.add_argument("--to", dest="end")
    q.add_argument("--kind", choices=["proposal", "stand_down", "no_advice"])
    q.add_argument("--full", action="store_true")
    q.set_defaults(fn=cmd_log)

    q = sub.add_parser("record")
    q.add_argument("--out", required=True)
    q.set_defaults(fn=cmd_record)

    q = sub.add_parser("kr")
    q.add_argument("which", choices=kr.CHECKS)
    q.add_argument("--from", dest="start")
    q.add_argument("--to", dest="end")
    q.add_argument("--plant", action="store_true", help="A-KR2: plant one bad row per check in a copy of the log")
    q.set_defaults(fn=cmd_kr)

    sub.add_parser("notify-test").set_defaults(fn=cmd_notify_test)

    q = sub.add_parser("margin-check")
    q.add_argument("--alert", help="proposal alert ID (default: the latest proposal in the log)")
    q.add_argument("--broker-bp", type=float, help="buying-power effect shown in the broker's ticket for the whole order")
    q.add_argument("--apply", action="store_true", help="write the new pm_house_multiplier to the params file")
    q.set_defaults(fn=cmd_margin_check)

    a = ap.parse_args(argv)
    if a.cmd == "profile" and a.action == "set" and (a.net_liq is None or a.margin is None):
        ap.error("profile set requires --net-liq and --margin")
    return a.fn(a, load_params(a.params))


if __name__ == "__main__":
    sys.exit(main())
