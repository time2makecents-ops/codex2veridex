from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import tempfile
import unittest
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

    def test_connection_status_uses_existing_office_app_token_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            status = service.connection_status()

        self.assertTrue(status["connected"])
        self.assertEqual(status["account_email"], "veridexcorp@gmail.com")
        self.assertNotIn("token", json.dumps(status).lower())

    @patch("gmail_gateway.urllib.request.urlopen")
    def test_search_gmail_returns_metadata_without_exposing_tokens(self, urlopen) -> None:
        urlopen.side_effect = [
            _FakeResponse({"messages": [{"id": "msg_1", "threadId": "thr_1"}]}),
            _FakeResponse(
                {
                    "id": "msg_1",
                    "threadId": "thr_1",
                    "snippet": "Project update",
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
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        raw = payload["raw"] + ("=" * (-len(payload["raw"]) % 4))
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
        self.assertIn("To: recipient@example.com", decoded)
        self.assertIn("Subject: Subject", decoded)
        self.assertIn("Body text", decoded)


if __name__ == "__main__":
    unittest.main()
