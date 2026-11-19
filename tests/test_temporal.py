"""Temporal digest emails and the proposal lifecycle (cloud/worker, cloud/schedules.py,
deploy/cloud/lifecycle.py): the workflows on the SDK's time-skipping test server, the activities
against moto's fake AWS, the schedule plan, the runner's sync from a real log."""
import asyncio
import importlib.util
import logging
import os
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from spx_quant import clock, decisions, digest, mark, pipeline, store
from tests.helpers import EOD, MARK_TIME, PARAMS, PatchedSource, memdb, pm150, replay

ROOT = Path(__file__).resolve().parents[1]
HAVE = all(importlib.util.find_spec(m) for m in ("temporalio", "boto3", "moto"))
if HAVE:
    sys.path[:0] = [str(ROOT / "cloud" / "worker"), str(ROOT / "deploy" / "cloud"), str(ROOT / "cloud")]
    from temporalio import activity
    from temporalio.client import WorkflowFailureError
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import ApplicationError
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    import activities
    import lifecycle
    import logdoc
    import schedules
    import worker as lambda_worker
    from workflows import GRACE, DigestWorkflow, ProposalWorkflow

NEED = "pip install -r cloud/requirements-dev.txt"
ME, YOU = "me@example.com", "you@example.com"


@unittest.skipUnless(HAVE, NEED)
class WorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = await WorkflowEnvironment.start_time_skipping()
        self.queue, self.sent, self.broken = f"q-{uuid.uuid4()}", [], set()

        @activity.defn(name="list_users")
        async def list_users(kind: str) -> list[dict]:
            return [{"email": ME, "book": "paper"}, {"email": YOU, "book": "taken"}]

        @activity.defn(name="send_digest")
        async def send_digest(kind: str, day: str, email: str, book: str) -> str:
            if email in self.broken:
                raise ApplicationError("mailbox refused", non_retryable=True)   # no retry timers to wait out
            self.sent.append((kind, day, email, book))
            return "sent"

        self.worker = Worker(self.env.client, task_queue=self.queue, workflows=[DigestWorkflow], activities=[list_users, send_digest])

    async def asyncTearDown(self):
        await self.env.shutdown()

    def start(self, *args, **kw):
        return self.env.client.start_workflow(DigestWorkflow.run, args=list(args), id=kw.pop("id", f"t-{uuid.uuid4()}"),
                                              task_queue=self.queue, **kw)

    async def test_a_scheduled_start_sends_each_user_once_for_the_market_date(self):
        async with self.worker:
            with self.env.auto_time_skipping_disabled():   # both starts must land on the same date
                h = await self.start("monday")
                out = await h.result()
                day = clock.market_date((await h.describe()).start_time).isoformat()
                again = await (await self.start("monday")).result()
            self.assertEqual(out, {"kind": "monday", "date": day, "users": 2, "sent": 2, "no_log": 0, "failed": 0})
            self.assertEqual(sorted(self.sent), [("monday", day, ME, "paper"), ("monday", day, YOU, "taken")])
            child = await self.env.client.get_workflow_handle(f"digest-monday-{day}").describe()
            self.assertEqual(child.status.name, "COMPLETED")
            self.assertEqual(again, {"kind": "monday", "date": day, "already_run": True})
            self.assertEqual(len(self.sent), 2)

    async def test_a_given_date_is_used_as_is(self):
        async with self.worker:
            out = await (await self.start("monday", "2026-11-16", id="digest-monday-2026-11-16")).result()
            self.assertEqual((out["date"], out["sent"]), ("2026-11-16", 2))

    async def test_one_failed_user_does_not_stop_the_other_and_the_date_can_run_again(self):
        self.broken.add(YOU)
        quiet(self)
        async with self.worker:
            with self.assertRaises(WorkflowFailureError):
                await (await self.start("monday", "2026-11-16", id="digest-monday-2026-11-16")).result()
            self.assertEqual([s[2] for s in self.sent], [ME])
            self.broken.clear()
            out = await (await self.start("monday", "2026-11-16", id="digest-monday-2026-11-16",
                                          id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY)).result()
            self.assertEqual(out["failed"], 0)


def quiet(case):
    logging.disable(logging.CRITICAL)   # the SDK logs each failed try with a traceback
    case.addCleanup(logging.disable, logging.NOTSET)


