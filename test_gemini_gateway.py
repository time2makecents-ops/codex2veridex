from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gemini_gateway


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode("utf-8"))

    def __exit__(self, exc_type, exc, tb):
        return False


class GeminiGatewayTests(unittest.TestCase):
    def test_loads_process_env_before_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env.local"
            env_file.write_text("GEMINI_API_KEY=file-secret\nGEMINI_MODEL=file-model\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"GEMINI_API_KEY": "process-secret", "GEMINI_MODEL": "process-model"},
                clear=True,
            ):
                config = gemini_gateway.load_gemini_config(env_file=env_file)

        self.assertEqual(config.api_key, "process-secret")
        self.assertEqual(config.model, "process-model")

    def test_env_file_fallback_enables_gemini_when_key_and_model_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env.local"
            env_file.write_text("GEMINI_API_KEY=file-secret\nGEMINI_MODEL=file-model\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = gemini_gateway.load_gemini_config(env_file=env_file)

        self.assertEqual(config.api_key, "file-secret")
        self.assertEqual(config.model, "file-model")
        self.assertTrue(gemini_gateway.gemini_enabled(config))

    def test_disabled_flag_or_missing_secret_disables_gemini(self) -> None:
        self.assertFalse(gemini_gateway.gemini_enabled(gemini_gateway.GeminiConfig("", "gemini-test", True)))
        self.assertFalse(gemini_gateway.gemini_enabled(gemini_gateway.GeminiConfig("secret", "", True)))
        self.assertFalse(gemini_gateway.gemini_enabled(gemini_gateway.GeminiConfig("secret", "gemini-test", False)))

    @patch("gemini_gateway.urllib.request.urlopen")
    def test_invoke_gemini_posts_text_request_and_returns_route_shape(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "Hello from Gemini."}]}}]}
        )
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "secret-key", "GEMINI_MODEL": "gemini-test"},
            clear=True,
        ):
            response = gemini_gateway.invoke_gemini(
                {
                    "task_type": "lobby_conversation",
                    "system_prompt": "You are the Receptionist.",
                    "user_prompt": "hello",
                    "context": {"current_room": {"title": "Lobby"}},
                }
            )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertIn("/v1beta/models/gemini-test:generateContent", request.full_url)
        self.assertNotIn("secret-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "secret-key")
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "hello")
        self.assertIn("Receptionist", body["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(response["provider"], "gemini_api")
        self.assertEqual(response["model"], "gemini-test")
        self.assertEqual(response["reasoning_effort"], "low")
        self.assertEqual(response["task_type"], "lobby_conversation")
        self.assertEqual(response["text"], "Hello from Gemini.")
        self.assertEqual(response["evidence"], [])
        self.assertNotIn("secret-key", json.dumps(response))


if __name__ == "__main__":
    unittest.main()
