"""Dependency-free local web server for standalone Codex + Veridex chat."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from codex_gateway import invoke_codex
from veridex_core import VeridexStore, classify_task, transcript_context


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"


def load_env(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env(ROOT / ".env.local")
DATA_ROOT = Path(os.environ.get("VERIDEX_DATA_DIR", str(ROOT / "data"))).resolve()
STORE = VeridexStore(DATA_ROOT)


def chat_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if not text:
        raise ValueError("text is required")
    if not session_id:
        raise ValueError("session_id is required")
    session = STORE.find_session(session_id)
    workspace_id = workspace_id or str(session["workspace_id"])
    previous = STORE.load_messages(workspace_id, session_id, limit=24)
    user_message = STORE.append_message(workspace_id, session_id, "user", text, speaker="You")
    task_type = classify_task(text)
    result = invoke_codex(
        {
            "task_type": task_type,
            "system_prompt": (
                "You are Veridex in My Office. Help the local user directly. "
                "Use the governed context for continuity, but do not claim actions that were not performed."
            ),
            "user_prompt": text,
            "context": transcript_context(previous),
        }
    )
    assistant_message = STORE.append_message(
        workspace_id,
        session_id,
        "assistant",
        result["text"],
        speaker="Veridex",
        provider=result["provider"],
        model=result["model"],
        reasoning_effort=result["reasoning_effort"],
        task_type=result["task_type"],
    )
    return {
        "ok": True,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "user_message": user_message,
        "message": assistant_message,
        "provider": result["provider"],
        "model": result["model"],
        "reasoning_effort": result["reasoning_effort"],
        "task_type": result["task_type"],
        "fallback_used": False,
    }


TOOLS = [
    {"name": "office.session_info", "description": "Read the active standalone session."},
    {"name": "office.workspace_list", "description": "List local workspaces."},
    {"name": "office.session_create", "description": "Create a session in a workspace."},
    {"name": "office.transcript_get", "description": "Read a session transcript."},
]


class VeridexHandler(BaseHTTPRequestHandler):
    server_version = "CodexVeridex/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _legacy_authorized(self) -> bool:
        expected = str(os.environ.get("VERIDEX_CODEX_TOKEN") or "").strip()
        if not expected:
            return True
        return self.headers.get("Authorization") == f"Bearer {expected}"

    def _serve_asset(self, route: str) -> None:
        relative = "index.html" if route in {"/", "/chat"} else route.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._json({"ok": True, "service": "codex2veridex", "data_root": str(DATA_ROOT)})
            elif parsed.path == "/api/bootstrap":
                self._json(STORE.ensure_default())
            elif parsed.path == "/api/state":
                self._json(
                    STORE.bootstrap(
                        str(query.get("workspace_id", [""])[0]),
                        str(query.get("session_id", [""])[0]),
                    )
                )
            elif parsed.path == "/api/messages":
                self._json(
                    {
                        "messages": STORE.load_messages(
                            str(query.get("workspace_id", [""])[0]),
                            str(query.get("session_id", [""])[0]),
                        )
                    }
                )
            elif parsed.path == "/tools":
                if not self._legacy_authorized():
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                else:
                    self._json({"tools": TOOLS})
            else:
                self._serve_asset(parsed.path)
        except KeyError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._body()
            if parsed.path == "/api/workspaces":
                workspace = STORE.create_workspace(str(payload.get("label") or "Workspace"))
                session = STORE.create_session(workspace["workspace_id"], "New session")
                self._json(STORE.bootstrap(workspace["workspace_id"], session["session_id"]), HTTPStatus.CREATED)
            elif parsed.path == "/api/sessions":
                session = STORE.create_session(
                    str(payload.get("workspace_id") or ""),
                    str(payload.get("title") or "New session"),
                )
                self._json(STORE.bootstrap(session["workspace_id"], session["session_id"]), HTTPStatus.CREATED)
            elif parsed.path in {"/api/chat", "/request"}:
                if parsed.path == "/request" and not self._legacy_authorized():
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                result = chat_response(payload)
                if parsed.path == "/request":
                    result = {
                        "content": [{"type": "text", "text": result["message"]["text"]}],
                        "structuredContent": result,
                    }
                self._json(result)
            elif parsed.path == "/call":
                if not self._legacy_authorized():
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                self._json(self._call_tool(payload))
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _call_tool(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tool = str(payload.get("tool") or "")
        args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        if tool == "office.session_info":
            session = STORE.find_session(str(args.get("session_id") or ""))
            value = dict(session)
        elif tool == "office.workspace_list":
            value = {"workspaces": STORE.list_workspaces()}
        elif tool == "office.session_create":
            value = STORE.create_session(str(args.get("workspace_id") or ""), str(args.get("title") or "New session"))
        elif tool == "office.transcript_get":
            session = STORE.find_session(str(args.get("session_id") or ""))
            value = {
                "workspace_id": session["workspace_id"],
                "session_id": session["session_id"],
                "entries": STORE.load_messages(session["workspace_id"], session["session_id"]),
            }
        else:
            raise ValueError(f"Unknown tool: {tool}")
        return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "structuredContent": value}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run standalone Codex + Veridex")
    parser.add_argument("--host", default=os.environ.get("VERIDEX_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VERIDEX_PORT", "8765")))
    args = parser.parse_args()
    STORE.ensure_default()
    server = ThreadingHTTPServer((args.host, args.port), VeridexHandler)
    print(f"Codex + Veridex running at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
