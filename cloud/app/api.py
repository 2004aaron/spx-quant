"""Settings site: one Lambda behind an HTTP API serves the page and the profile API.

  GET  /              the settings page (page.html, with the pool's client id filled in)
  GET  /api/profile   the signed-in user's settings, or the defaults if none are saved yet
  PUT  /api/profile   validate and save

The API routes sit behind a Cognito JWT authorizer, so the email always comes from the
signed-in token, never from the request. Validation is spx_quant.profile.validate, the
same check the command line runs, so both accept and reject exactly the same values.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from spx_quant import profile as prof

NUMBERS = ("net_liq", "bp_cap_pct", "delta_theta_limit", "max_worst_case_pct")
SWITCHES = {"alerts": True, "monday_email": True, "friday_email": True}
BOOKS = ("paper", "taken")
PAGE = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")
_table = None


def table():
    global _table
    if _table is None:
        import boto3
        _table = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"])
    return _table


def reply(status: int, body, kind: str = "application/json") -> dict:
    return {"statusCode": status, "headers": {"Content-Type": kind, "Cache-Control": "no-store"},
            "body": body if kind.startswith("text/html") else json.dumps(body)}


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
    dt = body.get("delta_theta_limit")
    p = prof.validate(body.get("net_liq"), body.get("margin_type"), body.get("bp_cap_pct", prof.DEFAULT_BP_CAP),
                      None if dt in (None, "") else dt, "email", email,
                      body.get("max_worst_case_pct", prof.DEFAULT_MAX_WORST_CASE))
    book = body.get("digest_book", "paper")
    if book not in BOOKS:
        raise prof.ProfileError(f"digest_book: {book!r} must be one of {BOOKS}")
    out = {"email": email, **{f: Decimal(str(getattr(p, f))) for f in NUMBERS}, "margin_type": p.margin_type, "digest_book": book,
           "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for k, default in SWITCHES.items():
        v = body.get(k, default)
        if not isinstance(v, bool):
            raise prof.ProfileError(f"{k}: must be true or false")
        out[k] = v
    return out


def handler(event, context):
    route = event.get("routeKey", "")
    if route == "GET /":
        return reply(200, PAGE.replace("__CLIENT_ID__", os.environ["CLIENT_ID"]).replace("__REGION__", os.environ["AWS_REGION"]),
                     "text/html; charset=utf-8")
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    email = (claims.get("email") or "").lower()
    if not email:
        return reply(401, {"error": "sign in first"})
    if route == "GET /api/profile":
        return reply(200, read(email))
    if route == "PUT /api/profile":
        try:
            body = json.loads(event.get("body") or "{}")
            item = check(email, body)
        except (ValueError, prof.ProfileError) as e:
            return reply(400, {"error": str(e)})
        table().put_item(Item=item)
        return reply(200, {**plain(item), "saved": True})
    return reply(404, {"error": f"no route {route}"})
