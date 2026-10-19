from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

import facebook_chrome_bridge
import veridex_server


class FacebookChromeBridgeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the Facebook bridge")
    def test_session_classifier_accepts_authenticated_home_redirect_without_nav(self) -> None:
        script = (
            "const { classifyFacebookSession } = require('./facebook_chrome_bridge.js');"
            "console.log(JSON.stringify(["
            "classifyFacebookSession({url:'https://www.facebook.com/home.php',login_form:false,checkpoint:false,navigation_shell:false}),"
            "classifyFacebookSession({url:'https://www.facebook.com/login/',login_form:true,checkpoint:false,navigation_shell:false}),"
            "classifyFacebookSession({url:'https://www.facebook.com/public.profile',login_form:false,checkpoint:false,navigation_shell:false})"
            "]));"
        )

        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            cwd=str(facebook_chrome_bridge.ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        home, login, public_profile = json.loads(completed.stdout)
        self.assertTrue(home["signed_in"])
        self.assertEqual(home["evidence"], "authenticated_route")
        self.assertFalse(login["signed_in"])
        self.assertFalse(public_profile["signed_in"])

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
            "office.facebook_marketplace_draft_create",
            "office.facebook_marketplace_prepare",
            "office.facebook_marketplace_resume",
            "office.facebook_group_share_prepare",
        }.issubset(names))

    @patch("facebook_chrome_bridge._run", return_value={"ok": True, "status": "facebook_prepared", "publish_clicked": False})
    def test_marketplace_prepare_uses_structured_stdin_payload(self, run) -> None:
        draft = {"draft_id": "fbdraft_one", "title": "Oak side table", "price": 45}

        result = facebook_chrome_bridge.prepare_marketplace_listing(draft, [r"C:\verified\one.jpg"])

        self.assertEqual(result["status"], "facebook_prepared")
        run.assert_called_once_with(
            "marketplace-prepare",
            timeout=120,
            payload={"draft": draft, "image_paths": [r"C:\verified\one.jpg"]},
        )

    def test_marketplace_javascript_has_no_publish_or_group_post_action(self) -> None:
        source = facebook_chrome_bridge.BRIDGE.read_text(encoding="utf-8")
        self.assertIn('publish_clicked: false', source)
        self.assertIn('post_clicked: false', source)
        self.assertNotIn('action === "marketplace-publish"', source)
        self.assertNotIn('action === "group-share-post"', source)
        self.assertIn("waitForLoginState", source)

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
