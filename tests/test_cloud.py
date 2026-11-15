"""Settings site (cloud/): email-code sign-in triggers and the profile API."""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud" / "app"))
import auth  # noqa: E402

HAVE_MOTO = all(importlib.util.find_spec(m) for m in ("boto3", "moto"))


def ev(trigger, **request):
    return {"triggerSource": trigger, "request": request, "response": {}}


class DefineTest(unittest.TestCase):
    def step(self, **req):
        return auth.handler(ev("DefineAuthChallenge_Authentication", **req), None)["response"]

    def test_first_step_asks_for_the_code(self):
        r = self.step(session=[])
        self.assertEqual((r["challengeName"], r["issueTokens"], r["failAuthentication"]), ("CUSTOM_CHALLENGE", False, False))

    def test_right_code_gets_tokens(self):
        self.assertTrue(self.step(session=[{"challengeName": "CUSTOM_CHALLENGE", "challengeResult": True}])["issueTokens"])

    def test_three_wrong_codes_fail(self):
        wrong = {"challengeName": "CUSTOM_CHALLENGE", "challengeResult": False}
        self.assertEqual(self.step(session=[wrong, wrong])["challengeName"], "CUSTOM_CHALLENGE")
        self.assertTrue(self.step(session=[wrong] * 3)["failAuthentication"])

    def test_uninvited_email_fails(self):
        r = self.step(session=[], userNotFound=True)
        self.assertTrue(r["failAuthentication"])
        self.assertNotIn("challengeName", r)


class CodeTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.send = lambda to, code: self.sent.append((to, code))

    def create(self, session):
        e = ev("CreateAuthChallenge_Authentication", session=session, userAttributes={"email": "me@example.com"})
        return auth.create(e, self.send)["response"]

    def test_code_is_six_digits_emailed_once_and_kept_private(self):
        r = self.create([])
        code = r["privateChallengeParameters"]["code"]
        self.assertRegex(code, r"^\d{6}$")
        self.assertEqual(self.sent, [("me@example.com", code)])
        self.assertNotIn(code, json.dumps(r["publicChallengeParameters"]))

    def test_a_retry_reuses_the_code_without_a_second_email(self):
        first = self.create([])
        meta = first["challengeMetadata"]
        again = self.create([{"challengeName": "CUSTOM_CHALLENGE", "challengeResult": False, "challengeMetadata": meta}])
        self.assertEqual(again["privateChallengeParameters"], first["privateChallengeParameters"])
        self.assertEqual(len(self.sent), 1)

    def test_verify_compares_the_answer(self):
        check = lambda a: auth.handler(ev("VerifyAuthChallengeResponse_Authentication", challengeAnswer=a,
                                          privateChallengeParameters={"code": "042117"}), None)["response"]["answerCorrect"]
        self.assertTrue(check(" 042117 "))
        self.assertFalse(check("42117"))
        self.assertFalse(check(""))


@unittest.skipUnless(HAVE_MOTO, "pip install -r cloud/requirements-dev.txt")
class ApiTest(unittest.TestCase):
    def setUp(self):
        from moto import mock_aws
        self.env = mock.patch.dict(os.environ, {"USERS_TABLE": "stormglass-users", "CLIENT_ID": "abc123", "AWS_REGION": "us-west-2",
                                                "AWS_DEFAULT_REGION": "us-west-2", "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x"})
        self.env.start()
        self.aws = mock_aws()
        self.aws.start()
        import boto3
        boto3.client("dynamodb").create_table(TableName="stormglass-users", BillingMode="PAY_PER_REQUEST",
                                              AttributeDefinitions=[{"AttributeName": "email", "AttributeType": "S"}],
                                              KeySchema=[{"AttributeName": "email", "KeyType": "HASH"}])
        import api
        api._table = None
        self.api = api

    def tearDown(self):
        self.aws.stop()
        self.env.stop()

    def call(self, route, body=None, email="Me@Example.com"):
        e = {"routeKey": route, "body": json.dumps(body) if body is not None else None,
             "requestContext": {"authorizer": {"jwt": {"claims": {"email": email}}}} if email else {}}
        r = self.api.handler(e, None)
        return r["statusCode"], (json.loads(r["body"]) if r["headers"]["Content-Type"] == "application/json" else r["body"])

    def test_page_is_served_with_the_client_id(self):
        status, html = self.call("GET /", email=None)
        self.assertEqual(status, 200)
        self.assertIn('"abc123"', html)
        self.assertNotIn("__CLIENT_ID__", html)

    def test_new_user_sees_defaults_then_saves(self):
        status, p = self.call("GET /api/profile")
        self.assertEqual((status, p["saved"], p["email"], p["bp_cap_pct"]), (200, False, "me@example.com", 0.08))
        status, saved = self.call("PUT /api/profile", {"net_liq": 150000, "margin_type": "portfolio", "bp_cap_pct": 0.08,
                                                       "max_worst_case_pct": 0.05, "monday_email": False})
        self.assertEqual((status, saved["delta_theta_limit"], saved["monday_email"], saved["alerts"]), (200, 2.0, False, True))
        _, p = self.call("GET /api/profile")
        self.assertEqual((p["saved"], p["net_liq"], p["margin_type"]), (True, 150000.0, "portfolio"))

    def test_same_rules_as_the_command_line(self):
        status, r = self.call("PUT /api/profile", {"net_liq": 50000, "margin_type": "portfolio"})
        self.assertEqual(status, 400)
        self.assertIn("portfolio margin needs at least $100,000", r["error"])
        self.assertEqual(self.call("PUT /api/profile", {"net_liq": 50000, "margin_type": "reg_t", "bp_cap_pct": 1.5})[0], 400)
        self.assertEqual(self.call("PUT /api/profile", {"net_liq": 50000, "margin_type": "reg_t", "alerts": "yes"})[0], 400)
        self.assertFalse(self.call("GET /api/profile")[1]["saved"])

    def test_the_email_comes_from_the_token_not_the_body(self):
        self.call("PUT /api/profile", {"net_liq": 200000, "margin_type": "reg_t", "email": "someone@else.com"})
        import boto3
        keys = [i["email"]["S"] for i in boto3.client("dynamodb").scan(TableName="stormglass-users")["Items"]]
        self.assertEqual(keys, ["me@example.com"])

    def test_no_token_no_profile(self):
        self.assertEqual(self.call("GET /api/profile", email=None)[0], 401)


if __name__ == "__main__":
    unittest.main()
