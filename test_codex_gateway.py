from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_gateway


class CodexGatewayTests(unittest.TestCase):
    def test_selects_strong_models_for_coding_and_planning(self) -> None:
        coding = codex_gateway.select_model("coding")
        planning = codex_gateway.select_model("architecture")
        self.assertEqual((coding.model, coding.reasoning_effort), ("gpt-5.6-sol", "high"))
        self.assertEqual((planning.model, planning.reasoning_effort), ("gpt-5.6-sol", "high"))

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
