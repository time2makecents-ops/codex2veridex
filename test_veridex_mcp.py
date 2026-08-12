import json
import unittest

from veridex_mcp import VeridexClient, dispatch


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


class VeridexMcpTests(unittest.TestCase):
    def test_activate_validates_session_and_sets_workspace(self):
        calls = []

        def opener(request, timeout=10):
            calls.append((request.full_url, json.loads(request.data.decode()) if request.data else None))
            if request.full_url.endswith("/call"):
                tool = calls[-1][1]["tool"]
                return FakeResponse({"structuredContent": {"session_id": "sess_1", "workspace_id": "ws_1", "title": "Codex"}, "content": [{"type": "text", "text": tool}]})
            return FakeResponse({})

        client = VeridexClient(base_url="http://127.0.0.1:8765", token="secret", opener=opener)
        result = client.activate("sess_1")
        self.assertTrue(result["active"])
        self.assertEqual(client.session_id, "sess_1")
        self.assertEqual(client.workspace_id, "ws_1")
        call_payloads = [payload for _, payload in calls if isinstance(payload, dict)]
        self.assertEqual(call_payloads[0]["arguments"]["session_id"], "sess_1")

    def test_request_requires_activation(self):
        with self.assertRaisesRegex(RuntimeError, "inactive"):
            dispatch(VeridexClient(), "veridex_request", {"text": "hello"})

    def test_deactivate_clears_state(self):
        client = VeridexClient(session_id="sess_1", workspace_id="ws_1")
        result = dispatch(client, "veridex_deactivate", {})
        self.assertFalse(result["active"])
        self.assertEqual(client.session_id, "")
        self.assertEqual(client.workspace_id, "")


if __name__ == "__main__":
    unittest.main()
