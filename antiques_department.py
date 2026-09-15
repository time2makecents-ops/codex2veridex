"""Museum state, consent, valuation, and research-case helpers."""

from __future__ import annotations

import json
import math
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from PIL import Image, ImageOps

from museum_visual_analysis import FOCUS_OPTIONS, PHOTO_ROLES


ROOM_ID = "antiques_department"
SHOPPING_MODE_HOURS = 4
DEFAULT_SETTINGS: Dict[str, Any] = {
    "currency": "USD",
    "market": "United States",
    "fee_percent": 15.0,
    "packing_shipping_allowance": 15.0,
    "uncertainty_reserve_percent": 10.0,
    "minimum_target_profit": 30.0,
    "quick_buy_cap_percent": 25.0,
}

SOURCE_REGISTRY = [
    {"id": "google_lens", "name": "Google Lens", "kind": "visual_match", "photo_upload": True, "optional_account": False},
    {"id": "google", "name": "Google Search", "kind": "web_search", "photo_upload": False, "optional_account": False},
    {"id": "ebay", "name": "eBay Product Research", "kind": "sold_comparables", "photo_upload": False, "optional_account": True},
    {"id": "liveauctioneers", "name": "LiveAuctioneers", "kind": "auction_results", "photo_upload": False, "optional_account": False},
    {"id": "kovels", "name": "Kovels Marks", "kind": "makers_marks", "photo_upload": False, "optional_account": False},
    {"id": "marks_project", "name": "The Marks Project", "kind": "ceramic_marks_and_artists", "photo_upload": False, "optional_account": False},
    {"id": "smithsonian", "name": "Smithsonian Collections", "kind": "museum_records", "photo_upload": False, "optional_account": False},
    {"id": "worthpoint", "name": "WorthPoint", "kind": "historical_comparables", "photo_upload": False, "optional_account": True},
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _bounded_text(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit]


class AntiquesDepartment:
    """Workspace-scoped Museum storage and deterministic policy."""

    def __init__(self, data_root: Path):
        self.workspaces_root = Path(data_root).resolve() / "workspaces"
        self._lock = threading.RLock()

    def root(self, workspace_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "", str(workspace_id or ""))
        if not safe:
            raise ValueError("workspace_id is required")
        return self.workspaces_root / safe / "antiques"

    def settings_path(self, workspace_id: str) -> Path:
        return self.root(workspace_id) / "settings.json"

    def shopping_path(self, workspace_id: str, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "", str(session_id or ""))
        if not safe:
            raise ValueError("session_id is required")
        return self.root(workspace_id) / "shopping_modes" / f"{safe}.json"

    def cases_root(self, workspace_id: str) -> Path:
        return self.root(workspace_id) / "cases"

    def pending_path(self, workspace_id: str, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "", str(session_id or ""))
        if not safe:
            raise ValueError("session_id is required")
        return self.root(workspace_id) / "pending" / f"{safe}.json"

    def case_path(self, workspace_id: str, case_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "", str(case_id or ""))
        if not safe:
            raise ValueError("case_id is required")
        return self.cases_root(workspace_id) / f"{safe}.json"

    def external_audit_path(self, workspace_id: str) -> Path:
        return self.root(workspace_id) / "external_uploads.ndjson"

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

    def settings(self, workspace_id: str) -> Dict[str, Any]:
        saved = self._read_json(self.settings_path(workspace_id), {})
        return {**DEFAULT_SETTINGS, **(saved if isinstance(saved, dict) else {})}

    def update_settings(self, workspace_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        numeric = {
            "fee_percent": (0.0, 50.0),
            "packing_shipping_allowance": (0.0, 10000.0),
            "uncertainty_reserve_percent": (0.0, 75.0),
            "minimum_target_profit": (0.0, 1000000.0),
            "quick_buy_cap_percent": (1.0, 100.0),
        }
        next_value = self.settings(workspace_id)
        for key, (minimum, maximum) in numeric.items():
            if key not in values:
                continue
            number = float(values[key])
            if not math.isfinite(number) or number < minimum or number > maximum:
                raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}")
            next_value[key] = round(number, 2)
        for key in ("currency", "market"):
            if key in values:
                text = _bounded_text(values[key], 100)
                if not text:
                    raise ValueError(f"{key} is required")
                next_value[key] = text
        next_value["updated_at"] = utc_now()
        with self._lock:
            self._write_json(self.settings_path(workspace_id), next_value)
        return next_value

    def start_shopping_mode(self, workspace_id: str, session_id: str, active_room: str) -> Dict[str, Any]:
        if active_room != ROOM_ID:
            raise ValueError("Shopping mode is available only in Museum")
        now = datetime.now(timezone.utc)
        value = {
            "active": True,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "scope": "google_lens_photo_uploads",
            "started_at": now.isoformat().replace("+00:00", "Z"),
            "last_activity_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(hours=SHOPPING_MODE_HOURS)).isoformat().replace("+00:00", "Z"),
            "consent_basis": "user_trigger_phrase",
        }
        with self._lock:
            self._write_json(self.shopping_path(workspace_id, session_id), value)
        return value

    def shopping_status(self, workspace_id: str, session_id: str, active_room: str = ROOM_ID) -> Dict[str, Any]:
        value = self._read_json(self.shopping_path(workspace_id, session_id), {})
        if not isinstance(value, dict) or not value.get("active"):
            return {"active": False, "scope": "google_lens_photo_uploads"}
        expires = _parse_time(value.get("expires_at"))
        if active_room != ROOM_ID or expires is None or expires <= datetime.now(timezone.utc):
            return self.end_shopping_mode(workspace_id, session_id, "room_exit" if active_room != ROOM_ID else "inactive_timeout")
        return value

    def touch_shopping_mode(self, workspace_id: str, session_id: str, active_room: str) -> Dict[str, Any]:
        value = self.shopping_status(workspace_id, session_id, active_room)
        if not value.get("active"):
            return value
        now = datetime.now(timezone.utc)
        value["last_activity_at"] = now.isoformat().replace("+00:00", "Z")
        value["expires_at"] = (now + timedelta(hours=SHOPPING_MODE_HOURS)).isoformat().replace("+00:00", "Z")
        with self._lock:
            self._write_json(self.shopping_path(workspace_id, session_id), value)
        return value

    def end_shopping_mode(self, workspace_id: str, session_id: str, reason: str = "user_trigger_phrase") -> Dict[str, Any]:
        prior = self._read_json(self.shopping_path(workspace_id, session_id), {})
        value = {
            **(prior if isinstance(prior, dict) else {}),
            "active": False,
            "scope": "google_lens_photo_uploads",
            "ended_at": utc_now(),
            "ended_reason": reason,
        }
        with self._lock:
            self._write_json(self.shopping_path(workspace_id, session_id), value)
        return value

    def may_upload_photo(self, workspace_id: str, session_id: str, active_room: str, confirmed: bool) -> tuple[bool, str]:
        status = self.shopping_status(workspace_id, session_id, active_room)
        if status.get("active"):
            return True, "shopping_mode"
        if confirmed:
            return True, "per_run_confirmation"
        return False, "confirmation_required"

    def save_pending_research(self, workspace_id: str, session_id: str, request: Dict[str, Any]) -> Dict[str, Any]:
        value = {
            "status": "confirmation_required",
            "workspace_id": workspace_id,
            "session_id": session_id,
            "destination": "Google Lens",
            "attachment_ids": list(dict.fromkeys(str(value) for value in request.get("attachment_ids", []) if str(value).strip())),
            "mode": "deep" if request.get("mode") == "deep" else "quick",
            "notes": _bounded_text(request.get("notes")),
            "case_id": str(request.get("case_id") or ""),
            "created_at": utc_now(),
        }
        with self._lock:
            self._write_json(self.pending_path(workspace_id, session_id), value)
        return value

    def pending_research(self, workspace_id: str, session_id: str) -> Dict[str, Any]:
        value = self._read_json(self.pending_path(workspace_id, session_id), {})
        return value if isinstance(value, dict) else {}

    def clear_pending_research(self, workspace_id: str, session_id: str) -> None:
        try:
            self.pending_path(workspace_id, session_id).unlink()
        except FileNotFoundError:
            pass

    def log_external_upload(
        self,
        workspace_id: str,
        session_id: str,
        destination: str,
        file_ids: Iterable[str],
        consent_basis: str,
    ) -> Dict[str, Any]:
        row = {
            "upload_id": _identifier("external"),
            "timestamp": utc_now(),
            "workspace_id": workspace_id,
            "session_id": session_id,
            "destination": destination,
            "file_ids": [str(value) for value in file_ids if str(value).strip()],
            "consent_basis": consent_basis,
        }
        path = self.external_audit_path(workspace_id)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def external_uploads(self, workspace_id: str, limit: int = 100) -> list[Dict[str, Any]]:
        path = self.external_audit_path(workspace_id)
        try:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError):
            return []
        return [row for row in rows[-max(1, limit):] if isinstance(row, dict)]

    def prepare_external_image(self, workspace_id: str, file_id: str, source_path: Path) -> Path:
        target = self.root(workspace_id) / "external_staging" / f"{re.sub(r'[^A-Za-z0-9_-]+', '', file_id)}.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if image.mode == "RGBA":
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            image.save(target, "JPEG", quality=92, optimize=True)
        return target.resolve()

    def calculate_max_buy(self, conservative_resale: float, overrides: Dict[str, Any] | None = None, workspace_id: str = "") -> Dict[str, Any]:
        settings = self.settings(workspace_id) if workspace_id else dict(DEFAULT_SETTINGS)
        settings.update({key: value for key, value in (overrides or {}).items() if key in DEFAULT_SETTINGS})
        low = max(0.0, float(conservative_resale or 0))
        fees = low * float(settings["fee_percent"]) / 100.0
        reserve = low * float(settings["uncertainty_reserve_percent"]) / 100.0
        formula_ceiling = max(
            0.0,
            low - fees - float(settings["packing_shipping_allowance"]) - reserve - float(settings["minimum_target_profit"]),
        )
        percentage_ceiling = low * float(settings["quick_buy_cap_percent"]) / 100.0
        recommended = min(formula_ceiling, percentage_ceiling)
        return {
            "currency": settings["currency"],
            "conservative_resale": round(low, 2),
            "fees": round(fees, 2),
            "packing_shipping_allowance": round(float(settings["packing_shipping_allowance"]), 2),
            "uncertainty_reserve": round(reserve, 2),
            "minimum_target_profit": round(float(settings["minimum_target_profit"]), 2),
            "profit_formula_ceiling": round(formula_ceiling, 2),
            "percentage_cap": round(percentage_ceiling, 2),
            "recommended_max_buy": round(recommended, 2),
            "rule": "lower_of_profit_formula_and_percentage_cap",
        }

    def save_case(
        self,
        workspace_id: str,
        session_id: str,
        attachment_ids: Iterable[str],
        report: Dict[str, Any],
        mode: str,
        notes: str = "",
        case_id: str = "",
    ) -> Dict[str, Any]:
        now = utc_now()
        existing = self._read_json(self.case_path(workspace_id, case_id), {}) if case_id else {}
        if not isinstance(existing, dict) or not existing:
            case_id = _identifier("antique")
            existing = {
                "case_id": case_id,
                "workspace_id": workspace_id,
                "created_at": now,
                "status": "researching",
                "revisions": [],
            }
        revision = {
            "revision_id": _identifier("revision"),
            "created_at": now,
            "session_id": session_id,
            "mode": mode,
            "attachment_ids": list(dict.fromkeys(str(value) for value in attachment_ids if str(value).strip())),
            "notes": _bounded_text(notes),
            "report": report,
        }
        revisions = list(existing.get("revisions") or [])
        revisions.append(revision)
        title = _bounded_text(report.get("identification") or report.get("title") or "Unidentified thrift-store item", 160)
        value = {
            **existing,
            "case_id": case_id,
            "title": title,
            "category": _bounded_text(report.get("category") or "unknown", 80),
            "status": "researched",
            "attachment_ids": revision["attachment_ids"],
            "latest_report": report,
            "revisions": revisions,
            "updated_at": now,
        }
        with self._lock:
            self._write_json(self.case_path(workspace_id, case_id), value)
        return value

    def list_cases(self, workspace_id: str) -> list[Dict[str, Any]]:
        rows = []
        for path in self.cases_root(workspace_id).glob("*.json"):
            row = self._read_json(path, {})
            if isinstance(row, dict) and row.get("case_id"):
                rows.append(row)
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return rows

    def get_case(self, workspace_id: str, case_id: str) -> Dict[str, Any]:
        value = self._read_json(self.case_path(workspace_id, case_id), {})
        if not isinstance(value, dict) or not value.get("case_id"):
            raise KeyError("Unknown Antiques research case")
        return value

    def bootstrap(self, workspace_id: str, session_id: str, active_room: str) -> Dict[str, Any]:
        return {
            "room_id": ROOM_ID,
            "persona": "Leo",
            "shopping_mode": self.shopping_status(workspace_id, session_id, active_room),
            "settings": self.settings(workspace_id),
            "sources": list(SOURCE_REGISTRY),
            "cases": self.list_cases(workspace_id),
            "external_uploads": self.external_uploads(workspace_id, 25),
            "visual_analysis": {
                "modes": ["quick", "detailed"],
                "focus_options": list(FOCUS_OPTIONS),
                "photo_roles": list(PHOTO_ROLES),
                "external_uploads_required": False,
            },
        }
