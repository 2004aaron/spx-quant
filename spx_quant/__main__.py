"""StormGlass CLI: python -m spx_quant [--profile P] [--db D] [--params F] <command>

  profile set --net-liq N --margin reg_t|portfolio [--bp-cap 0.08] [--dt-limit N] [--max-worst-case 0.05]
  profile show
  regime                                        VIX term structure -> regime and gate
  scan    [--slot HH:MM] [--replay FILE [--now ISO]]
                                                proposal or stand-down, logged with its quotes
  log     [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--kind K] [--full]
  kr      a1|a2|a3 [--from D] [--to D] [--plant]
                                                Alpha key-result checks
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from . import __version__, clock, kr, pipeline, store
from . import profile as prof
from .data import cboe
from .params import DEFAULT_PATH as PARAMS_PATH, load_params
from .regime import advisories, classify, gate


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
        p = prof.validate(a.net_liq, a.margin, a.bp_cap, a.dt_limit, a.max_worst_case)
    except prof.ProfileError as e:
        prev = _profile_or_none(a)
        print(f"rejected: {e}")
        print(f"previous profile unchanged: {prev}" if prev else "no profile saved")
        return 2
    print(f"saved {prof.save(p, a.profile)}\n{p}")
    return 0


def cmd_regime(a, params) -> int:
    src = _source(a, params)
    curve, stale = cboe.fetch_curve(src, params.feed["stale_after_minutes"])
    r = classify(curve.values, params, asof=curve.asof)
    print(r)
    for s in curve.notes:
        print(f"  note: {s}")
    ok, reasons = gate(r, params)
    print("gate: GO" if ok and not stale else "gate: STAND DOWN\n  " + "\n  ".join(reasons + stale))
    for n in advisories(r, params):
        print(f"  note: {n}")
    return 0


def cmd_scan(a, params) -> int:
    p = _profile(a)
    conn = store.connect(a.db)
    rec = pipeline.scan(conn, _source(a, params), p, params, a.slot)
    if rec.alert is None:
        print(f"{rec.result.outcome}: {'; '.join(rec.result.reasons)}")
        return 0
    print(rec.alert["text"])
    print(f"\nlogged {rec.alert['alert_id']} to {a.db}")
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


def cmd_kr(a, params) -> int:
    conn = store.connect(a.db) if a.which != "a3" else None
    start = date.fromisoformat(a.start) if a.start else None
    end = date.fromisoformat(a.end) if a.end else None
    text, passed = kr.run(a.which, conn, params, start, end, plant=a.plant)
    print(text)
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spx_quant", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"StormGlass (spx-quant) {__version__}")
    ap.add_argument("--profile", type=Path, default=Path(os.environ.get("SPX_QUANT_PROFILE", prof.DEFAULT_PATH)))
    ap.add_argument("--db", type=Path, default=Path(os.environ.get("SPX_QUANT_DB", store.DEFAULT_PATH)))
    ap.add_argument("--params", type=Path, default=PARAMS_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile")
    p.add_argument("action", choices=["set", "show"])
    p.add_argument("--net-liq", type=float)
    p.add_argument("--margin", choices=prof.MARGIN_TYPES)
    p.add_argument("--bp-cap", type=float, default=0.08)
    p.add_argument("--dt-limit", type=float, default=None,
                   help="delta:theta limit 1:N in SPY deltas (default by tier: 2 under $1M, 7 at $1M+)")
    p.add_argument("--max-worst-case", type=float, default=prof.DEFAULT_MAX_WORST_CASE,
                   help="largest stress-test loss allowed per proposal, as a fraction of net liq (default 0.05)")
    p.set_defaults(fn=cmd_profile)

    def replayable(q):
        q.add_argument("--replay", help="recorded .json.gz session instead of the live feed")
        q.add_argument("--now", help="ISO time to evaluate a replay at (default: when it was recorded)")

    q = sub.add_parser("regime")
    replayable(q)
    q.set_defaults(fn=cmd_regime)

    q = sub.add_parser("scan")
    q.add_argument("--slot", help="scheduled slot in Pacific time, e.g. 10:30")
    replayable(q)
    q.set_defaults(fn=cmd_scan)

    q = sub.add_parser("log")
    q.add_argument("--from", dest="start")
    q.add_argument("--to", dest="end")
    q.add_argument("--kind", choices=["proposal", "stand_down", "no_advice"])
    q.add_argument("--full", action="store_true")
    q.set_defaults(fn=cmd_log)

    q = sub.add_parser("kr")
    q.add_argument("which", choices=kr.CHECKS)
    q.add_argument("--from", dest="start")
    q.add_argument("--to", dest="end")
    q.add_argument("--plant", action="store_true", help="A-KR2: plant one bad row per check in a copy of the log")
    q.set_defaults(fn=cmd_kr)

    a = ap.parse_args(argv)
    if a.cmd == "profile" and a.action == "set" and (a.net_liq is None or a.margin is None):
        ap.error("profile set requires --net-liq and --margin")
    return a.fn(a, load_params(a.params))


if __name__ == "__main__":
    sys.exit(main())
