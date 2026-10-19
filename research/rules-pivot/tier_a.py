"""Re-run of the Tier A regime-gate study against the shipping classifier (rules pivot, 2026-10-19).

    python research/rules-pivot/tier_a.py [cache_dir]

Downloads Cboe daily histories (PUT, PUTD, WPUT, CNDR, BXMD, VIX, VIX3M, VIX9D) into cache_dir,
classifies every session with spx_quant.regime.classify, lags the signal one day, and compares
the mean 21-session forward return of each Cboe strategy index on GO vs STAND DOWN days for the
old gate (backwardation + floor + ceiling) and the new default (floor + ceiling). p-values come
from a circular block bootstrap with 21-session blocks, 2,000 draws.
"""
import csv
import json
import random
import statistics as st
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from spx_quant.params import load_params  # noqa: E402
from spx_quant.regime import classify  # noqa: E402

URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv"
PROGRAMS = ("PUT", "PUTD", "WPUT", "CNDR", "BXMD")
H = 21


def series(cache: Path, ticker: str, col: int = -1) -> dict:
    path = cache / f"{ticker}.csv"
    if not path.exists():
        req = urllib.request.Request(URL.format(ticker), headers={"User-Agent": "stormglass-research"})
        path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    out = {}
    with path.open() as f:
        rows = csv.reader(f)
        next(rows)
        for row in rows:
            try:
                out[datetime.strptime(row[0], "%m/%d/%Y").date()] = float(row[col])
            except (ValueError, IndexError):
                pass
    return out


def rule_gate(reg, rule: str) -> bool:
    if not reg.known or reg.bucket in ("crushed", "panic"):
        return False
    return not (rule == "old" and reg.state == "backwardation")


def boot_diff(xs, mask, n=2000, seed=7):
    ann = lambda x: x * 252 / H
    mean_split = lambda m: (st.mean([x for x, k in zip(xs, m) if k]), st.mean([x for x, k in zip(xs, m) if not k]))
    a, b = mean_split(mask)
    obs, rnd, N, hits = ann(a - b), random.Random(seed), len(xs), 0
    for _ in range(n):
        idx = []
        while len(idx) < N:
            s = rnd.randrange(N)
            idx += [(s + k) % N for k in range(H)]
        m2 = [mask[j] for j in idx[:N]]
        if any(m2) and not all(m2):
            a, b = mean_split(m2)
            hits += abs(ann(a - b)) >= abs(obs)
    return obs, (hits + 1) / (n + 1)


def main() -> None:
    cache = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / ".cache" / "cboe")
    cache.mkdir(parents=True, exist_ok=True)
    p = load_params()
    vix, v3m, v9d = (series(cache, t, 4) for t in ("VIX", "VIX3M", "VIX9D"))
    progs = {t: series(cache, t) for t in PROGRAMS}
    days = sorted(d for d in vix if d in v3m and d in v9d and d.year >= 2011 and all(d in s for s in progs.values()))
    regs = [classify({"vix": vix[d], "vix3m": v3m[d], "vix9d": v9d[d]}, p) for d in days]
    rows = [dict(reg=regs[i - 1], fwd={t: s[days[i + H]] / s[days[i]] - 1 for t, s in progs.items()})
            for i in range(1, len(days) - H)]
    out = {"sessions": len(rows), "first": str(days[1]), "last_signal": str(days[-H - 1]), "rules": {}}
    for rule in ("old", "new"):
        mask = [rule_gate(r["reg"], rule) for r in rows]
        res = out["rules"][rule] = {"go_share": round(sum(mask) / len(mask), 4)}
        for t in PROGRAMS:
            xs = [r["fwd"][t] for r in rows]
            diff, pv = boot_diff(xs, mask)
            go = st.mean([x for x, m in zip(xs, mask) if m]) * 252 / H
            sd = st.mean([x for x, m in zip(xs, mask) if not m]) * 252 / H
            res[t] = {"go": round(go, 4), "stand_down": round(sd, 4), "diff": round(diff, 4), "p": round(pv, 4)}
    xs = [r["fwd"]["PUTD"] for r in rows]
    diff, pv = boot_diff(xs, [r["reg"].state == "backwardation" for r in rows])
    out["backwardation_vs_rest_PUTD"] = {"n": sum(r["reg"].state == "backwardation" for r in rows),
                                         "diff": round(diff, 4), "p": round(pv, 4)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
