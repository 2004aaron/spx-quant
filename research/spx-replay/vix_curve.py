"""VIX futures curve from OptionsDX VIX option chains, 2010 to 2023.

    python research/spx-replay/vix_curve.py VIX_DATA OUT.csv [--cboe-cache .cache/cboe]

VIX options price off VIX futures, not spot VIX. Put-call parity at the strike where call and
put mids are closest gives the forward for each expiry: F = K + (C - P). That forward is the
market's price for VIX at that expiry, so the gap between it and spot VIX is the contango or
backwardation option sellers actually trade against.

Output, one row per session: date, spot VIX, the parity forward at the expiries nearest 30 and
90 days out, a 30-day constant-maturity forward interpolated between expiries, and the slope
(F30 - VIX) / VIX. If the Cboe cache holds VIX.csv, prints how far OptionsDX's spot VIX sits
from Cboe's close as a data check.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "spx-replay"))
from tier_b_spx import boards  # noqa: E402


def forward(strikes: dict) -> float | None:
    best = None
    for k, legs in strikes.items():
        (cb, ca, _), (pb, pa, _) = legs["C"], legs["P"]
        if None in (cb, ca, pb, pa) or ca <= 0 or pa <= 0 or ca < cb or pa < pb:
            continue
        c, p = (cb + ca) / 2, (pb + pa) / 2
        if best is None or abs(c - p) < best[0]:
            best = (abs(c - p), k + c - p)
    return best[1] if best else None


def curve_row(d: date, b) -> dict | None:
    fwd = sorted(((e - d).days, f) for e, ch in b.chains.items() if (e - d).days >= 5 and (f := forward(ch)) is not None)
    if not fwd:
        return None
    near = lambda target: min(fwd, key=lambda x: abs(x[0] - target))
    (d1, f1), (d3, f3) = near(30), near(90)
    lo = [x for x in fwd if x[0] <= 30]
    hi = [x for x in fwd if x[0] >= 30]
    if lo and hi:
        (a, fa), (z, fz) = lo[-1], hi[0]
        f30 = fa if z == a else fa + (fz - fa) * (30 - a) / (z - a)
    else:
        f30 = f1
    return {"date": d.isoformat(), "vix": round(b.spot, 2), "f30": round(f30, 3), "f1": round(f1, 3), "f1_dte": d1,
            "f3": round(f3, 3), "f3_dte": d3, "slope30": round((f30 - b.spot) / b.spot, 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--cboe-cache", type=Path, default=ROOT / ".cache" / "cboe")
    a = ap.parse_args()
    rows = [r for d, b in boards(a.data) if (r := curve_row(d, b))]
    with a.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} sessions, {rows[0]['date']} to {rows[-1]['date']} -> {a.out}")
    cboe = a.cboe_cache / "VIX.csv"
    if cboe.exists():
        sys.path.insert(0, str(ROOT / "research" / "rules-pivot"))
        from tier_a import series
        close = series(a.cboe_cache, "VIX", 4)
        gaps = sorted(abs(r["vix"] - close[d]) for r in rows if (d := date.fromisoformat(r["date"])) in close)
        print(f"spot VIX vs Cboe close: {len(gaps)} matched, median gap {gaps[len(gaps) // 2]:.2f}, "
              f"95th pct {gaps[int(0.95 * len(gaps))]:.2f}, max {gaps[-1]:.2f}")


if __name__ == "__main__":
    main()
