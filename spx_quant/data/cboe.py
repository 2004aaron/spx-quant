"""Cboe delayed-quote CDN source and the feed probe (US-11).

The endpoint is undocumented and about 15 minutes delayed. Run the probe before
trusting any number: it checks response shape and quote age and refuses to pass
stale or malformed data downstream.
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

CDN = "https://cdn.cboe.com/api/global/delayed_quotes"
OCC = re.compile(r"^(?P<root>[A-Z]+)(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")
CURVE = {"vix9d": "VIX9D", "vix": "VIX", "vix3m": "VIX3M", "vix6m": "VIX6M"}
REQUIRED_OPTION_FIELDS = ("option", "bid", "ask", "iv", "delta", "open_interest", "volume")


def fetch_json(url: str, timeout: float = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "spx-quant/0.3"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return json.load(r)


@dataclass
class Snapshot:
    spot: float
    asof: datetime
    rows: list[dict]
    curve: dict[str, float | None]
    source: str = "cboe (delayed ~15 min)"

    def age_minutes(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.asof).total_seconds() / 60.0


@dataclass
class ProbeResult:
    ok: bool
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    latency_ms: int = 0
    strikes: int = 0

    def __str__(self) -> str:
        head = f"probe: {'OK' if self.ok else 'FAIL'}  latency {self.latency_ms} ms  strikes parsed {self.strikes}"
        lines = [head] + [f"  ok   {c}" for c in self.checks] + [f"  FAIL {f}" for f in self.failures]
        return "\n".join(lines)


def parse_timestamp(raw: dict) -> datetime:
    ts = raw.get("timestamp") or raw.get("data", {}).get("last_trade_time")
    if not ts:
        raise KeyError("timestamp")
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_chain(raw: dict) -> tuple[float, list[dict]]:
    data = raw["data"]
    spot = float(data.get("current_price") or data["close"])
    rows = []
    for o in data["options"]:
        m = OCC.match(o["option"])
        if not m:
            continue
        bid, ask = float(o.get("bid") or 0), float(o.get("ask") or 0)
        rows.append({
            "sym": o["option"], "exp": date(2000 + int(m["y"]), int(m["m"]), int(m["d"])),
            "right": m["cp"], "strike": int(m["strike"]) / 1000.0,
            "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
            "iv": float(o.get("iv") or 0), "delta": float(o.get("delta") or 0),
            "oi": int(o.get("open_interest") or 0), "vol": int(o.get("volume") or 0),
        })
    return spot, rows


def probe_payload(raw: dict, stale_after_minutes: float, now: datetime | None = None) -> ProbeResult:
    """Pure check of one chain payload. Split from the network call so tests can replay recorded responses."""
    res = ProbeResult(ok=True)
    try:
        options = raw["data"]["options"]
        res.checks.append(f"shape: data.options present ({len(options)} rows)")
    except (KeyError, TypeError):
        res.failures.append("shape: field 'data.options' missing")
        res.ok = False
        return res
    sample = options[0] if options else {}
    for f in REQUIRED_OPTION_FIELDS:
        if f not in sample:
            res.failures.append(f"shape: field '{f}' missing at path data.options[0]")
    try:
        asof = parse_timestamp(raw)
        age = (now or datetime.now(timezone.utc)) - asof
        minutes = age.total_seconds() / 60
        if minutes > stale_after_minutes:
            res.failures.append(f"freshness: quotes are {minutes:.0f} min old (limit {stale_after_minutes:g})")
        else:
            res.checks.append(f"freshness: quotes {minutes:.0f} min old")
    except (KeyError, ValueError) as e:
        res.failures.append(f"shape: timestamp unreadable ({e})")
    try:
        _, rows = parse_chain(raw)
        res.strikes = len(rows)
        if not rows:
            res.failures.append("chain: zero parseable strikes")
    except (KeyError, TypeError, ValueError) as e:
        res.failures.append(f"chain: unparseable ({e})")
    res.ok = not res.failures
    return res


def probe(ticker: str = "_SPX", stale_after_minutes: float = 30, timeout: float = 30) -> ProbeResult:
    t0 = time.perf_counter()
    try:
        raw = fetch_json(f"{CDN}/options/{ticker}.json", timeout)
    except Exception as e:
        return ProbeResult(ok=False, failures=[f"fetch: {e}"], latency_ms=int((time.perf_counter() - t0) * 1000))
    res = probe_payload(raw, stale_after_minutes)
    res.latency_ms = int((time.perf_counter() - t0) * 1000)
    return res


def vix_curve(timeout: float = 30) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key, tick in CURVE.items():
        try:
            d = fetch_json(f"{CDN}/quotes/_{tick}.json", timeout)["data"]
            out[key] = float(d.get("current_price") or d.get("close"))
        except Exception:
            out[key] = None
    return out


def snapshot(ticker: str = "_SPX", timeout: float = 30) -> Snapshot:
    raw = fetch_json(f"{CDN}/options/{ticker}.json", timeout)
    spot, rows = parse_chain(raw)
    return Snapshot(spot, parse_timestamp(raw), rows, vix_curve(timeout))
