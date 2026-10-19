"""Carry the SQLite log between ephemeral cloud runs as a text document.

    python deploy/cloud/logdoc.py dump quant.db quant-log.sql
    python deploy/cloud/logdoc.py load quant-log.sql quant.db

The dump ends with a sha256 line over everything above it. load refuses a copy whose
checksum does not match, so a damaged copy can never overwrite the log.
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

TABLES = ("scan", "alert", "delivery", "mark", "feedback", "event")


def dump(db: str, out: str) -> str:
    body = "\n".join(sqlite3.connect(db).iterdump()) + "\n"
    Path(out).write_text(body + f"-- sha256 {hashlib.sha256(body.encode()).hexdigest()}\n", encoding="utf-8")
    return counts(db)


def load(src: str, db: str) -> str:
    text = Path(src).read_text(encoding="utf-8").rstrip("\n")
    body, _, last = text.rpartition("\n")
    body += "\n"
    if not last.startswith("-- sha256 ") or hashlib.sha256(body.encode()).hexdigest() != last.split()[-1]:
        raise SystemExit(f"{src}: checksum mismatch, the copy is damaged; nothing loaded")
    if Path(db).exists():
        raise SystemExit(f"{db} already exists; load into a fresh path")
    conn = sqlite3.connect(db)
    conn.executescript(body)
    conn.commit()
    return counts(db)


def counts(db: str) -> str:
    conn = sqlite3.connect(db)
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return "  ".join(f"{t}={conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}" for t in TABLES if t in have)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("dump", "load"):
        raise SystemExit(__doc__)
    print((dump if sys.argv[1] == "dump" else load)(sys.argv[2], sys.argv[3]))
