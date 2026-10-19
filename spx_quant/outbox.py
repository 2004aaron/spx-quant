"""Gmail route for alerts (US-07): the engine queues, the scheduled task sends.

The cloud tasks have no SMTP password or webhook, but they do have a Gmail connector.
So a scan with notify channel "gmail" logs a 'queued' delivery row; the task reads
`outbox`, sends each message through Gmail, and reports back with `delivered`, which
appends a 'delivered' row (B-KR1 measures it against the scan's finish time) or a
'failed' row. After max_attempts failures the alert is dropped from the outbox and a
delivery_failed event goes into the weekly report (US-07-AC3, US-12).
"""
from __future__ import annotations

from datetime import datetime

from . import clock, store


class OutboxError(ValueError):
    pass


def _attempts(conn, alert_id: str) -> tuple[list[dict], int, bool]:
    rows = store.rows(conn, "SELECT * FROM delivery WHERE alert_id = ? ORDER BY id", (alert_id,))
    failed = sum(r["status"] == "failed" and r["channel"] == "gmail" for r in rows)
    done = any(r["status"] == "delivered" for r in rows)
    return rows, failed, done


def pending(conn, params) -> list[dict]:
    """Queued Gmail messages that are neither delivered nor out of attempts, oldest first."""
    limit = int(params.notify.get("max_attempts", 3))
    out = []
    for r in store.rows(conn, """SELECT DISTINCT alert_id FROM delivery WHERE status = 'queued' AND channel = 'gmail'
                                 ORDER BY id"""):
        _, failed, done = _attempts(conn, r["alert_id"])
        if done or failed >= limit:
            continue
        a = store.get_alert(conn, r["alert_id"])
        out.append({"alert_id": a["alert_id"], "to": (a["profile"] or {}).get("email_to", ""),
                    "subject": a["subject"], "body": a["text"], "attempts_so_far": failed})
    return out


def record(conn, params, alert_id: str, now: datetime, ref: str | None = None, error: str | None = None) -> str:
    """Append the outcome of one Gmail send. Returns 'delivered', 'failed' or 'gave_up'."""
    if store.get_alert(conn, alert_id) is None:
        raise OutboxError(f"no logged alert with id {alert_id!r}")
    rows, failed, done = _attempts(conn, alert_id)
    if not any(r["status"] == "queued" for r in rows):
        raise OutboxError(f"alert {alert_id} was not queued for Gmail")
    if done:
        raise OutboxError(f"alert {alert_id} is already recorded as delivered")
    n = params.notify
    limit = int(n.get("max_attempts", 3))
    if error:
        store.insert(conn, "delivery", alert_id=alert_id, channel="gmail", attempt=failed + 1, sent_ts=now,
                     status="failed", error=error)
        if failed + 1 >= limit:
            store.event(conn, now, "delivery_failed", f"gmail: {limit} attempts; last error {error}", alert_id)
            return "gave_up"
        return "failed"
    store.insert(conn, "delivery", alert_id=alert_id, channel="gmail", attempt=failed + 1, sent_ts=now,
                 delivered_ts=now, status="delivered", error=None, ref=ref)
    scan = store.rows(conn, "SELECT finished_ts FROM scan WHERE alert_id = ? ORDER BY id DESC LIMIT 1", (alert_id,))
    if scan and scan[0]["finished_ts"]:
        late = (now - clock.parse_utc(scan[0]["finished_ts"])).total_seconds() / 60
        if late > float(n.get("latency_target_minutes", 20)):
            store.event(conn, now, "delivery_late", f"{late:.1f} min after scan completion", alert_id)
    return "delivered"
