"""CLI: python -m spx_quant <command>

  profile set --net-liq N --margin reg_t|portfolio [--bp-cap 0.08] [--dt-limit 2]
  profile show
  probe   [--ticker _SPX]
  regime
  scan    [--ticker _SPX]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from . import __version__, profile as prof
from .data import cboe
from .params import load_params
from .regime import classify, gate
from .strategies import pick_strangle


def cmd_profile(a) -> int:
    if a.action == "show":
        p = prof.load()
        print(p if p else "no profile saved; run: python -m spx_quant profile set --net-liq N --margin reg_t|portfolio")
        return 0
    try:
        p = prof.validate(a.net_liq, a.margin, a.bp_cap, a.dt_limit)
    except prof.ProfileError as e:
        prev = prof.load()
        print(f"rejected: {e}")
        print(f"previous profile unchanged: {prev}" if prev else "no profile saved")
        return 2
    path = prof.save(p)
    print(f"saved {path}\n{p}")
    return 0


def cmd_probe(a) -> int:
    params = load_params()
    res = cboe.probe(a.ticker, params.feed["stale_after_minutes"], params.feed["timeout_seconds"])
    print(res)
    return 0 if res.ok else 1


def cmd_regime(a) -> int:
    params = load_params()
    curve = cboe.vix_curve(params.feed["timeout_seconds"])
    r = classify(curve, params)
    print(r)
    ok, reasons = gate(r, params)
    print("gate: GO" if ok else "gate: STAND DOWN\n  " + "\n  ".join(reasons))
    return 0


def cmd_scan(a) -> int:
    params = load_params()
    res = cboe.probe(a.ticker, params.feed["stale_after_minutes"], params.feed["timeout_seconds"])
    if not res.ok:
        print(res)
        print("NO ADVICE: feed probe failed")
        return 1
    snap = cboe.snapshot(a.ticker, params.feed["timeout_seconds"])
    r = classify(snap.curve, params)
    print(f"{a.ticker.lstrip('_')} {snap.spot:,.2f}  asof {snap.asof:%Y-%m-%d %H:%M %Z}  ({snap.source})")
    print(r)
    ok, reasons = gate(r, params)
    if not ok:
        print("STAND DOWN\n  " + "\n  ".join(reasons))
        return 0
    trade = pick_strangle(snap.rows, date.today(), params)
    if trade is None:
        print(f"NO PROPOSAL: no strikes pass the liquidity filter {params.liquidity}")
        return 0
    print(f"candidate: {trade}")
    print(params.summary())
    print("sizing, risk block and logging are not implemented yet (US-05, US-06, US-08)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spx_quant", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"spx-quant {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile")
    p.add_argument("action", choices=["set", "show"])
    p.add_argument("--net-liq", type=float)
    p.add_argument("--margin", choices=prof.MARGIN_TYPES)
    p.add_argument("--bp-cap", type=float, default=0.08)
    p.add_argument("--dt-limit", type=float, default=2.0)
    p.set_defaults(fn=cmd_profile)

    for name, fn in (("probe", cmd_probe), ("scan", cmd_scan)):
        q = sub.add_parser(name)
        q.add_argument("--ticker", default="_SPX")
        q.set_defaults(fn=fn)

    sub.add_parser("regime").set_defaults(fn=cmd_regime)

    a = ap.parse_args(argv)
    if a.cmd == "profile" and a.action == "set" and (a.net_liq is None or a.margin is None):
        ap.error("profile set requires --net-liq and --margin")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
