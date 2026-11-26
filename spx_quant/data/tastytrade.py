"""tastytrade market-data source (real-time REST), shaped like the Cboe payloads so the probe and
parser in cboe.py check and read it unchanged.

    TASTYTRADE_CLIENT_SECRET=... TASTYTRADE_REFRESH_TOKEN=...   (read-only OAuth grant)

tastytrade's REST quotes carry bid, ask, volume and open interest but no greeks, so IV and delta
come from the engine's own Black-Scholes on the mid. Only the expirations nearest the target DTE
(plus any the caller asks for with `want`) and strikes within a band around spot are quoted, to
stay well under the 100-symbol-per-request limit.
"""
from __future__ import annotations

import gzip
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

from .. import clock
from ..greeks import bs, implied_vol
from ..strategies import years_to
from . import vixcalc
from .cboe import OCC

API = "https://api.tastyworks.com"
UA = "stormglass/1.0"
BATCH = 100
BAND = (0.80, 1.12)
COMPUTED = {"VIX3M": 93, "VIX9D": 9, "VIX6M": 182}   # not quoted by tastytrade: built from SPX options, Cboe method
WINGS = (0.30, 1.60)   # strikes priced for an index, as a fraction of spot   # strikes quoted, as a fraction of spot


def available() -> bool:
    return bool(os.environ.get("TASTYTRADE_CLIENT_SECRET") and os.environ.get("TASTYTRADE_REFRESH_TOKEN"))


