"""The AWS-only Monday outlook (cloud/sched/digests.py): every opted-in site user, once per date."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "cloud" / "sched"), str(ROOT / "deploy" / "cloud")]
HAVE_MOTO = all(importlib.util.find_spec(m) for m in ("boto3", "moto"))


class Mail:
    def __init__(self):
        self.sent = []

    def __call__(self, to):
        mail = self

        class C:
            def send(self, *message):
                mail.sent.append((to, message[0]))
        return C()


@unittest.skipUnless(HAVE_MOTO, "pip install -r cloud/requirements-dev.txt")
class AwsDigestTest(unittest.TestCase):
    def setUp(self):
        from moto import mock_aws
        self.env = mock.patch.dict(os.environ, {"USERS_TABLE": "u", "LOG_BUCKET": "logs-test", "AWS_DEFAULT_REGION": "us-east-2",
                                                "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x"})
        self.env.start()
        self.aws = mock_aws()
        self.aws.start()
        import boto3
        boto3.client("dynamodb").create_table(TableName="u", BillingMode="PAY_PER_REQUEST",
                                              AttributeDefinitions=[{"AttributeName": "email", "AttributeType": "S"}],
                                              KeySchema=[{"AttributeName": "email", "KeyType": "HASH"}])
        t = boto3.resource("dynamodb").Table("u")
        t.put_item(Item={"email": "a@example.com", "digest_book": "paper"})
        t.put_item(Item={"email": "b@example.com", "monday_email": False})
        t.put_item(Item={"email": "c@example.com"})
        self.s3 = boto3.client("s3")
        self.s3.create_bucket(Bucket="logs-test", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
        import logdoc
        from spx_quant import mark, pipeline, store
        from tests.helpers import MARK_TIME, PARAMS, pm150, replay
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "log.db")
            conn = store.connect(db)
            pipeline.scan(conn, replay(), pm150(), PARAMS, "13:25", send=False)
            mark.run(conn, replay(MARK_TIME), PARAMS)
            conn.close()
            logdoc.dump(db, str(Path(tmp) / "log.sql"))
            self.s3.upload_file(str(Path(tmp) / "log.sql"), "logs-test", "logs/a@example.com.sql")
        import digests
        self.d = digests

    def tearDown(self):
        self.aws.stop()
        self.env.stop()

    def test_sends_to_opted_in_users_with_a_log_once_per_date(self):
        mail = Mail()
        out = self.d.handler({"kind": "monday", "day": "2026-09-28"}, None, channel=mail)
        self.assertEqual((out["sent"], out["no_log"], out["already_sent"], out["failed"]), (1, 1, 0, []))
        self.assertEqual([to for to, _ in mail.sent], ["a@example.com"])
        again = self.d.handler({"kind": "monday", "day": "2026-09-28"}, None, channel=mail)
        self.assertEqual((again["sent"], again["already_sent"], len(mail.sent)), (0, 1, 1))

    def test_unknown_kind_sends_nothing(self):
        mail = Mail()
        self.assertIn("error", self.d.handler({"kind": "friday"}, None, channel=mail))
        self.assertEqual(mail.sent, [])


if __name__ == "__main__":
    unittest.main()
