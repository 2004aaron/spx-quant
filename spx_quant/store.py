"""SQLite log (US-08): six append-only tables, one file per user.

Triggers refuse UPDATE and DELETE on every table, so the weekly report can be
regenerated from the log and come out the same every time (US-11-AC1, QR-4).
JSON columns hold structured detail; scalar columns hold what gets queried.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .profile import HOME

DEFAULT_PATH = HOME / "quant.db"

SCHEMA = {
    "scan": """slot TEXT, slot_ts TEXT, started_ts TEXT, finished_ts TEXT, outcome TEXT NOT NULL,
               quote_age_min REAL, data_ts TEXT, alert_id TEXT, market_date TEXT, source TEXT,
               detail TEXT, leg_quotes TEXT""",
    "alert": """alert_id TEXT NOT NULL UNIQUE, slot TEXT, slot_ts TEXT, created_ts TEXT NOT NULL, data_ts TEXT,
                market_date TEXT, kind TEXT NOT NULL, outcome TEXT, ticker TEXT, strategy TEXT, regime TEXT,
                legs TEXT, contracts INTEGER, credit REAL, credit_per_lot REAL, bp_per_lot REAL, bp_total REAL,
                delta_per_lot REAL, theta_per_lot REAL, risk TEXT, reasons TEXT, codes TEXT, quotes TEXT,
                profile TEXT, candidates TEXT, fingerprint TEXT, repeat_of TEXT, subject TEXT, text TEXT""",
    "delivery": """alert_id TEXT NOT NULL, channel TEXT, attempt INTEGER, sent_ts TEXT, delivered_ts TEXT,
                   status TEXT NOT NULL, error TEXT, ref TEXT""",
    "mark": """alert_id TEXT NOT NULL, market_date TEXT NOT NULL, ts TEXT, dte INTEGER, spot REAL, mid REAL,
               pnl REAL, pnl_pct_credit REAL, settled INTEGER NOT NULL DEFAULT 0, exit_signal TEXT,
               basis TEXT, legs TEXT""",
    "feedback": """alert_id TEXT NOT NULL, received_ts TEXT, decision TEXT, reason TEXT, contracts INTEGER,
                   source TEXT, ref TEXT""",
    "event": """ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT, alert_id TEXT""",
}
JSON_COLS = {"detail", "leg_quotes", "regime", "legs", "risk", "reasons", "codes", "quotes", "profile", "candidates"}


def _enc(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, sort_keys=True, default=str)
    return v


def connect(path: Path | str = DEFAULT_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    for table, cols in SCHEMA.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})")
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col in (c.strip() for c in cols.split(",")):
            if col.split()[0] not in have:   # a log written by an older version gains the new columns
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        for op in ("UPDATE", "DELETE"):
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} BEFORE {op} ON {table}
                             BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END""")
    conn.commit()
    return conn


def insert(conn: sqlite3.Connection, table: str, **row) -> int:
    cols = list(row)
    cur = conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                       [_enc(row[c]) for c in cols])
    conn.commit()
    return cur.lastrowid


def decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in JSON_COLS & d.keys():
        v = d[k]
        if isinstance(v, str) and v[:1] in ("{", "[", '"') or v in ("null", "true", "false"):
            try:
                d[k] = json.loads(v)
            except ValueError:
                pass
    return d


def event(conn, ts: datetime, kind: str, detail: str, alert_id: str | None = None) -> None:
    insert(conn, "event", ts=ts, kind=kind, detail=detail, alert_id=alert_id)


def unique_alert_id(conn, aid: str) -> str:
    n, out = 1, aid
    while conn.execute("SELECT 1 FROM alert WHERE alert_id = ?", (out,)).fetchone():
        n += 1
        out = f"{aid}-{n}"
    return out


def alerts_between(conn, start: date, end: date, kind: str | None = None) -> list[dict]:
    """US-08-AC2: alerts whose market date falls in [start, end], in the order they were produced."""
    q = "SELECT * FROM alert WHERE market_date BETWEEN ? AND ?"
    args: list = [start.isoformat(), end.isoformat()]
    if kind:
        q += " AND kind = ?"
        args.append(kind)
    return [decode(r) for r in conn.execute(q + " ORDER BY created_ts, id", args)]


def get_alert(conn, alert_id: str) -> dict | None:
    return decode(conn.execute("SELECT * FROM alert WHERE alert_id = ?", (alert_id,)).fetchone())


def last_delivered(conn) -> dict | None:
    """The most recent alert that actually reached the investor."""
    return decode(conn.execute("""SELECT a.* FROM delivery d JOIN alert a ON a.alert_id = d.alert_id
                                  WHERE d.status = 'delivered' ORDER BY d.id DESC LIMIT 1""").fetchone())


def last_delivered_fingerprint(conn) -> str | None:
    a = last_delivered(conn)
    return a["fingerprint"] if a else None


def open_proposals(conn) -> list[dict]:
    """Every logged proposal that has no settled mark yet, taken or not (US-09)."""
    rows = conn.execute("""SELECT * FROM alert WHERE kind = 'proposal' AND alert_id NOT IN
                           (SELECT alert_id FROM mark WHERE settled = 1) ORDER BY created_ts, id""")
    return [decode(r) for r in rows]


def marked_on(conn, alert_id: str, market_date: date) -> bool:
    return conn.execute("SELECT 1 FROM mark WHERE alert_id = ? AND market_date = ?",
                        (alert_id, market_date.isoformat())).fetchone() is not None


def marks_for(conn, alert_id: str) -> list[dict]:
    return [decode(r) for r in conn.execute("SELECT * FROM mark WHERE alert_id = ? ORDER BY market_date, id", (alert_id,))]


def rows(conn, sql: str, args=()) -> list[dict]:
    return [decode(r) for r in conn.execute(sql, args)]
