"""Standalone single-user workspace, session, transcript, and routing core."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from veridex_governance import GovernanceRegistry
from veridex_rooms import room_by_id, rooms_payload


DEFAULT_ACCOUNT = {"user_id": "local-user", "display_name": "Local User"}
MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ð")
GOVERNANCE_REGISTRY_PATH = Path(__file__).resolve().parent / "governance" / "navigator_governance_v1.0.0.json"
GENERATED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
GENERATED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _title(text: str, fallback: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip(" .")
    if not cleaned:
        return fallback
    return cleaned if len(cleaned) <= 54 else cleaned[:51].rstrip() + "..."


def repair_text_encoding(text: Any) -> str:
    """Repair UTF-8 text that a Windows code page decoded before storage."""
    value = str(text or "")
    if not any(marker in value for marker in MOJIBAKE_MARKERS):
        return value
    try:
        repaired = value.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    original_markers = sum(value.count(marker) for marker in MOJIBAKE_MARKERS)
    repaired_markers = sum(repaired.count(marker) for marker in MOJIBAKE_MARKERS)
    return repaired if repaired_markers < original_markers else value


def classify_task(text: str) -> str:
    """Choose a deterministic task class; user text cannot name arbitrary models."""
    value = " ".join(str(text or "").lower().split())
    if not value:
        return "conversation"
    if re.search(r"\b(resume|curriculum vitae|cover letter|linkedin (?:headline|about)|job application)\b", value):
        return "resume_generation"
    if re.search(r"\b(legal|law|medical|diagnos|financial|investment|security audit|vulnerabilit)\w*\b", value):
        return "high_stakes"
    if re.search(
        r"\b(?:find|locate|search|open|inspect)\b.{0,80}\b(?:local|computer|drive|desktop|folder|directory|path|files?)\b|"
        r"\b(?:files?|folders?|directories|paths?|desktop|drive)\b.{0,80}\b(?:find|locate|search|open|inspect)\b|"
        r"\.(?:txt|md|pdf|docx?|xlsx?|csv|json|py|js|ts|tsx|html|css)\b",
        value,
    ):
        return "coding"
    if re.search(
        r"\b(search|research|latest|current|look up|find online|web|google|social media|upcoming shows?|concert dates?)\w*\b",
        value,
    ):
        return "search_synthesis"
    if re.search(r"\b(code|coding|python|javascript|typescript|react|api|function|class|bug|debug|refactor|compile|repository|git|sql|html|css)\w*\b", value):
        return "coding"
    if re.search(r"\b(architect|architecture|plan|planning|roadmap|design a system|technical design)\w*\b", value):
        return "planning"
    if re.search(r"\.(?:png|jpe?g|webp|gif)\b", value):
        return "media"
    if re.search(r"\b(image|photo|picture|video|frame|crop|visual|graphic|render|edit footage)\w*\b", value):
        return "media"
    if re.search(r"\b(test|testing|verify|validation|smoke check|quality assurance|qa)\w*\b", value):
        return "testing"
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

    def files_dir(self, workspace_id: str, session_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "files" / "uploads" / self._safe_path_component(session_id, "session")

    def generated_files_dir(self, workspace_id: str, room_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "files" / "generated" / self._safe_path_component(room_id, "room")

    def files_manifest_path(self, workspace_id: str, session_id: str) -> Path:
        return self.session_dir(workspace_id, session_id) / "files.json"

    def generated_staging_root(self, workspace_id: str, session_id: str) -> Path:
        return self.session_dir(workspace_id, session_id) / "generated_staging"

    def governance_state_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "governance_state.json"

    def governance_incidents_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "governance_incidents.ndjson"

    def artifact_ledger_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "artifact_ledger.ndjson"

    def governance_memos_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "governance_memos.ndjson"

    def pending_governance_path(self, workspace_id: str, session_id: str) -> Path:
        return self.session_dir(workspace_id, session_id) / "pending_governance.json"

    def pending_email_path(self, workspace_id: str, session_id: str) -> Path:
        return self.session_dir(workspace_id, session_id) / "pending_email.json"

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
            self.ensure_governance_state(workspace_id)
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
                "active_room": "lobby",
                "active_persona": "Receptionist",
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

    def set_room(self, workspace_id: str, session_id: str, room_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self.find_session(session_id)
            if session.get("workspace_id") != workspace_id:
                raise KeyError("Session does not belong to workspace")
            room = room_by_id(room_id)
            if not room:
                raise ValueError(f"Unknown room: {room_id}")
            previous_room = str(session.get("active_room") or "lobby")
            session["active_room"] = room["id"]
            session["active_persona"] = room["default_persona"]
            session["updated_at"] = utc_now()
            self._write_json(self.session_dir(workspace_id, session_id) / "session.json", session)
            self._touch_workspace(workspace_id)
            return {
                "previous_room": previous_room,
                "active_room": room["id"],
                "active_persona": room["default_persona"],
                "room_title": room["title"],
            }

    def ensure_governance_state(self, workspace_id: str) -> Dict[str, Any]:
        with self._lock:
            self.get_workspace(workspace_id)
            path = self.governance_state_path(workspace_id)
            state = self._read_json(path, {})
            if not isinstance(state, dict):
                state = {}
            defaults = GovernanceRegistry(GOVERNANCE_REGISTRY_PATH).gate_defaults
            gates = dict(state.get("gates") or {})
            for name, enabled in defaults.items():
                gates.setdefault(name, enabled)
            state.update(
                {
                    "navigator_status": "ACTIVE",
                    "navigator_always_present": True,
                    "navigator_visibility": "VISIBLE_STATUS",
                    "gates": gates,
                    "registry_path": str(GOVERNANCE_REGISTRY_PATH.resolve()),
                    "updated_at": state.get("updated_at") or utc_now(),
                }
            )
            self._write_json(path, state)
            return state

    def pending_governance(self, workspace_id: str, session_id: str) -> Dict[str, Any]:
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        value = self._read_json(self.pending_governance_path(workspace_id, session_id), {})
        return value if isinstance(value, dict) else {}

    def set_pending_governance(self, workspace_id: str, session_id: str, value: Dict[str, Any]) -> None:
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        self._write_json(self.pending_governance_path(workspace_id, session_id), dict(value))

    def clear_pending_governance(self, workspace_id: str, session_id: str) -> None:
        path = self.pending_governance_path(workspace_id, session_id)
        if path.exists():
            path.unlink()

    def pending_email(self, workspace_id: str, session_id: str) -> Dict[str, Any]:
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        value = self._read_json(self.pending_email_path(workspace_id, session_id), {})
        return value if isinstance(value, dict) else {}

    def set_pending_email(self, workspace_id: str, session_id: str, value: Dict[str, Any]) -> None:
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        self._write_json(self.pending_email_path(workspace_id, session_id), dict(value))

    def clear_pending_email(self, workspace_id: str, session_id: str) -> None:
        path = self.pending_email_path(workspace_id, session_id)
        if path.exists():
            path.unlink()

    @staticmethod
    def _append_ndjson(path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")

    @staticmethod
    def _safe_path_component(value: str, fallback: str) -> str:
        safe = Path(str(value or "").replace("\\", "/")).name.strip()
        safe = re.sub(r"[^\w.()\- ]+", "_", safe, flags=re.UNICODE).strip(" .")
        return safe or fallback

    def append_governance_incident(
        self,
        workspace_id: str,
        session_id: str,
        *,
        gate_ids: Iterable[str],
        attempted_action: str,
        reason: str,
        evidence: Any = None,
        disposition: str = "blocked",
    ) -> Dict[str, Any]:
        with self._lock:
            session = self.find_session(session_id)
            if session.get("workspace_id") != workspace_id:
                raise KeyError("Session does not belong to workspace")
            row = {
                "incident_id": _identifier("inc"),
                "timestamp": utc_now(),
                "workspace_id": workspace_id,
                "session_id": session_id,
                "room": session.get("active_room", "lobby"),
                "persona": session.get("active_persona", "Receptionist"),
                "gate_ids": [str(value) for value in gate_ids],
                "attempted_action": str(attempted_action or "")[:4000],
                "reason": str(reason or ""),
                "evidence": evidence if evidence is not None else [],
                "disposition": disposition,
                "resolution": None,
            }
            self._append_ndjson(self.governance_incidents_path(workspace_id), row)
            return row

    def list_governance_incidents(self, workspace_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        self.get_workspace(workspace_id)
        path = self.governance_incidents_path(workspace_id)
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows[-max(1, min(limit, 1000)) :]

    def list_artifact_ledger(self, workspace_id: str) -> List[Dict[str, Any]]:
        self.get_workspace(workspace_id)
        path = self.artifact_ledger_path(workspace_id)
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def append_governance_memo(
        self,
        workspace_id: str,
        session_id: str,
        text: str,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self.find_session(session_id)
            if session.get("workspace_id") != workspace_id:
                raise KeyError("Session does not belong to workspace")
            row = {
                "memo_id": _identifier("memo"),
                "created_at": utc_now(),
                "workspace_id": workspace_id,
                "session_id": session_id,
                "durability_scope": "persistent",
                "text": str(text or "").strip(),
                "gov_save": "complete",
                "app_commit": "unverified",
            }
            self._append_ndjson(self.governance_memos_path(workspace_id), row)
            return row

    def list_governance_memos(self, workspace_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        self.get_workspace(workspace_id)
        path = self.governance_memos_path(workspace_id)
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows[-max(1, min(limit, 1000)) :]

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
                "text": repair_text_encoding(text),
                "room": session.get("active_room", "lobby"),
            }
            row.update({key: value for key, value in metadata.items() if value not in (None, "")})
            transcript = self.session_dir(workspace_id, session_id) / "transcript.ndjson"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._touch_session(workspace_id, session_id, first_user_text=text if role == "user" else "")
            return row

    def save_file(
        self,
        workspace_id: str,
        session_id: str,
        filename: str,
        content: bytes,
        content_type: str = "",
        *,
        source: str = "upload",
        source_path: str = "",
        kind: str = "",
        scope: str = "",
        scope_ref: str = "",
        description: str = "",
        uploaded_by_session_id: str = "",
    ) -> Dict[str, Any]:
        with self._lock:
            session = self.find_session(session_id)
            if session.get("workspace_id") != workspace_id:
                raise KeyError("Session does not belong to workspace")
            safe_name = self._safe_path_component(filename, "")
            if not safe_name:
                raise ValueError("filename is required")
            file_id = _identifier("file")
            stored_name = f"{file_id}__{safe_name}"
            file_kind = str(kind or ("generated_file" if str(source or "") == "generated" else "upload"))
            file_scope = str(scope or ("room" if file_kind.startswith("generated_") else "session"))
            file_scope_ref = str(
                scope_ref
                or (session.get("active_room") if file_scope == "room" else session_id)
                or ("lobby" if file_scope == "room" else session_id)
            )
            if file_kind.startswith("generated_"):
                path = self.generated_files_dir(workspace_id, file_scope_ref) / stored_name
            else:
                path = self.files_dir(workspace_id, session_id) / stored_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            sha256 = hashlib.sha256(content).hexdigest()
            ledger_rows = self.list_artifact_ledger(workspace_id)
            artifact_number = len(ledger_rows) + 1
            now = utc_now()
            row = {
                "file_id": file_id,
                "artifact_number": artifact_number,
                "name": safe_name,
                "original_name": safe_name,
                "stored_name": stored_name,
                "content_type": content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
                "mime_type": content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
                "size": len(content),
                "byte_size": len(content),
                "sha256": sha256,
                "source": str(source or "upload"),
                "kind": file_kind,
                "scope": file_scope,
                "scope_ref": file_scope_ref,
                "room_id": str(session.get("active_room") or "lobby"),
                "description": str(description or ""),
                "uploaded_by_session_id": str(uploaded_by_session_id or session_id),
                "path": str(path.resolve()),
                "storage_path": str(path.resolve()),
                "created_at": now,
                "updated_at": now,
                "ledgered_at": now,
            }
            files = self.list_files(workspace_id, session_id)
            files.append(row)
            self._append_ndjson(
                self.artifact_ledger_path(workspace_id),
                {
                    "artifact_number": artifact_number,
                    "file_id": file_id,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "name": safe_name,
                    "content_type": row["content_type"],
                    "mime_type": row["mime_type"],
                    "size": len(content),
                    "byte_size": len(content),
                    "sha256": sha256,
                    "source": row["source"],
                    "kind": row["kind"],
                    "scope": row["scope"],
                    "scope_ref": row["scope_ref"],
                    "room_id": row["room_id"],
                    "description": row["description"],
                    "uploaded_by_session_id": row["uploaded_by_session_id"],
                    "source_path": str(source_path or ""),
                    "path": row["path"],
                    "storage_path": row["storage_path"],
                    "ledgered_at": row["ledgered_at"],
                },
            )
            self._write_json(self.files_manifest_path(workspace_id, session_id), files)
            self._touch_session(workspace_id, session_id)
            return row

    def prepare_generated_output_dir(self, workspace_id: str, session_id: str, request_id: str) -> Path:
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        safe_request_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(request_id or "generated")).strip("_")
        path = self.generated_staging_root(workspace_id, session_id) / (safe_request_id or "generated")
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    @staticmethod
    def _valid_generated_image(path: Path) -> bool:
        if path.suffix.lower() not in GENERATED_IMAGE_EXTENSIONS or not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("rb") as stream:
            header = stream.read(16)
        suffix = path.suffix.lower()
        if suffix == ".png":
            return header.startswith(b"\x89PNG\r\n\x1a\n")
        if suffix in {".jpg", ".jpeg"}:
            return header.startswith(b"\xff\xd8\xff")
        if suffix == ".gif":
            return header.startswith((b"GIF87a", b"GIF89a"))
        if suffix == ".webp":
            return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        return False

    @classmethod
    def _valid_generated_file(cls, path: Path) -> bool:
        """Validate supported generated media and document containers by content."""
        candidate = Path(path)
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        if candidate.suffix.lower() in GENERATED_IMAGE_EXTENSIONS:
            return cls._valid_generated_image(candidate)
        suffix = candidate.suffix.lower()
        if suffix not in GENERATED_DOCUMENT_EXTENSIONS:
            return False
        with candidate.open("rb") as stream:
            header = stream.read(8)
        if suffix == ".pdf":
            return header.startswith(b"%PDF-")
        if suffix == ".docx":
            if not header.startswith(b"PK"):
                return False
            try:
                import zipfile
                with zipfile.ZipFile(candidate) as archive:
                    names = set(archive.namelist())
                return "[Content_Types].xml" in names and "word/document.xml" in names
            except (OSError, zipfile.BadZipFile):
                return False
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        return bool(text.strip())

    def import_generated_file(
        self,
        workspace_id: str,
        session_id: str,
        source_path: Path,
        display_name: str = "",
    ) -> Dict[str, Any]:
        candidate = Path(source_path).resolve()
        if not self._valid_generated_file(candidate):
            raise ValueError(f"Generated file is missing, empty, unsupported, or invalid: {candidate}")
        content = candidate.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        file_kind = "generated_image" if candidate.suffix.lower() in GENERATED_IMAGE_EXTENSIONS else "generated_document"
        for existing in self.list_files(workspace_id, session_id):
            if str(existing.get("sha256") or "") == sha256 and str(existing.get("kind") or "") == file_kind:
                return existing
        session = self.find_session(session_id)
        active_room = str(session.get("active_room") or "lobby")
        name = display_name or candidate.name
        return self.save_file(
            workspace_id,
            session_id,
            name,
            content,
            mimetypes.guess_type(name)[0] or "application/octet-stream",
            source="generated",
            source_path=str(candidate),
            kind=file_kind,
            scope="room",
            scope_ref=active_room,
            description=f"Generated in {active_room}. Source staging file: {candidate}",
            uploaded_by_session_id=session_id,
        )

    def import_generated_artifacts(
        self,
        workspace_id: str,
        session_id: str,
        output_dir: Path,
    ) -> List[Dict[str, Any]]:
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        root = self.generated_staging_root(workspace_id, session_id).resolve()
        candidate_root = Path(output_dir).resolve()
        if candidate_root != root and root not in candidate_root.parents:
            raise ValueError("Generated output directory is outside the active session")
        if not candidate_root.is_dir():
            return []
        imported: List[Dict[str, Any]] = []
        for candidate in sorted(candidate_root.rglob("*")):
            if not self._valid_generated_file(candidate):
                continue
            imported.append(self.import_generated_file(workspace_id, session_id, candidate))
        return imported

    def verified_new_generated_files(
        self,
        workspace_id: str,
        session_id: str,
        known_file_ids: Iterable[str],
        room_id: str,
    ) -> List[Dict[str, Any]]:
        known = {str(file_id) for file_id in known_file_ids if str(file_id).strip()}
        ledger_by_file_id = {
            str(row.get("file_id")): row
            for row in self.list_artifact_ledger(workspace_id)
            if isinstance(row, dict) and str(row.get("file_id") or "").strip()
        }
        verified: List[Dict[str, Any]] = []
        for row in self.list_files(workspace_id, session_id):
            file_id = str(row.get("file_id") or "")
            if not file_id or file_id in known:
                continue
            if str(row.get("kind") or "") not in {"generated_image", "generated_document"}:
                continue
            if str(row.get("source") or "") != "generated":
                continue
            if str(row.get("scope") or "") != "room" or str(row.get("scope_ref") or "") != str(room_id or ""):
                continue
            if str(row.get("uploaded_by_session_id") or "") != session_id:
                continue
            path = Path(str(row.get("path") or ""))
            if not self._valid_generated_file(path):
                continue
            content = path.read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()
            if sha256 != str(row.get("sha256") or "").lower():
                continue
            if len(content) != int(row.get("size") or -1):
                continue
            ledger = ledger_by_file_id.get(file_id)
            if not ledger:
                continue
            if str(ledger.get("sha256") or "").lower() != sha256:
                continue
            if int(ledger.get("size") or -1) != len(content):
                continue
            if str(ledger.get("path") or "") != str(path.resolve()):
                continue
            if str(ledger.get("kind") or "") not in {"generated_image", "generated_document"}:
                continue
            if str(ledger.get("scope") or "") != "room" or str(ledger.get("scope_ref") or "") != str(room_id or ""):
                continue
            verified.append(row)
        return verified

    def list_files(self, workspace_id: str, session_id: str) -> List[Dict[str, Any]]:
        session = self.find_session(session_id)
        if session.get("workspace_id") != workspace_id:
            raise KeyError("Session does not belong to workspace")
        rows = self._read_json(self.files_manifest_path(workspace_id, session_id), [])
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict) and Path(str(row.get("path") or "")).is_file()]

    def resolve_files(self, workspace_id: str, session_id: str, file_ids: Iterable[str]) -> List[Dict[str, Any]]:
        wanted = {str(file_id) for file_id in file_ids if str(file_id).strip()}
        return [row for row in self.list_files(workspace_id, session_id) if str(row.get("file_id")) in wanted]

    def list_room_files(self, workspace_id: str, room_id: str) -> List[Dict[str, Any]]:
        """List ledgered files associated with one room across workspace sessions."""
        sessions = self.list_sessions(workspace_id)
        session_by_id = {str(row.get("session_id") or ""): row for row in sessions}
        legacy_rooms: Dict[str, str] = {}
        for session_id in session_by_id:
            for message in self.load_messages(workspace_id, session_id, limit=1000):
                message_room = str(message.get("room") or "")
                for collection_name in ("attachments", "generated_artifacts"):
                    artifacts = message.get(collection_name)
                    if not isinstance(artifacts, list):
                        continue
                    for artifact in artifacts:
                        if not isinstance(artifact, dict):
                            continue
                        file_id = str(artifact.get("file_id") or "")
                        if file_id and message_room:
                            legacy_rooms[file_id] = message_room

        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for ledger in self.list_artifact_ledger(workspace_id):
            file_id = str(ledger.get("file_id") or "")
            if not file_id or file_id in seen:
                continue
            artifact_room = (
                str(ledger.get("room_id") or "")
                or (
                    str(ledger.get("scope_ref") or "")
                    if str(ledger.get("scope") or "") == "room"
                    else ""
                )
                or legacy_rooms.get(file_id, "")
            )
            if artifact_room != room_id:
                continue
            path = Path(str(ledger.get("path") or ledger.get("storage_path") or ""))
            if not path.is_file() or path.stat().st_size <= 0:
                continue
            source_session_id = str(
                ledger.get("session_id") or ledger.get("uploaded_by_session_id") or ""
            )
            source_session = session_by_id.get(source_session_id, {})
            content_type = str(
                ledger.get("content_type")
                or ledger.get("mime_type")
                or mimetypes.guess_type(path.name)[0]
                or "application/octet-stream"
            )
            row = {
                **ledger,
                "file_id": file_id,
                "name": str(ledger.get("name") or path.name),
                "content_type": content_type,
                "mime_type": content_type,
                "size": int(ledger.get("size") or ledger.get("byte_size") or path.stat().st_size),
                "path": str(path.resolve()),
                "room_id": room_id,
                "source_session_id": source_session_id,
                "source_session_title": str(source_session.get("title") or "Room session"),
                "created_at": str(ledger.get("created_at") or ledger.get("ledgered_at") or ""),
            }
            seen.add(file_id)
            rows.append(row)
        return sorted(
            rows,
            key=lambda row: (
                str(row.get("created_at") or row.get("ledgered_at") or ""),
                int(row.get("artifact_number") or 0),
            ),
            reverse=True,
        )

    def list_generated_images(self, workspace_id: str, room_id: str = "art_department") -> List[Dict[str, Any]]:
        """List verified generated images for one room across workspace sessions."""
        rows: List[Dict[str, Any]] = []
        for row in self.list_room_files(workspace_id, room_id):
            is_generated = (
                str(row.get("kind") or "") == "generated_image"
                or str(row.get("source") or "") == "generated"
            )
            if not is_generated or not self._valid_generated_image(Path(str(row.get("path") or ""))):
                continue
            rows.append({
                **row,
                "source": "generated",
                "kind": "generated_image",
                "scope": "room",
                "scope_ref": room_id,
            })
        return rows

    def link_generated_image(
        self,
        workspace_id: str,
        session_id: str,
        file_id: str,
        room_id: str = "art_department",
    ) -> Dict[str, Any]:
        """Make a room-scoped generated image available to one session without copying it."""
        with self._lock:
            session = self.find_session(session_id)
            if session.get("workspace_id") != workspace_id:
                raise KeyError("Session does not belong to workspace")
            if str(session.get("active_room") or "") != room_id:
                raise ValueError("Generated Art Department images can only be attached from the Art Department.")
            normalized_file_id = str(file_id or "").strip()
            image = next(
                (
                    row for row in self.list_generated_images(workspace_id, room_id)
                    if str(row.get("file_id") or "") == normalized_file_id
                ),
                None,
            )
            if not image:
                raise KeyError("Unknown Art Department image")
            existing = next(
                (
                    row for row in self.list_files(workspace_id, session_id)
                    if str(row.get("file_id") or "") == normalized_file_id
                ),
                None,
            )
            if existing:
                existing["linked_at"] = utc_now()
                files = self.list_files(workspace_id, session_id)
                for index, row in enumerate(files):
                    if str(row.get("file_id") or "") == normalized_file_id:
                        files[index] = existing
                        break
                self._write_json(self.files_manifest_path(workspace_id, session_id), files)
                self._touch_session(workspace_id, session_id)
                return existing
            linked = {
                key: value for key, value in image.items()
                if key not in {"source_session_title"}
            }
            linked["linked_from_session_id"] = str(image.get("source_session_id") or "")
            linked["linked_at"] = utc_now()
            files = self.list_files(workspace_id, session_id)
            files.append(linked)
            self._write_json(self.files_manifest_path(workspace_id, session_id), files)
            self._touch_session(workspace_id, session_id)
            return linked

    def link_room_file(
        self,
        workspace_id: str,
        session_id: str,
        file_id: str,
        room_id: str,
    ) -> Dict[str, Any]:
        """Make a room-associated file available to the active session without copying it."""
        with self._lock:
            session = self.find_session(session_id)
            if session.get("workspace_id") != workspace_id:
                raise KeyError("Session does not belong to workspace")
            if str(session.get("active_room") or "") != str(room_id or ""):
                raise ValueError("Files can only be attached from the currently active room.")
            normalized_file_id = str(file_id or "").strip()
            source = next(
                (
                    row for row in self.list_room_files(workspace_id, room_id)
                    if str(row.get("file_id") or "") == normalized_file_id
                ),
                None,
            )
            if not source:
                raise KeyError("Unknown room file")
            files = self.list_files(workspace_id, session_id)
            existing = next(
                (row for row in files if str(row.get("file_id") or "") == normalized_file_id),
                None,
            )
            if existing:
                existing["linked_at"] = utc_now()
                self._write_json(self.files_manifest_path(workspace_id, session_id), files)
                self._touch_session(workspace_id, session_id)
                return existing
            linked = {
                key: value for key, value in source.items()
                if key not in {"source_session_title"}
            }
            linked["linked_from_session_id"] = str(source.get("source_session_id") or "")
            linked["linked_at"] = utc_now()
            files.append(linked)
            self._write_json(self.files_manifest_path(workspace_id, session_id), files)
            self._touch_session(workspace_id, session_id)
            return linked

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
                value["text"] = repair_text_encoding(value.get("text"))
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
        governance_state = self.ensure_governance_state(selected_workspace["workspace_id"])
        return {
            "account": self._read_json(self.account_path, DEFAULT_ACCOUNT),
            "workspaces": workspaces,
            "workspace": selected_workspace,
            "sessions": sessions,
            "session": selected_session,
            "messages": self.load_messages(selected_workspace["workspace_id"], selected_session["session_id"]),
            "files": self.list_files(selected_workspace["workspace_id"], selected_session["session_id"]),
            "rooms": rooms_payload(),
            "governance_state": governance_state,
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


def _compact_message_text(text: Any, max_chars: int = 650) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 14)].rstrip() + " ... [trimmed]"


def transcript_context(messages: Iterable[Dict[str, Any]], limit: int = 8) -> Dict[str, Any]:
    compact = []
    for row in list(messages)[-limit:]:
        compact.append(
            {
                "role": row.get("role"),
                "text": _compact_message_text(row.get("text")),
                "room": row.get("room"),
            }
        )
    return {"recent_transcript": compact, "governance": {"single_user": True, "active_room_limit": 1}}
