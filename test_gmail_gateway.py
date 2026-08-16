from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import tempfile
import unittest
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

import gmail_gateway


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode("utf-8"))

    def __exit__(self, exc_type, exc, tb):
        return False


class GmailGatewayTests(unittest.TestCase):
    def _service(self, temporary: str) -> gmail_gateway.GmailGateway:
        db_path = Path(temporary) / "veridex.db"
        service = gmail_gateway.GmailGateway(
            env={
                "VERIDEX_GMAIL_DB_PATH": str(db_path),
                "VERIDEX_INTEGRATION_ENCRYPTION_KEY": "x" * 40,
                "VERIDEX_GOOGLE_ACCOUNT": "veridexcorp@gmail.com",
                "GOOGLE_OAUTH_CLIENT_ID": "client-id",
                "GOOGLE_OAUTH_CLIENT_SECRET": "client-secret",
            },
            now_fn=lambda: "2026-08-14T12:00:00Z",
        )
        cipher = gmail_gateway.TokenCipher("x" * 40)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO user_integrations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "usr_1",
                "google",
                "veridexcorp@gmail.com",
                json.dumps(["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]),
                "connected",
                cipher.encrypt("access-token"),
                cipher.encrypt("refresh-token"),
                "2026-08-14T13:00:00Z",
                "2026-08-14T12:00:00Z",
                "2026-08-14T12:00:00Z",
            ),
        )
        conn.commit()
        conn.close()
        return service

    def test_connection_status_uses_veridex_local_token_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            status = service.connection_status()

        self.assertTrue(status["connected"])
        self.assertEqual(status["account_email"], "veridexcorp@gmail.com")

    def test_save_connection_encrypts_tokens_in_local_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            status = service.save_connection(
                account_email="veridexcorp@gmail.com",
                access_token="fresh-access",
                refresh_token="fresh-refresh",
                scopes=["gmail.readonly"],
            )
            self.assertTrue(status["connected"])
            conn = sqlite3.connect(service.db_path)
            try:
                row = conn.execute(
                    "SELECT access_token_ciphertext, refresh_token_ciphertext FROM user_integrations WHERE user_id = ?",
                    ("local",),
                ).fetchone()
            finally:
                conn.close()
            self.assertNotIn("fresh-access", row[0])
            self.assertNotIn("fresh-refresh", row[1])
        self.assertNotIn("token", json.dumps(status).lower())

    @patch("gmail_gateway.urllib.request.urlopen")
    def test_search_gmail_returns_metadata_without_exposing_tokens(self, urlopen) -> None:
        urlopen.side_effect = [
            _FakeResponse({"messages": [{"id": "msg_1", "threadId": "thr_1"}]}),
            _FakeResponse(
                {
                    "id": "msg_1",
                    "threadId": "thr_1",
                    "snippet": "We&#39;ll send a project update",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "James Willis <time2makecents@gmail.com>"},
                            {"name": "Subject", "value": "Re: Update"},
                            {"name": "Date", "value": "Fri, 14 Aug 2026 10:00:00 -0700"},
                        ]
                    },
                }
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            messages = service.search("in:inbox is:unread", max_results=5)

        self.assertEqual(messages[0]["id"], "msg_1")
        self.assertEqual(messages[0]["from"], "James Willis <time2makecents@gmail.com>")
        self.assertEqual(messages[0]["subject"], "Re: Update")
        self.assertEqual(messages[0]["snippet"], "We'll send a project update")
        request = urlopen.call_args_list[0].args[0]
        self.assertIn("gmail.googleapis.com/gmail/v1/users/me/messages", request.full_url)
        self.assertNotIn("access-token", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer access-token")

    @patch("gmail_gateway.urllib.request.urlopen")
    def test_send_gmail_encodes_raw_message(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse({"id": "sent_1", "threadId": "thr_sent"})
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            result = service.send(["recipient@example.com"], "Subject", "Body text")

        self.assertEqual(result["id"], "sent_1")
        self.assertTrue(result["rfc_message_id"].startswith("<"))
        request = urlopen.call_args_list[0].args[0]
        payload = json.loads(request.data.decode("utf-8"))
        raw = payload["raw"] + ("=" * (-len(payload["raw"]) % 4))
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
        self.assertIn("To: recipient@example.com", decoded)
        self.assertIn("From: veridexcorp@gmail.com", decoded)
        self.assertIn("Subject: Subject", decoded)
        self.assertIn("Date: Fri, 14 Aug 2026 12:00:00 +0000", decoded)
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw.encode("ascii")))
        alternatives = list(message.iter_parts())
        self.assertEqual([part.get_content_type() for part in alternatives], ["text/plain", "text/html"])
        self.assertEqual(alternatives[0].get_content(), "Body text\n")
        self.assertEqual(alternatives[1].get_content(), "<div>Body text</div>\n")

    def test_address_book_saves_and_updates_practical_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            saved = service.save_contact({
                "name": "Nancy Client",
                "email": "Client@Example.com",
                "phone": "555-0100",
                "company": "Example Co",
                "notes": "Prefers morning calls.",
            })
            updated = service.save_contact({**saved, "company": "Updated Co"})
            contacts = service.list_contacts("updated")

        self.assertEqual(saved["email"], "client@example.com")
        self.assertEqual(updated["contact_id"], saved["contact_id"])
        self.assertEqual(contacts[0]["company"], "Updated Co")

    def test_address_book_deletes_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            saved = service.save_contact({"name": "Delete Me", "email": "delete@example.com"})
            deleted = service.delete_contact(saved["contact_id"])
            contacts = service.list_contacts()

        self.assertEqual(deleted["email"], "delete@example.com")
        self.assertEqual(contacts, [])

    @patch("gmail_gateway.urllib.request.urlopen")
    def test_sent_mail_sync_imports_unique_recipients_and_excludes_self(self, urlopen) -> None:
        urlopen.side_effect = [
            _FakeResponse({"messages": [{"id": "sent_a"}, {"id": "sent_b"}]}),
            _FakeResponse({
                "payload": {"headers": [
                    {"name": "To", "value": "Alice Example <alice@example.com>, veridexcorp@gmail.com"},
                    {"name": "Date", "value": "Fri, 14 Aug 2026 10:00:00 -0700"},
                ]}
            }),
            _FakeResponse({
                "payload": {"headers": [
                    {"name": "Cc", "value": "Alice Example <alice@example.com>, Bob <bob@example.com>"},
                    {"name": "Date", "value": "Fri, 14 Aug 2026 11:00:00 -0700"},
                ]}
            }),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            result = service.sync_contacts(max_messages=500)

        self.assertEqual(result["messages_scanned"], 2)
        self.assertTrue(result["sync"]["completed"])
        self.assertEqual([row["email"] for row in result["contacts"]], ["alice@example.com", "bob@example.com"])
        self.assertEqual(result["contacts"][0]["email_count"], 2)

    @patch("gmail_gateway.urllib.request.urlopen")
    def test_delayed_bounce_is_correlated_and_deduplicated(self, urlopen) -> None:
        urlopen.side_effect = [
            _FakeResponse({"id": "sent_3", "threadId": "thread_3"}),
            _FakeResponse({
                "payload": {"headers": [{"name": "Message-ID", "value": "<gmail-sent-3@mail.gmail.com>"}]}
            }),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            sent = service.send(
                ["missing@example.com"],
                "Project follow-up",
                "Please review the project update.",
                context={"workspace_id": "ws_1", "session_id": "sess_1"},
            )
            bounce = EmailMessage()
            bounce["From"] = "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"
            bounce["Subject"] = "Delivery Status Notification (Failure)"
            bounce.set_content(
                "Final-Recipient: rfc822; missing@example.com\n"
                "Action: failed\n"
                "Status: 5.1.1\n"
                "Diagnostic-Code: smtp; 550 5.1.1 The email account does not exist\n"
                f"Message-ID: {sent['rfc_message_id']}\n"
            )
            raw = base64.urlsafe_b64encode(bounce.as_bytes()).decode("ascii").rstrip("=")
            urlopen.side_effect = [
                _FakeResponse({"messages": [{"id": "bounce_1"}]}),
                _FakeResponse({"id": "bounce_1", "raw": raw}),
                _FakeResponse({"messages": [{"id": "bounce_1"}]}),
            ]
            first = service.check_delivery_failures()
            second = service.check_delivery_failures()

        self.assertEqual(len(first["new_failures"]), 1)
        self.assertEqual(first["alerts"][0]["recipient"], "missing@example.com")
        self.assertEqual(first["alerts"][0]["subject"], "Project follow-up")
        self.assertEqual(first["alerts"][0]["status_code"], "5.1.1")
        self.assertEqual(second["new_failures"], [])
        self.assertEqual(len(second["alerts"]), 1)

    @patch("gmail_gateway.urllib.request.urlopen")
    def test_send_gmail_builds_mime_attachments(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse({"id": "sent_2"})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.txt"
            path.write_bytes(b"attachment body")
            service = self._service(temporary)
            service.send(
                ["recipient@example.com"],
                "Attached report",
                "Please review.",
                [{"name": "report.txt", "path": str(path), "content_type": "text/plain"}],
            )

        request = urlopen.call_args_list[0].args[0]
        payload = json.loads(request.data.decode("utf-8"))
        raw = payload["raw"] + ("=" * (-len(payload["raw"]) % 4))
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw.encode("ascii")))
        attached = list(message.iter_attachments())
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0].get_filename(), "report.txt")
        self.assertEqual(attached[0].get_content(), "attachment body")


if __name__ == "__main__":
    unittest.main()