@unittest.skipUnless(HAVE, NEED)
class ProposalTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = await WorkflowEnvironment.start_time_skipping()
        self.queue, self.sent, self.broken = f"q-{uuid.uuid4()}", [], False
        self.today = clock.market_date(await self.env.get_current_time())
        self.expires = (self.today + timedelta(days=30)).isoformat()

        @activity.defn(name="send_target")
        async def send_target(email: str, alert_id: str, day: str) -> str:
            if self.broken:
                raise ApplicationError("mailbox refused", non_retryable=True)
            self.sent.append((email, alert_id, day))
            return "sent"

        self.worker = Worker(self.env.client, task_queue=self.queue, workflows=[ProposalWorkflow], activities=[send_target])

    async def asyncTearDown(self):
        await self.env.shutdown()

    def start(self, user=ME, contracts=4, expires=None):
        return self.env.client.start_workflow(ProposalWorkflow.run, args=[user, "a1", expires or self.expires, contracts],
                                              id=f"proposal-{user}-{uuid.uuid4()}", task_queue=self.queue)

    def mark(self, n, pnl, exit=False, settled=False, ago=0):
        return {"id": n, "date": (self.today - timedelta(days=ago)).isoformat(), "pnl": pnl, "exit": exit, "settled": settled}

    async def state(self, h, **want):
        """The status query, once the run has handled every signal sent so far."""
        for _ in range(100):
            s = await h.query(ProposalWorkflow.status)
            if all(s[k] == v for k, v in want.items()):
                return s
            await asyncio.sleep(0.05)
        self.fail(f"status never reached {want}: {s}")

    async def test_taken_then_one_email_at_the_target_then_closed_with_the_pnl_of_the_lots_held(self):
        async with self.worker:
            h = await self.start()
            self.assertEqual((await self.state(h))["status"], "proposed")
            await h.signal(ProposalWorkflow.marked, self.mark(1, 80.0, exit=True))        # flagged before it was taken: no email
            await h.signal(ProposalWorkflow.decision, {"id": 1, "decision": "modified", "contracts": 2})
            s = await self.state(h, decision=1)
            self.assertEqual((s["status"], s["lots"], s["pnl"], s["target_email"]), ("taken", 2, 40.0, None))
            await h.signal(ProposalWorkflow.marked, self.mark(2, 500.0, exit=True))
            await h.signal(ProposalWorkflow.marked, self.mark(2, 500.0, exit=True))        # the same row sent twice counts once
            await h.signal(ProposalWorkflow.marked, self.mark(3, 520.0, exit=True))        # still at target: no second email
            s = await self.state(h, mark=3)
            self.assertEqual((s["target_email"], s["pnl"], s["marked"]), ("sent", 260.0, self.today.isoformat()))
            self.assertEqual(self.sent, [(ME, "a1", self.today.isoformat())])
            self.assertEqual(await (await h.describe()).memo(), {"decision": 1, "mark": 3})
            await h.signal(ProposalWorkflow.decision, {"id": 2, "decision": "closed", "contracts": None})
            out = await h.result()
            self.assertEqual((out["status"], out["lots"], out["pnl"], out["user"], out["alert_id"]), ("closed", 2, 260.0, ME, "a1"))
            self.assertEqual(len(self.sent), 1)

    async def test_no_decision_ends_after_expiration_and_declined_ends_at_once(self):
        async with self.worker:
            h = await self.start()
            await h.signal(ProposalWorkflow.decision, {"id": 1, "decision": "closed", "contracts": None})   # never taken: ignored
            await h.signal(ProposalWorkflow.marked, self.mark(1, 50.0))
            before = await self.env.get_current_time()
            out = await h.result()                                                         # the test server skips ahead
            self.assertEqual((out["status"], out["lots"], out["pnl"]), ("not_taken", None, None))
            waited = await self.env.get_current_time() - before
            self.assertGreater(waited, timedelta(days=30) + GRACE - timedelta(days=2))
            h = await self.start()
            await h.signal(ProposalWorkflow.decision, {"id": 1, "decision": "declined", "contracts": None})
            self.assertEqual((await h.result())["status"], "declined")

    async def test_settlement_ends_a_taken_run_with_the_final_pnl(self):
        async with self.worker:
            h = await self.start()
            await h.signal(ProposalWorkflow.decision, {"id": 1, "decision": "accepted", "contracts": 4})
            await h.signal(ProposalWorkflow.marked, self.mark(1, 817.0, settled=True))
            out = await h.result()
            self.assertEqual((out["status"], out["pnl"], out["target_email"]), ("settled", 817.0, None))
            h = await self.start()
            await h.signal(ProposalWorkflow.decision, {"id": 1, "decision": "accepted", "contracts": 4})
            await h.signal(ProposalWorkflow.marked, self.mark(1, -300.0))
            out = await h.result()                                                         # no settlement mark ever came
            self.assertEqual((out["status"], out["pnl"]), ("unsettled", -300.0))

    async def test_an_old_mark_a_user_without_an_inbox_and_a_failed_send_never_stop_the_run(self):
        quiet(self)
        async with self.worker:
            h = await self.start()
            await h.signal(ProposalWorkflow.decision, {"id": 1, "decision": "accepted", "contracts": 4})
            await h.signal(ProposalWorkflow.marked, self.mark(1, 500.0, exit=True, ago=5))
            self.assertEqual((await self.state(h, mark=1))["target_email"], "stale")
            self.broken = True
            await h.signal(ProposalWorkflow.marked, self.mark(2, 500.0, exit=True))
            await self.state(h, mark=2, target_email="failed")
            self.broken = False
            await h.signal(ProposalWorkflow.marked, self.mark(3, 510.0, exit=True))        # the next flagged mark tries again
            await self.state(h, mark=3, target_email="sent")
            auto = await self.start(user="auto")
            await auto.signal(ProposalWorkflow.decision, {"id": 1, "decision": "accepted", "contracts": 4})
            await auto.signal(ProposalWorkflow.marked, self.mark(1, 500.0, exit=True))
            self.assertEqual((await self.state(auto, mark=1))["target_email"], "no_address")
            self.assertEqual(len(self.sent), 1)


