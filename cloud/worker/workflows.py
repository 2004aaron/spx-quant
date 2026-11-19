"""The digest emails and the life of one proposal as Temporal workflows (issue #63, items 8 and 9).

Temporal is a service that runs a function, called a workflow, so that every step is recorded
and a crash or a timeout resumes from the last finished step. Work that touches the outside
world (AWS, the mail server) sits in activities, which Temporal retries on failure.

A Temporal Schedule starts DigestWorkflow with only the kind ("monday" or "friday"). That run
works out the market date and hands over to a child run whose id is digest-<kind>-<date>.
Temporal refuses a second run with an id that already finished, so one date sends once however
it was started. The child lists the users who want the email and sends each one on its own
activity, three tries each. A user whose send still fails marks the run failed, after the
others got theirs, and a failed date can be started again.

ProposalWorkflow is one run per proposal, id proposal-<user>-<alert_id>, alive from the scan that
logged it until the position is over. It learns what happened through signals, messages a
client sends to a running workflow: `decision` for each reply the runner records and `marked`
for each daily mark (deploy/cloud/lifecycle.py sends both from the log). It waits for a decision
until expiration at most. Once the proposal is taken it follows the marks and, the first time one
flags the profit target, sends the investor one email. It ends on a declined or closed decision or
on the settlement mark, and returns the P/L of the lots held. `status` is a query, a read of the
run's state that changes nothing. Every signal carries the id of its log row, so one sent twice
counts once, and the run publishes the last ids it handled as its memo (a note readable without
a worker) so the runner sends only newer rows.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, VersioningBehavior, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from spx_quant import clock

RETRY = RetryPolicy(initial_interval=timedelta(seconds=30), backoff_coefficient=2.0, maximum_attempts=3)
STEP = {"start_to_close_timeout": timedelta(minutes=2), "retry_policy": RETRY}
NOTICE = {"start_to_close_timeout": timedelta(minutes=2),   # tries at 0, 1, 3, 7 and 15 minutes: the log copy may lag the signal
          "retry_policy": RetryPolicy(initial_interval=timedelta(minutes=1), backoff_coefficient=2.0, maximum_attempts=5)}
GRACE = timedelta(days=4)        # how long after expiration a late settlement mark is waited for (a weekend and a holiday)
BACKFILL = timedelta(hours=1)    # a run started after that point still waits this long for the rows the runner sends next
OPEN = ("proposed", "taken")


@workflow.defn(versioning_behavior=VersioningBehavior.AUTO_UPGRADE)
class DigestWorkflow:
    @workflow.run
    async def run(self, kind: str, day: str = "") -> dict:
        if not day:
            day = clock.market_date(workflow.now()).isoformat()
            try:
                return await workflow.execute_child_workflow(
                    DigestWorkflow.run, args=[kind, day], id=f"digest-{kind}-{day}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY)
            except WorkflowAlreadyStartedError:
                return {"kind": kind, "date": day, "already_run": True}
        users = await workflow.execute_activity("list_users", kind, result_type=list, **STEP)
        done = await asyncio.gather(*(workflow.execute_activity("send_digest", args=[kind, day, u["email"], u["book"]],
                                                                result_type=str, **STEP) for u in users),
                                    return_exceptions=True)
        out = {"kind": kind, "date": day, "users": len(users), "sent": sum(d == "sent" for d in done),
               "no_log": sum(d == "no_log" for d in done), "failed": sum(isinstance(d, BaseException) for d in done)}
        if out["failed"]:
            raise ApplicationError(f"{kind} digest {day}: {out['failed']} of {len(users)} sends failed", out, non_retryable=True)
        return out


@workflow.defn(versioning_behavior=VersioningBehavior.AUTO_UPGRADE)
class ProposalWorkflow:
    def __init__(self) -> None:
        self.inbox: list[tuple[str, dict]] = []
        self.last: dict | None = None    # the latest mark, P/L at the proposed size
        self.s = {"status": "proposed", "lots": None, "pnl": None, "marked": None, "target_email": None, "decision": 0, "mark": 0}

    @workflow.signal
    def decision(self, row: dict) -> None:
        """{id, decision: accepted | modified | declined | closed, contracts}"""
        self.inbox.append(("decision", row))

    @workflow.signal
    def marked(self, row: dict) -> None:
        """{id, date, pnl, exit: profit target flagged, settled}"""
        self.inbox.append(("mark", row))

    @workflow.query
    def status(self) -> dict:
        return dict(self.s)

    @workflow.run
    async def run(self, user: str, alert_id: str, expires: str, contracts: int) -> dict:
        s = self.s
        s.update(user=user, alert_id=alert_id, expires=expires)
        deadline = clock.options_close(date.fromisoformat(expires)) + GRACE
        workflow.upsert_memo({"decision": 0, "mark": 0})   # tells the runner a worker has picked this run up
        while s["status"] in OPEN:
            try:
                await workflow.wait_condition(lambda: bool(self.inbox), timeout=max(deadline - workflow.now(), BACKFILL))
            except asyncio.TimeoutError:
                s["status"] = "unsettled" if s["lots"] else "not_taken"
                break
            kind, row = self.inbox.pop(0)
            if row["id"] <= s[kind]:
                continue
            s[kind] = row["id"]
            if kind == "decision":
                what = row["decision"]
                if what in ("accepted", "modified"):
                    s.update(status="taken", lots=row.get("contracts") or contracts)
                elif what == "declined" or s["lots"]:
                    s["status"] = what
            else:
                self.last = row
                if row["settled"]:
                    s["status"] = "settled" if s["lots"] else "not_taken"
                elif row["exit"] and s["lots"] and s["target_email"] != "sent":
                    s["target_email"] = await self.notify(user, alert_id, row["date"])
            if self.last:
                s.update(marked=self.last["date"], pnl=round(self.last["pnl"] * s["lots"] / contracts, 2) if s["lots"] else None)
            workflow.upsert_memo({"decision": s["decision"], "mark": s["mark"]})
        return dict(s)

    async def notify(self, user: str, alert_id: str, day: str) -> str:
        """One try at the target email per flagged mark until one is sent. A send that fails never ends the run."""
        if "@" not in user:
            return "no_address"   # the autonomous account has no inbox
        if date.fromisoformat(day) < clock.market_date(workflow.now()) - timedelta(days=1):
            return "stale"        # an old mark arriving late (the first sync of a long-open position) is not news
        try:
            return await workflow.execute_activity("send_target", args=[user, alert_id, day], result_type=str, **NOTICE)
        except ActivityError:
            return "failed"
