"""Write a run's profile file from the settings site's saved row.

    python deploy/cloud/siteprofile.py EMAIL OUT.json [--no-email]      (run from the repo root)

The settings site (cloud/) keeps one DynamoDB row per signed-in email. The runner calls this
before a scan so the account settings come from the site instead of repo secrets. It reads the
row with the AWS command line tool, which GitHub's runners already have, so nothing is installed
at scan time. The row goes through spx_quant.profile.validate, the same check the page and
`profile set` run. Alerts go to EMAIL unless the row has alerts switched off or --no-email is
given. Any failure (no credentials, no row, a bad value) exits 1 and leaves OUT.json untouched,
and the runner then falls back to its secrets.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spx_quant import profile as prof  # noqa: E402

TABLE = os.environ.get("USERS_TABLE", "stormglass-users")


def aws(*args: str) -> str:
    r = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError((r.stderr.strip().splitlines() or [f"aws exited with {r.returncode}"])[-1])
    return r.stdout


def plain(item: dict) -> dict:
    """DynamoDB's typed JSON ({"N": "150000"}, {"BOOL": true}, {"S": "reg_t"}) as plain values."""
    kinds = {"N": float, "S": str, "BOOL": bool, "NULL": lambda _: None}
    return {k: kinds[t](v) for k, typed in item.items() for t, v in typed.items() if t in kinds}


def fetch(email: str, run=aws) -> dict | None:
    out = run("dynamodb", "get-item", "--table-name", TABLE, "--consistent-read",
              "--key", json.dumps({"email": {"S": email.strip().lower()}}))
    item = json.loads(out or "{}").get("Item")
    return plain(item) if item else None


def build(row: dict, email: str, send: bool = True) -> prof.Profile:
    on = send and row.get("alerts", True)
    return prof.validate(row.get("net_liq"), row.get("margin_type"), row.get("bp_cap_pct", prof.DEFAULT_BP_CAP),
                         row.get("delta_theta_limit"), "email" if on else "none", email if on else "",
                         row.get("max_worst_case_pct", prof.DEFAULT_MAX_WORST_CASE))


def main(argv: list[str], run=aws) -> int:
    args = [a for a in argv if a != "--no-email"]
    if len(args) != 2:
        print(__doc__)
        return 2
    email, out = args
    try:
        row = fetch(email, run)
        if row is None:
            print("settings site: no saved settings for this email; using the runner's secrets")
            return 1
        p = build(row, email, send=len(args) == len(argv))
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
        print(f"settings site: {e}; using the runner's secrets")
        return 1
    prof.save(p, Path(out))
    print(f"settings site: using the profile saved {row.get('updated_at', '?')}, alerts {'on' if p.notify_channel == 'email' else 'off'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
