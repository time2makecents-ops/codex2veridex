from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import veridex_server
from veridex_core import VeridexStore


class VeridexServerTests(unittest.TestCase):
    def test_chat_saves_exact_model_route_with_no_external_app_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            payload = {
                "workspace_id": initial["workspace"]["workspace_id"],
                "session_id": initial["session"]["session_id"],
                "text": "Debug this Python function",
            }
            response = {
                "ok": True,
                "provider": "codex_cli",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "task_type": "coding",
                "text": "Here is the fix.",
            }
            with patch.object(veridex_server, "STORE", store), patch.object(veridex_server, "invoke_codex", return_value=response):
                result = veridex_server.chat_response(payload)
            self.assertEqual(result["model"], "gpt-5.6-sol")
            self.assertEqual(result["reasoning_effort"], "high")
            rows = store.load_messages(payload["workspace_id"], payload["session_id"])
            self.assertEqual(rows[-1]["provider"], "codex_cli")
            self.assertEqual(rows[-1]["task_type"], "coding")
            self.assertEqual(rows[-1]["room"], "lobby")
            self.assertEqual(rows[-1]["speaker"], "Receptionist")

    def test_new_workspace_prompt_identifies_lobby_not_my_office(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            workspace = store.create_workspace("Fresh workspace")
            session = store.create_session(workspace["workspace_id"], "New session")
            response = {
                "ok": True,
                "provider": "codex_cli",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "low",
                "task_type": "simple",
                "text": "You’re in the Lobby.",
            }
            with patch.object(veridex_server, "STORE", store), patch.object(
                veridex_server, "invoke_codex", return_value=response
            ) as invoke:
                veridex_server.chat_response(
                    {"workspace_id": workspace["workspace_id"], "session_id": session["session_id"], "text": "Where am I?"}
                )
            prompt = invoke.call_args.args[0]["system_prompt"]
            self.assertIn("active room is Lobby", prompt)
            self.assertNotIn("My Office", prompt)


if __name__ == "__main__":
    unittest.main()
