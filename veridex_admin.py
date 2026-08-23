"""Versioned, explicitly-approved administration for Veridex."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


PROPOSAL_STATUSES = {
    "draft",
    "awaiting_approval",
    "awaiting_second_approval",
    "approved",
    "applying",
    "verified",
    "failed",
    "rejected",
    "rolled_back",
}

PROTECTED_GOVERNANCE_IDS = {
    "NAVIGATOR-AUTHORITY",
    "TOOL-TRUTH-BOUNDARY",
    "PERSISTENCE-TRUTH",
    "NO-UNRELATED-DESTRUCTION",
    "PREFLIGHT",
    "VERIFICATION",
    "GATE-PREFLIGHT",
    "GATE-VERIFY",
    "DESTRUCTIVE-SCOPE-GATE",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def slug(value: str, separator: str = "_") -> str:
    normalized = re.sub(r"[^a-z0-9]+", separator, str(value or "").casefold()).strip(separator)
    return normalized


def policy_id(value: str) -> str:
    return slug(value, "-").upper()


def json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AdminService:
    """Own global catalogs, governed proposals, version history, and audit evidence."""

    def __init__(
        self,
        data_root: Path,
        repository_root: Path,
        base_rooms: Iterable[Dict[str, Any]],
        base_governance_path: Path,
        program_runner: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.repository_root = Path(repository_root).resolve()
        self.admin_root = self.data_root / "system" / "administration"
        self.room_catalog_path = self.admin_root / "room_catalog.json"
        self.governance_root = self.admin_root / "governance"
        self.active_governance_path = self.governance_root / "active.json"
        self.governance_versions_root = self.governance_root / "versions"
        self.proposals_root = self.admin_root / "proposals"
        self.audit_path = self.admin_root / "audit.ndjson"
        self.backups_root = self.admin_root / "backups"
        self.base_rooms = [dict(row) for row in base_rooms]
        self.base_governance_path = Path(base_governance_path).resolve()
        self.program_runner = program_runner
        self._lock = threading.RLock()
        self.ensure_initialized()

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

    def _audit(self, event: str, proposal: Dict[str, Any], **details: Any) -> Dict[str, Any]:
        row = {
            "audit_id": identifier("audit"),
            "timestamp": utc_now(),
            "event": event,
            "proposal_id": proposal.get("proposal_id"),
            "kind": proposal.get("kind"),
            "action": proposal.get("action"),
            "status": proposal.get("status"),
            **details,
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def ensure_initialized(self) -> None:
        with self._lock:
            if not self.room_catalog_path.exists():
                now = utc_now()
                rooms = []
                for row in self.base_rooms:
                    room = dict(row)
                    room.setdefault("purpose", f"Governed workspace for {room.get('title', room.get('id', 'this room'))}.")
                    room.setdefault("capabilities", [])
                    room.setdefault("aliases", [])
                    room.setdefault("created_at", now)
                    room.setdefault("updated_at", now)
                    rooms.append(room)
                self._write_json(
                    self.room_catalog_path,
                    {"catalog_id": "VERIDEX-GLOBAL-ROOMS", "version": 1, "updated_at": now, "rooms": rooms},
                )
            if not self.active_governance_path.exists():
                governance = self._read_json(self.base_governance_path, {})
                if not isinstance(governance, dict):
                    raise ValueError("The base governance registry is invalid")
                snapshot = dict(governance.get("snapshot") or {})
                snapshot.update({
                    "admin_revision": 1,
                    "activated_at": utc_now(),
                    "parent_sha256": None,
                    "base_registry_path": str(self.base_governance_path),
                })
                governance["snapshot"] = snapshot
                self._save_governance_version(governance)
            else:
                governance = self._read_json(self.active_governance_path, {})
                snapshot = dict(governance.get("snapshot") or {}) if isinstance(governance, dict) else {}
                if governance and not snapshot.get("base_registry_path"):
                    snapshot["base_registry_path"] = str(self.base_governance_path)
                    governance["snapshot"] = snapshot
                    self._save_governance_version(governance)

    def _save_governance_version(self, governance: Dict[str, Any]) -> None:
        revision = int((governance.get("snapshot") or {}).get("admin_revision") or 1)
        version_path = self.governance_versions_root / f"governance-{revision:06d}.json"
        self._write_json(version_path, governance)
        self._write_json(self.active_governance_path, governance)

    def room_catalog(self) -> Dict[str, Any]:
        value = self._read_json(self.room_catalog_path, {})
        if not isinstance(value, dict) or not isinstance(value.get("rooms"), list):
            raise ValueError("The global room catalog is invalid")
        return value

    def rooms(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in self.room_catalog().get("rooms", []) if isinstance(row, dict)]
        return rows if include_archived else [row for row in rows if row.get("is_active", False)]

    def governance(self) -> Dict[str, Any]:
        value = self._read_json(self.active_governance_path, {})
        if not isinstance(value, dict):
            raise ValueError("The active governance snapshot is invalid")
        return value

    def versions(self) -> Dict[str, Any]:
        catalog = self.room_catalog()
        governance = self.governance()
        return {
            "room_catalog": int(catalog.get("version") or 1),
            "governance": int((governance.get("snapshot") or {}).get("admin_revision") or 1),
        }

    def _proposal_path(self, proposal_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", str(proposal_id or ""))
        if not safe:
            raise ValueError("proposal_id is required")
        return self.proposals_root / f"{safe}.json"

    def get_proposal(self, proposal_id: str) -> Dict[str, Any]:
        value = self._read_json(self._proposal_path(proposal_id), None)
        if not isinstance(value, dict):
            raise KeyError(f"Unknown proposal: {proposal_id}")
        return value

    def list_proposals(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if self.proposals_root.exists():
            for path in self.proposals_root.glob("proposal_*.json"):
                value = self._read_json(path, None)
                if isinstance(value, dict):
                    rows.append(value)
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return rows[: max(1, min(int(limit or 100), 500))]

    def audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows[-max(1, min(int(limit or 100), 1000)) :]

    def _current_version_for(self, kind: str) -> int:
        versions = self.versions()
        return versions["room_catalog"] if kind == "room" else versions["governance"] if kind in {"rule", "gate"} else 0

    def repository_revision(self) -> str:
        rows: Dict[str, str] = {}
        excluded = {".git", "data", "__pycache__", ".pytest_cache", "node_modules", ".next"}
        for path in self.repository_root.rglob("*"):
            if not path.is_file() or any(part in excluded for part in path.relative_to(self.repository_root).parts):
                continue
            try:
                rows[path.relative_to(self.repository_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
        return json_hash(rows)

    @staticmethod
    def _required_text(payload: Dict[str, Any], name: str) -> str:
        value = " ".join(str(payload.get(name) or "").split()).strip()
        if not value:
            raise ValueError(f"{name} is required")
        return value

    def _normalize_payload(self, kind: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        value = dict(payload or {})
        if kind == "room":
            if action == "create":
                title = self._required_text(value, "title")
                value["title"] = title
                value["id"] = slug(str(value.get("id") or title))
                value["default_persona"] = " ".join(str(value.get("default_persona") or "Room Steward").split())
                value["purpose"] = " ".join(str(value.get("purpose") or f"Governed workspace for {title}.").split())
                value["capabilities"] = sorted({str(item).strip() for item in value.get("capabilities", []) if str(item).strip()})
                value["aliases"] = sorted({str(item).strip() for item in value.get("aliases", []) if str(item).strip()})
            else:
                value["target_id"] = slug(self._required_text(value, "target_id"))
        elif kind in {"rule", "gate"}:
            if action == "add":
                text_field = "text" if kind == "rule" else "definition"
                statement = self._required_text(value, text_field)
                value[text_field] = statement
                value["id"] = policy_id(str(value.get("id") or statement[:48]))
            else:
                value["target_id"] = policy_id(self._required_text(value, "target_id"))
                if action == "amend":
                    text_field = "text" if kind == "rule" else "definition"
                    value[text_field] = self._required_text(value, text_field)
                reason = " ".join(str(value.get("reason") or "").split())
                if action == "disable" and not reason:
                    raise ValueError("reason is required when disabling governance")
                value["reason"] = reason
        elif kind == "program":
            value["title"] = self._required_text(value, "title")
            value["instructions"] = self._required_text(value, "instructions")
            allowed_paths = [str(item).replace("\\", "/").strip(" /") for item in value.get("allowed_paths", []) if str(item).strip(" /")]
            if not allowed_paths:
                raise ValueError("allowed_paths must name at least one repository-scoped file or directory")
            for relative in allowed_paths:
                candidate = (self.repository_root / relative).resolve()
                if candidate != self.repository_root and self.repository_root not in candidate.parents:
                    raise ValueError(f"allowed path leaves the Veridex repository: {relative}")
                if relative.startswith((".git", "data/", "data\\")):
                    raise ValueError(f"administrative code changes cannot target {relative}")
            value["allowed_paths"] = sorted(set(allowed_paths))
            value["tests"] = [str(item).strip() for item in value.get("tests", []) if str(item).strip()]
            if not value["tests"]:
                raise ValueError("tests must include at least one verification command")
        else:
            raise ValueError(f"Unsupported proposal kind: {kind}")
        return value

    def _validate_target(self, kind: str, action: str, payload: Dict[str, Any]) -> None:
        if kind == "room":
            rows = self.rooms(include_archived=True)
            if action == "create" and any(row.get("id") == payload.get("id") for row in rows):
                raise ValueError(f"Room already exists: {payload.get('id')}")
            if action != "create" and not any(row.get("id") == payload.get("target_id") for row in rows):
                raise ValueError(f"Unknown room: {payload.get('target_id')}")
            if action == "archive" and payload.get("target_id") in {"lobby", "control_room", "infrastructure_room"}:
                raise ValueError("Core operating rooms cannot be archived")
        elif kind in {"rule", "gate"}:
            collection = "core_rules" if kind == "rule" else "gates"
            rows = [row for row in self.governance().get(collection, []) if isinstance(row, dict)]
            target_id = payload.get("id") if action == "add" else payload.get("target_id")
            found = next((row for row in rows if str(row.get("id") or "").upper() == target_id), None)
            if action == "add" and found:
                raise ValueError(f"Governance item already exists: {target_id}")
            if action != "add" and not found:
                raise ValueError(f"Unknown governance item: {target_id}")
            if action == "disable" and target_id in PROTECTED_GOVERNANCE_IDS:
                raise ValueError(f"{target_id} is part of the non-disableable safety kernel")

    def create_proposal(
        self,
        kind: str,
        action: str,
        payload: Dict[str, Any],
        *,
        requested_by: str = "Local User",
        workspace_id: str = "",
        session_id: str = "",
    ) -> Dict[str, Any]:
        kind = str(kind or "").strip().lower()
        action = str(action or "").strip().lower()
        allowed_actions = {
            "room": {"create", "update", "archive", "restore"},
            "rule": {"add", "amend", "disable", "restore"},
            "gate": {"add", "amend", "disable", "restore"},
            "program": {"change"},
        }
        if action not in allowed_actions.get(kind, set()):
            raise ValueError(f"Unsupported {kind or 'administrative'} action: {action}")
        normalized = self._normalize_payload(kind, action, payload)
        self._validate_target(kind, action, normalized)
        high_risk = kind == "program" or (kind in {"rule", "gate"} and action in {"amend", "disable"})
        current_version = self._current_version_for(kind)
        now = utc_now()
        proposal = {
            "proposal_id": identifier("proposal"),
            "kind": kind,
            "action": action,
            "status": "awaiting_approval",
            "scope": "global",
            "payload": normalized,
            "base_version": current_version,
            "base_revision": self.repository_revision() if kind == "program" else "",
            "risk_level": "high" if high_risk else "standard",
            "approvals_required": 2 if kind in {"rule", "gate"} and action in {"amend", "disable"} else 1,
            "approvals_received": 0,
            "navigator": {
                "status": "validated",
                "protected_kernel": sorted(PROTECTED_GOVERNANCE_IDS),
                "findings": self._impact_findings(kind, action, normalized),
            },
            "requested_by": requested_by,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
        }
        self._write_json(self._proposal_path(proposal["proposal_id"]), proposal)
        self._audit("proposal_created", proposal, base_version=current_version, risk_level=proposal["risk_level"])
        return proposal

    def _impact_findings(self, kind: str, action: str, payload: Dict[str, Any]) -> List[str]:
        if kind == "room":
            if action == "create":
                return ["The room will appear in every workspace.", "Existing sessions remain in their current room."]
            return ["Existing transcripts retain their recorded room ID.", "Active sessions are not moved automatically."]
        if kind in {"rule", "gate"}:
            findings = ["A new hashed governance snapshot will become active globally."]
            if action in {"amend", "disable"}:
                findings.append("This can weaken existing protections and therefore requires two approvals.")
            return findings
        return ["Approved code edits are limited to the listed paths.", "Tests and Navigator verification must pass before activation."]

    def reject(self, proposal_id: str, reason: str = "") -> Dict[str, Any]:
        with self._lock:
            proposal = self.get_proposal(proposal_id)
            if proposal.get("status") not in {"awaiting_approval", "awaiting_second_approval"}:
                raise ValueError("Only pending proposals may be rejected")
            proposal.update({"status": "rejected", "rejection_reason": str(reason or "User rejected proposal"), "updated_at": utc_now()})
            self._write_json(self._proposal_path(proposal_id), proposal)
            self._audit("proposal_rejected", proposal, reason=proposal["rejection_reason"])
            return proposal

    def approve_and_apply(
        self,
        proposal_id: str,
        *,
        expected_version: int,
        confirm: bool,
        second_confirmation_token: str = "",
    ) -> Dict[str, Any]:
        with self._lock:
            proposal = self.get_proposal(proposal_id)
            if not confirm:
                return {"status": "confirmation_required", "proposal": proposal}
            if proposal.get("status") not in {"awaiting_approval", "awaiting_second_approval"}:
                raise ValueError(f"Proposal is not awaiting approval: {proposal.get('status')}")
            current_version = self._current_version_for(str(proposal.get("kind") or ""))
            if int(expected_version) != int(proposal.get("base_version") or 0) or current_version != int(proposal.get("base_version") or 0):
                raise ValueError("Proposal is stale; create a new preview against the current version")
            if proposal.get("kind") == "program" and str(proposal.get("base_revision") or "") != self.repository_revision():
                raise ValueError("Program proposal is stale; the Veridex source changed after its preview")
            if int(proposal.get("approvals_required") or 1) == 2:
                if proposal.get("status") == "awaiting_approval":
                    token = secrets.token_urlsafe(18)
                    proposal.update({
                        "status": "awaiting_second_approval",
                        "approvals_received": 1,
                        "second_confirmation_token": token,
                        "updated_at": utc_now(),
                    })
                    self._write_json(self._proposal_path(proposal_id), proposal)
                    self._audit("first_approval_recorded", proposal)
                    return {
                        "status": "second_confirmation_required",
                        "warning": "This change weakens or replaces active governance. Review the impact and confirm again.",
                        "second_confirmation_token": token,
                        "proposal": proposal,
                    }
                expected_token = str(proposal.get("second_confirmation_token") or "")
                if not expected_token or not secrets.compare_digest(expected_token, str(second_confirmation_token or "")):
                    raise ValueError("The second confirmation token is missing or invalid")
            proposal.update({"status": "approved", "approvals_received": proposal.get("approvals_required", 1), "updated_at": utc_now()})
            proposal.pop("second_confirmation_token", None)
            self._write_json(self._proposal_path(proposal_id), proposal)
            self._audit("proposal_approved", proposal)
            proposal["status"] = "applying"
            proposal["updated_at"] = utc_now()
            self._write_json(self._proposal_path(proposal_id), proposal)
            try:
                result = self._apply(proposal)
            except Exception as exc:
                proposal.update({"status": "failed", "error": str(exc), "updated_at": utc_now()})
                self._write_json(self._proposal_path(proposal_id), proposal)
                self._audit("proposal_failed", proposal, error=str(exc))
                raise
            if proposal.get("kind") == "program":
                result["applied_revision"] = self.repository_revision()
            proposal.update({"status": "verified", "result": result, "verified_at": utc_now(), "updated_at": utc_now()})
            self._write_json(self._proposal_path(proposal_id), proposal)
            self._audit("proposal_verified", proposal, result=result)
            return proposal

    def _apply(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(proposal["kind"])
        if kind == "room":
            return self._apply_room(proposal)
        if kind in {"rule", "gate"}:
            return self._apply_governance(proposal)
        if kind == "program":
            if self.program_runner is None:
                raise RuntimeError("Program-change runner is unavailable")
            result = self.program_runner(proposal)
            if not isinstance(result, dict) or not result.get("verified"):
                raise RuntimeError(str((result or {}).get("error") or "Program change did not pass verification"))
            return result
        raise ValueError(f"Unsupported proposal kind: {kind}")

    def _apply_room(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        catalog = self.room_catalog()
        before = json.loads(json.dumps(catalog))
        rooms = [dict(row) for row in catalog.get("rooms", [])]
        payload = dict(proposal["payload"])
        action = proposal["action"]
        now = utc_now()
        if action == "create":
            rooms.append({
                "id": payload["id"],
                "title": payload["title"],
                "default_persona": payload["default_persona"],
                "purpose": payload["purpose"],
                "capabilities": payload.get("capabilities", []),
                "aliases": payload.get("aliases", []),
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            })
        else:
            target = next(row for row in rooms if row.get("id") == payload["target_id"])
            if action == "update":
                for key in ("title", "default_persona", "purpose", "capabilities", "aliases"):
                    if key in payload:
                        target[key] = payload[key]
            elif action == "archive":
                target["is_active"] = False
            elif action == "restore":
                target["is_active"] = True
            target["updated_at"] = now
        catalog.update({"version": int(catalog.get("version") or 1) + 1, "updated_at": now, "rooms": rooms})
        self._write_json(self.room_catalog_path, catalog)
        backup_path = self.backups_root / proposal["proposal_id"] / "room_catalog.json"
        self._write_json(backup_path, before)
        return {"catalog_version": catalog["version"], "room_count": len([row for row in rooms if row.get("is_active")]), "rollback_path": str(backup_path)}

    def _apply_governance(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        governance = self.governance()
        before = json.loads(json.dumps(governance))
        payload = dict(proposal["payload"])
        collection = "core_rules" if proposal["kind"] == "rule" else "gates"
        rows = [dict(row) for row in governance.get(collection, [])]
        action = proposal["action"]
        now = utc_now()
        if action == "add":
            if proposal["kind"] == "rule":
                rows.append({"id": payload["id"], "text": payload["text"], "status": "active", "created_at": now})
            else:
                rows.append({
                    "id": payload["id"],
                    "version": f"admin-{int((governance.get('snapshot') or {}).get('admin_revision') or 1) + 1}",
                    "status": "active",
                    "applicability": str(payload.get("applicability") or "configured"),
                    "definition": payload["definition"],
                    "created_at": now,
                })
        else:
            target = next(row for row in rows if str(row.get("id") or "").upper() == payload["target_id"])
            history = list(target.get("history") or [])
            history.append({"changed_at": now, "proposal_id": proposal["proposal_id"], "previous": dict(target)})
            if action == "amend":
                target["text" if proposal["kind"] == "rule" else "definition"] = payload["text" if proposal["kind"] == "rule" else "definition"]
                target["status"] = "active"
            elif action == "disable":
                target["status"] = "disabled"
                target["disabled_reason"] = payload["reason"]
            elif action == "restore":
                target["status"] = "active"
                target.pop("disabled_reason", None)
            target["history"] = history
            target["updated_at"] = now
        governance[collection] = rows
        previous_hash = json_hash(before)
        snapshot = dict(governance.get("snapshot") or {})
        revision = int(snapshot.get("admin_revision") or 1) + 1
        snapshot.update({
            "admin_revision": revision,
            "version": f"1.0.0-admin.{revision}",
            "activated_at": now,
            "parent_sha256": previous_hash,
            "proposal_id": proposal["proposal_id"],
        })
        governance["snapshot"] = snapshot
        backup_path = self.backups_root / proposal["proposal_id"] / "governance.json"
        self._write_json(backup_path, before)
        self._save_governance_version(governance)
        return {"governance_version": revision, "registry_sha256": json_hash(governance), "rollback_path": str(backup_path)}

    def rollback(self, proposal_id: str, *, confirm: bool) -> Dict[str, Any]:
        with self._lock:
            proposal = self.get_proposal(proposal_id)
            if not confirm:
                return {"status": "confirmation_required", "proposal": proposal}
            if proposal.get("status") != "verified":
                raise ValueError("Only verified proposals may be rolled back")
            if proposal.get("kind") == "room":
                if int(self.room_catalog().get("version") or 0) != int((proposal.get("result") or {}).get("catalog_version") or -1):
                    raise ValueError("Room catalog changed after this proposal; direct rollback would overwrite newer changes")
                backup = self._read_json(self.backups_root / proposal_id / "room_catalog.json", None)
                if not isinstance(backup, dict):
                    raise ValueError("Room rollback evidence is unavailable")
                current = self.room_catalog()
                backup["version"] = int(current.get("version") or 1) + 1
                backup["updated_at"] = utc_now()
                self._write_json(self.room_catalog_path, backup)
                result = {"catalog_version": backup["version"]}
            elif proposal.get("kind") in {"rule", "gate"}:
                if int((self.governance().get("snapshot") or {}).get("admin_revision") or 0) != int((proposal.get("result") or {}).get("governance_version") or -1):
                    raise ValueError("Governance changed after this proposal; direct rollback would overwrite newer changes")
                backup = self._read_json(self.backups_root / proposal_id / "governance.json", None)
                if not isinstance(backup, dict):
                    raise ValueError("Governance rollback evidence is unavailable")
                current_revision = int((self.governance().get("snapshot") or {}).get("admin_revision") or 1)
                snapshot = dict(backup.get("snapshot") or {})
                snapshot.update({
                    "admin_revision": current_revision + 1,
                    "version": f"1.0.0-admin.{current_revision + 1}",
                    "activated_at": utc_now(),
                    "rollback_of": proposal_id,
                })
                backup["snapshot"] = snapshot
                self._save_governance_version(backup)
                result = {"governance_version": current_revision + 1, "registry_sha256": json_hash(backup)}
            else:
                if str((proposal.get("result") or {}).get("applied_revision") or "") != self.repository_revision():
                    raise ValueError("Veridex source changed after this proposal; direct rollback would overwrite newer work")
                rollback = (proposal.get("result") or {}).get("rollback")
                if not isinstance(rollback, dict) or not rollback.get("supported"):
                    raise ValueError("Program rollback evidence is unavailable")
                manifest = rollback.get("manifest") if isinstance(rollback.get("manifest"), list) else []
                if not manifest:
                    raise ValueError("Program rollback manifest is unavailable")
                restored: List[str] = []
                for row in manifest:
                    relative = str(row.get("path") or "").replace("\\", "/").strip("/")
                    target = (self.repository_root / relative).resolve()
                    if target != self.repository_root and self.repository_root not in target.parents:
                        raise ValueError(f"Rollback target leaves the repository: {relative}")
                    backup = Path(str(row.get("backup_path") or "")).resolve() if row.get("backup_path") else None
                    existed = bool(row.get("existed"))
                    if target.exists():
                        if target.is_dir():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    if existed:
                        if backup is None or not backup.exists():
                            raise ValueError(f"Rollback backup is unavailable for {relative}")
                        if backup.is_dir():
                            shutil.copytree(backup, target)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(backup, target)
                    restored.append(relative)
                result = {"restored_paths": restored, "restart_required": True}
            proposal.update({"status": "rolled_back", "rolled_back_at": utc_now(), "rollback_result": result, "updated_at": utc_now()})
            self._write_json(self._proposal_path(proposal_id), proposal)
            self._audit("proposal_rolled_back", proposal, result=result)
            return proposal

    def bootstrap(self) -> Dict[str, Any]:
        governance = self.governance()
        proposals = []
        for stored in self.list_proposals():
            public = dict(stored)
            public.pop("second_confirmation_token", None)
            proposals.append(public)
        return {
            "versions": self.versions(),
            "rooms": self.rooms(include_archived=True),
            "proposals": proposals,
            "audit": self.audit_log(limit=30),
            "protected_governance_ids": sorted(PROTECTED_GOVERNANCE_IDS),
            "governance_snapshot": {
                "version": (governance.get("snapshot") or {}).get("version"),
                "admin_revision": (governance.get("snapshot") or {}).get("admin_revision"),
                "sha256": json_hash(governance),
            },
        }