class TastytradeSource:
    name = "tastytrade (real-time)"

    def __init__(self, params, timeout: float = 30):
        self.timeout = timeout
        self.rate = params.risk["rate"]
        e = params.expiry
        self.target, self.lo, self.hi = e["target_dte"], e["dte_min"], e["dte_max"]
        self.per_root = 2
        self.wanted: set[str] = set()
        self._token = None
        self._chains: dict[str, list] = {}

    def want(self, syms) -> None:
        """Quote these option symbols too (open positions being marked)."""
        self.wanted |= set(syms)

    def _get(self, path: str, query: dict | None = None) -> dict:
        try:
            return self._call(path, query)
        except urllib.error.HTTPError as e:
            raw = e.read()
            body = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode(errors="replace")[:300]
            step = "oauth token" if self._token is None else path
            raise RuntimeError(f"tastytrade {step}: HTTP {e.code} {body}") from None

    def _call(self, path: str, query: dict | None = None) -> dict:
        if self._token is None:
            body = urllib.parse.urlencode({"grant_type": "refresh_token",
                                           "refresh_token": os.environ["TASTYTRADE_REFRESH_TOKEN"],
                                           "client_secret": os.environ["TASTYTRADE_CLIENT_SECRET"]}).encode()
            req = urllib.request.Request(f"{API}/oauth/token", body,
                                         {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self._token = json.load(r)["access_token"]
        url = f"{API}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Authorization": f"Bearer {self._token}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def _quotes(self, kind: str, syms: list[str]) -> dict[str, dict]:
        out = {}
        for i in range(0, len(syms), BATCH):
            data = self._get("/market-data/by-type", {kind: ",".join(syms[i:i + BATCH])})
            for it in data.get("data", {}).get("items", []):
                out[it["symbol"]] = it
        return out

    def _index(self, sym: str) -> dict:
        q = self._quotes("index", [sym]).get(sym)
        if not q:
            raise LookupError(f"no tastytrade quote for {sym}")
        return q

    @staticmethod
    def _px(q: dict) -> float | None:
        for k in ("last", "mark", "mid", "close", "prev-close"):
            v = q.get(k)
            if v not in (None, "") and float(v) > 0:
                return float(v)
        return None

    @staticmethod
    def _et(ts: str) -> str:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return clock.to_local("ET", dt).replace(tzinfo=None).isoformat(timespec="seconds")

    def chain_payload(self, ticker: str) -> dict:
        und = ticker.lstrip("_")
        try:
            q = self._index(und)
            spot = self._px(q)
        except LookupError:
            if und != "XSP":
                raise
            q = self._index("SPX")
            spot = self._px(q) / 10 if self._px(q) else None
        if not spot:
            raise LookupError(f"no price for {und}")
        now = self.now()
        today = clock.market_date(now)
        wanted = {OCC.match(s)["root"] + s[-15:-9] for s in self.wanted if OCC.match(s)}
        syms = []
        for chain in self._get(f"/option-chains/{und}/nested")["data"]["items"]:
            root = chain["root-symbol"]
            exps = []
            for e in chain["expirations"]:
                d = date.fromisoformat(e["expiration-date"])
                exps.append(((d - today).days, d, e))
            near = sorted((x for x in exps if self.lo <= x[0] <= self.hi), key=lambda x: abs(x[0] - self.target))
            keep = {d for _, d, _ in near[:self.per_root]} | {d for _, d, _ in exps if f"{root}{d:%y%m%d}" in wanted}
            for _, d, e in exps:
                if d not in keep:
                    continue
                for s in e["strikes"]:
                    k = float(s["strike-price"])
                    if BAND[0] * spot <= k <= BAND[1] * spot or any(
                            x.replace(" ", "") in self.wanted for x in (s["call"], s["put"])):
                        syms += [s["call"], s["put"]]
        quotes = self._quotes("equity-option", syms)
        options = []
        for sym in syms:
            o = quotes.get(sym)
            occ = sym.replace(" ", "")
            m = OCC.match(occ)
            if not o or not m:
                continue
            bid, ask = float(o.get("bid") or 0), float(o.get("ask") or 0)
            k, right = int(m["strike"]) / 1000.0, m["cp"]
            t = years_to(m["root"], date(2000 + int(m["y"]), int(m["m"]), int(m["d"])), now)
            iv = implied_vol((bid + ask) / 2, spot, k, t, right, self.rate) if ask > 0 else None
            options.append({"option": occ, "bid": bid, "ask": ask, "iv": iv or 0,
                            "delta": bs(spot, k, t, iv, right, self.rate).delta if iv else 0,
                            "open_interest": int(float(o.get("open-interest") or 0)),
                            "volume": int(float(o.get("volume") or 0))})
        return {"timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "data": {"current_price": spot, "last_trade_time": self._et(q["updated-at"]), "options": options}}

    def nested(self, und: str) -> list:
        if und not in self._chains:
            self._chains[und] = self._get(f"/option-chains/{und}/nested")["data"]["items"]
        return self._chains[und]

    def computed(self, days: float) -> tuple[float, dict, dict]:
        """A constant-maturity SPX volatility index built from live quotes: (value, details, SPX quote)."""
        q = self._index("SPX")
        spot, now = self._px(q), self.now()
        listed = {(c["root-symbol"], date.fromisoformat(e["expiration-date"])): e["strikes"]
                  for c in self.nested("SPX") for e in c["expirations"]}
        near, far = vixcalc.bracket([{"root": r, "exp": d} for r, d in listed], now, days)
        syms = []
        for root, exp, _ in (near, far):
            for s in listed[(root, exp)]:
                k = float(s["strike-price"])
                if WINGS[0] * spot <= k <= 1.05 * spot:
                    syms.append(s["put"])
                if 0.95 * spot <= k <= WINGS[1] * spot:
                    syms.append(s["call"])
        got = self._quotes("equity-option", syms)
        rows = []
        for sym in syms:
            o, m = got.get(sym), OCC.match(sym.replace(" ", ""))
            if o and m:
                rows.append({"root": m["root"], "exp": date(2000 + int(m["y"]), int(m["m"]), int(m["d"])), "right": m["cp"],
                             "strike": int(m["strike"]) / 1000.0, "bid": float(o.get("bid") or 0), "ask": float(o.get("ask") or 0)})
        value, info = vixcalc.index(rows, now, self.rate, days)
        return value, info, q

    def quote_payload(self, symbol: str) -> dict:
        if symbol in COMPUTED:
            value, _, q = self.computed(COMPUTED[symbol])
            return {"data": {"current_price": value, "last_trade_time": self._et(q["updated-at"])}}
        q = self._index(symbol)
        return {"data": {"current_price": self._px(q), "last_trade_time": self._et(q["updated-at"])}}

    def history_text(self) -> str:
        from ..trend import fetch_text
        return fetch_text(timeout=self.timeout)

    def now(self) -> datetime:
        return clock.now_utc()
