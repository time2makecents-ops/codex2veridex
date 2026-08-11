"""Local MCP bridge from Codex to the governed Veridex HTTP API."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _load_env_file(path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        return


@dataclass
class VeridexClient:
    base_url: str = "http://127.0.0.1:8078"
    token: str = ""
    session_id: str = ""
    workspace_id: str = ""
    opener: Callable[..., Any] = urllib_request.urlopen

    def ensure_backend(self) -> Dict[str, Any]:
        try:
            return self.request("/health")
        except RuntimeError as initial_error:
            if _env("VERIDEX_AUTOSTART", "true").lower() not in {"1", "true", "yes", "on"}:
                raise initial_error
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                r"C:\Office-App\veridex.ps1",
                "-Action",
                "start",
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                subprocess.Popen(command, cwd=r"C:\Office-App", creationflags=creation_flags)
            except OSError as exc:
                raise RuntimeError(f"Veridex is not running and could not be started: {exc}") from exc
            deadline = time.monotonic() + 30
            last_error = initial_error
            while time.monotonic() < deadline:
                try:
                    return self.request("/health")
                except RuntimeError as exc:
                    last_error = exc
                    time.sleep(0.5)
            raise RuntimeError(f"Veridex did not become ready after startup: {last_error}") from last_error

    @classmethod
    def from_env(cls) -> "VeridexClient":
        _load_env_file(r"C:\codex2veridex\.env.local")
        _load_env_file(r"C:\Office-App\.env.local")
        return cls(
            base_url=_env("VERIDEX_BASE_URL", "http://127.0.0.1:8078").rstrip("/"),
            token=_env("VERIDEX_CODEX_TOKEN"),
            session_id=_env("VERIDEX_CODEX_SESSION_ID"),
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, path: str, *, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=self._headers(),
        )
        try:
            with self.opener(request, timeout=10) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"Veridex HTTP {exc.code}: {detail}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Unable to reach Veridex at {self.base_url}: {exc.reason}") from exc

    def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        args = dict(arguments or {})
        if self.session_id and "session_id" not in args:
            args["session_id"] = self.session_id
        if self.workspace_id and "workspace_id" not in args:
            args["workspace_id"] = self.workspace_id
        return self.request("/call", method="POST", payload={"tool": tool, "arguments": args})

    def activate(self, session_id: Optional[str] = None, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        candidate_session = str(session_id or self.session_id).strip()
        if not candidate_session:
            raise RuntimeError("No Veridex session configured. Pass session_id to veridex_activate or set VERIDEX_CODEX_SESSION_ID.")
        previous_session, previous_workspace = self.session_id, self.workspace_id
        self.session_id = candidate_session
        try:
            health = self.ensure_backend()
            result = self.call("office.session_info")
            structured = result.get("structuredContent") if isinstance(result, dict) else {}
            structured = structured if isinstance(structured, dict) else {}
            resolved_workspace = str(workspace_id or structured.get("workspace_id") or "").strip()
            if workspace_id and resolved_workspace != str(structured.get("workspace_id") or "").strip():
                result = self.call("office.workspace_activate", {"workspace_id": resolved_workspace})
                structured = result.get("structuredContent") if isinstance(result, dict) else {}
                structured = structured if isinstance(structured, dict) else {}
            self.workspace_id = str(structured.get("workspace_id") or resolved_workspace).strip()
            return {
                "active": True,
                "session_id": self.session_id,
                "workspace_id": self.workspace_id,
                "health": health,
                "session": structured,
            }
        except Exception:
            self.session_id, self.workspace_id = previous_session, previous_workspace
            raise

    def deactivate(self) -> Dict[str, Any]:
        session_id, workspace_id = self.session_id, self.workspace_id
        self.session_id = ""
        self.workspace_id = ""
        return {"active": False, "previous_session_id": session_id, "previous_workspace_id": workspace_id}


MCP_TOOLS = [
    {
        "name": "veridex_activate",
        "description": "Activate governed Veridex mode for a user-owned Veridex session.",
        "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "workspace_id": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "veridex_status",
        "description": "Check Veridex backend health and the active Codex session.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "veridex_request",
        "description": "Send natural-language work through Veridex governance and the active room/session.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
    },
    {
        "name": "veridex_call",
        "description": "Call one existing Veridex tool with governed routing.",
        "inputSchema": {"type": "object", "properties": {"tool": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["tool"], "additionalProperties": False},
    },
    {
        "name": "veridex_list_tools",
        "description": "List the tools currently exposed by Veridex.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "veridex_deactivate",
        "description": "Stop routing work through the active Veridex session.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _content(value: Any) -> list[Dict[str, str]]:
    return [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}]


def dispatch(client: VeridexClient, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "veridex_activate":
        return client.activate(arguments.get("session_id"), arguments.get("workspace_id"))
    if name == "veridex_status":
        health = client.request("/health")
        return {"backend": health, "active": bool(client.session_id), "session_id": client.session_id, "workspace_id": client.workspace_id}
    if name == "veridex_request":
        if not client.session_id:
            raise RuntimeError("Veridex is inactive. Call veridex_activate first.")
        text = str(arguments.get("text") or "").strip()
        if not text:
            raise RuntimeError("text is required")
        return client.request("/request", method="POST", payload={"text": text, "session_id": client.session_id})
    if name == "veridex_call":
        if not client.session_id:
            raise RuntimeError("Veridex is inactive. Call veridex_activate first.")
        return client.call(str(arguments.get("tool") or "").strip(), arguments.get("arguments") or {})
    if name == "veridex_list_tools":
        return client.request("/tools")
    if name == "veridex_deactivate":
        return client.deactivate()
    raise RuntimeError(f"Unknown MCP tool: {name}")


def serve(client: Optional[VeridexClient] = None) -> None:
    client = client or VeridexClient.from_env()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            method = message.get("method")
            request_id = message.get("id")
            if method == "notifications/initialized":
                continue
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "veridex-local", "version": "1.0.0"},
                }
            elif method == "tools/list":
                result = {"tools": MCP_TOOLS}
            elif method == "tools/call":
                params = message.get("params") or {}
                value = dispatch(client, str(params.get("name") or ""), params.get("arguments") or {})
                result = {"content": _content(value), "structuredContent": value}
            else:
                raise RuntimeError(f"Unsupported MCP method: {method}")
            if request_id is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
        except Exception as exc:
            if request_id is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}), flush=True)


if __name__ == "__main__":
    serve()
