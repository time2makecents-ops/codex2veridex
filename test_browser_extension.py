from __future__ import annotations

import base64
import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from browser_extension import BrowserExtensionBroker, BrowserRelayError, origin
from chrome_native_host import EXTENSION_ID, load_settings, read_message, relay, write_message


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.scope = {"workspace_id": "ws_1", "session_id": "sess_1", "room": "lobby"}
        self.time = 10.0
        self.events = []
        self.denied = False
        self.broker = BrowserExtensionBroker(self.context, lambda *_: {"allowed": not self.denied},
            lambda scope, event: self.events.append(event), clock=lambda: self.time)
        self.selection = {"scope": dict(self.scope), "url": "https://example.test/", "tab_id": 7}
        self.poll()

    def context(self, args):
        for key, value in self.scope.items():
            if args.get(key) != value:
                raise ValueError("Scope changed")
        return dict(self.scope)

    def poll(self, event=None, connection="c1", selection=True):
        return self.broker.relay({"connection_id": connection,
            "selection": self.selection if selection else None, **({"event": event} if event else {})})

    def submit(self, action="read", **extra):
        return self.broker.call(action, {**self.scope, "intent": "Inspect the authorized test page", **extra})

    def observation(self, snapshot="s1"):
        return {"url": "https://example.test/", "document_id": "d1", "snapshot_id": snapshot,
            "text": "Synthetic page", "elements": [{"target_id": "t1", "tag": "button", "label": "Show details"}]}

    def complete_read(self):
        job = self.submit()
        self.poll()
        self.poll({"type": "claim", "request_id": job["request_id"]})
        self.poll({"type": "result", "request_id": job["request_id"],
            "result": {"status": "completed", "observation": self.observation()}})
        return job

    def test_read_claim_result_and_scoped_status(self):
        job = self.complete_read()
        status = self.broker.call("status", {**self.scope, "request_id": job["request_id"]})
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["result"]["observation"]["document_id"], "d1")
        self.assertNotIn("command", status)

    def test_missing_scope_and_intent_are_rejected(self):
        with self.assertRaises(ValueError):
            self.broker.call("read", {})
        with self.assertRaisesRegex(ValueError, "intent"):
            self.broker.call("read", self.scope)

    def test_navigator_denial_never_queues_work(self):
        self.denied = True
        self.assertEqual(self.submit()["status"], "blocked")
        self.assertFalse(self.broker.jobs)

    def test_mutation_requires_selected_tab(self):
        self.poll(selection=False)
        with self.assertRaisesRegex(ValueError, "Select"):
            self.submit("navigate", url="https://example.test/next")

    def test_mutation_requires_local_approval_at_claim(self):
        job = self.submit("navigate", url="https://example.test/next")
        self.poll()
        with self.assertRaisesRegex(ValueError, "local approval"):
            self.poll({"type": "claim", "request_id": job["request_id"]})
        result = self.poll({"type": "claim", "request_id": job["request_id"], "approved_locally": True})
        self.assertTrue(result["execute"])

    def test_guard_rechecked_at_execution(self):
        job = self.submit()
        self.poll()
        self.denied = True
        result = self.poll({"type": "claim", "request_id": job["request_id"]})
        self.assertNotIn("execute", result)
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "blocked")

    def test_click_requires_latest_scoped_observation(self):
        self.complete_read()
        job = self.submit("click", document_id="d1", snapshot_id="s1", target_id="t1")
        command = self.poll()["command"]
        self.assertEqual(command["request_id"], job["request_id"])
        self.assertEqual(command["target_preview"]["label"], "Show details")
        with self.assertRaisesRegex(ValueError, "latest observation"):
            self.submit("click", document_id="d1", snapshot_id="old", target_id="t1")

    def test_other_tab_cannot_reuse_observation(self):
        self.complete_read()
        self.selection["tab_id"] = 8
        self.poll()
        with self.assertRaisesRegex(ValueError, "latest observation"):
            self.submit("fill", document_id="d1", snapshot_id="s1", target_id="t1", text="hello")

    def test_room_change_stops_pending_work(self):
        job = self.submit()
        self.scope["room"] = "museum"
        self.poll(selection=False)
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "stopped")

    def test_stop_before_claim_prevents_execution(self):
        job = self.submit()
        self.poll()
        stopped = self.broker.call("stop", {**self.scope, "request_id": job["request_id"]})
        self.assertEqual(stopped["status"], "stopped")
        self.assertNotIn("execute", self.poll({"type": "claim", "request_id": job["request_id"]}))

    def test_stop_after_claim_reports_unknown_not_false_stopped(self):
        job = self.submit()
        self.poll()
        self.poll({"type": "claim", "request_id": job["request_id"]})
        status = self.broker.call("stop", {**self.scope, "request_id": job["request_id"]})
        self.assertEqual(status["status"], "outcome_unknown")

    def test_connection_replacement_does_not_replay(self):
        job = self.submit()
        self.poll()
        self.time += 13
        self.assertNotIn("command", self.poll(connection="replacement"))
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "stopped")

    def test_idle_other_profile_cannot_displace_selected_connection(self):
        job = self.submit()
        self.poll()
        self.time += 1
        result = self.poll(connection="other-profile", selection=False)
        self.assertEqual(result["connection_status"], "another_connection_selected")
        self.assertEqual(self.broker.connection["connection_id"], "c1")
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "awaiting_browser")
        self.assertEqual(self.broker.last_seen, 10)

    def test_another_selected_connection_requires_existing_owner_to_disconnect(self):
        with self.assertRaises(BrowserRelayError) as error:
            self.poll(connection="other-profile")
        self.assertEqual(error.exception.code, "connection_in_use")
        self.assertEqual(self.broker.connection["connection_id"], "c1")

    def test_invalid_scope_cannot_refresh_heartbeat_or_cancel_work(self):
        job = self.submit()
        self.poll()
        self.time += 1
        bad = {"scope": {**self.scope, "room": "Art_Room"}, "url": "https://example.test/", "tab_id": 7}
        with self.assertRaises(ValueError):
            self.broker.relay({"connection_id": "invalid", "selection": bad})
        self.assertEqual(self.broker.connection["connection_id"], "c1")
        self.assertEqual(self.broker.last_seen, 10)
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "awaiting_browser")

    def test_disconnect_and_deadline_expire_pending_jobs(self):
        job = self.submit()
        self.poll()
        self.time += 13
        self.broker.call("status", self.scope)
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "stopped")
        job = self.submit()
        self.time += 121
        self.broker.call("status", self.scope)
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "stopped")

    def test_human_approval_survives_chat_delay_but_still_expires(self):
        job = self.submit("navigate", url="https://example.test/next")
        self.poll()
        for _ in range(30):
            self.time += 10
            self.poll()
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "awaiting_browser")
        for _ in range(31):
            self.time += 10
            self.poll()
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "stopped")

    def test_unclaimed_approval_is_redelivered_without_duplicate_execution(self):
        job = self.submit("navigate", url="https://example.test/next")
        first = self.poll()
        deadline = self.broker.jobs[job["request_id"]]["deadline"]
        self.time += 2
        repeated = self.poll()
        self.assertEqual(repeated["command"]["request_id"], first["command"]["request_id"])
        self.assertEqual(self.broker.jobs[job["request_id"]]["deadline"], deadline)
        self.poll({"type": "claim", "request_id": job["request_id"], "approved_locally": True})
        self.assertNotIn("command", self.poll())
        with self.assertRaises(ValueError):
            self.poll({"type": "claim", "request_id": job["request_id"], "approved_locally": True})
        self.assertEqual(sum(event["status"] == "running" for event in self.events), 1)

    def test_approval_wait_does_not_extend_execution_deadline(self):
        job = self.submit("navigate", url="https://example.test/next")
        self.poll()
        for _ in range(30):
            self.time += 10
            self.poll()
        self.poll({"type": "claim", "request_id": job["request_id"], "approved_locally": True})
        for _ in range(13):
            self.time += 10
            self.poll()
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "outcome_unknown")

    def test_result_before_claim_and_fake_completion_rejected(self):
        job = self.submit()
        self.poll()
        with self.assertRaisesRegex(ValueError, "before"):
            self.poll({"type": "result", "request_id": job["request_id"], "result": {"status": "completed"}})
        self.poll({"type": "claim", "request_id": job["request_id"]})
        with self.assertRaisesRegex(ValueError, "observation"):
            self.poll({"type": "result", "request_id": job["request_id"], "result": {"status": "completed"}})

    def test_unverified_click_cannot_report_completed(self):
        job = self.submit("navigate", url="https://example.test/next")
        self.poll()
        self.poll({"type": "claim", "request_id": job["request_id"], "approved_locally": True})
        with self.assertRaisesRegex(ValueError, "verified effect"):
            self.poll({"type": "result", "request_id": job["request_id"],
                "result": {"status": "completed", "observation": self.observation()}})

    def test_result_postflight_can_block_evidence(self):
        self.broker.postflight = lambda *_: {"allowed": False}
        job = self.complete_read()
        self.assertEqual(self.broker.jobs[job["request_id"]]["status"], "blocked")

    def test_request_id_cannot_be_replayed_and_other_scope_cannot_read(self):
        job = self.submit()
        with self.assertRaisesRegex(ValueError, "reuse"):
            self.submit(request_id=job["request_id"])
        with self.assertRaises(ValueError):
            self.broker.call("status", {**self.scope, "session_id": "other", "request_id": job["request_id"]})

    def test_queue_bound_and_audit_has_no_content(self):
        for _ in range(16):
            self.submit()
        with self.assertRaisesRegex(ValueError, "full"):
            self.submit()
        self.assertNotIn("example.test", json.dumps(self.events))
        self.assertNotIn("Inspect the authorized", json.dumps(self.events))


