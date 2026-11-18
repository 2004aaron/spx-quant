"""Activities of the digest workflow: who gets the email, then build and send one.

An activity is the part of a workflow that touches the outside world. These read the settings
table, the plain log copy the scan runner leaves in the private bucket (logs/<email>.sql) and
the mail account, so Temporal retries them when AWS or Gmail has a bad minute.

The email itself is spx_quant.digest, the same code as `python -m spx_quant digest`, built from
the user's log loaded into a temporary SQLite file. Nothing is written back to the log: the
runner owns it, and the workflow id already keeps a date from sending twice.
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


@activity.defn
def list_users(kind: str) -> list[dict]:
    """Every saved user with the switch for this email on, and the book they chose."""
    import boto3
    table, out, page = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"]), [], {}
    while True:
        got = table.scan(ConsistentRead=True, **page)
        out += [{"email": i["email"], "book": i.get("digest_book", "paper")} for i in got["Items"] if i.get(f"{kind}_email", True)]
        if "LastEvaluatedKey" not in got:
            return sorted(out, key=lambda u: u["email"])
        page = {"ExclusiveStartKey": got["LastEvaluatedKey"]}


@activity.defn
def send_digest(kind: str, day: str, email: str, book: str) -> str:
    """sent, or no_log when the runner has not copied a log for this user yet."""
    import boto3
    from botocore.exceptions import ClientError
    if kind not in digest.KINDS or book not in digest.BOOKS:
        raise ApplicationError(f"no {kind} digest for the {book} book in this build", non_retryable=True)
    with tempfile.TemporaryDirectory() as tmp:
        src, db = Path(tmp) / "log.sql", Path(tmp) / "log.db"
        try:
            boto3.client("s3").download_file(os.environ["LOG_BUCKET"], f"logs/{email}.sql", str(src))
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return "no_log"
            raise
        try:
            logdoc.load(str(src), str(db))
        except SystemExit as e:   # checksum mismatch; the runner's next copy replaces it
            raise ApplicationError(str(e).replace(str(src), f"logs/{email}.sql")) from None
        conn = store.connect(db)
        message = digest.build(kind, conn, date.fromisoformat(day), book)
        conn.close()
    channel(email).send(*message)
    return "sent"
