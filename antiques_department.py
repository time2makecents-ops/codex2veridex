"""Museum state, consent, valuation, and research-case helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
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

MATCH_TIERS = ("same_item_candidate", "same_model_or_edition", "similar", "rejected")
EXACT_MATCH_TIERS = ("same_item_candidate", "same_model_or_edition")
MATCH_CONFIDENCE = ("low", "medium", "high")
SALE_STATUSES = ("sold", "unsold", "active", "estimate")
PRICE_BASES = ("sold_price", "accepted_offer", "hammer", "realized_with_premium", "asking", "estimate")
SOLD_PRICE_BASES = ("sold_price", "accepted_offer", "hammer", "realized_with_premium")
ITEM_ATTRIBUTE_FIELDS = ("maker", "model", "pattern", "edition", "dimensions", "material", "condition", "provenance")
ENGAGEMENT_FIELDS = ("watchers", "likes", "favorites", "saves", "bids", "unique_bidders", "views", "quantity_sold")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _bounded_text(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _bounded_strings(values: Any, limit: int = 12, text_limit: int = 500) -> list[str]:
    if not isinstance(values, list):
        return []
    rows = []
    for value in values:
        text = _bounded_text(value, text_limit)
        if text and text not in rows:
            rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _bounded_money(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number >= 100_000_000:
        return None
    return round(number, 2)


def _bounded_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > 1_000_000_000 or not number.is_integer():
        return None
    return int(number)


def _http_url(value: Any) -> str:
    text = _bounded_text(value, 2000)
    return text if re.match(r"^https?://", text, re.IGNORECASE) else ""


def _source_urls(source: Dict[str, Any]) -> set[str]:
    urls = {_http_url(source.get("page_url"))}
    for key in ("links", "opened_sources", "results"):
        for row in source.get(key) or []:
            url = _http_url(row.get("url") if isinstance(row, dict) else row)
            if url:
                urls.add(url)
    urls.discard("")
    return urls


def _source_supports_price(
    source: Dict[str, Any],
    amount: float | None,
    sale_status: str,
    source_url: str = "",
    listing_id: str = "",
) -> bool:
    if amount is None:
        return False

    evidence: Dict[str, Any] = source
    structured_results = [row for row in source.get("results") or [] if isinstance(row, dict)]
    if structured_results:
        matched = []
        for row in structured_results:
            row_url = _http_url(row.get("url") or row.get("source_url"))
            row_id = _bounded_text(
                row.get("listing_or_lot_id") or row.get("listing_id") or row.get("item_id") or row.get("lot_id"),
                160,
            )
            if (source_url and row_url == source_url) or (listing_id and row_id == listing_id):
                matched.append(row)
        if not matched:
            return False
        evidence = matched[0]

        explicit_amounts = []
        for key in ("amount", "sold_price", "current_price", "value"):
            value = _bounded_money(evidence.get(key))
            if value is not None:
                explicit_amounts.append(value)
        price = evidence.get("price")
        if isinstance(price, dict):
            value = _bounded_money(price.get("value") or price.get("amount"))
        else:
            value = _bounded_money(price)
        if value is not None:
            explicit_amounts.append(value)
        if explicit_amounts and amount not in explicit_amounts:
            return False
        explicit_status = _bounded_text(evidence.get("sale_status") or evidence.get("status"), 40).casefold()
        if explicit_status and sale_status.casefold() not in explicit_status:
            return False

    text = json.dumps(evidence, ensure_ascii=False, sort_keys=True).replace(",", "")
    if float(amount).is_integer():
        amount_pattern = rf"(?<![\d.]){int(amount)}(?:\.00)?(?!\d)"
    else:
        compact = f"{amount:.2f}".rstrip("0")
        amount_pattern = rf"(?<![\d.]){re.escape(compact)}0?(?!\d)"
    if not re.search(amount_pattern, text):
        return False
    if sale_status == "sold" and not re.search(r"\b(?:sold|accepted offer|hammer|realized|sale price)\b", text, re.IGNORECASE):
        return False
    return True


def _observation_key(source_id: str, listing_id: str, source_url: str, title: str, sold_at: str) -> str:
    identity = listing_id or source_url or f"{title}|{sold_at}"
    return hashlib.sha256(f"{source_id}|{identity}".casefold().encode("utf-8")).hexdigest()


def _observation_version_key(row: Dict[str, Any]) -> str:
    material = {
        key: row.get(key)
        for key in (
            "observation_key", "match_tier", "match_confidence", "match_reasons", "differences",
            "source_url", "title", "sale_status", "price_basis", "amount", "currency",
            "shipping", "buyer_premium", "sold_at", "item_attributes", "evidence_status",
            "engagement", "engagement_captured_at",
        )
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


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

    def price_observations_root(self, workspace_id: str) -> Path:
        return self.root(workspace_id) / "price_observations"

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

    def price_observations_path(self, workspace_id: str, case_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "", str(case_id or ""))
        if not safe:
            raise ValueError("case_id is required")
        return self.price_observations_root(workspace_id) / f"{safe}.ndjson"

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

    def normalize_price_observations(
        self,
        values: Any,
        sources: Iterable[Dict[str, Any]],
        default_currency: str = "USD",
    ) -> list[Dict[str, Any]]:
        """Accept only bounded comparables tied to evidence captured in this run."""
        if not isinstance(values, list):
            return []
        source_index: Dict[str, Dict[str, Any]] = {}
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = _bounded_text(source.get("source_id"), 80)
            if source_id:
                entry = source_index.setdefault(source_id, {"rows": [], "urls": set()})
                entry["rows"].append(source)
                entry["urls"].update(_source_urls(source))

        normalized = []
        seen = set()
        for raw in values[:100]:
            if not isinstance(raw, dict):
                continue
            source_id = _bounded_text(raw.get("source_id"), 80)
            source = source_index.get(source_id)
            if source is None:
                continue
            match_tier = _bounded_text(raw.get("match_tier"), 40)
            if match_tier not in MATCH_TIERS:
                continue
            sale_status = _bounded_text(raw.get("sale_status"), 20)
            if sale_status not in SALE_STATUSES:
                continue
            price_basis = _bounded_text(raw.get("price_basis"), 40)
            if sale_status == "sold" and price_basis not in SOLD_PRICE_BASES:
                price_basis = "sold_price"
            elif sale_status == "active":
                price_basis = "asking"
            elif sale_status in {"estimate", "unsold"} and price_basis not in {"asking", "estimate"}:
                price_basis = "estimate"
            if price_basis not in PRICE_BASES:
                continue

            proposed_source_url = _http_url(raw.get("source_url"))
            source_rows = source["rows"]
            source_row = source_rows[0]
            amount = _bounded_money(raw.get("amount"))
            source_url = proposed_source_url if proposed_source_url in source["urls"] else ""
            captured_values = [_parse_time(row.get("searched_at")) for row in source_rows]
            captured = max((value for value in captured_values if value is not None), default=None)
            captured_at = captured.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if captured else utc_now()
            sold = _parse_time(raw.get("sold_at"))
            sold_at = sold.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if sold else ""
            title = _bounded_text(raw.get("title"), 300) or f"{source_id.replace('_', ' ').title()} comparable"
            listing_id = _bounded_text(raw.get("listing_or_lot_id"), 160)
            evidence_status = (
                "supported"
                if source_url
                and any(
                    _source_supports_price(row, amount, sale_status, source_url, listing_id)
                    for row in source_rows
                )
                else "limited"
            )
            key = _observation_key(source_id, listing_id, source_url, title, sold_at)
            if key in seen:
                continue
            seen.add(key)
            confidence = _bounded_text(raw.get("match_confidence"), 20)
            attributes = raw.get("item_attributes") if isinstance(raw.get("item_attributes"), dict) else {}
            raw_engagement = raw.get("engagement") if isinstance(raw.get("engagement"), dict) else {}
            engagement = {}
            for field in ENGAGEMENT_FIELDS:
                count = _bounded_count(raw_engagement.get(field, raw.get(field)))
                if count is not None:
                    engagement[field] = count
            observation = {
                "observation_key": key,
                "match_tier": match_tier,
                "match_confidence": confidence if confidence in MATCH_CONFIDENCE else "low",
                "match_reasons": _bounded_strings(raw.get("match_reasons")),
                "differences": _bounded_strings(raw.get("differences")),
                "source_id": source_id,
                "platform": _bounded_text(raw.get("platform") or source_row.get("provider") or source_id, 120),
                "venue": _bounded_text(raw.get("venue"), 160),
                "location": _bounded_text(raw.get("location"), 160),
                "source_url": source_url,
                "listing_or_lot_id": listing_id,
                "title": title,
                "sale_status": sale_status,
                "price_basis": price_basis,
                "amount": amount,
                "currency": (
                    _bounded_text(raw.get("currency"), 3).upper()
                    if re.fullmatch(r"[A-Za-z]{3}", _bounded_text(raw.get("currency"), 3))
                    else _bounded_text(default_currency, 3).upper() or "USD"
                ),
                "shipping": _bounded_money(raw.get("shipping")),
                "buyer_premium": _bounded_money(raw.get("buyer_premium")),
                "sold_at": sold_at,
                "captured_at": captured_at,
                "item_attributes": {
                    key: _bounded_text(attributes.get(key), 500)
                    for key in ITEM_ATTRIBUTE_FIELDS
                    if _bounded_text(attributes.get(key), 500)
                },
                "evidence_status": evidence_status,
                "engagement": engagement,
                "engagement_captured_at": (
                    (_bounded_text(raw.get("engagement_captured_at"), 40) or captured_at)
                    if engagement else ""
                ),
            }
            version_key = _observation_version_key(observation)
            observation["observation_version_key"] = version_key
            observation["observation_id"] = f"price_{version_key[:16]}"
            normalized.append(observation)
        return normalized

    def price_observations(self, workspace_id: str, case_id: str) -> list[Dict[str, Any]]:
        try:
            lines = self.price_observations_path(workspace_id, case_id).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("observation_id"):
                rows.append(row)
        return rows

    def _append_price_observations(self, workspace_id: str, case_id: str, rows: Iterable[Dict[str, Any]]) -> None:
        values = list(rows)
        if not values:
            return
        path = self.price_observations_path(workspace_id, case_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in values:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def summarize_price_observations(rows: Iterable[Dict[str, Any]], currency: str = "USD") -> Dict[str, Any]:
        latest_by_identity: Dict[str, Dict[str, Any]] = {}
        for source_row in rows:
            if not isinstance(source_row, dict):
                continue
            row = dict(source_row)
            identity = str(row.get("observation_key") or row.get("observation_id") or "")
            prior = latest_by_identity.get(identity)
            if prior is None or str(row.get("captured_at") or "") >= str(prior.get("captured_at") or ""):
                latest_by_identity[identity] = row
        observations = list(latest_by_identity.values())
        tier_rank = {value: index for index, value in enumerate(MATCH_TIERS)}
        observations.sort(key=lambda row: str(row.get("sold_at") or row.get("captured_at") or ""), reverse=True)
        observations.sort(key=lambda row: tier_rank.get(str(row.get("match_tier") or ""), 99))
        exact = [row for row in observations if row.get("match_tier") in EXACT_MATCH_TIERS]
        similar = [row for row in observations if row.get("match_tier") == "similar"]
        supported_sold = [
            row for row in exact
            if row.get("sale_status") == "sold"
            and row.get("price_basis") in SOLD_PRICE_BASES
            and row.get("evidence_status") == "supported"
            and row.get("amount") is not None
            and row.get("match_confidence") in {"medium", "high"}
        ]
        currency_sold = [
            row for row in supported_sold
            if str(row.get("currency") or "").upper() == currency.upper()
        ]
        primary_tier = "same_item_candidate" if any(row.get("match_tier") == "same_item_candidate" for row in currency_sold) else "same_model_or_edition"
        primary_sales = [
            row for row in currency_sold
            if row.get("match_tier") == primary_tier
        ]
        adjusted_sales = []
        for row in observations:
            reasons = []
            if row.get("match_tier") not in EXACT_MATCH_TIERS:
                reasons.append("not_exact_match")
            if row.get("match_confidence") not in {"medium", "high"}:
                reasons.append("low_match_confidence")
            if row.get("evidence_status") != "supported":
                reasons.append("unsupported_evidence")
            if row.get("sale_status") != "sold":
                reasons.append("not_sold")
            if row.get("price_basis") not in SOLD_PRICE_BASES:
                reasons.append("unsupported_price_basis")
            if row.get("amount") is None:
                reasons.append("missing_amount")
            if str(row.get("currency") or "").upper() != currency.upper():
                reasons.append("different_currency")
            if primary_sales and row.get("match_tier") != primary_tier:
                reasons.append("non_primary_exact_tier")

            valuation_amount = None
            amount = _bounded_money(row.get("amount"))
            if not reasons and amount is not None:
                valuation_amount = amount
                if row.get("price_basis") == "realized_with_premium":
                    premium = _bounded_money(row.get("buyer_premium"))
                    if premium is None or premium > amount:
                        reasons.append("unknown_or_invalid_buyer_premium")
                        valuation_amount = None
                    else:
                        valuation_amount = round(amount - premium, 2)
            row["valuation_eligible"] = not reasons and valuation_amount is not None
            row["valuation_amount"] = valuation_amount
            row["valuation_exclusion_reasons"] = reasons
            if row["valuation_eligible"]:
                adjusted_sales.append((row, float(valuation_amount)))
        amounts = [amount for _, amount in adjusted_sales]
        expected = {
            "currency": currency.upper(),
            "low": round(min(amounts), 2) if amounts else None,
            "high": round(max(amounts), 2) if amounts else None,
            "median": round(float(statistics.median(amounts)), 2) if amounts else None,
            "sold_count": len(amounts),
            "match_tier": primary_tier if amounts else "",
            "method": "single_supported_sale" if len(amounts) == 1 else "observed_supported_sales" if amounts else "insufficient_supported_sales",
            "confidence": "medium" if len(amounts) >= 3 else "low",
            "excluded_currency_count": len([
                row for row in supported_sold
                if row.get("match_tier") == primary_tier and str(row.get("currency") or "").upper() != currency.upper()
            ]),
            "excluded_incomparable_basis_count": len(primary_sales) - len(adjusted_sales),
            "basis_policy": "Shipping excluded; realized-with-premium prices require a known premium amount and are reduced to hammer-equivalent value.",
        }
        last_sold = adjusted_sales[0][0] if adjusted_sales else None
        counts = {
            "total": len(observations),
            "exact": len(exact),
            "same_item_candidates": len([row for row in exact if row.get("match_tier") == "same_item_candidate"]),
            "same_model_or_edition": len([row for row in exact if row.get("match_tier") == "same_model_or_edition"]),
            "similar": len(similar),
            "sold": len([row for row in observations if row.get("sale_status") == "sold"]),
            "exact_sold": len([row for row in exact if row.get("sale_status") == "sold"]),
            "active_asking": len([row for row in observations if row.get("sale_status") == "active"]),
            "exact_active_asking": len([row for row in exact if row.get("sale_status") == "active"]),
            "estimates": len([row for row in observations if row.get("sale_status") == "estimate"]),
            "supported": len([row for row in observations if row.get("evidence_status") == "supported"]),
            "limited": len([row for row in observations if row.get("evidence_status") == "limited"]),
            "valuation_eligible_sold": len(adjusted_sales),
        }
        return {
            "observations": observations,
            "exact_results": exact,
            "similar_candidates": similar,
            "last_sold": last_sold,
            "expected_resale": expected,
            "evidence_summary": counts,
            "similar_search_prompt": "No exact match found. Search similar items?" if not exact else "",
            "disclaimer": "Research-supported resale guidance only; not authentication or a professional appraisal.",
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
        source_results: Iterable[Dict[str, Any]] | None = None,
        valuation_overrides: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        with self._lock:
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
            revision_id = _identifier("revision")
            settings = self.settings(workspace_id)
            proposed = report.get("price_observations")
            if not isinstance(proposed, list):
                prior_evaluation = report.get("price_evaluation") if isinstance(report.get("price_evaluation"), dict) else {}
                proposed = prior_evaluation.get("observations")
            normalized = self.normalize_price_observations(
                proposed,
                source_results or [],
                str(settings.get("currency") or "USD"),
            )
            existing_observations = self.price_observations(workspace_id, case_id)
            known_versions = {
                str(row.get("observation_version_key") or row.get("observation_id") or "")
                for row in existing_observations
            }
            additions = []
            for row in normalized:
                version_key = str(row.get("observation_version_key") or row.get("observation_id") or "")
                if version_key in known_versions:
                    continue
                additions.append({**row, "case_id": case_id, "research_run_id": revision_id})
                known_versions.add(version_key)
            self._append_price_observations(workspace_id, case_id, additions)
            price_evaluation = self.summarize_price_observations(
                [*existing_observations, *additions],
                str(settings.get("currency") or "USD"),
            )
            report.pop("price_observations", None)
            report["price_evaluation"] = price_evaluation
            expected = price_evaluation["expected_resale"]
            valuation = report.get("valuation") if isinstance(report.get("valuation"), dict) else {}
            valuation = {
                **valuation,
                "currency": expected["currency"],
                "conservative_low": expected["low"],
                "likely_high": expected["high"],
                "comparable_notes": (
                    f"Derived from {expected['sold_count']} supported {expected['match_tier'].replace('_', ' ')} sold record(s)."
                    if expected["sold_count"]
                    else "No supported exact sold-comparable evidence; asking prices and estimates were excluded."
                ),
            }
            report["valuation"] = valuation
            report["buying"] = (
                self.calculate_max_buy(expected["low"], valuation_overrides or {}, workspace_id)
                if expected["low"] is not None
                else {"recommended_max_buy": None, "reason": "Insufficient supported exact sold-comparable evidence"}
            )
            revision_price_evaluation = {
                "observation_ids": [
                    str(row.get("observation_id"))
                    for row in price_evaluation["observations"]
                    if row.get("observation_id")
                ],
                "last_sold_id": (
                    str(price_evaluation["last_sold"].get("observation_id"))
                    if isinstance(price_evaluation.get("last_sold"), dict)
                    else ""
                ),
                "expected_resale": price_evaluation["expected_resale"],
                "evidence_summary": price_evaluation["evidence_summary"],
                "similar_search_prompt": price_evaluation["similar_search_prompt"],
                "disclaimer": price_evaluation["disclaimer"],
            }
            revision = {
                "revision_id": revision_id,
                "created_at": now,
                "session_id": session_id,
                "mode": mode,
                "attachment_ids": list(dict.fromkeys(str(value) for value in attachment_ids if str(value).strip())),
                "notes": _bounded_text(notes),
                "report": {**report, "price_evaluation": revision_price_evaluation},
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
