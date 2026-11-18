"""Create or update the Temporal Schedules that start the digest emails.

    python cloud/schedules.py            (run from the repo root; prints what it did)
    python cloud/schedules.py --show     (print the plan, connect to nothing)

A Temporal Schedule is a timer kept by Temporal that starts a workflow at set times, on time,
in a named time zone. One per digest the engine can build: Mondays 06:00 and Fridays 17:00
America/Los_Angeles. A start that would overlap a run still going is skipped, and a start
missed during an outage is made up only within 12 hours, so a stale outlook never goes out.

The connection comes from the environment, the way the Temporal command line tool reads it:
TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_API_KEY. Running it again changes nothing.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spx_quant import digest  # noqa: E402

QUEUE = "stormglass"
ZONE = "America/Los_Angeles"
WHEN = {"monday": "0 6 * * 1", "friday": "0 17 * * 5"}


def plan() -> dict:
    """Schedule id -> Schedule, for every digest in WHEN that this engine version builds."""
    from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec
    return {f"stormglass-digest-{kind}": Schedule(
        action=ScheduleActionStartWorkflow("DigestWorkflow", kind, id=f"digest-{kind}", task_queue=QUEUE),
        spec=ScheduleSpec(cron_expressions=[cron], time_zone_name=ZONE),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(hours=12)))
        for kind, cron in WHEN.items() if kind in digest.KINDS}


async def apply(client) -> list[str]:
    from temporalio.client import ScheduleAlreadyRunningError, ScheduleUpdate
    out = []
    for name, sched in plan().items():
        try:
            await client.create_schedule(name, sched)
            out.append(f"{name}: created")
        except ScheduleAlreadyRunningError:
            await client.get_schedule_handle(name).update(lambda _, s=sched: ScheduleUpdate(schedule=s))
            out.append(f"{name}: updated")
    return out


async def main() -> list[str]:
    from temporalio.client import Client
    from temporalio.envconfig import ClientConfigProfile
    return await apply(await Client.connect(**ClientConfigProfile.load().to_client_connect_config()))


if __name__ == "__main__":
    if sys.argv[1:] == ["--show"]:
        print("\n".join(f"{n}: {s.spec.cron_expressions[0]} {s.spec.time_zone_name}" for n, s in plan().items()))
    elif sys.argv[1:]:
        raise SystemExit(__doc__)
    else:
        print("\n".join(asyncio.run(main())))
