from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_gateway
from request_control import RequestCancelled


class CodexGatewayTests(unittest.TestCase):
    def test_full_access_is_the_default_and_read_only_remains_explicit(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(codex_gateway.access_mode(), "full")
        with patch.dict(os.environ, {"VERIDEX_CODEX_ACCESS_MODE": "read_only"}, clear=True):
            self.assertEqual(codex_gateway.access_mode(), "read_only")
        with patch.dict(os.environ, {"VERIDEX_CODEX_ACCESS_MODE": "invalid"}, clear=True):
            self.assertEqual(codex_gateway.access_mode(), "full")

    def test_selects_strong_models_for_coding_and_planning(self) -> None:
        coding = codex_gateway.select_model("coding")
        planning = codex_gateway.select_model("architecture")
        self.assertEqual((coding.model, coding.reasoning_effort), ("gpt-5.6-sol", "high"))
        self.assertEqual((planning.model, planning.reasoning_effort), ("gpt-5.6-sol", "high"))
        deep_search = codex_gateway.select_model("search_deep")
        self.assertEqual((deep_search.model, deep_search.reasoning_effort), ("gpt-5.6-sol", "high"))
        resume = codex_gateway.select_model("resume_generation")
        self.assertEqual((resume.model, resume.reasoning_effort), ("gpt-5.6-sol", "high"))

    def test_selects_lower_cost_plan_models_for_general_and_simple_chat(self) -> None:
        conversation = codex_gateway.select_model("conversation")
        simple = codex_gateway.select_model("simple")
        testing = codex_gateway.select_model("testing")
        self.assertEqual((conversation.model, conversation.reasoning_effort), ("gpt-5.6-terra", "medium"))
        self.assertEqual((simple.model, simple.reasoning_effort), ("gpt-5.6-luna", "low"))
        self.assertEqual((testing.model, testing.reasoning_effort), ("gpt-5.6-luna", "low"))

    def test_extracts_last_agent_message_from_json_events(self) -> None:
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "abc"}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "final"}}),
            ]
        )
        self.assertEqual(codex_gateway.extract_agent_text(stdout), "final")

    def test_extracts_bounded_execution_evidence_from_json_events(self) -> None:
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "status": "completed",
                            "command": "rg --files",
                            "aggregated_output": "README.md\nveridex_server.py",
                        },
                    }
                ),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Found files"}}),
            ]
        )
        evidence = codex_gateway.extract_execution_evidence(stdout)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["type"], "command_execution")
        self.assertEqual(evidence[0]["command"], "rg --files")
        self.assertIn("README.md", evidence[0]["output"])

    def test_prompt_embeds_personal_governance_rules(self) -> None:
        prompt = codex_gateway.build_prompt(
            {"system_prompt": "system", "user_prompt": "hello", "context": {}},
            codex_gateway.select_model("conversation"),
        )
        self.assertIn("never switch rooms implicitly", prompt)
        self.assertIn("tool-backed evidence", prompt)
        self.assertIn("durable memory", prompt)

    def test_governed_context_is_compacted_to_token_economy_budget(self) -> None:
        prompt = codex_gateway.build_prompt(
            {
                "system_prompt": "system",
                "user_prompt": "hello",
                "context": {
                    "recent_transcript": [
                        {"role": "assistant", "text": "x" * 4000, "room": "art_department"}
                        for _ in range(12)
                    ],
                    "available_rooms": [{"id": f"room_{index}", "description": "y" * 800} for index in range(20)],
                    "governance": {"large": "z" * 20000},
                },
            },
            codex_gateway.select_model("conversation"),
        )

        self.assertLess(len(prompt), 18000)
        self.assertIn("Governed context", prompt)
        self.assertIn("User request:\nhello", prompt)

    def test_context_compaction_preserves_high_value_fields(self) -> None:
        prompt = codex_gateway.build_prompt(
            {
                "system_prompt": "system",
                "user_prompt": "what did we discuss?",
                "context": {
                    "available_rooms": [{"id": f"room_{index}", "description": "y" * 2000} for index in range(20)],
                    "governance": {"large": "z" * 20000},
                    "current_local_date": "2026-08-12",
                    "event_time_scope": "all_relevant_dates",
                    "recent_transcript": [
                        {"role": "user", "text": "keep this recent topic", "room": "art_department"}
                    ],
                },
            },
            codex_gateway.select_model("conversation"),
        )

        self.assertLess(len(prompt), 18000)
        self.assertIn("keep this recent topic", prompt)
        self.assertIn("2026-08-12", prompt)
        self.assertIn("all_relevant_dates", prompt)

    def test_media_prompt_requires_copy_to_exact_veridex_output_directory(self) -> None:
        output_dir = r"C:\codex2veridex\data\workspaces\ws\sessions\sess\generated_staging\msg"
        prompt = codex_gateway.build_prompt(
            {
                "system_prompt": "system",
                "user_prompt": "create an image",
                "context": {},
                "artifact_output_dir": output_dir,
            },
            codex_gateway.select_model("media"),
        )
        self.assertIn(output_dir, prompt)
        self.assertIn("copy each final image", prompt)
        self.assertIn("Desktop", prompt)
        self.assertIn("default Codex generated-images directory", prompt)
        self.assertIn("no verified file was created", prompt)

    def test_document_prompt_supports_verified_spreadsheets(self) -> None:
        output_dir = r"C:\codex2veridex\data\workspaces\ws\sessions\sess\generated_staging\msg"
        prompt = codex_gateway.build_prompt(
            {
                "system_prompt": "system",
                "user_prompt": "create an Excel spreadsheet",
                "context": {},
                "artifact_output_dir": output_dir,
            },
            codex_gateway.select_model("search_synthesis"),
        )
        self.assertIn("XLSX, CSV", prompt)
        self.assertIn("openpyxl", prompt)
        self.assertIn("public source URL per row", prompt)
        self.assertIn("QA summary sheet", prompt)
        self.assertIn(output_dir, prompt)

    def test_google_prompt_uses_supplied_browser_evidence_and_current_date(self) -> None:
        prompt = codex_gateway.build_prompt(
            {
                "system_prompt": "system",
                "user_prompt": "check Google for Stella Jones",
                "context": {
                    "current_local_date": "2026-08-12",
                    "event_time_scope": "all_relevant_dates",
                    "google_browser_search": {
                        "provider": "google_chrome_profile",
                        "result_text": "September 1, 2026 - Blairally",
                        "opened_sources": [
                            {
                                "title": "Venue calendar",
                                "url": "https://example.com/show",
                                "status": "completed",
                                "text": "Stella Jones performs September 1, 2026.",
                            }
                        ],
                    },
                },
            },
            codex_gateway.select_model("search_deep"),
        )
        self.assertIn("dedicated signed-in Chrome profile", prompt)
        self.assertIn("do not invoke a generic web-search substitute", prompt)
        self.assertIn("current local date is 2026-08-12", prompt)
        self.assertIn("past dates are valid evidence", prompt)
        self.assertIn("all_relevant_dates", prompt)
        self.assertIn("September 1, 2026 - Blairally", prompt)
        self.assertIn("https://example.com/show", prompt)
        self.assertIn("Prefer opened-source text", prompt)

    @patch("codex_gateway.subprocess.run")
    @patch("codex_gateway.subprocess.Popen")
    @patch("codex_gateway.shutil.which", return_value=r"C:\tools\codex.cmd")
    def test_cancellable_invocation_terminates_process_tree(self, _which, popen, run) -> None:
        process = popen.return_value
        process.pid = 4321
        process.communicate.return_value = ("", "")
        cancelled = threading.Event()
        cancelled.set()
        with patch.dict(os.environ, {"VERIDEX_CODEX_WORKDIR": os.getcwd()}, clear=False):
            with self.assertRaises(RequestCancelled):
                codex_gateway.invoke_codex(
                    {
                        "task_type": "conversation",
                        "system_prompt": "system",
                        "user_prompt": "hello",
                        "context": {},
                        "cancel_event": cancelled,
                    }
                )
        self.assertIn("taskkill", str(run.call_args.args[0][0]).casefold())

    def test_execution_evidence_ignores_started_events(self) -> None:
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {"type": "command_execution", "status": "in_progress", "command": "Copy-Item source target"},
                    }
                ),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Done"}}),
            ]
        )
        self.assertEqual(codex_gateway.extract_execution_evidence(stdout), [])

    @patch("codex_gateway.subprocess.run")
    @patch("codex_gateway.shutil.which", return_value=r"C:\tools\codex.cmd")
    def test_invocation_passes_prompt_on_stdin_and_uses_cli_model_fallback(self, _which, run) -> None:
        unsupported = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "abc"}),
                json.dumps(
                    {
                        "type": "error",
                        "message": json.dumps(
                            {
                                "type": "error",
                                "status": 400,
                                "error": {
                                    "type": "invalid_request_error",
                                    "message": "The 'gpt-5.6-luna' model requires a newer version of Codex. Please upgrade to the latest app or CLI and try again.",
                                },
                            }
                        ),
                    }
                ),
                json.dumps({"type": "turn.failed", "error": {"message": "unsupported model"}}),
            ]
        )
        run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout=unsupported, stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Ready"}}),
                stderr="",
            ),
        ]
        with patch.dict(
            os.environ,
            {"VERIDEX_CODEX_WORKDIR": os.getcwd(), "VERIDEX_CODEX_ACCESS_MODE": "read_only"},
            clear=False,
        ):
            response = codex_gateway.invoke_codex(
                {"task_type": "simple", "system_prompt": "Be useful", "user_prompt": "Plan this", "context": {}}
            )
        first_command = run.call_args_list[0].args[0]
        second_command = run.call_args_list[1].args[0]
        self.assertIn("--model", first_command)
        self.assertNotIn("--model", second_command)
        self.assertNotIn("-", first_command[first_command.index("exec") + 1 :])
        self.assertNotIn("User request:\nPlan this", " ".join(first_command))
        self.assertIn("User request:\nPlan this", run.call_args_list[0].kwargs["input"])
        self.assertNotIn("stdin", run.call_args_list[0].kwargs)
        self.assertEqual(response["model"], "codex_cli_default")
        self.assertEqual(response["requested_model"], "gpt-5.6-luna")
        self.assertTrue(response["model_fallback_used"])
        self.assertEqual(response["text"], "Ready")

    @patch("codex_gateway.subprocess.run")
    @patch("codex_gateway.shutil.which", return_value=r"C:\tools\codex.cmd")
    def test_long_prompt_is_not_put_on_windows_command_line(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Ready"}}),
            stderr="",
        )
        long_context = {"history": "x" * 40000}
        with patch.dict(os.environ, {"VERIDEX_CODEX_WORKDIR": os.getcwd()}, clear=False):
            codex_gateway.invoke_codex(
                {
                    "task_type": "media",
                    "system_prompt": "system",
                    "user_prompt": "create another image",
                    "context": long_context,
                }
            )
        command = run.call_args.args[0]
        self.assertLess(len(" ".join(command)), 20000)
        self.assertIn("x" * 1000, run.call_args.kwargs["input"])
        self.assertIn("User request:\ncreate another image", run.call_args.kwargs["input"])

    @patch("codex_gateway.subprocess.run")
    @patch("codex_gateway.shutil.which", return_value=r"C:\tools\codex.cmd")
    def test_invocation_is_ephemeral_read_only_and_ignores_user_config(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "Ready"}}
            ),
            stderr="",
        )
        with patch.dict(
            os.environ,
            {"VERIDEX_CODEX_WORKDIR": os.getcwd(), "VERIDEX_CODEX_ACCESS_MODE": "read_only"},
            clear=False,
        ):
            response = codex_gateway.invoke_codex(
                {"task_type": "coding", "system_prompt": "Be useful", "user_prompt": "Plan this", "context": {}}
            )
        command = run.call_args.args[0]
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertLess(command.index("--ask-for-approval"), command.index("exec"))
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(command[command.index("--ask-for-approval") + 1], "never")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertNotIn("stdin", run.call_args.kwargs)
        self.assertNotIn("-", command[command.index("exec") + 1 :])
        self.assertNotIn("User request:\nPlan this", " ".join(command))
        self.assertIn("User request:\nPlan this", run.call_args.kwargs["input"])
        self.assertEqual(response["provider"], "codex_cli")
        self.assertEqual(response["text"], "Ready")

    @patch("codex_gateway.subprocess.run")
    @patch("codex_gateway.shutil.which", return_value=r"C:\tools\codex.cmd")
    def test_full_access_uses_documented_danger_full_access_sandbox(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Found it"}}),
            stderr="",
        )
        with patch.dict(
            os.environ,
            {"VERIDEX_CODEX_WORKDIR": os.getcwd(), "VERIDEX_CODEX_ACCESS_MODE": "full"},
            clear=False,
        ):
            response = codex_gateway.invoke_codex(
                {"task_type": "conversation", "system_prompt": "Search when asked", "user_prompt": "Find my file", "context": {}}
            )
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--sandbox") + 1], "danger-full-access")
        self.assertEqual(command[command.index("--ask-for-approval") + 1], "never")
        self.assertEqual(response["access_mode"], "full")
        self.assertIn("full local computer access", run.call_args.kwargs["input"])

    @patch("codex_gateway.subprocess.run")
    @patch("codex_gateway.shutil.which", return_value=r"C:\tools\codex.cmd")
    def test_image_attachments_are_passed_to_exec(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Seen"}}),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "reference.png"
            image_path.write_bytes(b"png-placeholder")
            with patch.dict(os.environ, {"VERIDEX_CODEX_WORKDIR": os.getcwd()}, clear=False):
                codex_gateway.invoke_codex(
                    {
                        "task_type": "image_video",
                        "system_prompt": "Inspect the image",
                        "user_prompt": "Describe it",
                        "context": {},
                        "attachment_paths": [str(image_path)],
                    }
                )
        command = run.call_args.args[0]
        self.assertGreater(command.index("--image"), command.index("exec"))
        self.assertEqual(command[command.index("--image") + 1], str(image_path.resolve()))


if __name__ == "__main__":
    unittest.main()
