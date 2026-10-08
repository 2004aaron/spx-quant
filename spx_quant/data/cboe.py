"""Cboe delayed-quote CDN source, recorded replays, and the feed check (US-06).

The endpoint is undocumented and about 15 minutes delayed. Two timestamps matter:
  * payload "timestamp" is when the CDN built the file (UTC). It is always fresh,
    even hours after the close, so it says nothing about the quotes.
  * data.last_trade_time is the underlying's last print, in US Eastern wall time.
    That is the quote time used for every freshness decision (QR-1).
The chain is fetched once per scan; the same payload is checked and then used.
"""
from __future__ import annotations

import gzip
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .. import clock

CDN = "https://cdn.cboe.com/api/global/delayed_quotes"
OCC = re.compile(r"^(?P<root>[A-Z]+)(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")
CURVE = {"vix9d": "VIX9D", "vix": "VIX", "vix3m": "VIX3M", "vix6m": "VIX6M"}
REQUIRED_CURVE = ("vix", "vix3m")
REQUIRED_OPTION_FIELDS = ("option", "bid", "ask", "iv", "delta", "open_interest", "volume")
MULTIPLIER = 100


RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_WAITS = (2, 5, 10)     # seconds; the CDN rate-limits bursts (HTTP 429), seen live on 2026-10-08
_sleep = time.sleep


def fetch_json(url: str, timeout: float = 30) -> dict:
    """GET a CDN payload, retrying rate limits, server errors and network drops up to three
    times (honoring Retry-After up to 15 seconds). Anything else fails at once."""
    req = urllib.request.Request(url, headers={"User-Agent": "spx-quant/0.5"})
    for wait in (*RETRY_WAITS, None):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or wait is None:
                raise
            after = e.headers.get("Retry-After") if e.headers else None
            if after and after.strip().isdigit():
                wait = min(max(int(after), wait), 15)
        except (urllib.error.URLError, TimeoutError):
            if wait is None:
                raise
        _sleep(wait)


class LiveSource:
    name = "cboe (delayed ~15 min)"

    def __init__(self, timeout: float = 30):
        self.timeout = timeout

    def chain_payload(self, ticker: str) -> dict:
        return fetch_json(f"{CDN}/options/{ticker}.json", self.timeout)

    def quote_payload(self, symbol: str) -> dict:
        return fetch_json(f"{CDN}/quotes/_{symbol}.json", self.timeout)

    def now(self) -> datetime:
        return clock.now_utc()


class ReplaySource:
    """A recorded session. `now` defaults to when it was recorded, so staleness replays faithfully."""

    def __init__(self, path: Path | str, now: datetime | None = None):
        path = Path(path)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            self.rec = json.load(f)
        self._now = now or clock.parse_utc(self.rec["recorded_utc"])
        self.name = f"replay {path.name}"

    def chain_payload(self, ticker: str) -> dict:
        try:
            return self.rec["chains"][ticker]
        except KeyError:
            raise LookupError(f"{ticker} not in recording") from None

    def quote_payload(self, symbol: str) -> dict:
        try:
            return self.rec["curve"][symbol]
        except KeyError:
            raise LookupError(f"{symbol} not in recording") from None

    def now(self) -> datetime:
        return self._now


def quote_time(raw: dict) -> datetime:
    ts = (raw.get("data") or {}).get("last_trade_time")
    if not ts:
        raise KeyError("data.last_trade_time")
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt.astimezone(clock.UTC) if dt.tzinfo else clock.local_to_utc("ET", dt)


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
            "sym": o["option"], "root": m["root"], "exp": date(2000 + int(m["y"]), int(m["m"]), int(m["d"])),
            "right": m["cp"], "strike": int(m["strike"]) / 1000.0,
            "bid": bid, "ask": ask, "mid": round((bid + ask) / 2, 4),
            "iv": float(o.get("iv") or 0), "delta": float(o.get("delta") or 0),
            "oi": int(o.get("open_interest") or 0), "vol": int(o.get("volume") or 0),
        })
    return spot, rows


@dataclass
class ProbeResult:
    ok: bool
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    latency_ms: int = 0
    strikes: int = 0
    quote_age_min: float | None = None
    kind: str = ""  # feed_failure | stale_data | "" when ok

    def __str__(self) -> str:
        head = f"probe: {'OK' if self.ok else 'FAIL'}  latency {self.latency_ms} ms  strikes parsed {self.strikes}"
        lines = [head] + [f"  ok   {c}" for c in self.checks] + [f"  FAIL {f}" for f in self.failures]
        return "\n".join(lines)


