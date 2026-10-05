"""Margin check: compare the engine's buying power with one broker trade ticket.

The engine's portfolio-margin number is a model of the broker's rules. Entering the
proposed order in the broker's ticket (without sending it) shows the broker's real
buying-power effect. The ratio broker / engine becomes margin.pm_house_multiplier,
so later proposals are sized on the broker's number instead of the model's.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

VALUE = re.compile(r"^(pm_house_multiplier\s*=\s*)([0-9.]+)(.*)$", re.M)
PROV = re.compile(r'^"margin\.pm_house_multiplier"\s*=\s*\{.*\}\s*$', re.M)


def latest_proposal(conn) -> dict | None:
    from .store import decode
    return decode(conn.execute(
        "SELECT * FROM alert WHERE kind = 'proposal' ORDER BY created_ts DESC, id DESC LIMIT 1").fetchone())


def engine_bp(alert: dict, params) -> float:
    """The alert's total buying power with the house multiplier taken back out."""
    total = float(alert["bp_total"])
    if alert["profile"]["margin_type"] == "portfolio":
        total /= float(params.margin["pm_house_multiplier"])
    return total


def ticket(alert: dict) -> list[str]:
    n = int(alert["contracts"])
    lines = []
    for leg in alert["legs"]:
        side = "SELL" if leg["qty"] < 0 else "BUY"
        right = "put" if leg["right"] == "P" else "call"
        lines.append(f"  {side} {abs(leg['qty']) * n} {leg['sym']}  ({right} {leg['strike']:g}, exp {leg['exp']})")
    lines.append(f"  Limit: ${alert['credit_per_lot'] / 100:.2f} credit (any price works; buying power does not depend on it)")
    return lines


def report(alert: dict, params, broker_bp: float | None) -> tuple[str, float | None]:
    margin_type = alert["profile"]["margin_type"]
    raw = engine_bp(alert, params)
    head = [f"Proposal {alert['alert_id']} ({alert['strategy'].replace('_', ' ')}, {alert['contracts']} lot(s), {margin_type} margin)",
            "Enter this order in the broker's trade ticket. Do not send it.", *ticket(alert),
            f"Engine buying power: ${raw:,.2f}" + (" (multiplier 1.00)" if margin_type == "portfolio" else "")]
    if broker_bp is None:
        head.append("Then run again with --broker-bp <the buying-power effect the ticket shows>.")
        return "\n".join(head), None
    if broker_bp <= 0:
        raise ValueError(f"--broker-bp must be positive, got {broker_bp:g}")
    ratio = broker_bp / raw
    head.append(f"Broker buying power: ${broker_bp:,.2f}  ({ratio:.2f}x the engine)")
    if margin_type != "portfolio":
        head.append("Reg-T has no house multiplier. A gap here means the Reg-T formula does not match the broker; "
                    "note it in docs/operations.md.")
        return "\n".join(head), None
    head.append(f"Set margin.pm_house_multiplier = {ratio:.3f}" + ("" if ratio >= 1 else
                "  (below 1: the broker asks for less than the model, so sizing gets less conservative)"))
    return "\n".join(head), round(ratio, 3)


def apply(path: Path, ratio: float, alert: dict, broker_bp: float, raw: float, today: date) -> None:
    text = Path(path).read_text()
    if not VALUE.search(text) or not PROV.search(text):
        raise ValueError(f"{path}: pm_house_multiplier or its provenance line not found")
    text = VALUE.sub(lambda m: f"{m.group(1)}{ratio}{m.group(3)}", text, count=1)
    src = (f"one tastytrade ticket check {today.isoformat()}: broker ${broker_bp:,.2f} vs engine ${raw:,.2f} "
           f"on {alert['alert_id']} ({alert['strategy'].replace('_', ' ')}); rerun margin-check on other structures")
    text = PROV.sub(lambda m: f'"margin.pm_house_multiplier" = {{ tag = "unvalidated: partially supported", source = "{src}" }}',
                    text, count=1)
    Path(path).write_text(text)
