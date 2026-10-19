import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HOOK_PATH = ROOT / ".codex" / "hooks" / "block_large_inline_payloads.py"
SPEC = importlib.util.spec_from_file_location("block_large_inline_payloads", HOOK_PATH)
assert SPEC and SPEC.loader
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class LargeInlinePayloadHookTests(unittest.TestCase):
    def gmail_event(self, payload):
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__codex_apps__gmail_create_draft",
            "tool_input": payload,
        }

    def test_blocks_large_gmail_base64_without_echoing_it(self):
        encoded = "A" * (HOOK.MAX_INLINE_BINARY_CHARS + 1)
        decision = HOOK.decision_for_event(
            self.gmail_event({"payload": {"parts": [{"body": {"base64_url_content": encoded}}]}})
        )

        self.assertEqual(
            decision["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertNotIn(encoded, json.dumps(decision))

    def test_blocks_aggregate_inline_binary_size(self):
        half = (HOOK.MAX_INLINE_BINARY_CHARS // 2) + 1
        decision = HOOK.decision_for_event(
            self.gmail_event(
                {
                    "payload": {
                        "parts": [
                            {"body": {"base64_url_content": "A" * half}},
                            {"body": {"base64_url_content": "B" * half}},
                        ]
                    }
                }
            )
        )

        self.assertIsNotNone(decision)

    def test_allows_small_gmail_payload(self):
        decision = HOOK.decision_for_event(
            self.gmail_event({"payload": {"body": {"base64_url_content": "A" * 100}}})
        )

        self.assertIsNone(decision)

    def test_ignores_non_gmail_tools(self):
        decision = HOOK.decision_for_event(
            {
                "tool_name": "mcp__images__upload",
                "tool_input": {"base64_url_content": "A" * (HOOK.MAX_INLINE_BINARY_CHARS + 1)},
            }
        )

        self.assertIsNone(decision)

    def test_command_line_contract_outputs_pretooluse_denial(self):
        event = self.gmail_event(
            {"payload": {"body": {"base64_url_content": "A" * (HOOK.MAX_INLINE_BINARY_CHARS + 1)}}}
        )
        completed = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