@unittest.skipUnless(HAVE, NEED)
class LifecycleTest(unittest.IsolatedAsyncioTestCase):
    """deploy/cloud/lifecycle.py against a log written by the engine."""
    D = date(2026, 9, 28)

    def setUp(self):
        self.conn = memdb()
        self.alert = pipeline.scan(self.conn, replay(), pm150(), PARAMS, "13:25", send=False).alert
        self.aid = self.alert["alert_id"]
        self.addCleanup(self.conn.close)

    def next_day(self, d, put, call):
        legs = {l["right"]: l["sym"] for l in self.alert["legs"]}
        now = clock.local_to_utc("PT", datetime(2026, 9, d, 13, 35))
        mark.run(self.conn, PatchedSource(now, quote_et=f"2026-09-{d}T16:14:59", mids={legs["P"]: put, legs["C"]: call}), PARAMS)

    def test_plan_lists_each_proposal_in_play_with_its_rows_in_time_order(self):
        self.assertEqual(lifecycle.plan(self.conn, self.D), [{"alert_id": self.aid, "expires": "2026-11-30", "contracts": 1, "signals": []}])
        mark.run(self.conn, replay(MARK_TIME), PARAMS)
        decisions.record(self.conn, self.aid, "accepted", MARK_TIME + timedelta(hours=1))
        self.next_day(29, 2.0, 1.0)
        p, = lifecycle.plan(self.conn, date(2026, 9, 29))
        self.assertEqual(p["signals"], [("marked", {"id": 1, "date": "2026-09-28", "pnl": 0.0, "exit": False, "settled": False}),
                                        ("decision", {"id": 1, "decision": "accepted", "contracts": 1}),
                                        ("marked", {"id": 2, "date": "2026-09-29", "pnl": 517.0, "exit": True, "settled": False})])
        decisions.record(self.conn, self.aid, "closed", clock.local_to_utc("PT", datetime(2026, 9, 29, 14)))
        self.assertEqual(len(lifecycle.plan(self.conn, date(2026, 10, 2))), 1)     # closed three days ago: the last row may still be owed
        self.assertEqual(lifecycle.plan(self.conn, date(2026, 10, 5)), [])

    def test_a_settled_proposal_drops_out_after_a_few_days_and_a_repeat_needs_a_reply(self):
        row = {k: v for k, v in self.alert.items() if k != "id"}
        store.insert(self.conn, "alert", **dict(row, alert_id="again", repeat_of=self.aid))
        self.assertEqual([p["alert_id"] for p in lifecycle.plan(self.conn, self.D)], [self.aid])
        decisions.record(self.conn, "again", "accepted", EOD)
        self.assertEqual([p["alert_id"] for p in lifecycle.plan(self.conn, self.D)], [self.aid, "again"])
        store.insert(self.conn, "mark", alert_id=self.aid, market_date="2026-11-30", ts=MARK_TIME, pnl=817.0, settled=1)
        self.assertEqual([p["alert_id"] for p in lifecycle.plan(self.conn, date(2026, 12, 3))], [self.aid, "again"])
        self.assertEqual([p["alert_id"] for p in lifecycle.plan(self.conn, date(2026, 12, 4))], ["again"])

    async def test_sync_starts_each_run_once_and_sends_only_rows_the_run_has_not_seen(self):
        env = await WorkflowEnvironment.start_time_skipping()
        self.addAsyncCleanup(env.shutdown)
        sent = []

        @activity.defn(name="send_target")
        async def send_target(email: str, alert_id: str, day: str) -> str:
            sent.append(day)
            return "sent"

        mark.run(self.conn, replay(MARK_TIME), PARAMS)
        decisions.record(self.conn, self.aid, "accepted", MARK_TIME + timedelta(hours=1))
        counts = lambda **n: {"started": 0, "signals": 0, "waiting": 0, "finished": 0, "failed": 0, **n}
        sync = lambda day: lifecycle.sync(env.client, self.conn, ME, day)
        with mock.patch.object(lifecycle, "QUEUE", f"q-{uuid.uuid4()}"):
            self.assertEqual(await sync(self.D), counts(started=1, signals=2))
            self.assertEqual(await sync(self.D), counts(waiting=1))     # no worker yet: the rows are queued once, not again
            async with Worker(env.client, task_queue=lifecycle.QUEUE, workflows=[ProposalWorkflow], activities=[send_target]):
                h = env.client.get_workflow_handle(f"proposal-{ME}-{self.aid}")
                for _ in range(100):
                    if await (await h.describe()).memo() == {"decision": 1, "mark": 1}:
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(await sync(self.D), counts())
                self.next_day(29, 2.0, 1.0)
                decisions.record(self.conn, self.aid, "closed", clock.local_to_utc("PT", datetime(2026, 9, 29, 14)))
                self.assertEqual(await sync(date(2026, 9, 29)), counts(signals=2))
                out = await h.result()
                self.assertEqual((out["status"], out["lots"], out["pnl"], out["target_email"]), ("closed", 1, 517.0, "stale"))
                self.assertEqual(await sync(date(2026, 9, 29)), counts(finished=1))
                self.assertEqual(sent, [])   # the recorded session is long past, so its target mark is not news

