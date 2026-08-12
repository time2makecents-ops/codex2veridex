"""Standalone single-user workspace, session, transcript, and routing core."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_ACCOUNT = {"user_id": "local-user", "display_name": "Local User"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _title(text: str, fallback: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip(" .")
    if not cleaned:
        return fallback
    return cleaned if len(cleaned) <= 54 else cleaned[:51].rstrip() + "..."


def classify_task(text: str) -> str:
    """Choose a deterministic task class; user text cannot name arbitrary models."""
    value = " ".join(str(text or "").lower().split())
    if not value:
        return "conversation"
    if re.search(r"\b(legal|law|medical|diagnos|financial|investment|security audit|vulnerabilit)\w*\b", value):
        return "high_stakes"
    if re.search(r"\b(code|coding|python|javascript|typescript|react|api|function|class|bug|debug|refactor|compile|repository|git|sql|html|css)\w*\b", value):
        return "coding"
    if re.search(r"\b(architect|architecture|plan|planning|roadmap|design a system|technical design)\w*\b", value):
        return "planning"
    if re.search(r"\b(image|photo|picture|video|frame|crop|visual|graphic|render|edit footage)\w*\b", value):
        return "media"
    if re.search(r"\b(test|testing|verify|validation|smoke check|quality assurance|qa)\w*\b", value):
        return "testing"
    if re.search(r"\b(search|research|latest|current|look up|find online|web)\w*\b", value):
        return "search_synthesis"
    simple = re.sub(r"[^a-z0-9 ]", "", value).strip()
    if simple in {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yes", "no", "good morning", "good night"}:
        return "simple"
    return "conversation"


class VeridexStore:
    """File-backed state rooted entirely inside this repository by default."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.account_path = self.root / "account.json"
        self.workspaces_root = self.root / "workspaces"
        self._lock = threading.RLock()

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def workspace_dir(self, workspace_id: str) -> Path:
        return self.workspaces_root / workspace_id

    def session_dir(self, workspace_id: str, session_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "sessions" / session_id

    def ensure_default(self) -> Dict[str, Any]:
        with self._lock:
            if not self.account_path.exists():
                self._write_json(self.account_path, DEFAULT_ACCOUNT)
            workspaces = self.list_workspaces()
            workspace = workspaces[0] if workspaces else self.create_workspace("My Workspace")
            sessions = self.list_sessions(workspace["workspace_id"])
            session = sessions[0] if sessions else self.create_session(workspace["workspace_id"], "New session")
            return self.bootstrap(workspace["workspace_id"], session["session_id"])

    def create_workspace(self, label: str) -> Dict[str, Any]:
        with self._lock:
            workspace_id = _identifier("ws")
            now = utc_now()
            row = {
                "workspace_id": workspace_id,
                "label": _title(label, "Workspace"),
                "created_at": now,
                "updated_at": now,
            }
            self._write_json(self.workspace_dir(workspace_id) / "workspace.json", row)
            return row

    def list_workspaces(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = []
            if self.workspaces_root.exists():
                for path in self.workspaces_root.glob("*/workspace.json"):
                    row = self._read_json(path, None)
                    if isinstance(row, dict):
                        rows.append(row)
            return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)

    def get_workspace(self, workspace_id: str) -> Dict[str, Any]:
        row = self._read_json(self.workspace_dir(workspace_id) / "workspace.json", None)
        if not isinstance(row, dict):
            raise KeyError(f"Unknown workspace: {workspace_id}")
        return row

    def create_session(self, workspace_id: str, title: str) -> Dict[str, Any]:
        with self._lock:
            self.get_workspace(workspace_id)
            session_id = _identifier("sess")
            now = utc_now()
            row = {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "title": _title(title, "New session"),
                "active_room": "my_office",
                "active_persona": "Veridex",
                "created_at": now,
                "updated_at": now,
            }
            self._write_json(self.session_dir(workspace_id, session_id) / "session.json", row)
            self._touch_workspace(workspace_id)
            return row

    def list_sessions(self, workspace_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            self.get_workspace(workspace_id)
            rows = []
            root = self.workspace_dir(workspace_id) / "sessions"
            if root.exists():
                for path in root.glob("*/session.json"):
                    row = self._read_json(path, None)
                    if isinstance(row, dict):
                        rows.append(row)
            return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)

    def find_session(self, session_id: str) -> Dict[str, Any]:
        if self.workspaces_root.exists():
            for path in self.workspaces_root.glob(f"*/sessions/{session_id}/session.json"):
                row = self._read_json(path, None)
                if isinstance(row, dict):
                    return row
        raise KeyError(f"Unknown session: {session_id}")

    def append_message(
        self,
        workspace_id: str,
        session_id: str,
        role: str,
        text: str,
        **metadata: Any,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self.find_session(session_id)
            if session.get("workspace_id") != workspace_id:
                raise KeyError("Session does not belong to workspace")
            row = {
                "message_id": _identifier("msg"),
                "timestamp": utc_now(),
                "role": role,
                "text": str(text),
                "room": session.get("active_room", "my_office"),
            }
            row.update({key: value for key, value in metadata.items() if value not in (None, "")})
            transcript = self.session_dir(workspace_id, session_id) / "transcript.ndjson"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._touch_session(workspace_id, session_id, first_user_text=text if role == "user" else "")
            return row

    def load_messages(self, workspace_id: str, session_id: str, limit: int = 300) -> List[Dict[str, Any]]:
        self.get_workspace(workspace_id)
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        transcript = self.session_dir(workspace_id, session_id) / "transcript.ndjson"
        if not transcript.exists():
            return []
        rows = []
        for line in transcript.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows[-max(1, min(limit, 1000)) :]

    def bootstrap(self, workspace_id: str = "", session_id: str = "") -> Dict[str, Any]:
        workspaces = self.list_workspaces()
        if not workspaces:
            return self.ensure_default()
        selected_workspace = next((row for row in workspaces if row["workspace_id"] == workspace_id), workspaces[0])
        sessions = self.list_sessions(selected_workspace["workspace_id"])
        if not sessions:
            sessions = [self.create_session(selected_workspace["workspace_id"], "New session")]
        selected_session = next((row for row in sessions if row["session_id"] == session_id), sessions[0])
        return {
            "account": self._read_json(self.account_path, DEFAULT_ACCOUNT),
            "workspaces": workspaces,
            "workspace": selected_workspace,
            "sessions": sessions,
            "session": selected_session,
            "messages": self.load_messages(selected_workspace["workspace_id"], selected_session["session_id"]),
        }

    def _touch_workspace(self, workspace_id: str) -> None:
        path = self.workspace_dir(workspace_id) / "workspace.json"
        row = self._read_json(path, None)
        if isinstance(row, dict):
            row["updated_at"] = utc_now()
            self._write_json(path, row)

    def _touch_session(self, workspace_id: str, session_id: str, first_user_text: str = "") -> None:
        path = self.session_dir(workspace_id, session_id) / "session.json"
        row = self._read_json(path, None)
        if not isinstance(row, dict):
            return
        if first_user_text and row.get("title") == "New session":
            row["title"] = _title(first_user_text, "New session")
        row["updated_at"] = utc_now()
        self._write_json(path, row)
        self._touch_workspace(workspace_id)


def transcript_context(messages: Iterable[Dict[str, Any]], limit: int = 20) -> Dict[str, Any]:
    compact = []
    for row in list(messages)[-limit:]:
        compact.append({"role": row.get("role"), "text": row.get("text"), "room": row.get("room")})
    return {"recent_transcript": compact, "governance": {"single_user": True, "active_room_limit": 1}}
