import copy
import gzip
import json
from datetime import datetime
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
