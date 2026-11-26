"""Scheduled digest emails on AWS alone: EventBridge Scheduler starts this Lambda (no Temporal).

    event {"kind": "monday"}   (template.yaml sets the schedule and the time zone)

For every user on the settings site with that email switched on, it loads their log copy from the
private bucket (logs/<email>.sql), builds the digest with spx_quant.digest and sends it. A marker
at sent/<kind>/<date>/<email> keeps a retried or repeated start from sending twice.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import logdoc
from spx_quant import clock, digest, notify, store

_smtp: dict | None = None


def s3():
    import boto3
    return boto3.client("s3")


def smtp_channel(to: str):
    global _smtp
    if _smtp is None:
        import boto3
        prefix = os.environ.get("SMTP_PARAM", "/stormglass/smtp")
        got = boto3.client("ssm").get_parameters(Names=[f"{prefix}/user", f"{prefix}/password"], WithDecryption=True)
        _smtp = {p["Name"].rsplit("/", 1)[1]: p["Value"] for p in got["Parameters"]}
    return notify.EmailChannel(to, {"SPX_QUANT_SMTP_HOST": "smtp.gmail.com", "SPX_QUANT_SMTP_USER": _smtp["user"],
                                    "SPX_QUANT_SMTP_PASSWORD": _smtp["password"]})


def users(kind: str) -> list[dict]:
    import boto3
    table, out, page = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"]), [], {}
    while True:
        got = table.scan(ConsistentRead=True, **page)
        out += got["Items"]
        if "LastEvaluatedKey" not in got:
            break
        page = {"ExclusiveStartKey": got["LastEvaluatedKey"]}
    return sorted(({"email": i["email"], "book": i.get("digest_book", "paper")} for i in out if i.get(f"{kind}_email", True)),
                  key=lambda u: u["email"])


def exists(key: str) -> bool:
    from botocore.exceptions import ClientError
    try:
        s3().head_object(Bucket=os.environ["LOG_BUCKET"], Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def send_one(kind: str, day: str, email: str, book: str, channel=smtp_channel) -> str:
    marker = f"sent/{kind}/{day}/{email}"
    if exists(marker):
        return "already_sent"
    if not exists(f"logs/{email}.sql"):
        return "no_log"
    with tempfile.TemporaryDirectory() as tmp:
        src, db = Path(tmp) / "log.sql", Path(tmp) / "log.db"
        s3().download_file(os.environ["LOG_BUCKET"], f"logs/{email}.sql", str(src))
        logdoc.load(str(src), str(db))
        conn = store.connect(db)
        message = digest.build(kind, conn, date.fromisoformat(day), book)
        conn.close()
    channel(email).send(*message)
    s3().put_object(Bucket=os.environ["LOG_BUCKET"], Key=marker, Body=b"")
    return "sent"


def handler(event, context, channel=smtp_channel):
    kind = (event or {}).get("kind", "monday")
    if kind not in digest.KINDS:
        return {"kind": kind, "error": "not built by this engine version"}
    day = (event or {}).get("day") or clock.market_date(clock.now_utc()).isoformat()
    out = {"kind": kind, "date": day, "sent": 0, "already_sent": 0, "no_log": 0, "failed": []}
    for u in users(kind):
        try:
            out[send_one(kind, day, u["email"], u["book"], channel)] += 1
        except Exception as e:   # one user's failure never stops the others
            out["failed"].append(f"{u['email']}: {type(e).__name__}: {e}"[:300])
    print(out)
    if out["failed"]:
        raise RuntimeError(f"{len(out['failed'])} digest sends failed: {out['failed']}")
    return out
