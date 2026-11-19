"""Activities of the digest and proposal workflows: who gets an email, then build and send one.

An activity is the part of a workflow that touches the outside world. These read the settings
table, the plain log copy the scan runner leaves in the private bucket (logs/<email>.sql) and
the mail account, so Temporal retries them when AWS or Gmail has a bad minute.

Each email is built by spx_quant.digest, the same code as `python -m spx_quant digest`, from the
user's log loaded into a temporary SQLite file. Nothing is written back to the log: the runner
owns it, and the workflows already keep a date or a position from sending twice.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

import logdoc
from spx_quant import digest, notify, store

_smtp: dict | None = None


def smtp_creds() -> dict:
    global _smtp
    if _smtp is None:
        import boto3
        prefix = os.environ.get("SMTP_PARAM", "/stormglass/smtp")
        got = boto3.client("ssm").get_parameters(Names=[f"{prefix}/user", f"{prefix}/password"], WithDecryption=True)
        _smtp = {p["Name"].rsplit("/", 1)[1]: p["Value"] for p in got["Parameters"]}
    return _smtp


def channel(to: str):
    c = smtp_creds()
    return notify.EmailChannel(to, {"SPX_QUANT_SMTP_HOST": "smtp.gmail.com", "SPX_QUANT_SMTP_USER": c["user"],
                                    "SPX_QUANT_SMTP_PASSWORD": c["password"]})


def rows() -> list[dict]:
    """Every row of the settings table."""
    import boto3
    table, out, page = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"]), [], {}
    while True:
        got = table.scan(ConsistentRead=True, **page)
        out += got["Items"]
        if "LastEvaluatedKey" not in got:
            return out
        page = {"ExclusiveStartKey": got["LastEvaluatedKey"]}


def open_log(email: str, tmp: str):
    """The user's log copy as an open SQLite connection, or None when the runner has not copied one yet."""
    import boto3
    from botocore.exceptions import ClientError
    src, db = Path(tmp) / "log.sql", Path(tmp) / "log.db"
    try:
        boto3.client("s3").download_file(os.environ["LOG_BUCKET"], f"logs/{email}.sql", str(src))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise
    try:
        logdoc.load(str(src), str(db))
    except SystemExit as e:   # checksum mismatch; the runner's next copy replaces it
        raise ApplicationError(str(e).replace(str(src), f"logs/{email}.sql")) from None
    return store.connect(db)


@activity.defn
def list_users(kind: str) -> list[dict]:
    """Every saved user with the switch for this email on, and the book they chose."""
    return sorted(({"email": i["email"], "book": i.get("digest_book", "paper")} for i in rows() if i.get(f"{kind}_email", True)),
                  key=lambda u: u["email"])


@activity.defn
def send_digest(kind: str, day: str, email: str, book: str) -> str:
    """sent, or no_log when the runner has not copied a log for this user yet."""
    if kind not in digest.KINDS or book not in digest.BOOKS:
        raise ApplicationError(f"no {kind} digest for the {book} book in this build", non_retryable=True)
    with tempfile.TemporaryDirectory() as tmp:
        conn = open_log(email, tmp)
        if conn is None:
            return "no_log"
        message = digest.build(kind, conn, date.fromisoformat(day), book)
        conn.close()
    channel(email).send(*message)
    return "sent"


@activity.defn
def send_target(email: str, alert_id: str, day: str) -> str:
    """The target-reached notice for one taken position: sent, alerts_off (the site's alerts switch) or no_log.
    The runner signals a mark after it copies the log, so a copy that does not show the position at
    target on `day` is an old one: an error, and Temporal tries again a little later."""
    if not next((u.get("alerts", True) for u in rows() if u["email"] == email), True):
        return "alerts_off"
    with tempfile.TemporaryDirectory() as tmp:
        conn = open_log(email, tmp)
        if conn is None:
            return "no_log"
        message = digest.target(conn, alert_id, date.fromisoformat(day))
        conn.close()
    if message is None:
        raise ApplicationError(f"logs/{email}.sql does not show {alert_id} held at the profit target on {day}")
    channel(email).send(*message)
    return "sent"
