"""Temporal digest emails (cloud/worker, cloud/schedules.py): the workflow on the SDK's
time-skipping test server, the activities against moto's fake AWS, the schedule plan."""
import importlib.util
import logging
import os
import sys
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest import mock

from spx_quant import clock, digest, pipeline, store
from tests.helpers import PARAMS, pm150, replay

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
    import logdoc
    import schedules
    import worker as lambda_worker
    from workflows import DigestWorkflow

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
        logging.disable(logging.CRITICAL)   # the SDK logs each failed try with a traceback
        self.addCleanup(logging.disable, logging.NOTSET)
        async with self.worker:
            with self.assertRaises(WorkflowFailureError):
                await (await self.start("monday", "2026-11-16", id="digest-monday-2026-11-16")).result()
            self.assertEqual([s[2] for s in self.sent], [ME])
            self.broken.clear()
            out = await (await self.start("monday", "2026-11-16", id="digest-monday-2026-11-16",
                                          id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY)).result()
            self.assertEqual(out["failed"], 0)


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

    def put_log(self, email, damage=False):
        d = Path(self.tmp.name)
        conn = store.connect(d / "a.db")
        pipeline.scan(conn, replay(), pm150(), PARAMS, slot="13:25", send=False)
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
        self.assertEqual((w["task_queue"], w["workflows"]), ("stormglass", [DigestWorkflow]))
        self.assertEqual([a.__name__ for a in w["activities"]], ["list_users", "send_digest"])
        self.assertEqual(cfg.client_connect_config["api_key"], "secret")
        self.assertGreater(cfg.shutdown_deadline_buffer, w["graceful_shutdown_timeout"])
        self.assertTrue(callable(lambda_worker.lambda_handler))

    def test_one_schedule_per_digest_the_engine_builds_in_pacific_time(self):
        plan = schedules.plan()
        self.assertEqual(set(plan), {f"stormglass-digest-{k}" for k in digest.KINDS if k in schedules.WHEN})
        mon = plan["stormglass-digest-monday"]
        self.assertEqual((mon.spec.cron_expressions, mon.spec.time_zone_name), (["0 6 * * 1"], "America/Los_Angeles"))
        self.assertEqual((mon.action.workflow, mon.action.args, mon.action.task_queue), ("DigestWorkflow", ["monday"], schedules.QUEUE))
        self.assertEqual(schedules.QUEUE, lambda_worker.QUEUE)


if __name__ == "__main__":
    unittest.main()