@unittest.skipUnless(HAVE, NEED)
class ActivityTest(unittest.TestCase):
    def setUp(self):
        from moto import mock_aws
        self.env = mock.patch.dict(os.environ, {"USERS_TABLE": "stormglass-users", "LOG_BUCKET": "logs-test", "AWS_DEFAULT_REGION": "us-west-2",
                                                "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x"})
        self.env.start()
        self.aws = mock_aws()
        self.aws.start()
        import boto3
        boto3.client("dynamodb").create_table(TableName="stormglass-users", BillingMode="PAY_PER_REQUEST",
                                              AttributeDefinitions=[{"AttributeName": "email", "AttributeType": "S"}],
                                              KeySchema=[{"AttributeName": "email", "KeyType": "HASH"}])
        self.table = boto3.resource("dynamodb").Table("stormglass-users")
        self.s3 = boto3.client("s3")
        self.s3.create_bucket(Bucket="logs-test", CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
        self.tmp = tempfile.TemporaryDirectory()
        self.mail = []
        sender = mock.Mock(send=lambda *m: self.mail.append(m))
        self.channel = mock.patch.object(activities, "channel", lambda to: self.mail.append(to) or sender)
        self.channel.start()

    def tearDown(self):
        self.channel.stop()
        self.tmp.cleanup()
        self.aws.stop()
        self.env.stop()

    def put_log(self, email, damage=False, at_target=False):
        d = Path(self.tmp.name)
        conn = store.connect(d / "a.db")
        a = pipeline.scan(conn, replay(), pm150(), PARAMS, slot="13:25", send=False).alert
        if at_target:
            decisions.record(conn, a["alert_id"], "accepted", EOD)
            store.insert(conn, "mark", alert_id=a["alert_id"], market_date="2026-09-29", ts=MARK_TIME, spot=768.0, pnl=517.0,
                         pnl_pct_credit=0.63, settled=0, exit_signal="profit target (63% of credit)")
        conn.close()
        logdoc.dump(str(d / "a.db"), str(d / "a.sql"))
        text = (d / "a.sql").read_text()
        self.s3.put_object(Bucket="logs-test", Key=f"logs/{email}.sql", Body=text.replace("INSERT", "INSERTT", 1) if damage else text)
        (d / "a.db").unlink()

    def test_list_users_follows_each_switch_and_defaults_to_on(self):
        self.table.put_item(Item={"email": ME, "monday_email": True, "friday_email": False, "digest_book": "taken"})
        self.table.put_item(Item={"email": YOU})
        self.assertEqual(activities.list_users("monday"), [{"email": ME, "book": "taken"}, {"email": YOU, "book": "paper"}])
        self.assertEqual(activities.list_users("friday"), [{"email": YOU, "book": "paper"}])

    def test_send_builds_the_same_email_as_the_command_line_from_the_s3_copy(self):
        self.put_log(ME)
        self.assertEqual(activities.send_digest("monday", "2026-09-28", ME, "paper"), "sent")
        conn = store.connect(":memory:")
        pipeline.scan(conn, replay(), pm150(), PARAMS, slot="13:25", send=False)
        want = digest.build("monday", conn, date(2026, 9, 28), "paper")
        self.assertEqual(self.mail[0], ME)
        self.assertEqual(self.mail[1][0], want[0])
        self.assertIn("1 open position", self.mail[1][0])
        self.assertEqual(len(self.mail[1]), 3)

    def test_target_notice_goes_out_from_the_s3_copy_unless_alerts_are_off(self):
        aid = "2026-09-28-2026-11-30"
        self.assertEqual(activities.send_target(ME, aid, "2026-09-29"), "no_log")
        self.put_log(ME)
        with self.assertRaises(ApplicationError) as e:      # an old copy: retried until the runner's next one shows the mark
            activities.send_target(ME, aid, "2026-09-29")
        self.assertFalse(e.exception.non_retryable)
        self.assertEqual(self.mail, [])
        self.put_log(ME, at_target=True)
        self.assertEqual(activities.send_target(ME, aid, "2026-09-29"), "sent")
        self.assertEqual(self.mail[0], ME)
        self.assertIn("TARGET REACHED: strangle XSP 717P/811C at 63% of credit, +$517", self.mail[1][0])
        self.assertEqual(len(self.mail[1]), 3)
        self.table.put_item(Item={"email": ME, "alerts": False})
        self.assertEqual(activities.send_target(ME, aid, "2026-09-29"), "alerts_off")
        self.assertEqual(len(self.mail), 2)

    def test_no_log_yet_sends_nothing(self):
        self.assertEqual(activities.send_digest("monday", "2026-09-28", ME, "paper"), "no_log")
        self.assertEqual(self.mail, [])

    def test_a_damaged_copy_or_an_unknown_digest_is_an_error_and_sends_nothing(self):
        self.put_log(ME, damage=True)
        with self.assertRaises(ApplicationError) as e:
            activities.send_digest("monday", "2026-09-28", ME, "paper")
        self.assertIn("checksum mismatch", str(e.exception))
        self.assertFalse(e.exception.non_retryable)
        with self.assertRaises(ApplicationError) as e:
            activities.send_digest("yearly", "2026-09-28", ME, "paper")
        self.assertTrue(e.exception.non_retryable)
        self.assertEqual(self.mail, [])


@unittest.skipUnless(HAVE, NEED)
class WiringTest(unittest.TestCase):
    def test_worker_registers_the_workflow_and_reads_the_key_once_configured(self):
        from temporalio.contrib.aws.lambda_worker import LambdaWorkerConfig
        cfg = LambdaWorkerConfig()
        lambda_worker.configure(cfg, key=lambda: "secret")
        w = cfg.worker_config
        self.assertEqual((w["task_queue"], w["workflows"]), ("stormglass", [DigestWorkflow, ProposalWorkflow]))
        self.assertEqual([a.__name__ for a in w["activities"]], ["list_users", "send_digest", "send_target"])
        self.assertEqual(cfg.client_connect_config["api_key"], "secret")
        self.assertGreater(cfg.shutdown_deadline_buffer, w["graceful_shutdown_timeout"])
        self.assertTrue(callable(lambda_worker.lambda_handler))

    def test_one_schedule_per_digest_the_engine_builds_in_pacific_time(self):
        plan = schedules.plan()
        self.assertEqual(set(plan), {f"stormglass-digest-{k}" for k in digest.KINDS if k in schedules.WHEN})
        mon = plan["stormglass-digest-monday"]
        self.assertEqual((mon.spec.cron_expressions, mon.spec.time_zone_name), (["0 6 * * 1"], "America/Los_Angeles"))
        self.assertEqual((mon.action.workflow, mon.action.args, mon.action.task_queue), ("DigestWorkflow", ["monday"], schedules.QUEUE))
        self.assertEqual({schedules.QUEUE, lifecycle.QUEUE}, {lambda_worker.QUEUE})


if __name__ == "__main__":
    unittest.main()