class NativeProtocolTests(unittest.TestCase):
    def test_native_http_errors_are_actionable_without_echoing_private_input(self):
        from urllib.error import HTTPError
        for code, message in [("room_changed", "room"), ("connection_in_use", "Another Chrome"), ("scope_unavailable", "workspace")]:
            error = HTTPError("http://127.0.0.1/relay", 409, "Conflict", {},
                io.BytesIO(json.dumps({"error_code": code, "error": "synthetic-private-canary"}).encode()))
            result = relay({"rpc_id": "r1"}, {"base_url": "http://127.0.0.1:8765", "token": "synthetic" * 8}, "c1", Mock(side_effect=error))
            self.assertIn(message, result["error"])
            self.assertNotIn("synthetic-private-canary", result["error"])
    def test_round_trip_unicode_and_clean_eof(self):
        stream = io.BytesIO()
        write_message(stream, {"text": "Synthetic café"})
        stream.seek(0)
        self.assertEqual(read_message(stream), {"text": "Synthetic café"})
        self.assertIsNone(read_message(stream))

    def test_truncated_oversized_and_nonobject_messages(self):
        for data, error in [(b"\x04", EOFError), (struct.pack("<I", 999999), ValueError),
                            (struct.pack("<I", 2) + b"[]", ValueError)]:
            with self.assertRaises(error):
                read_message(io.BytesIO(data))

    def test_settings_require_loopback_and_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for value in ({"base_url": "https://example.test", "token": "test" * 12},
                          {"base_url": "http://127.0.0.1:8765", "token": "short"}):
                path.write_text(json.dumps(value), "utf-8")
                with self.assertRaises(ValueError):
                    load_settings(path)

    def test_extension_cannot_choose_relay_target_or_credentials(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"active_request_ids": []}'
        opener = Mock(return_value=response)
        result = relay({"rpc_id": "rpc1", "base_url": "https://untrusted.test", "token": "attacker", "connection_id": "fake"},
            {"base_url": "http://127.0.0.1:8765", "token": "synthetic" * 8}, "actual", opener)
        request = opener.call_args.args[0]
        self.assertTrue(request.full_url.startswith("http://127.0.0.1:8765/"))
        self.assertEqual(json.loads(request.data)["connection_id"], "actual")
        self.assertEqual(result["rpc_id"], "rpc1")

    def test_public_manifest_key_matches_fixed_extension_id(self):
        manifest = json.loads((Path(__file__).parent / "chrome_extension" / "manifest.json").read_text("utf-8"))
        digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
        self.assertEqual("".join(chr(97 + int(char, 16)) for char in digest), EXTENSION_ID)
        self.assertNotIn("debugger", manifest["permissions"])
        self.assertNotIn("<all_urls>", manifest.get("host_permissions", []))

    def test_preparation_never_overwrites_unrelated_existing_files(self):
        from scripts.prepare_browser_extension import write_owned
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prepared.cmd"
            path.write_bytes(b"unrelated existing content")
            with self.assertRaisesRegex(ValueError, "review"):
                write_owned(path, b"new content")
            self.assertEqual(path.read_bytes(), b"unrelated existing content")
            path.write_bytes(b"identical text\r\n")
            write_owned(path, b"identical text\n")
            self.assertEqual(path.read_bytes(), b"identical text\r\n")


