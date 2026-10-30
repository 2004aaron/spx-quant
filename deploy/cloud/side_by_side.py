"""Two users' logs side by side, one row per scheduled scan.

    python deploy/cloud/side_by_side.py pilot.db demo.db [--labels pilot demo]

Shows when each user's scan started and what it answered, so two users running the
same code at the same time can be checked from their logs alone. Account sizes stay
out of the table (QR-5).
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spx_quant import clock  # noqa: E402

SQL = """SELECT s.market_date, s.slot, s.started_ts, s.outcome, a.ticker, a.strategy, a.contracts
         FROM scan s LEFT JOIN alert a ON a.alert_id = s.alert_id ORDER BY s.id"""


def scans(db: str) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = {}
    for r in conn.execute(SQL):
        out.setdefault((r["market_date"], r["slot"]), dict(r))
    return out


def answer(r: dict | None) -> str:
    if r is None:
        return "no scan"
    if r["outcome"] == "proposal":
        return f"PROPOSAL {r['strategy']} {r['ticker'].lstrip('_')} x{r['contracts']}"
    return r["outcome"].upper().replace("_", " ")


def started(r: dict | None) -> str:
    return clock.to_local("PT", clock.parse_utc(r["started_ts"])).strftime("%H:%M:%S") if r else ""


def table(a: str, b: str, labels=("user A", "user B")) -> str:
    sa, sb = scans(a), scans(b)
    la, lb = labels
    lines = [f"| Date | Slot | {la} started (PT) | {la} answer | {lb} started (PT) | {lb} answer | Start gap |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    gaps = []
    for key in sorted(set(sa) | set(sb)):
        ra, rb = sa.get(key), sb.get(key)
        gap = ""
        if ra and rb:
            s = abs((clock.parse_utc(ra["started_ts"]) - clock.parse_utc(rb["started_ts"])).total_seconds())
            gaps.append(s)
            gap = f"{s:.0f} s"
        lines.append(f"| {key[0]} | {key[1]} | {started(ra)} | {answer(ra)} | {started(rb)} | {answer(rb)} | {gap} |")
    both = len(gaps)
    lines.append("")
    lines.append(f"{both} slot{'' if both == 1 else 's'} in both logs, {len(sa) - both} only in {la}'s, {len(sb) - both} only in {lb}'s."
                 + (f" Median start gap {statistics.median(gaps):.0f} s." if gaps else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    labels = ("user A", "user B")
    if "--labels" in args:
        i = args.index("--labels")
        labels, args = tuple(args[i + 1:i + 3]), args[:i] + args[i + 3:]
    if len(args) != 2 or len(labels) != 2:
        raise SystemExit(__doc__)
    print(table(*args, labels=labels))
