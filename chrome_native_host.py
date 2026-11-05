"""Chrome Native Messaging stdio relay. Credentials remain in ignored local state."""
from __future__ import annotations

import argparse
import json
import struct
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

EXTENSION_ID = "agigaaikljlfallmmpechfbfckbhagbe"
ROOT = Path(__file__).resolve().parent
MAX_FRAME = 262144


def read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        block = stream.read(size - len(chunks))
        if not block:
            raise EOFError("Truncated native message")
        chunks.extend(block)
    return bytes(chunks)


def read_message(stream) -> dict | None:
    prefix = stream.read(4)
    if not prefix:
        return None
    if len(prefix) < 4:
        prefix += read_exact(stream, 4 - len(prefix))
    size = struct.unpack("<I", prefix)[0]
    if not 0 < size <= MAX_FRAME:
        raise ValueError("Native message exceeds the limit")
    value = json.loads(read_exact(stream, size).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Native message must be an object")
    return value


def write_message(stream, value: dict) -> None:
    encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_FRAME:
        raise ValueError("Native response exceeds the limit")
    stream.write(struct.pack("<I", len(encoded)) + encoded)
    stream.flush()


def load_settings(path: Path) -> dict:
    from urllib.parse import urlsplit
    value = json.loads(path.read_text("utf-8"))
    parsed = urlsplit(str(value.get("base_url") or ""))
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Native host requires the existing loopback Veridex URL")
    if not isinstance(value.get("token"), str) or len(value["token"]) < 40:
        raise ValueError("Native relay credentials are not prepared")
    return value


def relay(value: dict, settings: dict, connection_id: str, opener=urlopen) -> dict:
    # Extension input cannot choose an endpoint, token, connection identity or headers.
    payload = {"connection_id": connection_id, "selection": value.get("selection")}
    if "event" in value:
        payload["event"] = value["event"]
    request = Request(settings["base_url"].rstrip("/") + "/api/browser-extension/relay",
                      data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + settings["token"]})
    try:
        with opener(request, timeout=5) as response:
            result = json.loads(response.read(MAX_FRAME).decode("utf-8"))
        return {**result, "rpc_id": str(value.get("rpc_id") or "")[:128]}
    except HTTPError as exc:
        messages = {
            "scope_unavailable": "The saved workspace or session is unavailable. Check Connection settings and select the tab again.",
            "room_changed": "The room changed or its ID is incorrect. Open the companion and choose Use this tab to bind the current room.",
            "connection_in_use": "Another Chrome connection has a selected tab. Close or disable the companion in the other Chrome profile before selecting this tab.",
        }
        code = ""
        try:
            code = json.loads(exc.read(2048)).get("error_code", "")
        except (ValueError, AttributeError):
            pass
        message = messages.get(code)
        if not message:
            message = {401: "The native connector is not authorized. Check its local registration and settings.",
                       404: "Veridex needs to be restarted to load companion support.",
                       400: "Veridex rejected the request. Check the saved workspace/session and select the tab again."}.get(exc.code,
                       "Veridex could not complete the request. Check broker status before retrying.")
        return {"rpc_id": str(value.get("rpc_id") or "")[:128], "error": message}
    except Exception:
        # HTTP errors can echo input; never leak credentials or form text to logs.
        return {"rpc_id": str(value.get("rpc_id") or "")[:128],
                "error": "Veridex relay unavailable or rejected the request; inspect broker status before retrying"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("--config", type=Path, default=ROOT / ".runtime" / "browser-extension" / "settings.json")
    args, _ = parser.parse_known_args()
    if args.origin != f"chrome-extension://{EXTENSION_ID}/":
        print("Unauthorized extension origin", file=sys.stderr)
        return 1
    try:
        settings = load_settings(args.config)
        connection_id = uuid.uuid4().hex
        while (value := read_message(sys.stdin.buffer)) is not None:
            write_message(sys.stdout.buffer, relay(value, settings, connection_id))
    except (ValueError, OSError, EOFError):
        print("Native relay stopped: configuration or protocol error", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
