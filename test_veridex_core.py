from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from veridex_core import VeridexStore, classify_task, repair_text_encoding, transcript_context


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
            self.assertEqual(restored["session"]["active_room"], "lobby")
            self.assertEqual(restored["session"]["active_persona"], "Receptionist")
            self.assertTrue(any(room["id"] == "art_department" for room in restored["rooms"]))
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
        self.assertEqual(
            classify_task("check social media and google for a band called Stella Jones"),
            "search_synthesis",
        )
        self.assertEqual(
            classify_task("take the file adam.png and have the character sitting next to an animated dog"),
            "media",
        )

    def test_repairs_windows_mojibake_in_existing_transcript_text(self) -> None:
        self.assertEqual(repair_text_encoding("Youâ€™re in the Lobby."), "You’re in the Lobby.")

    def test_transcript_context_is_bounded_for_model_prompt_economy(self) -> None:
        messages = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "text": f"message {index} " + ("x" * 2000),
                "room": "art_department",
                "execution_evidence": [{"output": "large ignored output" * 200}],
            }
            for index in range(20)
        ]

        context = transcript_context(messages)

        recent = context["recent_transcript"]
        self.assertLessEqual(len(recent), 8)
        self.assertNotIn("execution_evidence", recent[-1])
        self.assertLessEqual(max(len(row["text"]) for row in recent), 700)
        self.assertIn("message 19", recent[-1]["text"])

    def test_session_files_are_saved_locally_and_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            saved = store.save_file(workspace_id, session_id, "../notes.txt", b"hello", "text/plain")
            self.assertEqual(saved["name"], "notes.txt")
            self.assertEqual(saved["artifact_number"], 1)
            self.assertEqual(Path(saved["path"]).read_bytes(), b"hello")
            self.assertIn(str(Path(temporary) / "workspaces" / workspace_id / "files" / "uploads" / session_id), saved["path"])
            self.assertEqual(saved["kind"], "upload")
            self.assertEqual(saved["scope"], "session")
            self.assertEqual(saved["scope_ref"], session_id)
            self.assertEqual(store.resolve_files(workspace_id, session_id, [saved["file_id"]])[0]["name"], "notes.txt")
            self.assertEqual(store.bootstrap(workspace_id, session_id)["files"][0]["size"], 5)
            self.assertEqual(store.list_artifact_ledger(workspace_id)[0]["file_id"], saved["file_id"])
            self.assertEqual(saved["source"], "upload")
            self.assertEqual(len(saved["sha256"]), 64)

    def test_generated_image_is_validated_imported_hashed_and_ledgered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            store.set_room(workspace_id, session_id, "art_department")
            staging = store.prepare_generated_output_dir(workspace_id, session_id, "msg_test")
            image = staging / "ant-drummer.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"verified-image-payload")

            imported = store.import_generated_artifacts(workspace_id, session_id, staging)

            self.assertEqual(len(imported), 1)
            self.assertEqual(imported[0]["name"], "ant-drummer.png")
            self.assertEqual(imported[0]["source"], "generated")
            self.assertEqual(imported[0]["kind"], "generated_image")
            self.assertEqual(imported[0]["scope"], "room")
            self.assertEqual(imported[0]["scope_ref"], "art_department")
            self.assertEqual(imported[0]["uploaded_by_session_id"], session_id)
            self.assertEqual(len(imported[0]["sha256"]), 64)
            self.assertTrue(Path(imported[0]["path"]).is_file())
            self.assertIn(
                str(Path(temporary) / "workspaces" / workspace_id / "files" / "generated" / "art_department"),
                imported[0]["path"],
            )
            self.assertNotIn(str(store.files_dir(workspace_id, session_id)), imported[0]["path"])
            resolved = store.resolve_files(workspace_id, session_id, [imported[0]["file_id"]])
            self.assertEqual(resolved[0]["file_id"], imported[0]["file_id"])
            ledger = store.list_artifact_ledger(workspace_id)
            self.assertEqual(ledger[0]["sha256"], imported[0]["sha256"])
            self.assertEqual(ledger[0]["source_path"], str(image.resolve()))
            self.assertEqual(ledger[0]["kind"], "generated_image")
            self.assertEqual(ledger[0]["scope"], "room")
            self.assertEqual(ledger[0]["scope_ref"], "art_department")

    def test_invalid_generated_image_is_not_imported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            staging = store.prepare_generated_output_dir(workspace_id, session_id, "msg_invalid")
            (staging / "not-really-an-image.png").write_bytes(b"plain text")
            self.assertEqual(store.import_generated_artifacts(workspace_id, session_id, staging), [])
            self.assertEqual(store.list_artifact_ledger(workspace_id), [])

    def test_discovers_only_new_generated_files_with_matching_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            store.set_room(workspace_id, session_id, "art_department")
            before_ids = {str(row["file_id"]) for row in store.list_files(workspace_id, session_id)}

            staging = store.prepare_generated_output_dir(workspace_id, session_id, "custom_dir")
            image = staging / "adam_with_animated_dog.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"verified-image-payload")
            imported = store.import_generated_artifacts(workspace_id, session_id, staging)[0]

            discovered = store.verified_new_generated_files(
                workspace_id,
                session_id,
                before_ids,
                "art_department",
            )

            self.assertEqual([row["file_id"] for row in discovered], [imported["file_id"]])
            self.assertEqual(discovered[0]["kind"], "generated_image")
            self.assertEqual(discovered[0]["scope_ref"], "art_department")

    def test_room_transition_is_validated_persisted_and_session_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            first_session_id = initial["session"]["session_id"]
            second = store.create_session(workspace_id, "Second")
            transition = store.set_room(workspace_id, first_session_id, "art_department")
            self.assertEqual(transition["active_persona"], "Creative Director")
            self.assertEqual(store.find_session(first_session_id)["active_room"], "art_department")
            self.assertEqual(store.find_session(second["session_id"])["active_room"], "lobby")
            with self.assertRaises(ValueError):
                store.set_room(workspace_id, first_session_id, "imaginary_room")

    def test_governance_state_pending_and_incidents_are_workspace_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = VeridexStore(Path(temporary))
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            state = store.ensure_governance_state(workspace_id)
            self.assertTrue(state["navigator_always_present"])
            self.assertTrue(state["gates"]["PREFLIGHT"])
            store.set_pending_governance(workspace_id, session_id, {"kind": "durability_scope"})
            self.assertEqual(store.pending_governance(workspace_id, session_id)["kind"], "durability_scope")
            incident = store.append_governance_incident(
                workspace_id,
                session_id,
                gate_ids=["GATE-CONFLICT"],
                attempted_action="replace canon",
                reason="unsupported",
            )
            self.assertEqual(store.list_governance_incidents(workspace_id)[0]["incident_id"], incident["incident_id"])
            memo = store.append_governance_memo(workspace_id, session_id, "Remember concise answers")
            self.assertEqual(store.list_governance_memos(workspace_id)[0]["memo_id"], memo["memo_id"])
            self.assertEqual(memo["app_commit"], "unverified")


if __name__ == "__main__":
    unittest.main()
