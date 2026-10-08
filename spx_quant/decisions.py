"""The investor's decision on each proposal (US-10) and the buying power it holds (US-13).

Decisions are append-only feedback rows; the latest one for an alert counts. They come
from the CLI or from an email reply whose first word is the decision (the scheduled task
parses the reply and passes the Gmail message id as `ref`, so a reply is never counted twice).

  accepted   taken at the proposed size
  modified   taken at a different size (--contracts N); counts at that size
  declined   not taken
  closed     a taken position closed before expiration; releases its buying power
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from . import clock, store

DECISIONS = ("accepted", "modified", "declined", "closed")
TAKEN = ("accepted", "modified")
REPLY = re.compile(r"^\s*(accepted|accept|declined|decline|modified|modify|closed|close)\b[\s,:.-]*(\d+)?", re.I)
ALIASES = {"accept": "accepted", "decline": "declined", "modify": "modified", "close": "closed"}


class DecisionError(ValueError):
    pass


@dataclass(frozen=True)
class Held:
    alert_id: str
    contracts: int
    bp: float


def parse_reply(body: str) -> tuple[str, int | None] | None:
    """'Accepted' / 'modified 2' / 'Declined, too close to earnings' -> (decision, contracts)."""
    m = REPLY.match(body or "")
    if not m:
        return None
    word = m.group(1).lower()
    return ALIASES.get(word, word), int(m.group(2)) if m.group(2) else None


def latest(conn, alert_id: str, asof: datetime | None = None) -> dict | None:
    q, args = "SELECT * FROM feedback WHERE alert_id = ?", [alert_id]
    if asof is not None:
        q += " AND received_ts <= ?"
        args.append(asof.isoformat())
    r = store.rows(conn, q + " ORDER BY received_ts DESC, id DESC LIMIT 1", args)
    return r[0] if r else None


def history(conn, alert_id: str) -> list[dict]:
    return store.rows(conn, "SELECT * FROM feedback WHERE alert_id = ? ORDER BY received_ts, id", (alert_id,))


def record(conn, alert_id: str, decision: str, now: datetime, reason: str = "", contracts: int | None = None,
           source: str = "cli", ref: str | None = None) -> str:
    """Validate and store one decision. Returns 'recorded' or 'duplicate' (same ref seen before)."""
    decision = ALIASES.get(decision.lower(), decision.lower())
    a = store.get_alert(conn, alert_id)
    if a is None:
        raise DecisionError(f"no logged alert with id {alert_id!r}; nothing stored")
    if a["kind"] != "proposal":
        raise DecisionError(f"{alert_id} is a {a['kind'].replace('_', ' ')}, not a proposal; nothing to accept or decline")
    if decision not in DECISIONS:
        raise DecisionError(f"decision must be one of {', '.join(DECISIONS)}; got {decision!r}")
    if ref and store.rows(conn, "SELECT 1 FROM feedback WHERE ref = ?", (ref,)):
        return "duplicate"
    if decision == "modified":
        if not contracts or contracts < 1:
            raise DecisionError("a modified decision needs the size you actually took (--contracts N, at least 1)")
    elif decision == "closed":
        prev = latest(conn, alert_id)
        if prev is None or prev["decision"] not in TAKEN:
            raise DecisionError(f"{alert_id} was never recorded as taken, so it cannot be closed")
        contracts = None
    else:
        contracts = a["contracts"] if decision == "accepted" else None
    store.insert(conn, "feedback", alert_id=alert_id, received_ts=now, decision=decision, reason=reason.strip(),
                 contracts=contracts, source=source, ref=ref)
    return "recorded"


def held(conn, asof: datetime) -> list[Held]:
    """Positions taken and still open at `asof`: latest decision accepted or modified, not
    closed, and not settled by the marking job (US-13, S-KR1)."""
    out = []
    ids = [r["alert_id"] for r in store.rows(conn, "SELECT DISTINCT alert_id FROM feedback WHERE received_ts <= ? ORDER BY alert_id",
                                             (asof.isoformat(),))]
    day = clock.market_date(asof).isoformat()
    for aid in ids:
        d = latest(conn, aid, asof)
        if d is None or d["decision"] not in TAKEN:
            continue
        if store.rows(conn, "SELECT 1 FROM mark WHERE alert_id = ? AND settled = 1 AND market_date <= ?", (aid, day)):
            continue
        a = store.get_alert(conn, aid)
        n = int(d["contracts"] or a["contracts"] or 0)
        out.append(Held(aid, n, round((a["bp_per_lot"] or 0.0) * n, 2)))
    return out


def taken_size(conn, alert: dict, asof: datetime) -> int | None:
    """Contracts the investor holds (or held) on this alert as of `asof`, None if never taken."""
    taken = [d for d in history(conn, alert["alert_id"]) if d["received_ts"] <= asof.isoformat() and d["decision"] in TAKEN]
    return int(taken[-1]["contracts"] or alert["contracts"]) if taken else None
