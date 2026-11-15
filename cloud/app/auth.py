"""Email one-time-code sign-in: the three Cognito custom-auth triggers in one handler.

Cognito calls this function at each step of a CUSTOM_AUTH sign-in. Define decides what comes
next, Create makes a 6-digit code and emails it, Verify checks the answer. The code travels in
Cognito's private challenge parameters, so nothing is stored here. Only invited users exist in
the pool (admin-created), and an unknown email fails the same way a wrong code does.

Mail goes over the same Gmail SMTP account the alerts use; its user and app password are SSM
SecureString parameters under SMTP_PARAM (default /stormglass/smtp).
"""
from __future__ import annotations

import hmac
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage

MAX_TRIES = 3
_smtp: dict | None = None


def smtp_creds() -> dict:
    global _smtp
    if _smtp is None:
        import boto3
        prefix = os.environ.get("SMTP_PARAM", "/stormglass/smtp")
        got = boto3.client("ssm").get_parameters(Names=[f"{prefix}/user", f"{prefix}/password"], WithDecryption=True)
        _smtp = {p["Name"].rsplit("/", 1)[1]: p["Value"] for p in got["Parameters"]}
    return _smtp


def send_code(to: str, code: str) -> None:
    c = smtp_creds()
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = f"StormGlass sign-in code: {code}", c["user"], to
    msg.set_content(f"Your StormGlass sign-in code is {code}.\n\nIt works for 10 minutes. "
                    "If you didn't try to sign in, ignore this email.")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(c["user"], c["password"])
        s.send_message(msg)


def define(event: dict) -> dict:
    req, res = event["request"], event["response"]
    session = req.get("session") or []
    res.update(issueTokens=False, failAuthentication=False)
    if req.get("userNotFound"):
        res["failAuthentication"] = True
    elif session and session[-1].get("challengeName") == "CUSTOM_CHALLENGE" and session[-1].get("challengeResult"):
        res["issueTokens"] = True
    elif len(session) >= MAX_TRIES:
        res["failAuthentication"] = True
    else:
        res["challengeName"] = "CUSTOM_CHALLENGE"
    return event


def create(event: dict, send=send_code) -> dict:
    req, res = event["request"], event["response"]
    prior = [s.get("challengeMetadata", "") for s in req.get("session") or [] if s.get("challengeName") == "CUSTOM_CHALLENGE"]
    code = prior[-1][5:] if prior and prior[-1].startswith("CODE-") else f"{secrets.randbelow(10**6):06d}"
    if not prior:
        send(req["userAttributes"]["email"], code)
    res.update(publicChallengeParameters={"delivery": "email"}, privateChallengeParameters={"code": code},
               challengeMetadata=f"CODE-{code}")
    return event


def verify(event: dict) -> dict:
    req = event["request"]
    answer = str(req.get("challengeAnswer", "")).strip()
    event["response"]["answerCorrect"] = hmac.compare_digest(answer, req["privateChallengeParameters"].get("code", ""))
    return event


STEPS = {"DefineAuthChallenge_Authentication": define, "CreateAuthChallenge_Authentication": create,
         "VerifyAuthChallengeResponse_Authentication": verify}


def handler(event, context):
    return STEPS[event["triggerSource"]](event)
