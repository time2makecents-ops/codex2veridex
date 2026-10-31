from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gmail_oauth


class GmailOauthBrowserTests(unittest.TestCase):
    def test_unified_veridex_browser_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            gmail_oauth, "_debug_json", side_effect=[{"Browser": "Chrome"}, {"id": "oauth-tab"}]
        ) as debug_json:
            gmail_oauth._open_google_authorization(
                "https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
                {
                    "VERIDEX_BROWSER_PROFILE_DIR": str(Path(temporary) / "veridex-browser"),
                    "VERIDEX_BROWSER_DEBUG_PORT": "9555",
                    "VERIDEX_GOOGLE_DEBUG_PORT": "9444",
                },
            )

        self.assertEqual(debug_json.call_args_list[0].args, (9555, "/json/version"))

    def test_running_dedicated_profile_receives_google_authorization_tab(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            gmail_oauth, "_debug_json", side_effect=[{"Browser": "Chrome"}, {"id": "oauth-tab"}]
        ) as debug_json, patch.object(gmail_oauth.subprocess, "Popen") as popen:
            gmail_oauth._open_google_authorization(
                "https://accounts.google.com/o/oauth2/v2/auth?client_id=test&state=private",
                {
                    "VERIDEX_GOOGLE_PROFILE_DIR": str(Path(temporary) / "profile"),
                    "VERIDEX_GOOGLE_DEBUG_PORT": "9444",
                },
            )

        self.assertEqual(debug_json.call_args_list[0].args, (9444, "/json/version"))
        self.assertEqual(debug_json.call_args_list[1].kwargs["method"], "PUT")
        self.assertIn("/json/new?https%3A%2F%2Faccounts.google.com", debug_json.call_args_list[1].args[1])
        popen.assert_not_called()

    def test_missing_profile_launches_dedicated_chrome_not_default_browser(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            gmail_oauth, "_debug_json", side_effect=OSError("not running")
        ), patch.object(
            gmail_oauth, "_chrome_path", return_value=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        ), patch.object(gmail_oauth.subprocess, "Popen") as popen:
            profile = Path(temporary) / "profile"
            gmail_oauth._open_google_authorization(
                "https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
                {"VERIDEX_GOOGLE_PROFILE_DIR": str(profile), "VERIDEX_GOOGLE_DEBUG_PORT": "9444"},
            )

        command = popen.call_args.args[0]
        self.assertIn(f"--user-data-dir={profile.resolve()}", command)
        self.assertIn("--remote-debugging-port=9444", command)
        self.assertEqual(command[-1], "https://accounts.google.com/o/oauth2/v2/auth?client_id=test")

    def test_non_google_authorization_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(gmail_oauth.GmailGatewayError, "non-Google OAuth URL"):
            gmail_oauth._open_google_authorization("https://example.com/oauth", {})


if __name__ == "__main__":
    unittest.main()
