from __future__ import annotations

import json
import os
import subprocess
import unittest
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
        with patch.dict(os.environ, {"VERIDEX_CODEX_WORKDIR": os.getcwd()}, clear=False):
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
        self.assertEqual(response["provider"], "codex_cli")
        self.assertEqual(response["text"], "Ready")


if __name__ == "__main__":
    unittest.main()