class ServerIntegrationTests(unittest.TestCase):
    def test_actual_mcp_http_native_stdio_round_trip_without_registration(self):
        import veridex_server as server
        from veridex_core import VeridexStore
        from veridex_mcp import VeridexClient

        class QuietHandler(server.VeridexHandler):
            def log_message(self, *_):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = VeridexStore(root / "store")
            state = store.ensure_default()
            scope = {"workspace_id": state["workspace"]["workspace_id"],
                     "session_id": state["session"]["session_id"], "room": "lobby"}
            broker = BrowserExtensionBroker(server.browser_extension_context, server.browser_extension_guard,
                server.browser_extension_audit, server.browser_extension_postflight)
            with patch.object(server, "STORE", store), patch.object(server, "ROOT", root), patch.object(server, "BROWSER_EXTENSION", broker), patch.dict("os.environ", {"VERIDEX_CODEX_TOKEN": "synthetic-mcp-token"}):
                http = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
                thread = threading.Thread(target=http.serve_forever, daemon=True)
                thread.start()
                try:
                    settings = root / ".runtime" / "browser-extension" / "settings.json"
                    settings.parent.mkdir(parents=True)
                    base_url = f"http://127.0.0.1:{http.server_address[1]}"
                    settings.write_text(json.dumps({"base_url": base_url, "token": "synthetic-native-token" * 3}), "utf-8")
                    client = VeridexClient(base_url=base_url, token="synthetic-mcp-token",
                        session_id=scope["session_id"], workspace_id=scope["workspace_id"])
                    job = client.call("browser.read", {"intent": "Read the selected synthetic test page"})["structuredContent"]
                    selection = {"scope": {key: value for key, value in scope.items() if key != "room"},
                                 "tab_id": 7, "url": "https://example.test/"}
                    stream = io.BytesIO()
                    for message in [
                        {"rpc_id": "bad-room", "selection": {**selection, "scope": {**scope, "room": "Art_Room"}}},
                        {"rpc_id": "poll", "selection": selection},
                        {"rpc_id": "claim", "selection": selection, "event": {"type": "claim", "request_id": job["request_id"]}},
                        {"rpc_id": "result", "selection": selection, "event": {"type": "result", "request_id": job["request_id"],
                            "result": {"status": "completed", "observation": {"document_id": "d1", "snapshot_id": "s1",
                                "url": "https://example.test/", "text": "Synthetic fixture", "elements": []}}}},
                    ]:
                        write_message(stream, message)
                    child = subprocess.run([sys.executable, str(Path(__file__).parent / "chrome_native_host.py"),
                        f"chrome-extension://{EXTENSION_ID}/", "--config", str(settings)],
                        input=stream.getvalue(), capture_output=True, timeout=20)
                    self.assertEqual(child.returncode, 0, child.stderr.decode())
                    replies = io.BytesIO(child.stdout)
                    self.assertIn("room", read_message(replies)["error"])
                    first_reply = read_message(replies)
                    self.assertEqual(first_reply["command"]["request_id"], job["request_id"])
                    self.assertEqual(first_reply["selection"]["scope"]["room"], "lobby")
                    self.assertTrue(read_message(replies)["execute"])
                    self.assertEqual(read_message(replies)["rpc_id"], "result")
                    status = client.call("browser.status", {"request_id": job["request_id"]})["structuredContent"]
                    self.assertEqual(status["status"], "completed")
                    self.assertNotIn("synthetic-native-token", child.stdout.decode(errors="replace"))
                finally:
                    http.shutdown()
                    http.server_close()
                    thread.join(timeout=5)

    def test_browser_tools_use_existing_call_shape(self):
        import veridex_server as server
        handler = object.__new__(server.VeridexHandler)
        with patch.object(server.BROWSER_EXTENSION, "call", return_value={"status": "disconnected"}) as call:
            result = handler._call_tool({"tool": "browser.status", "arguments": {"session_id": "s"}})
        call.assert_called_once_with("status", {"session_id": "s"})
        self.assertEqual(result["structuredContent"]["status"], "disconnected")
        self.assertTrue(all(any(row["name"] == "browser." + action for row in server.TOOLS)
                            for action in ("status", "read", "navigate", "click", "fill", "stop")))

    def test_relay_auth_fails_closed_for_remote_origin_or_missing_secret(self):
        import veridex_server as server
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "ROOT", Path(directory)):
            settings = Path(directory) / ".runtime" / "browser-extension" / "settings.json"
            handler = SimpleNamespace(client_address=("127.0.0.1", 1), headers={"Authorization": "Bearer " + "test" * 12})
            self.assertFalse(server.browser_extension_relay_authorized(handler))
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"token": "test" * 12}), "utf-8")
            self.assertTrue(server.browser_extension_relay_authorized(handler))
            handler.headers["Origin"] = "http://127.0.0.1:8765"
            self.assertFalse(server.browser_extension_relay_authorized(handler))
            handler.headers.pop("Origin")
            handler.client_address = ("192.168.1.2", 1)
            self.assertFalse(server.browser_extension_relay_authorized(handler))

    def test_real_store_context_governance_and_metadata_audit(self):
        import veridex_server as server
        from veridex_core import VeridexStore
        with tempfile.TemporaryDirectory() as directory:
            store = VeridexStore(Path(directory))
            state = store.ensure_default()
            args = {"workspace_id": state["workspace"]["workspace_id"], "session_id": state["session"]["session_id"]}
            with patch.object(server, "STORE", store):
                scope = server.browser_extension_context(args)
                with self.assertRaises(ValueError):
                    server.browser_extension_context({**args, "room": "museum"})
                with patch.object(server, "access_mode", return_value="read_only"):
                    self.assertFalse(server.browser_extension_guard(scope, "click", {"intent": "Click synthetic button"})["allowed"])
                server.browser_extension_audit(scope, {"request_id": "synthetic", "status": "queued"})
                self.assertTrue((store.workspace_dir(args["workspace_id"]) / "browser-extension-audit.ndjson").is_file())


if __name__ == "__main__":
    unittest.main()
