"""HTML email bodies: same facts as the plain text, inline styles only, nothing about other positions."""
import os
import unittest
from datetime import timedelta
from unittest import mock

from spx_quant import decisions, htmlmail, notify, outbox, pipeline, store
from spx_quant.profile import validate
from spx_quant.synthetic import SyntheticSource
from tests.helpers import EOD, MARK_TIME, PARAMS, memdb, pm150, replay

EMAIL = validate(150_000, "portfolio", 0.08, 2, "email", "me@example.com")


class HtmlChannel:
    name, html = "fake", True

    def __init__(self):
        self.sent = []

    def send(self, subject, body, html=None):
        self.sent.append((subject, body, html))


class ProposalHtmlTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.ch = memdb(), HtmlChannel()
        self.alert = pipeline.scan(self.conn, replay(), EMAIL, PARAMS, "13:25", channel=self.ch, sleep=lambda s: None).alert
        self.html = self.alert["html"]

    def test_b_kr3_quotes_and_both_timestamps_in_the_html(self):
        for s in ("Output: 2026-09-28 13:25 PT", "Data as of: 2026-09-28 13:14 PT", "7,683.69", "VIX9D 14.39", "VIX3M 18.23"):
            self.assertIn(s, self.html)
        for leg in self.alert["legs"]:
            for s in (leg["sym"], f"{leg['bid']:.2f}", f"{leg['ask']:.2f}"):
                self.assertIn(s, self.html)

    def test_html_carries_the_headline_numbers_and_the_reply_instruction(self):
        risk = self.alert["risk"]
        for s in (self.alert["alert_id"], f"${self.alert['credit']:,.0f}", f"{risk['pop']:.0%}",
                  f"-${-risk['worst_case']:,.0f}", "ACCEPTED", "DECLINED", "MODIFIED", "never places orders"):
            self.assertIn(s, self.html)

    def test_inline_styles_only_so_mail_clients_keep_the_layout(self):
        for banned in ("<style", "class=", "<script", "background:"):
            self.assertNotIn(banned, self.html)

    def test_the_email_goes_out_with_both_bodies_and_the_text_stays_the_record(self):
        subject, body, html = self.ch.sent[0]
        self.assertEqual((body, html), (self.alert["text"], self.html))
        self.assertTrue(body.startswith("STORMGLASS | PROPOSAL"))

    def test_a_repeat_gets_the_short_no_change_card(self):
        again = pipeline.scan(self.conn, replay(MARK_TIME), EMAIL, PARAMS, "13:25", channel=self.ch, sleep=lambda s: None).alert
        self.assertEqual(again["repeat_of"], self.alert["alert_id"])
        self.assertIn("NO CHANGE", again["html"])
        self.assertIn(f"Same proposal as {self.alert['alert_id']}", again["html"])
        self.assertNotIn("Assumptions", again["html"])

    def test_other_open_positions_stay_out_of_both_bodies_and_in_the_log(self):
        decisions.record(self.conn, self.alert["alert_id"], "accepted", EOD + timedelta(seconds=30))
        rec = pipeline.scan(self.conn, replay(MARK_TIME), EMAIL, PARAMS, "13:25", send=False)
        self.assertTrue(any(n.startswith("remaining buying power") for n in rec.result.notes))
        for body in (rec.alert["text"], rec.alert["html"]):
            self.assertNotIn("open position", body)
            self.assertNotIn(f"{self.alert['alert_id']} x", body)
        detail = store.rows(self.conn, "SELECT detail FROM scan ORDER BY id DESC LIMIT 1")[0]["detail"]
        self.assertTrue(any("after 1 open position" in n for n in detail["notes"]))

    def test_a_layout_bug_costs_the_html_not_the_scan(self):
        conn = memdb()
        with mock.patch.object(htmlmail, "alert_html", side_effect=KeyError("boom")):
            rec = pipeline.scan(conn, replay(), EMAIL, PARAMS, "13:25", channel=self.ch, sleep=lambda s: None)
        self.assertEqual(rec.delivery, "delivered")
        self.assertIsNone(rec.alert["html"])
        self.assertEqual(self.ch.sent[-1][:2], (rec.alert["subject"], rec.alert["text"]))
        self.assertEqual(store.rows(conn, "SELECT kind FROM event")[0]["kind"], "html_failed")

    def test_gmail_outbox_carries_the_html(self):
        conn = memdb()
        gmail = validate(150_000, "portfolio", notify_channel="gmail", email_to="me@example.com")
        a = pipeline.scan(conn, replay(), gmail, PARAMS, "13:25", sleep=lambda s: None).alert
        self.assertEqual(outbox.pending(conn, PARAMS)[0]["html"], a["html"])


class OtherKindsTest(unittest.TestCase):
    def test_stand_down_card_gives_the_reasons(self):
        a = pipeline.scan(memdb(), SyntheticSource(35.0, "flat"), pm150(), PARAMS, "10:30", send=False).alert
        self.assertEqual(a["kind"], "stand_down")
        self.assertIn("STAND DOWN", a["html"])
        self.assertIn("Do not enter today", a["html"])
        self.assertIn(htmlmail.escape(a["reasons"][0]), a["html"])

    def test_smtp_message_is_multipart_with_text_first(self):
        env = {"SPX_QUANT_SMTP_HOST": "smtp.example.com", "SPX_QUANT_SMTP_USER": "u@example.com", "SPX_QUANT_SMTP_PASSWORD": "x"}
        with mock.patch.object(notify.smtplib, "SMTP") as smtp:
            notify.EmailChannel("me@example.com", env).send("s", "plain body", "<html><body>rich</body></html>")
        msg = smtp.return_value.__enter__.return_value.send_message.call_args[0][0]
        self.assertEqual([p.get_content_type() for p in msg.iter_parts()], ["text/plain", "text/html"])


if __name__ == "__main__":
    unittest.main()
