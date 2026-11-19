"""Tell Temporal what one user's log says about each proposal (issue #63, item 9).

    python deploy/cloud/lifecycle.py DB USER             (run from the repo root; prints what it did)
    python deploy/cloud/lifecycle.py DB USER --show      (print the plan, connect to nothing)

The scan runner calls this at the end of a run, after the log copy is in the bucket. For every
proposal still in play it makes sure the run `proposal-<USER>-<alert id>` of ProposalWorkflow
(cloud/worker/workflows.py) exists, then sends it the decisions and marks it has not seen yet as
signals, oldest first. A signal is a message to a running workflow. Each one carries its log
row id, and the workflow publishes the last ids it handled, so nothing here keeps state: a run
that was cut short is finished by the next one, and sending a row twice counts once.

In play: a proposal (a NO CHANGE repeat only if it got a reply) that has not settled, or was
settled, declined or closed within the last RECENT days, so a missed run can still deliver the
final row. USER is the email the alerts go to, or `auto` for the autonomous account.

The connection comes from the environment, the way the Temporal command line tool reads it:
TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_API_KEY. Exit 1 when any proposal could not be
synced; the runner prints that and carries on.
"""
from __future__ import annotations

import asyncio
import heapq
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spx_quant import clock, decisions, store  # noqa: E402

QUEUE = "stormglass"
RECENT = 3
OVER = ("declined", "closed")


def plan(conn, today: date) -> list[dict]:
    """One entry per proposal in play: its start arguments and every signal in time order."""
    cutoff, out = (today - timedelta(days=RECENT)).isoformat(), []
    for a in store.rows(conn, """SELECT * FROM alert WHERE kind = 'proposal'
                                 AND (repeat_of IS NULL OR alert_id IN (SELECT alert_id FROM feedback))
                                 AND alert_id NOT IN (SELECT alert_id FROM mark WHERE settled = 1 AND market_date < ?)
                                 ORDER BY id""", (cutoff,)):
        said = sorted(decisions.history(conn, a["alert_id"]), key=lambda d: d["id"])
        if said and said[-1]["decision"] in OVER and said[-1]["received_ts"][:10] < cutoff:
            continue
        ds = [(d["received_ts"], "decision", {"id": d["id"], "decision": d["decision"], "contracts": d["contracts"]}) for d in said]
        ms = [(m["ts"] or m["market_date"], "marked", {"id": m["id"], "date": m["market_date"], "pnl": m["pnl"], "exit": bool(m["exit_signal"]),
                                   "settled": bool(m["settled"])}) for m in sorted(store.marks_for(conn, a["alert_id"]), key=lambda m: m["id"])]
        out.append({"alert_id": a["alert_id"], "expires": a["legs"][0]["exp"], "contracts": a["contracts"],
                    "signals": [e[1:] for e in heapq.merge(ds, ms, key=lambda e: e[0])]})
    return out


async def sync(client, conn, user: str, today: date) -> dict:
    """Start what is missing and send what is new. Counts of started, signals, finished and failed."""
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.service import RPCError, RPCStatusCode
    n = {"started": 0, "signals": 0, "finished": 0, "failed": 0}
    for p in plan(conn, today):
        h = client.get_workflow_handle(f"proposal-{user}-{p['alert_id']}")
        try:
            try:
                d = await h.describe()
                if d.status != WorkflowExecutionStatus.RUNNING:
                    n["finished"] += 1
                    continue
                seen = await d.memo()
            except RPCError as e:
                if e.status != RPCStatusCode.NOT_FOUND:
                    raise
                h = await client.start_workflow("ProposalWorkflow", args=[user, p["alert_id"], p["expires"], p["contracts"]],
                                                id=h.id, task_queue=QUEUE)
                seen, n["started"] = {}, n["started"] + 1
            for name, row in p["signals"]:
                if row["id"] > seen.get("mark" if name == "marked" else name, 0):
                    await h.signal(name, row)
                    n["signals"] += 1
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:   # the run ended between two signals; the rest no longer matter
                n["finished"] += 1
            else:
                n["failed"] += 1
                print(f"{h.id}: {e.status.name} {e.message}")
    return n


async def main(db: str, user: str) -> dict:
    from temporalio.client import Client
    from temporalio.envconfig import ClientConfigProfile
    client = await Client.connect(**ClientConfigProfile.load().to_client_connect_config())
    conn = store.connect(db)
    return await sync(client, conn, user, clock.market_date(clock.now_utc()))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--show"]
    if len(args) != 2:
        raise SystemExit(__doc__)
    if len(args) < len(sys.argv) - 1:
        todo = plan(store.connect(args[0]), clock.market_date(clock.now_utc()))
        print("\n".join(f"proposal-{args[1]}-{p['alert_id']}: expires {p['expires']}, {len(p['signals'])} rows" for p in todo)
              or "no proposals in play")
    else:
        try:
            done = asyncio.run(main(*args))
        except Exception as e:   # no connection, a bad key: one line for the runner's output, not a traceback
            raise SystemExit(f"lifecycle: {type(e).__name__}: {e}") from None
        print("lifecycle: " + ", ".join(f"{v} {k}" for k, v in done.items()))
        sys.exit(1 if done["failed"] else 0)
