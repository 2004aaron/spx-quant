import copy
import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path

from spx_quant import clock, store
from spx_quant.data.cboe import ReplaySource
from spx_quant.params import load_params
from spx_quant.profile import validate

REPLAY = Path(__file__).parent / "data" / "cboe-2026-09-28-close.json.gz"
EOD = clock.local_to_utc("PT", datetime(2026, 9, 28, 13, 25))    # 10 minutes after the recorded close
MARK_TIME = clock.local_to_utc("PT", datetime(2026, 9, 28, 13, 35))
PARAMS = load_params()


def replay(now=EOD):
    return ReplaySource(REPLAY, now)


def pm150():
    return validate(150_000, "portfolio", 0.08, 2)


def pm150_loose():
    """Delta:theta loosened to 1:0.5 so a naked put (about 1:0.7 in SPY deltas) also fits."""
    return validate(150_000, "portfolio", 0.08, 0.5)


def memdb():
    return store.connect(":memory:")


class PatchedSource:
    """The recorded session with edits: a different clock, spot, or leg quotes."""

    def __init__(self, now, spot=None, mids=None, quote_et=None, drop=(), curve=None):
        with gzip.open(REPLAY, "rt") as f:
            self.rec = json.load(f)
        self._now = now
        for t, raw in self.rec["chains"].items():
            d = raw["data"]
            if spot is not None:
                d["current_price"] = d["close"] = spot if t == "_SPX" else spot / 10
            if quote_et:
                d["last_trade_time"] = quote_et
            opts = []
            for o in d["options"]:
                if o["option"] in drop:
                    continue
                if mids and o["option"] in mids:
                    o = dict(o, bid=mids[o["option"]] - 0.05, ask=mids[o["option"]] + 0.05)
                opts.append(o)
            d["options"] = opts
        if quote_et:
            for raw in self.rec["curve"].values():
                raw["data"]["last_trade_time"] = quote_et
        for sym, v in (curve or {}).items():
            self.rec["curve"][sym]["data"]["current_price"] = v
        self.name = "patched replay"

    def chain_payload(self, ticker):
        return self.rec["chains"][ticker]

    def quote_payload(self, symbol):
        return self.rec["curve"][symbol]

    def now(self):
        return self._now


def params_without(section, key):
    p = copy.deepcopy(PARAMS)
    del p.sections[section][key]
    return p


def params_with(section, **values):
    p = copy.deepcopy(PARAMS)
    p.sections[section].update(values)
    return p


class TrendReplay(ReplaySource):
    """The recorded session plus a synthetic SPX daily history ending the session before (drift > 0 is an uptrend)."""

    def __init__(self, drift=0.001, now=EOD):
        super().__init__(REPLAY, now)
        from spx_quant.synthetic import history
        text = history(clock.market_date(now) - timedelta(days=3), drift=drift)
        self.history_text = lambda: text
