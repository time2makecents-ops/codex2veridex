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
    def test_status_uses_passive_cookie_evidence_without_creating_a_tab(self) -> None:
        script = (
            "const { classifyFacebookCookies } = require('./facebook_chrome_bridge.js');"
            "console.log(JSON.stringify(["
            "classifyFacebookCookies([{domain:'.facebook.com',name:'c_user'},{domain:'.facebook.com',name:'xs'}]),"
            "classifyFacebookCookies([{domain:'.facebook.com',name:'datr'}])"
            "]));"
        )
        completed = subprocess.run(
            [shutil.which("node"), "-e", script], cwd=str(facebook_chrome_bridge.ROOT),
            capture_output=True, text=True, check=True,
        )
        authenticated, anonymous = json.loads(completed.stdout)
        self.assertTrue(authenticated["signed_in"])
        self.assertFalse(anonymous["signed_in"])
        source = facebook_chrome_bridge.BRIDGE.read_text(encoding="utf-8")
        status_source = source.split("async function status()", 1)[1].split("async function login()", 1)[0]
        self.assertIn("passiveFacebookSession", status_source)
        self.assertNotIn("withTab(", status_source)

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

    def test_facebook_uses_dedicated_profile_unless_shared_profile_is_explicitly_enabled(self) -> None:
        source = facebook_chrome_bridge.BRIDGE.read_text(encoding="utf-8")
        self.assertIn("VERIDEX_FACEBOOK_USE_SHARED_PP_PROFILE", source)
        self.assertIn('path.join(repoRoot, "data", "browser_profiles", "veridex_browser")', source)
        self.assertIn('useSharedProfile ? sharedUserDataDir : ""', source)

    def test_group_fetch_uses_temporary_background_tab(self) -> None:
        source = facebook_chrome_bridge.BRIDGE.read_text(encoding="utf-8")
        group_source = source.split("async function readGroup(target)", 1)[1].split("async function fillMessageComposer", 1)[0]
        self.assertIn("withBackgroundTab(aboutUrl.href", group_source)
        self.assertNotIn("withExistingFacebookTab", group_source)
        background_source = source.split("async function withBackgroundTab", 1)[1].split("async function pageState", 1)[0]
        self.assertIn('Page.navigate", { url }', background_source)
        self.assertIn('Target.createTarget", { url: "about:blank", background: true }', background_source)
        self.assertIn('Target.closeTarget", { targetId }', background_source)
        self.assertIn("document.body.innerText || document.body.textContent", group_source)
        self.assertIn("about_context", group_source)
        self.assertIn('meta[name="description"], meta[property="og:description"]', group_source)
        self.assertIn("aboutUrl.href", group_source)
        self.assertIn("expandFacebookSeeMore", group_source)
        self.assertIn("facebookAccessibilityText", group_source)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the Facebook bridge")
    def test_group_about_parser_separates_rules(self) -> None:
        script = (
            "const { parseFacebookGroupSections } = require('./facebook_chrome_bridge.js');"
            "console.log(JSON.stringify(parseFacebookGroupSections('About\\nLocal buying and selling.\\nPrivate\\nGroup rules from the admins\\n1\\nInclude a price\\n2\\nNo spam\\nActivity\\n10 posts today')));"
        )
        completed = subprocess.run(
            [shutil.which("node"), "-e", script], cwd=str(facebook_chrome_bridge.ROOT),
            capture_output=True, text=True, check=True,
        )
        parsed = json.loads(completed.stdout)
        self.assertIn("Local buying and selling", parsed["about"])
        self.assertIn("Include a price", parsed["rules_text"])
        self.assertIn("No spam", parsed["rules_text"])
        self.assertNotIn("10 posts today", parsed["rules_text"])

        inline_script = (
            "const { parseFacebookGroupSections } = require('./facebook_chrome_bridge.js');"
            "console.log(JSON.stringify(parseFacebookGroupSections('Joined More About About this group No spam. Please include a firm price. Admins may remove prohibited posts. Public Anyone can see who is in the group. History Group created yesterday')));"
        )
        inline_completed = subprocess.run(
            [shutil.which("node"), "-e", inline_script], cwd=str(facebook_chrome_bridge.ROOT),
            capture_output=True, text=True, check=True,
        )
        inline = json.loads(inline_completed.stdout)
        self.assertIn("firm price", inline["about"])
        self.assertEqual(inline["rules_text"], "")
        self.assertNotIn("History", inline["rules_text"])

        details_script = (
            "const { parseFacebookGroupSections } = require('./facebook_chrome_bridge.js');"
            "console.log(JSON.stringify(parseFacebookGroupSections('About this group\\nLocal buying and selling.\\nPrivate\\nOnly members can see who is in the group and what they post.\\nVisible\\nAnyone can find this group.\\nHistory\\nGroup created on July 11, 2012 See more\\nTags\\nFashion\\nKids Clothing & Accessories\\nEugene, Oregon\\nGroup rules from the admins\\n1\\nInclude a price')));"
        )
        details_completed = subprocess.run(
            [shutil.which("node"), "-e", details_script], cwd=str(facebook_chrome_bridge.ROOT),
            capture_output=True, text=True, check=True,
        )
        details = json.loads(details_completed.stdout)
        self.assertIn("Local buying and selling", details["about"])
        self.assertIn("Private", details["about"])
        self.assertIn("Only members can see", details["about"])
        self.assertIn("Visible", details["about"])
        self.assertIn("Group created on July 11, 2012", details["about"])
        self.assertIn("Fashion", details["about"])
        self.assertIn("Kids Clothing & Accessories", details["about"])
        self.assertIn("Eugene, Oregon", details["about"])
        self.assertNotIn("See more", details["about"])
        self.assertNotIn("Include a price", details["about"])
        self.assertIn("Private", details["profile"]["privacy"])
        self.assertIn("Visible", details["profile"]["visibility"])
        self.assertIn("July 11, 2012", details["profile"]["history"])
        self.assertIn("Fashion", details["profile"]["tags"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the Facebook bridge")
    def test_group_about_parser_detects_collapsed_see_more_text(self) -> None:
        script = (
            "const { isCollapsedFacebookSection } = require('./facebook_chrome_bridge.js');"
            "console.log(JSON.stringify(["
            "isCollapsedFacebookSection('Local buying and selling. See more'),"
            "isCollapsedFacebookSection('Local buying and selling. See less'),"
            "isCollapsedFacebookSection('See more details in the rules.')"
            "]));"
        )
        completed = subprocess.run(
            [shutil.which("node"), "-e", script], cwd=str(facebook_chrome_bridge.ROOT),
            capture_output=True, text=True, check=True,
        )
        collapsed, expanded, sentence = json.loads(completed.stdout)
        self.assertTrue(collapsed)
        self.assertFalse(expanded)
        self.assertFalse(sentence)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the Facebook bridge")
    def test_group_access_classifier_uses_visible_membership_controls(self) -> None:
        script = (
            "const { classifyFacebookGroupAccess } = require('./facebook_chrome_bridge.js');"
            "console.log(JSON.stringify(["
            "classifyFacebookGroupAccess(['Joined', 'Invite']),"
            "classifyFacebookGroupAccess(['Cancel request']),"
            "classifyFacebookGroupAccess(['Join group']),"
            "classifyFacebookGroupAccess(['Share'])"
            "]));"
        )
        completed = subprocess.run([shutil.which("node"), "-e", script], cwd=str(facebook_chrome_bridge.ROOT), capture_output=True, text=True, check=True)
        joined, pending, not_joined, unknown = json.loads(completed.stdout)
        self.assertEqual(joined["status"], "joined")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(not_joined["status"], "not_joined")
        self.assertEqual(unknown["status"], "unknown")

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