def probe_payload(raw: dict, stale_after_minutes: float, now: datetime | None = None, min_rows: int = 1) -> ProbeResult:
    """Pure check of one chain payload: shape, size, and quote age (older than the limit fails; equal passes)."""
    res = ProbeResult(ok=True)
    try:
        options = raw["data"]["options"]
        res.checks.append(f"shape: data.options present ({len(options)} rows)")
    except (KeyError, TypeError):
        res.failures.append("shape: field 'data.options' missing")
        res.ok, res.kind = False, "feed_failure"
        return res
    if len(options) < min_rows:
        res.failures.append(f"size: {len(options)} rows, expected at least {min_rows}")
    sample = options[0] if options else {}
    for f in REQUIRED_OPTION_FIELDS:
        if f not in sample:
            res.failures.append(f"shape: field '{f}' missing at path data.options[0]")
    stale = False
    try:
        age = ((now or clock.now_utc()) - quote_time(raw)).total_seconds() / 60
        res.quote_age_min = round(age, 1)
        if age > stale_after_minutes:
            stale = True
            res.failures.append(f"freshness: quotes are {age:.0f} min old (limit {stale_after_minutes:g})")
        else:
            res.checks.append(f"freshness: quotes {age:.0f} min old")
    except (KeyError, ValueError) as e:
        res.failures.append(f"shape: quote time unreadable ({e})")
    try:
        _, rows = parse_chain(raw)
        res.strikes = len(rows)
        if not rows:
            res.failures.append("chain: zero parseable strikes")
    except (KeyError, TypeError, ValueError) as e:
        res.failures.append(f"chain: unparseable ({e})")
    res.ok = not res.failures
    if not res.ok:
        res.kind = "stale_data" if stale and len(res.failures) == 1 else "feed_failure"
    return res


@dataclass
class Chain:
    ticker: str
    spot: float
    quote_ts: datetime
    rows: list[dict]
    probe: ProbeResult

    @property
    def multiplier(self) -> int:
        return MULTIPLIER


def fetch_chain(source, ticker: str, stale_after_minutes: float, min_rows: int = 1,
                now: datetime | None = None) -> tuple[Chain | None, ProbeResult]:
    """One fetch, checked, then parsed. Returns (None, failed probe) instead of passing bad data on."""
    now = now or source.now()
    t0 = time.perf_counter()
    try:
        raw = source.chain_payload(ticker)
    except Exception as e:
        res = ProbeResult(ok=False, failures=[f"fetch {ticker}: {e}"], kind="feed_failure")
        res.latency_ms = int((time.perf_counter() - t0) * 1000)
        return None, res
    res = probe_payload(raw, stale_after_minutes, now, min_rows)
    res.latency_ms = int((time.perf_counter() - t0) * 1000)
    if not res.ok:
        return None, res
    spot, rows = parse_chain(raw)
    return Chain(ticker, spot, quote_time(raw), rows, res), res


@dataclass
class Curve:
    values: dict[str, float | None]
    quote_ts: dict[str, datetime | None]
    notes: list[str] = field(default_factory=list)

    @property
    def asof(self) -> datetime | None:
        """Oldest quote among the points actually used (dropped points do not count)."""
        stamps = [t for k, t in self.quote_ts.items() if t and self.values.get(k) is not None]
        return min(stamps) if stamps else None


def fetch_curve(source, stale_after_minutes: float, now: datetime | None = None) -> tuple[Curve, list[str]]:
    """VIX term structure. Returns (curve, stale_failures). A point that cannot be fetched is None;
    a required point that is older than the limit is a staleness failure (US-06-AC2)."""
    now = now or source.now()
    vals: dict[str, float | None] = {}
    stamps: dict[str, datetime | None] = {}
    notes, stale = [], []
    for key, sym in CURVE.items():
        try:
            raw = source.quote_payload(sym)
            d = raw["data"]
            vals[key] = float(d.get("current_price") or d.get("close"))
            stamps[key] = quote_time(raw)
        except Exception as e:
            vals[key], stamps[key] = None, None
            notes.append(f"{sym}: {e}")
            continue
        age = (now - stamps[key]).total_seconds() / 60
        if age > stale_after_minutes:
            if key in REQUIRED_CURVE:
                stale.append(f"freshness: {sym} is {age:.0f} min old (limit {stale_after_minutes:g})")
            else:
                notes.append(f"{sym} dropped: {age:.0f} min old")
                vals[key] = None
    return Curve(vals, stamps, notes), stale


def record(source, tickers: list[str], path: Path | str, dte_max: int = 75) -> Path:
    """Save the current payloads for replay, trimmed to expirations within dte_max."""
    now = source.now()
    today = clock.market_date(now)
    chains = {}
    for t in tickers:
        raw = source.chain_payload(t)
        keep = []
        for o in raw["data"]["options"]:
            m = OCC.match(o.get("option", ""))
            if m and (date(2000 + int(m["y"]), int(m["m"]), int(m["d"])) - today).days <= dte_max:
                keep.append(o)
        raw = dict(raw, data=dict(raw["data"], options=keep))
        chains[t] = raw
    curve = {}
    for sym in CURVE.values():
        try:
            curve[sym] = source.quote_payload(sym)
        except Exception:
            pass
    rec = {"recorded_utc": now.isoformat(), "chains": chains, "curve": curve}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rec, f, separators=(",", ":"))
    return path
