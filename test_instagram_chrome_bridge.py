from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import instagram_chrome_bridge
import veridex_server


class InstagramChromeBridgeTests(unittest.TestCase):
    @patch("instagram_chrome_bridge.subprocess.run")
    @patch("instagram_chrome_bridge.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe")
    def test_status_uses_dedicated_bridge(self, _which, run) -> None:
        payload = {"ok": True, "configured": True, "signed_in": True}
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        self.assertEqual(instagram_chrome_bridge.instagram_profile_status(), payload)
        self.assertEqual(run.call_args.args[0][-1], "status")

    @patch("instagram_chrome_bridge.subprocess.run")
    @patch("instagram_chrome_bridge.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe")
    def test_profile_and_draft_are_available_to_program(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps({"ok": True}), "")
        instagram_chrome_bridge.read_instagram_profile("frank_nichols")
        self.assertEqual(run.call_args.args[0][-2:], ["profile", "frank_nichols"])
        instagram_chrome_bridge.draft_instagram_message("frank_nichols", "Hello from the museum")
        self.assertEqual(run.call_args.args[0][-3:], ["draft-message", "frank_nichols", "Hello from the museum"])

    @patch("instagram_chrome_bridge._run")
    def test_send_requires_confirmation_before_bridge_runs(self, run) -> None:
        result = instagram_chrome_bridge.send_instagram_message("frank_nichols", "Hello")
        self.assertEqual(result["status"], "confirmation_required")
        self.assertFalse(result["sent"])
        run.assert_not_called()

    @patch("instagram_chrome_bridge._run", return_value={"ok": True, "status": "sent", "sent": True})
    def test_confirmed_send_calls_explicit_send_action(self, run) -> None:
        result = instagram_chrome_bridge.send_instagram_message("frank_nichols", "Hello", confirmed=True)
        self.assertTrue(result["sent"])
        run.assert_called_once_with("send-message", "frank_nichols", "Hello", timeout=60)

    @patch("instagram_chrome_bridge.subprocess.run")
    @patch("instagram_chrome_bridge.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe")
    def test_bridge_error_is_reported(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, json.dumps({"ok": False, "error": "not signed in"}), "")
        with self.assertRaisesRegex(instagram_chrome_bridge.InstagramChromeBridgeError, "not signed in"):
            instagram_chrome_bridge.instagram_profile_status()

    def test_veridex_exposes_instagram_tools(self) -> None:
        names = {row["name"] for row in veridex_server.TOOLS}
        self.assertTrue({
            "office.instagram_status",
            "office.instagram_profile_get",
            "office.instagram_follow",
            "office.instagram_post",
            "office.instagram_message_draft",
            "office.instagram_message_send",
        }.issubset(names))

    @patch("instagram_chrome_bridge._run")
    def test_follow_requires_confirmation(self, run) -> None:
        result = instagram_chrome_bridge.follow_instagram_account("oregonartcenter")
        self.assertEqual(result["status"], "confirmation_required")
        self.assertFalse(result["followed"])
        run.assert_not_called()

        run.return_value = {"ok": True, "status": "following", "followed": True}
        confirmed = instagram_chrome_bridge.follow_instagram_account("oregonartcenter", confirmed=True)
        self.assertTrue(confirmed["followed"])
        run.assert_called_once_with("follow", "oregonartcenter", timeout=60)

    @patch("instagram_chrome_bridge._run")
    def test_post_requires_confirmation(self, run) -> None:
        result = instagram_chrome_bridge.create_instagram_post("instagram/first_post.png", "Welcome")
        self.assertEqual(result["status"], "confirmation_required")
        self.assertFalse(result["posted"])
        run.assert_not_called()

    @patch("veridex_server.send_instagram_message")
    def test_server_send_tool_preserves_confirmation_gate(self, send) -> None:
        send.return_value = {"ok": True, "status": "confirmation_required", "sent": False}
        handler = object.__new__(veridex_server.VeridexHandler)

        result = handler._call_tool({
            "tool": "office.instagram_message_send",
            "arguments": {"handle": "frank_nichols", "message": "Hello", "confirm": False},
        })

        self.assertEqual(result["structuredContent"]["status"], "confirmation_required")
        send.assert_called_once_with("frank_nichols", "Hello", confirmed=False)
