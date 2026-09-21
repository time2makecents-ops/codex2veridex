from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import facebook_chrome_bridge
import veridex_server


class FacebookChromeBridgeTests(unittest.TestCase):
    @patch("facebook_chrome_bridge.subprocess.run")
    @patch("facebook_chrome_bridge.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe")
    def test_status_uses_dedicated_bridge(self, _which, run) -> None:
        payload = {"ok": True, "configured": True, "signed_in": True}
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        self.assertEqual(facebook_chrome_bridge.facebook_profile_status(), payload)
        self.assertEqual(run.call_args.args[0][-1], "status")

    @patch("facebook_chrome_bridge.subprocess.run")
    @patch("facebook_chrome_bridge.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe")
    def test_profile_and_draft_are_available_to_program(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps({"ok": True}), "")
        target = "https://www.facebook.com/melanie.vanderlip.5"
        facebook_chrome_bridge.read_facebook_profile(target)
        self.assertEqual(run.call_args.args[0][-2:], ["profile", target])
        facebook_chrome_bridge.draft_facebook_message(target, "Hello from the museum")
        self.assertEqual(run.call_args.args[0][-3:], ["draft-message", target, "Hello from the museum"])

    @patch("facebook_chrome_bridge._run")
    def test_send_requires_confirmation_before_bridge_runs(self, run) -> None:
        result = facebook_chrome_bridge.send_facebook_message("melanie.vanderlip.5", "Hello")
        self.assertEqual(result["status"], "confirmation_required")
        self.assertFalse(result["sent"])
        run.assert_not_called()

    @patch("facebook_chrome_bridge._run", return_value={"ok": True, "status": "sent", "sent": True})
    def test_confirmed_send_calls_explicit_send_action(self, run) -> None:
        result = facebook_chrome_bridge.send_facebook_message("melanie.vanderlip.5", "Hello", confirmed=True)
        self.assertTrue(result["sent"])
        run.assert_called_once_with("send-message", "melanie.vanderlip.5", "Hello", timeout=60)

    @patch("facebook_chrome_bridge.subprocess.run")
    @patch("facebook_chrome_bridge.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe")
    def test_bridge_error_is_reported(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, json.dumps({"ok": False, "error": "not signed in"}), "")
        with self.assertRaisesRegex(facebook_chrome_bridge.FacebookChromeBridgeError, "not signed in"):
            facebook_chrome_bridge.facebook_profile_status()

    def test_veridex_exposes_facebook_tools(self) -> None:
        names = {row["name"] for row in veridex_server.TOOLS}
        self.assertTrue({
            "office.facebook_status",
            "office.facebook_profile_get",
            "office.facebook_message_draft",
            "office.facebook_message_send",
        }.issubset(names))

    @patch("veridex_server.send_facebook_message")
    def test_server_send_tool_preserves_confirmation_gate(self, send) -> None:
        send.return_value = {"ok": True, "status": "confirmation_required", "sent": False}
        handler = object.__new__(veridex_server.VeridexHandler)

        result = handler._call_tool({
            "tool": "office.facebook_message_send",
            "arguments": {
                "target": "melanie.vanderlip.5",
                "message": "Hello",
                "confirm": False,
            },
        })

        self.assertEqual(result["structuredContent"]["status"], "confirmation_required")
        send.assert_called_once_with("melanie.vanderlip.5", "Hello", confirmed=False)


if __name__ == "__main__":
    unittest.main()
