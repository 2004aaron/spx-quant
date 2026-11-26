"""Settings site: one Lambda behind an HTTP API serves the page, the profile API and the portfolio.

  GET  /                the page (page.html, with the pool's client id and a per-response nonce filled in)
  GET  /api/profile     the signed-in user's settings, or the defaults if none are saved yet
  PUT  /api/profile     validate and save
  GET  /api/portfolio   the signed-in user's positions and totals, read from their log copy in S3

The API routes sit behind a Cognito JWT authorizer, so the email always comes from the signed-in
token, never from the request, and only a verified email is accepted. Every user reads and writes
only the row and the log named by that email; there is no admin route. Validation is
spx_quant.profile.validate, the same check the command line runs.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from spx_quant import clock, digest, store
from spx_quant import profile as prof

NUMBERS = ("net_liq", "bp_cap_pct", "delta_theta_limit", "max_worst_case_pct")
SWITCHES = {"alerts": True, "monday_email": True, "friday_email": True}
BOOKS = ("paper", "taken")
FIELDS = {"net_liq", "margin_type", "bp_cap_pct", "delta_theta_limit", "max_worst_case_pct", "digest_book", *SWITCHES}
MAX_BODY = 2048
EMAIL = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9.\-]{1,190}\.[a-z]{2,24}$")
PAGE = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")
SECURITY = {"Strict-Transport-Security": "max-age=63072000; includeSubDomains", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()"}
_table = None


def table():
    global _table
    if _table is None:
        import boto3
        _table = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"])
    return _table


def reply(status: int, body, kind: str = "application/json", extra: dict | None = None) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": kind, **SECURITY, **(extra or {})},
            "body": body if kind.startswith("text/html") else json.dumps(body)}


def page() -> dict:
    nonce = secrets.token_urlsafe(16)
    region = os.environ["AWS_REGION"]
    csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src 'self' data:; "
           f"connect-src 'self' https://cognito-idp.{region}.amazonaws.com; form-action 'none'; "
           f"frame-ancestors 'none'; base-uri 'none'")
    html = PAGE.replace("__CLIENT_ID__", os.environ["CLIENT_ID"]).replace("__REGION__", region).replace("__NONCE__", nonce)
    return reply(200, html, "text/html; charset=utf-8", {"Content-Security-Policy": csp})


def plain(item: dict) -> dict:
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in item.items()}


def defaults(email: str) -> dict:
    return {"email": email, "saved": False, "net_liq": None, "margin_type": "reg_t", "bp_cap_pct": prof.DEFAULT_BP_CAP,
            "delta_theta_limit": None, "max_worst_case_pct": prof.DEFAULT_MAX_WORST_CASE, "digest_book": "paper", **SWITCHES}


def read(email: str) -> dict:
    item = table().get_item(Key={"email": email}).get("Item")
    return {**defaults(email), **plain(item), "saved": True} if item else defaults(email)


def check(email: str, body: dict) -> dict:
    """The saved item, or raises ProfileError with the message the page shows."""
    if not isinstance(body, dict):
        raise prof.ProfileError("expected a JSON object")
    unknown = set(body) - FIELDS
    if unknown:
        raise prof.ProfileError(f"unknown field: {sorted(unknown)[0]}")
    for f in NUMBERS:
        if isinstance(body.get(f), bool):
            raise prof.ProfileError(f"{f}: must be a number")
    dt = body.get("delta_theta_limit")
    p = prof.validate(body.get("net_liq"), body.get("margin_type"), body.get("bp_cap_pct", prof.DEFAULT_BP_CAP),
                      None if dt in (None, "") else dt, "email", email,
                      body.get("max_worst_case_pct", prof.DEFAULT_MAX_WORST_CASE))
    if not p.net_liq <= 1e10 or not p.delta_theta_limit <= 1000:
        raise prof.ProfileError("a value is out of range")
    book = body.get("digest_book", "paper")
    if book not in BOOKS:
        raise prof.ProfileError(f"digest_book: must be one of {BOOKS}")
    out = {"email": email, **{f: Decimal(str(getattr(p, f))) for f in NUMBERS}, "margin_type": p.margin_type, "digest_book": book,
           "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for k, default in SWITCHES.items():
        v = body.get(k, default)
        if not isinstance(v, bool):
            raise prof.ProfileError(f"{k}: must be true or false")
        out[k] = v
    return out


def log(email: str, tmp: str):
    """The user's log copy as an open SQLite connection, or None when the runner has not copied one yet."""
    import boto3
    import logdoc
    from botocore.exceptions import ClientError
    src, db = Path(tmp) / "log.sql", Path(tmp) / "log.db"
    try:
        boto3.client("s3").download_file(os.environ["LOG_BUCKET"], f"logs/{email}.sql", str(src))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "403", "AccessDenied"):
            return None
        raise
    logdoc.load(str(src), str(db))
    return store.connect(db)


