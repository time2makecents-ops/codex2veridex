"""Workspace-scoped, review-first Facebook Marketplace listing drafts."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable
from urllib.parse import urlparse


ALLOWED_STATUSES = {
    "draft",
    "facebook_prepared",
    "human_action_required",
    "published_observed",
    "group_share_prepared",
    "failed",
}
ALLOWED_CONDITIONS = {"new", "like_new", "good", "fair", "poor"}
MAX_PHOTOS = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _body_text(value: Any, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()[:limit]


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class FacebookMarketplace:
    """Atomic workspace persistence for Marketplace drafts and approved groups."""

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root).resolve()
        self._lock = threading.RLock()

    @staticmethod
    def _safe_component(value: str, label: str) -> str:
        candidate = str(value or "").strip()
        if not candidate or not re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
            raise ValueError(f"{label} is invalid")
        return candidate

    def root(self, workspace_id: str) -> Path:
        workspace = self._safe_component(workspace_id, "workspace_id")
        return self.data_root / "workspaces" / workspace / "integrations" / "facebook_marketplace"

    def drafts_path(self, workspace_id: str) -> Path:
        return self.root(workspace_id) / "drafts.json"

    def groups_path(self, workspace_id: str) -> Path:
        return self.root(workspace_id) / "groups.json"

    def audit_path(self, workspace_id: str) -> Path:
        return self.root(workspace_id) / "audit.ndjson"

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

    def _audit(self, workspace_id: str, event: str, **details: Any) -> None:
        path = self.audit_path(workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"timestamp": _now(), "event": event, **details}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def normalize_group_url(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("Facebook group URL is required")
        try:
            parsed = urlparse(raw)
        except ValueError as exc:
            raise ValueError("Facebook group URL is invalid") from exc
        if parsed.scheme != "https" or parsed.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"}:
            raise ValueError("Group URL must be an HTTPS facebook.com URL")
        match = re.fullmatch(r"/groups/([A-Za-z0-9._-]+)/?", parsed.path)
        if not match:
            raise ValueError("Group URL must identify one Facebook group")
        return f"https://www.facebook.com/groups/{match.group(1)}"

    def list_groups(self, workspace_id: str) -> list[Dict[str, Any]]:
        rows = self._read_json(self.groups_path(workspace_id), [])
        return [dict(row) for row in rows if isinstance(row, dict) and row.get("group_id")]

    def save_group(self, workspace_id: str, value: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            url = self.normalize_group_url(value.get("url"))
            name = _text(value.get("name"), 120) or url.rsplit("/", 1)[-1]
            rows = self.list_groups(workspace_id)
            requested_id = str(value.get("group_id") or "").strip()
            existing = next((row for row in rows if row.get("group_id") == requested_id or row.get("url") == url), None)
            now = _now()
            row = {
                "group_id": str((existing or {}).get("group_id") or _identifier("fbgroup")),
                "name": name,
                "url": url,
                "created_at": str((existing or {}).get("created_at") or now),
                "updated_at": now,
            }
            rows = [candidate for candidate in rows if candidate.get("group_id") != row["group_id"] and candidate.get("url") != url]
            rows.append(row)
            rows.sort(key=lambda candidate: str(candidate.get("name") or "").lower())
            self._write_json(self.groups_path(workspace_id), rows)
            self._audit(workspace_id, "group_saved", group_id=row["group_id"], url=row["url"])
            return row

    def delete_group(self, workspace_id: str, group_id: str) -> bool:
        with self._lock:
            target = self._safe_component(group_id, "group_id")
            rows = self.list_groups(workspace_id)
            remaining = [row for row in rows if str(row.get("group_id") or "") != target]
            if len(remaining) == len(rows):
                return False
            self._write_json(self.groups_path(workspace_id), remaining)
            self._audit(workspace_id, "group_removed", group_id=target)
            return True

    def list_drafts(self, workspace_id: str) -> list[Dict[str, Any]]:
        rows = self._read_json(self.drafts_path(workspace_id), [])
        drafts = [dict(row) for row in rows if isinstance(row, dict) and row.get("draft_id")]
        drafts.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return drafts

    def get_draft(self, workspace_id: str, draft_id: str) -> Dict[str, Any]:
        target = self._safe_component(draft_id, "draft_id")
        row = next((value for value in self.list_drafts(workspace_id) if value.get("draft_id") == target), None)
        if not row:
            raise KeyError("Unknown Facebook Marketplace draft")
        return row

    @staticmethod
    def _price(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Asking price must be a number") from exc
        if not math.isfinite(number) or number < 0 or number >= 100_000_000:
            raise ValueError("Asking price is outside the supported range")
        return round(number, 2)

    def save_draft(
        self,
        workspace_id: str,
        session_id: str,
        value: Dict[str, Any],
        verified_photos: Iterable[Dict[str, Any]],
        *,
        price_suggestion: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        with self._lock:
            title = _text(value.get("title"), 200)
            description = _body_text(value.get("description"), 5000)
            category = _text(value.get("category"), 120)
            condition = str(value.get("condition") or "good").strip().lower()
            if not title:
                raise ValueError("Listing title is required")
            if not description:
                raise ValueError("Listing description is required")
            if not category:
                raise ValueError("Listing category is required")
            if condition not in ALLOWED_CONDITIONS:
                raise ValueError("Listing condition is invalid")
            photos = []
            seen: set[str] = set()
            for photo in verified_photos:
                file_id = str(photo.get("file_id") or "")
                if not file_id or file_id in seen:
                    continue
                seen.add(file_id)
                photos.append({key: photo.get(key) for key in (
                    "file_id", "session_id", "name", "content_type", "size", "sha256", "path"
                ) if photo.get(key) not in (None, "")})
            if not photos:
                raise ValueError("Select at least one verified item photo")
            if len(photos) > MAX_PHOTOS:
                raise ValueError(f"Facebook Marketplace drafts support up to {MAX_PHOTOS} photos")
            allowed_group_ids = {str(row.get("group_id") or "") for row in self.list_groups(workspace_id)}
            selected_group_ids = list(dict.fromkeys(
                str(group_id) for group_id in value.get("group_ids", []) if str(group_id) in allowed_group_ids
            ))
            rows = self.list_drafts(workspace_id)
            requested_id = str(value.get("draft_id") or "").strip()
            existing = next((row for row in rows if row.get("draft_id") == requested_id), {})
            now = _now()
            revision = int(existing.get("revision") or 0) + 1
            draft = {
                **existing,
                "draft_id": str(existing.get("draft_id") or _identifier("fbdraft")),
                "workspace_id": self._safe_component(workspace_id, "workspace_id"),
                "session_id": self._safe_component(session_id, "session_id"),
                "source_case_id": _text(value.get("source_case_id"), 100),
                "title": title,
                "description": description,
                "category": category,
                "condition": condition,
                "price": self._price(value.get("price")),
                "currency": "USD",
                "fulfillment": "local_pickup",
                "location_policy": "facebook_existing",
                "photos": photos,
                "group_ids": selected_group_ids,
                "price_suggestion": dict(price_suggestion or value.get("price_suggestion") or {}),
                "status": "draft",
                "last_error": "",
                "revision": revision,
                "created_at": str(existing.get("created_at") or now),
                "updated_at": now,
                "group_preparations": list(existing.get("group_preparations") or []),
            }
            rows = [row for row in rows if row.get("draft_id") != draft["draft_id"]]
            rows.append(draft)
            self._write_json(self.drafts_path(workspace_id), rows)
            fingerprint = hashlib.sha256(json.dumps({
                "title": title, "price": draft["price"], "photos": [row["sha256"] for row in photos]
            }, sort_keys=True).encode("utf-8")).hexdigest()
            self._audit(
                workspace_id,
                "draft_saved",
                draft_id=draft["draft_id"],
                revision=revision,
                fingerprint=fingerprint,
            )
            return draft

    def update_status(
        self,
        workspace_id: str,
        draft_id: str,
        status: str,
        *,
        result: Dict[str, Any] | None = None,
        error: str = "",
    ) -> Dict[str, Any]:
        if status not in ALLOWED_STATUSES:
            raise ValueError("Marketplace draft status is invalid")
        with self._lock:
            draft = self.get_draft(workspace_id, draft_id)
            now = _now()
            draft["status"] = status
            draft["updated_at"] = now
            draft["last_error"] = _text(error, 1000)
            safe_result = dict(result or {})
            if safe_result.get("listing_url"):
                draft["listing_url"] = str(safe_result["listing_url"])
            if safe_result.get("page_url"):
                draft["last_page_url"] = str(safe_result["page_url"])
            if safe_result.get("group_id"):
                preparations = list(draft.get("group_preparations") or [])
                preparations.append({
                    "group_id": str(safe_result.get("group_id") or ""),
                    "prepared_at": now,
                    "page_url": str(safe_result.get("page_url") or ""),
                })
                draft["group_preparations"] = preparations[-100:]
            rows = [row for row in self.list_drafts(workspace_id) if row.get("draft_id") != draft["draft_id"]]
            rows.append(draft)
            self._write_json(self.drafts_path(workspace_id), rows)
            self._audit(
                workspace_id,
                "draft_status_changed",
                draft_id=draft["draft_id"],
                status=status,
                evidence={key: safe_result.get(key) for key in ("listing_url", "page_url", "group_id") if safe_result.get(key)},
                error=draft["last_error"],
            )
            return draft

    @staticmethod
    def public_draft(value: Dict[str, Any]) -> Dict[str, Any]:
        draft = json.loads(json.dumps(value))
        for photo in draft.get("photos", []):
            if isinstance(photo, dict):
                photo.pop("path", None)
        return draft

    def bootstrap(self, workspace_id: str) -> Dict[str, Any]:
        return {
            "drafts": [self.public_draft(row) for row in self.list_drafts(workspace_id)],
            "groups": self.list_groups(workspace_id),
            "constraints": {
                "max_photos": MAX_PHOTOS,
                "conditions": sorted(ALLOWED_CONDITIONS),
                "fulfillment": "local_pickup",
                "final_publish_is_manual": True,
                "final_group_post_is_manual": True,
            },
        }
