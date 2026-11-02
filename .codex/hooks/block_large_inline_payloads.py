"""Reject oversized inline Gmail binary arguments without echoing their contents."""

from __future__ import annotations

import json
import sys
from typing import Any


MAX_INLINE_BINARY_CHARS = 16_384
_BINARY_KEYS = {
    "base64", "base64_content", "base64_url_content", "base64url",
    "content_bytes", "data_base64", "raw",
}


def decision_for_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return None
    if "gmail" not in str(event.get("tool_name", "")).casefold():
        return None
    payload = event.get("tool_input", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    total = 0
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in _BINARY_KEYS and isinstance(child, str):
                    total += len(child)
                else:
                    pending.append(child)
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and value.startswith("data:") and ";base64," in value:
            total += len(value.split(";base64,", 1)[1])
        if total > MAX_INLINE_BINARY_CHARS:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "Gmail inline binary arguments exceed the size limit. "
                        "Use session attachment IDs through the governed Veridex Gmail path."
                    ),
                }
            }
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if isinstance(event, dict):
        decision = decision_for_event(event)
        if decision:
            print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