def position(p: digest.Position) -> dict:
    return {"id": p.alert["alert_id"], "name": p.name, "strikes": p.strikes, "lots": p.lots, "entered": p.entered,
            "expires": p.expires, "dte": p.dte, "credit": p.credit, "pnl": p.pnl, "pct": p.pct, "marked": p.marked,
            "worst": p.worst, "bp": p.bp, "away": p.away, "at_target": p.at_target, "closed": p.closed, "how": p.how}


def portfolio(email: str, book: str, saved: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            conn = log(email, tmp)
        except SystemExit:
            return {"book": book, "ready": False, "note": "Your log copy is being replaced. Try again after the next scan."}
        if conn is None:
            return {"book": book, "ready": False, "note": "No log yet. It appears after your first scan."}
        try:
            asof = clock.market_date(clock.now_utc())
            pos = digest.book(conn, asof, book)
            last = conn.execute("SELECT MAX(market_date) FROM mark").fetchone()[0]
        finally:
            conn.close()
    open_, closed = [p for p in pos if not p.closed], [p for p in pos if p.closed]
    done = [p.pnl for p in closed if p.pnl is not None]
    net_liq = saved.get("net_liq")
    bp = round(sum(p.bp for p in open_), 2)
    return {"book": book, "ready": True, "asof": asof.isoformat(), "marked": last,
            "totals": {"open": len(open_), "closed": len(closed), "credit_open": round(sum(p.credit for p in open_), 2),
                       "pnl_open": round(sum(p.pnl or 0 for p in open_), 2), "pnl_closed": round(sum(done), 2),
                       "wins": sum(v > 0 for v in done), "bp_used": bp, "net_liq": net_liq,
                       "bp_pct": round(bp / net_liq, 4) if net_liq else None,
                       "worst_open": round(sum(p.worst or 0 for p in open_), 2)},
            "open": [position(p) for p in sorted(open_, key=lambda p: p.expires)],
            "closed": [position(p) for p in sorted(closed, key=lambda p: p.closed, reverse=True)]}


def handler(event, context):
    route = event.get("routeKey", "")
    if route == "GET /":
        return page()
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    email = str(claims.get("email") or "").lower()
    if not EMAIL.match(email) or str(claims.get("email_verified")).lower() != "true" or claims.get("token_use") not in (None, "id"):
        return reply(401, {"error": "sign in first"})
    if route == "GET /api/profile":
        return reply(200, read(email))
    if route == "GET /api/portfolio":
        book = (event.get("queryStringParameters") or {}).get("book", "paper")
        if book not in BOOKS:
            return reply(400, {"error": f"book must be one of {BOOKS}"})
        return reply(200, portfolio(email, book, read(email)))
    if route == "PUT /api/profile":
        raw = event.get("body") or "{}"
        if len(raw) > MAX_BODY:
            return reply(413, {"error": "request too large"})
        try:
            item = check(email, json.loads(raw))
        except (ValueError, prof.ProfileError) as e:
            return reply(400, {"error": str(e)})
        table().put_item(Item=item)
        return reply(200, {**plain(item), "saved": True})
    return reply(404, {"error": "not found"})
