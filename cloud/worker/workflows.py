"""The weekly digest emails as a Temporal workflow (issue #63, item 8).

Temporal is a service that runs a function, called a workflow, so that every step is recorded
and a crash or a timeout resumes from the last finished step. Work that touches the outside
world (AWS, the mail server) sits in activities, which Temporal retries on failure.

A Temporal Schedule starts DigestWorkflow with only the kind ("monday" or "friday"). That run
works out the market date and hands over to a child run whose id is digest-<kind>-<date>.
Temporal refuses a second run with an id that already finished, so one date sends once however
it was started. The child lists the users who want the email and sends each one on its own
activity, three tries each. A user whose send still fails marks the run failed, after the
others got theirs, and a failed date can be started again.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, VersioningBehavior, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from spx_quant import clock

RETRY = RetryPolicy(initial_interval=timedelta(seconds=30), backoff_coefficient=2.0, maximum_attempts=3)
STEP = {"start_to_close_timeout": timedelta(minutes=2), "retry_policy": RETRY}


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
