"""Alert delivery (US-07): email over SMTP/TLS or a Discord webhook, with retry and dedupe.

Credentials come from environment variables, never files (proposal 4.5):
  email   SPX_QUANT_SMTP_HOST, SPX_QUANT_SMTP_PORT (587 STARTTLS or 465 SSL),
          SPX_QUANT_SMTP_USER, SPX_QUANT_SMTP_PASSWORD, SPX_QUANT_SMTP_FROM (defaults to USER)
  discord SPX_QUANT_DISCORD_WEBHOOK
The recipient address lives in the account profile. Every attempt is one delivery
row; a final failure is also an event, so the report can list it (US-07-AC3, US-12).
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import time
import urllib.request
from datetime import datetime
from email.message import EmailMessage

from . import clock, store
from .profile import Profile

DISCORD_LIMIT = 1700  # Discord caps a message at 2,000 characters; leaves room for subject and fences


class ChannelError(RuntimeError):
    pass


class EmailChannel:
    name = "email"

    def __init__(self, to: str, env=os.environ):
        self.to = to
        try:
            self.host = env["SPX_QUANT_SMTP_HOST"]
            self.user = env["SPX_QUANT_SMTP_USER"]
            self.password = env["SPX_QUANT_SMTP_PASSWORD"]
        except KeyError as e:
            raise ChannelError(f"environment variable {e.args[0]} is not set") from None
        self.port = int(env.get("SPX_QUANT_SMTP_PORT", "587"))
        self.sender = env.get("SPX_QUANT_SMTP_FROM", self.user)

    def send(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.sender, self.to
        msg.set_content(body)
        ctx = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=30) as s:
                s.login(self.user, self.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(self.user, self.password)
                s.send_message(msg)


class DiscordChannel:
    name = "discord"

    def __init__(self, env=os.environ):
        try:
            self.url = env["SPX_QUANT_DISCORD_WEBHOOK"]
        except KeyError:
            raise ChannelError("environment variable SPX_QUANT_DISCORD_WEBHOOK is not set") from None

    @staticmethod
    def chunks(subject: str, body: str) -> list[str]:
        parts, cur = [], ""
        for line in body.splitlines():
            if len(cur) + len(line) + 1 > DISCORD_LIMIT:
                parts.append(cur)
                cur = ""
            cur += line + "\n"
        parts.append(cur)
        return [(f"**{subject}**\n" if i == 0 else "") + f"```\n{p}```" for i, p in enumerate(parts)]

    def send(self, subject: str, body: str) -> None:
        for content in self.chunks(subject, body):
            req = urllib.request.Request(self.url + ("&" if "?" in self.url else "?") + "wait=true",
                                         data=json.dumps({"content": content}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "spx-quant/0.4"})
            with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
                if r.status >= 300:
                    raise ChannelError(f"discord returned HTTP {r.status}")


def channel_for(profile: Profile, env=os.environ):
    if profile.notify_channel == "email":
        return EmailChannel(profile.email_to, env)
    if profile.notify_channel == "discord":
        return DiscordChannel(env)
    return None


def deliver(conn, alert: dict, finished_ts: datetime, profile: Profile, params, channel=None,
            now=clock.now_utc, sleep=time.sleep) -> str:
    """Send one logged alert. Returns the final delivery status."""
    n = params.notify
    aid, subject, body = alert["alert_id"], alert["subject"], alert["text"]
    try:
        channel = channel or channel_for(profile)
    except ChannelError as e:
        store.insert(conn, "delivery", alert_id=aid, channel=profile.notify_channel, attempt=0, status="failed", error=str(e))
        store.event(conn, now(), "delivery_failed", f"{profile.notify_channel}: {e}", aid)
        return "failed"
    if channel is None:
        store.insert(conn, "delivery", alert_id=aid, channel="none", attempt=0, status="no_channel", error=None)
        return "no_channel"

    if n.get("repeat_policy", "brief") == "suppress" and store.last_delivered_fingerprint(conn) == alert["fingerprint"]:
        store.insert(conn, "delivery", alert_id=aid, channel=channel.name, attempt=0, status="suppressed_repeat", error=None)
        return "suppressed_repeat"

    attempts = int(n.get("max_attempts", 3))
    last_err = ""
    for i in range(1, attempts + 1):
        sent = now()
        try:
            channel.send(subject, body)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            store.insert(conn, "delivery", alert_id=aid, channel=channel.name, attempt=i, sent_ts=sent, status="failed", error=last_err)
            if i < attempts:
                sleep(float(n.get("retry_wait_seconds", 5)) * i)
            continue
        done = now()
        store.insert(conn, "delivery", alert_id=aid, channel=channel.name, attempt=i, sent_ts=sent, delivered_ts=done,
                     status="delivered", error=None)
        late = (done - finished_ts).total_seconds() / 60
        if late > float(n.get("latency_target_minutes", 20)):
            store.event(conn, done, "delivery_late", f"{late:.1f} min after scan completion", aid)
        return "delivered"
    store.event(conn, now(), "delivery_failed", f"{channel.name}: {attempts} attempts; last error {last_err}", aid)
    return "failed"
