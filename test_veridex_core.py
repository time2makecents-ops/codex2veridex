from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from veridex_core import VeridexStore, classify_task


class VeridexCoreTests(unittest.TestCase):
    def test_creates_one_local_account_with_workspace_session_and_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            store.append_message(workspace_id, session_id, "user", "Remember this chat.", speaker="You")
            store.append_message(
                workspace_id,
                session_id,
                "assistant",
                "Saved in the transcript.",
                provider="codex_cli",
                model="gpt-5.6-sol",
                reasoning_effort="high",
                task_type="coding",
            )
            restored = store.bootstrap(workspace_id, session_id)
            self.assertEqual(restored["account"]["user_id"], "local-user")
            self.assertEqual(len(restored["messages"]), 2)
            self.assertEqual(restored["messages"][1]["model"], "gpt-5.6-sol")
            transcript = Path(temporary) / "workspaces" / workspace_id / "sessions" / session_id / "transcript.ndjson"
            self.assertTrue(transcript.is_file())

    def test_workspaces_and_sessions_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            first = store.ensure_default()
            second_workspace = store.create_workspace("Second")
            second_session = store.create_session(second_workspace["workspace_id"], "Other chat")
            store.append_message(second_workspace["workspace_id"], second_session["session_id"], "user", "Only second")
            first_messages = store.load_messages(first["workspace"]["workspace_id"], first["session"]["session_id"])
            self.assertEqual(first_messages, [])

    def test_task_routing_uses_strong_models_for_code_and_lower_route_for_ui_checks(self) -> None:
        self.assertEqual(classify_task("Refactor this Python service"), "coding")
        self.assertEqual(classify_task("Plan the system architecture"), "planning")
        self.assertEqual(classify_task("Run a smoke check of the UI"), "testing")
        self.assertEqual(classify_task("hello"), "simple")


if __name__ == "__main__":
    unittest.main()
