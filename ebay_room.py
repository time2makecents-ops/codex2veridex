"""Workspace-scoped inventory coordination for the governed eBay room."""

from __future__ import annotations

import json
import hashlib
import mimetypes
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

from ebay_gateway import EbayGateway, EbayGatewayError
from seller_intake import SellerIntakeCatalog


class EbayRoomError(RuntimeError):
    """A bounded, safe-to-display eBay room failure."""


DEFAULT_MARKETS = (
    {"market_id": "craigslist", "name": "Craigslist", "kind": "default"},
    {"market_id": "facebook", "name": "Facebook Marketplace", "kind": "default"},
    {"market_id": "ebay", "name": "eBay", "kind": "default"},
    {"market_id": "etsy", "name": "Etsy", "kind": "default"},
)
PRESET_MARKETS = {
    "offerup": "OfferUp",
    "mercari": "Mercari",
    "poshmark": "Poshmark",
    "depop": "Depop",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _posting_rule(text: Any) -> Dict[str, Any]:
    """Extract only explicit numeric group-post limits from saved rules."""
    source = " ".join(str(text or "").split())
    patterns = (
        (r"\b(?:no more than|up to|maximum of|limit(?:ed)? to)\s*(\d+)\s*(?:posts?\s*)?(?:per|a|each)\s*(day|week)\b", "per_"),
        (r"\b(\d+)\s+posts?\s+(?:per|a|each)\s*(day|week)\b", "per_"),
        (r"\b(?:no more than|up to|maximum of|limit(?:ed)? to)\s*(\d+)\s+posts?\s+(?:at a time|active)\b", ""),
    )
    for pattern, prefix in patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if not match:
            continue
        limit = int(match.group(1))
        period = f"{prefix}{match.group(2).lower()}" if prefix else "active_total"
        return {"limit": limit, "period": period, "evidence": match.group(0)}
    return {"limit": 0, "period": "", "evidence": ""}


def _group_rule_guidance(text: Any) -> list[str]:
    """Conservative checklist extracted from explicit saved group rules."""
    source = " ".join(str(text or "").split())
    checks = (
        (r"\b(?:include|post|list)\b.{0,60}\bprice\b|\bfirm price\b", "Include a price."),
        (r"\b(?:local|location|pickup)\b", "Check whether location or local pickup details are needed."),
        (r"\b(?:admin|approval|approved|ask an admin)\b", "Admin approval may be required."),
        (r"\bno business(?:es)?\b|\bbusiness ads?\b", "Business or commercial posts are restricted."),
        (r"\b(?:no spam|spamming)\b", "Avoid duplicate or promotional posts."),
        (r"\bno bidding\b", "Do not use bidding language."),
        (r"\bdelete sold\b", "Remove or mark the post after the item sells."),
        (r"\b(?:no animals?|no pets?)\b", "Animals or pet listings are prohibited."),
        (r"\b(?:no (?:drugs?|alcohol|weapons?|adult))\b", "Review prohibited-item restrictions before posting."),
    )
    return [label for pattern, label in checks if re.search(pattern, source, re.IGNORECASE)]


class EbayRoom:
    """Joins Item Intake records to account listings without duplicating inventory."""

    def __init__(self, workspace_root: Path, intake: SellerIntakeCatalog) -> None:
        self.root = Path(workspace_root).resolve() / "integrations" / "ebay_room"
        self.db_path = self.root / "catalog.sqlite3"
        self.intake = intake
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS listing_snapshots (
                    listing_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sku TEXT NOT NULL DEFAULT '',
                    price TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT 'USD',
                    quantity INTEGER NOT NULL DEFAULT 0,
                    quantity_sold INTEGER NOT NULL DEFAULT 0,
                    listing_url TEXT NOT NULL DEFAULT '',
                    picture_urls_json TEXT NOT NULL DEFAULT '[]',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS item_links (
                    listing_id TEXT PRIMARY KEY REFERENCES listing_snapshots(listing_id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL,
                    link_source TEXT NOT NULL,
                    linked_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channel_drafts (
                    draft_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_runs (
                    sync_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    listing_count INTEGER NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS item_markets (
                    market_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(item_id, market_id)
                );
                CREATE TABLE IF NOT EXISTS facebook_groups (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    rules_text TEXT NOT NULL DEFAULT '',
                    requirements_text TEXT NOT NULL DEFAULT '',
                    allowed_item_types TEXT NOT NULL DEFAULT '',
                    posting_notes TEXT NOT NULL DEFAULT '',
                    eligibility_status TEXT NOT NULL DEFAULT 'not_reviewed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS item_group_targets (
                    item_id TEXT NOT NULL,
                    group_id TEXT NOT NULL REFERENCES facebook_groups(group_id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'planned',
                    note TEXT NOT NULL DEFAULT '',
                    post_url TEXT NOT NULL DEFAULT '',
                    posted_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(item_id, group_id)
                );
                CREATE TABLE IF NOT EXISTS group_post_events (
                    event_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL REFERENCES facebook_groups(group_id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL,
                    posted_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facebook_group_visible_items (
                    group_id TEXT NOT NULL REFERENCES facebook_groups(group_id) ON DELETE CASCADE,
                    item_fingerprint TEXT NOT NULL,
                    item_text TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, item_fingerprint)
                );
                CREATE INDEX IF NOT EXISTS ebay_room_item_link_idx ON item_links(item_id);
                CREATE INDEX IF NOT EXISTS ebay_room_draft_item_idx ON channel_drafts(item_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS ebay_room_market_item_idx ON item_markets(item_id, created_at);
                CREATE INDEX IF NOT EXISTS ebay_room_group_target_idx ON item_group_targets(group_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS ebay_room_group_post_event_idx ON group_post_events(group_id, posted_at DESC);
                CREATE INDEX IF NOT EXISTS ebay_room_visible_item_idx ON facebook_group_visible_items(group_id, observed_at DESC);
                """
            )
            existing = {str(row["name"]) for row in connection.execute("PRAGMA table_info(facebook_groups)").fetchall()}
            for name, definition in (
                ("facebook_access_status", "TEXT NOT NULL DEFAULT ''"),
                ("facebook_access_detail", "TEXT NOT NULL DEFAULT ''"),
                ("facebook_access_checked_at", "TEXT NOT NULL DEFAULT ''"),
                ("privacy_text", "TEXT NOT NULL DEFAULT ''"),
                ("visibility_text", "TEXT NOT NULL DEFAULT ''"),
                ("history_text", "TEXT NOT NULL DEFAULT ''"),
                ("tags_text", "TEXT NOT NULL DEFAULT ''"),
                ("location_text", "TEXT NOT NULL DEFAULT ''"),
                ("membership_status", "TEXT NOT NULL DEFAULT ''"),
                ("membership_status_source", "TEXT NOT NULL DEFAULT ''"),
                ("posting_limit", "INTEGER NOT NULL DEFAULT 0"),
                ("posting_limit_period", "TEXT NOT NULL DEFAULT ''"),
                ("facebook_visible_items_count", "INTEGER NOT NULL DEFAULT -1"),
                ("facebook_visible_items_detail", "TEXT NOT NULL DEFAULT ''"),
                ("facebook_visible_items_checked_at", "TEXT NOT NULL DEFAULT ''"),
                ("manual_active_posts", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in existing:
                    connection.execute(f"ALTER TABLE facebook_groups ADD COLUMN {name} {definition}")
            target_existing = {str(row["name"]) for row in connection.execute("PRAGMA table_info(item_group_targets)").fetchall()}
            if "posted_at" not in target_existing:
                connection.execute("ALTER TABLE item_group_targets ADD COLUMN posted_at TEXT NOT NULL DEFAULT ''")
            if "post_url" not in target_existing:
                connection.execute("ALTER TABLE item_group_targets ADD COLUMN post_url TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def listing_id(value: Any) -> str:
        raw = str(value or "").strip()
        match = re.search(r"(?:/itm/(?:[^/?]+/)?|item=)(\d{9,15})", raw, re.IGNORECASE)
        candidate = match.group(1) if match else raw
        if not re.fullmatch(r"\d{9,15}", candidate):
            raise EbayRoomError("Enter an eBay item number or listing URL.")
        return candidate

    def _all_items(self, batch_id: str = "") -> list[Dict[str, Any]]:
        items: list[Dict[str, Any]] = []
        batches = self.intake.list_batches()
        if batch_id:
            requested = str(batch_id).strip()
            batches = [batch for batch in batches if str(batch.get("batch_id")) == requested]
            if not batches:
                raise EbayRoomError("That eBay list is not available.")
        for batch in batches:
            try:
                summaries = self.intake.get_batch(str(batch["batch_id"]), include_archived=False).get("items") or []
                # The board intentionally uses item summaries.  Photos and research stay
                # inside the selected item's workspace rather than cluttering the room.
                items.extend(summaries)
            except KeyError:
                continue
        return items

    def sync(self, gateway: EbayGateway) -> Dict[str, Any]:
        sync_id, observed = _identifier("sync"), _now()
        try:
            listings_by_id: Dict[str, Dict[str, Any]] = {}
            page = 1
            while page <= 50:
                result = gateway.seller_listings(page=page, per_page=200)
                rows = result.get("listings") if isinstance(result.get("listings"), list) else []
                for row in rows:
                    if isinstance(row, dict) and str(row.get("listing_id") or "").strip():
                        listings_by_id[str(row["listing_id"])] = row
                total = int(result.get("total") or 0)
                if not rows or not total or len(listings_by_id) >= total:
                    break
                page += 1
            listings = list(listings_by_id.values())
            with self._connection() as connection:
                for row in listings:
                    if not isinstance(row, dict) or not str(row.get("listing_id") or "").strip():
                        continue
                    listing_id = self.listing_id(row["listing_id"])
                    connection.execute(
                        """
                        INSERT INTO listing_snapshots (
                            listing_id, status, title, sku, price, currency, quantity,
                            quantity_sold, listing_url, picture_urls_json, first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(listing_id) DO UPDATE SET
                            status=excluded.status, title=excluded.title, sku=excluded.sku,
                            price=excluded.price, currency=excluded.currency, quantity=excluded.quantity,
                            quantity_sold=excluded.quantity_sold, listing_url=excluded.listing_url,
                            picture_urls_json=excluded.picture_urls_json, last_seen_at=excluded.last_seen_at
                        """,
                        (
                            listing_id, str(row.get("status") or "unknown")[:40], str(row.get("title") or "")[:500],
                            str(row.get("sku") or "")[:100], str(row.get("price") or "")[:40],
                            str(row.get("currency") or "USD")[:12], int(row.get("quantity") or 0),
                            int(row.get("quantity_sold") or 0), str(row.get("listing_url") or "")[:2000],
                            json.dumps(row.get("picture_urls") or []), observed, observed,
                        ),
                    )
                connection.execute(
                    "INSERT INTO sync_runs(sync_id, status, listing_count, error, created_at) VALUES(?, 'complete', ?, '', ?)",
                    (sync_id, len(listings), observed),
                )
            return {"sync_id": sync_id, "status": "complete", "listing_count": len(listings), "synced_at": observed}
        except Exception as exc:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO sync_runs(sync_id, status, listing_count, error, created_at) VALUES(?, 'failed', 0, ?, ?)",
                    (sync_id, str(exc)[:1000], observed),
                )
            raise

    @staticmethod
    def _public_listing(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        try:
            result["picture_urls"] = json.loads(str(result.pop("picture_urls_json") or "[]"))
        except json.JSONDecodeError:
            result["picture_urls"] = []
        return result

    def board(self, batch_id: str = "") -> Dict[str, Any]:
        items = self._all_items(batch_id)
        by_id = {str(item["item_id"]): item for item in items}
        with self._connection() as connection:
            listings = [self._public_listing(row) for row in connection.execute("SELECT * FROM listing_snapshots ORDER BY last_seen_at DESC").fetchall()]
            links = [dict(row) for row in connection.execute("SELECT * FROM item_links").fetchall()]
            drafts = []
            for row in connection.execute("SELECT * FROM channel_drafts ORDER BY updated_at DESC").fetchall():
                value = dict(row)
                try:
                    value["payload"] = json.loads(str(value.pop("payload_json") or "{}"))
                except json.JSONDecodeError:
                    value["payload"] = {}
                drafts.append(value)
            latest_sync = connection.execute("SELECT * FROM sync_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        listing_by_id = {row["listing_id"]: row for row in listings}
        links_by_item: Dict[str, list[Dict[str, Any]]] = {}
        for link in links:
            if link["item_id"] in by_id:
                links_by_item.setdefault(link["item_id"], []).append({**link, "listing": listing_by_id.get(link["listing_id"])})
        drafts_by_item: Dict[str, list[Dict[str, Any]]] = {}
        for draft in drafts:
            if draft["item_id"] in by_id:
                drafts_by_item.setdefault(draft["item_id"], []).append(draft)
        cards = []
        for item in items:
            item_id = str(item["item_id"])
            item_links = links_by_item.get(item_id, [])
            card = {**item, "ebay_links": item_links, "channel_drafts": drafts_by_item.get(item_id, [])}
            if any(str(link.get("listing", {}).get("status") or "") == "active" for link in item_links):
                card["board_state"] = "listed"
            elif item_links:
                card["board_state"] = "ended"
            elif str(item.get("description") or "").strip() and int(item.get("asset_count") or 0) > 0:
                card["board_state"] = "ready"
            else:
                card["board_state"] = "needs_work"
            cards.append(card)
        linked = {row["listing_id"] for row in links}
        return {
            "batch_id": str(batch_id or ""),
            "items": cards,
            "listings": listings,
            "unmatched": [row for row in listings if row["listing_id"] not in linked],
            "latest_sync": dict(latest_sync) if latest_sync else None,
        }

    def link(self, listing: Dict[str, Any], item_id: str, *, source: str = "manual") -> Dict[str, Any]:
        item = self.intake.get_item(str(item_id or ""))
        listing_id = self.listing_id(listing.get("listing_id"))
        observed = _now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO listing_snapshots(listing_id,status,title,sku,price,currency,quantity,quantity_sold,listing_url,picture_urls_json,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(listing_id) DO UPDATE SET status=excluded.status,title=excluded.title,sku=excluded.sku,price=excluded.price,currency=excluded.currency,quantity=excluded.quantity,quantity_sold=excluded.quantity_sold,listing_url=excluded.listing_url,picture_urls_json=excluded.picture_urls_json,last_seen_at=excluded.last_seen_at",
                (listing_id, str(listing.get("status") or "active"), str(listing.get("title") or item.get("title") or ""), str(listing.get("sku") or ""), str(listing.get("price") or ""), str(listing.get("currency") or "USD"), int(listing.get("quantity") or 0), int(listing.get("quantity_sold") or 0), str(listing.get("listing_url") or ""), json.dumps(listing.get("picture_urls") or []), observed, observed),
            )
            connection.execute(
                "INSERT INTO item_links(listing_id,item_id,link_source,linked_at) VALUES(?,?,?,?) ON CONFLICT(listing_id) DO UPDATE SET item_id=excluded.item_id,link_source=excluded.link_source,linked_at=excluded.linked_at",
                (listing_id, item["item_id"], source[:40], observed),
            )
        return {"listing_id": listing_id, "item_id": item["item_id"], "link_source": source, "linked_at": observed}

    @staticmethod
    def _download_photo(url: str, maximum: int = 15 * 1024 * 1024) -> tuple[bytes, str, str]:
        parsed = urllib.parse.urlparse(str(url or ""))
        if parsed.scheme != "https" or not parsed.netloc:
            raise EbayRoomError("eBay returned an invalid photo URL.")
        request = urllib.request.Request(url, headers={"User-Agent": "Veridex/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content_type = str(response.headers.get_content_type() or "application/octet-stream")
                content = response.read(maximum + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EbayRoomError("An eBay listing photo could not be downloaded.") from exc
        if len(content) > maximum or not content_type.startswith("image/"):
            raise EbayRoomError("An eBay listing photo was not a supported image.")
        extension = mimetypes.guess_extension(content_type) or Path(parsed.path).suffix or ".jpg"
        return content, content_type, extension[:8]

    def import_listing(self, gateway: EbayGateway, listing_value: str) -> Dict[str, Any]:
        listing = gateway.get_item(self.listing_id(listing_value))
        batches = self.intake.list_batches()
        batch = next((row for row in batches if str(row.get("title") or "") == "eBay imports"), None)
        if batch is None:
            batch = self.intake.create_batch({"title": "eBay imports", "notes": "Listings approved for import from the connected eBay seller account."})
        try:
            estimated_value: Any = float(listing.get("price")) if str(listing.get("price") or "").strip() else None
        except ValueError:
            estimated_value = None
        item = self.intake.create_item({
            "batch_id": batch["batch_id"],
            "title": listing.get("title"),
            "description": listing.get("description"),
            "estimated_value": estimated_value,
            "currency": listing.get("currency") or "USD",
            "status": "listed" if int(listing.get("quantity") or 0) > int(listing.get("quantity_sold") or 0) else "needs_review",
            "reference_id": listing["listing_id"],
            "tags": ["eBay import"],
        })
        imported_photos = []
        for index, url in enumerate((listing.get("picture_urls") or [])[:12], start=1):
            content, content_type, extension = self._download_photo(str(url))
            imported_photos.append(self.intake.add_asset(item["item_id"], f"ebay-{listing['listing_id']}-{index}{extension}", content, content_type, "photo"))
        link = self.link({**listing, "status": "active" if item["status"] == "listed" else "ended"}, item["item_id"], source="approved_import")
        return {"item": self.intake.get_item(item["item_id"]), "link": link, "imported_photo_count": len(imported_photos)}

    def find_listing(self, gateway: EbayGateway, listing_value: str) -> Dict[str, Any]:
        """Read one connected-seller listing for review in the item workspace."""
        return gateway.get_item(self.listing_id(listing_value))

    def populate_item_from_listing(
        self,
        gateway: EbayGateway,
        item_id: str,
        listing_value: str,
        *,
        extract_media: bool = False,
    ) -> Dict[str, Any]:
        """Apply verified eBay listing facts locally and optionally copy its photos."""
        listing = self.find_listing(gateway, listing_value)
        listing_id = self.listing_id(listing.get("listing_id") or listing_value)
        try:
            estimated_value: Any = float(listing.get("price")) if str(listing.get("price") or "").strip() else None
        except (TypeError, ValueError):
            estimated_value = None
        remaining = int(listing.get("quantity") or 0) - int(listing.get("quantity_sold") or 0)
        item = self.intake.update_item({
            "item_id": item_id,
            "title": listing.get("title") or "",
            "description": listing.get("description") or "",
            "estimated_value": estimated_value,
            "currency": listing.get("currency") or "USD",
            "reference_id": listing_id,
            "status": "listed" if remaining > 0 else "needs_review",
        })
        link = self.link({**listing, "status": "active" if remaining > 0 else "ended"}, item_id, source="workspace_listing_lookup")
        imported_photos: list[Dict[str, Any]] = []
        if extract_media:
            existing_names = {str(row.get("name") or "") for row in (self.intake.get_item(item_id).get("assets") or [])}
            for index, url in enumerate((listing.get("picture_urls") or [])[:12], start=1):
                content, content_type, extension = self._download_photo(str(url))
                filename = f"ebay-{listing_id}-{index}{extension}"
                if filename in existing_names:
                    continue
                imported_photos.append(self.intake.add_asset(item_id, filename, content, content_type, "photo"))
                existing_names.add(filename)
        return {
            "listing": listing,
            "item": self.intake.get_item(item_id),
            "link": link,
            "imported_photo_count": len(imported_photos),
            "imported_photos": imported_photos,
        }

    def save_draft(self, item_id: str, channel: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        item = self.intake.get_item(item_id)
        target = str(channel or "").strip().lower()
        allowed = {row["market_id"] for row in self.item_markets(item_id)}
        if target not in allowed:
            raise EbayRoomError("Add that marketplace to this item before saving its draft.")
        now, draft_id = _now(), _identifier("draft")
        value = dict(payload or {})
        value.setdefault("title", item.get("title") or "")
        value.setdefault("description", item.get("description") or "")
        value.setdefault("price", item.get("estimated_value"))
        value.setdefault("currency", item.get("currency") or "USD")
        value["photo_asset_ids"] = list(item.get("listing_photo_asset_ids") or [])
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO channel_drafts(draft_id,item_id,channel,status,payload_json,created_at,updated_at) VALUES(?,?,?,'draft',?,?,?)",
                (draft_id, item_id, target, json.dumps(value, ensure_ascii=False), now, now),
            )
        return {"draft_id": draft_id, "item_id": item_id, "channel": target, "status": "draft", "payload": value, "created_at": now, "updated_at": now}

    def item_markets(self, item_id: str) -> list[Dict[str, Any]]:
        self.intake.get_item(str(item_id or ""))
        with self._connection() as connection:
            added = [dict(row) for row in connection.execute(
                "SELECT market_id,item_id,name,kind,created_at FROM item_markets WHERE item_id=? ORDER BY created_at,name",
                (item_id,),
            ).fetchall()]
        return [{**row, "item_id": item_id, "created_at": ""} for row in DEFAULT_MARKETS] + added

    def add_item_market(self, item_id: str, *, preset: str = "", name: str = "") -> Dict[str, Any]:
        self.intake.get_item(str(item_id or ""))
        preset_id = re.sub(r"[^a-z0-9_-]", "", str(preset or "").strip().lower())
        if preset_id:
            if preset_id not in PRESET_MARKETS:
                raise EbayRoomError("Choose OfferUp, Mercari, Poshmark, or Depop.")
            market_id, display_name, kind = preset_id, PRESET_MARKETS[preset_id], "preset"
        else:
            display_name = " ".join(str(name or "").split())[:80]
            if not display_name:
                raise EbayRoomError("Enter a marketplace name.")
            slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")[:48]
            if not slug:
                raise EbayRoomError("Enter a marketplace name using letters or numbers.")
            market_id, kind = f"custom-{slug}", "custom"
        if market_id in {row["market_id"] for row in DEFAULT_MARKETS}:
            raise EbayRoomError("That marketplace is already available on this item.")
        now = _now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO item_markets(market_id,item_id,name,kind,created_at) VALUES(?,?,?,?,?) ON CONFLICT(item_id,market_id) DO UPDATE SET name=excluded.name,kind=excluded.kind",
                (market_id, item_id, display_name, kind, now),
            )
        return {"market_id": market_id, "item_id": item_id, "name": display_name, "kind": kind, "created_at": now}

    def facebook_groups(self, item_id: str = "") -> list[Dict[str, Any]]:
        if item_id:
            self.intake.get_item(str(item_id))
        with self._connection() as connection:
            groups = [dict(row) for row in connection.execute(
                "SELECT * FROM facebook_groups ORDER BY updated_at DESC, name"
            ).fetchall()]
            targets = [dict(row) for row in connection.execute(
                "SELECT * FROM item_group_targets ORDER BY updated_at DESC"
            ).fetchall()]
            post_events = [dict(row) for row in connection.execute(
                "SELECT group_id,item_id,posted_at FROM group_post_events ORDER BY posted_at DESC"
            ).fetchall()]
            visible_items = [dict(row) for row in connection.execute(
                "SELECT group_id,item_text,source_url,observed_at FROM facebook_group_visible_items ORDER BY observed_at DESC"
            ).fetchall()]
        target_by_group = {}
        for target in targets:
            if not item_id or str(target["item_id"]) == str(item_id):
                target_by_group[str(target["group_id"])] = target
        item_titles = {}
        for target in targets:
            try:
                item = self.intake.get_item(str(target["item_id"]))
                item_titles[str(target["item_id"])] = str(item.get("title") or target["item_id"])
            except Exception:
                item_titles[str(target["item_id"])] = str(target["item_id"])
        for group in groups:
            target = target_by_group.get(str(group["group_id"]))
            group["targeted"] = bool(target)
            group["target"] = target
            group["target_items"] = [
                {"item_id": row["item_id"], "title": item_titles.get(str(row["item_id"]), row["item_id"]), "status": row["status"], "note": row["note"], "post_url": row.get("post_url", "")}
                for row in targets if str(row["group_id"]) == str(group["group_id"])
            ]
            group_id = str(group["group_id"])
            # Facebook exposes a visible sample, not a durable authoritative listing feed.
            # Keep every observed entry as private reconciliation evidence without claiming
            # that a later partial read means a previous entry was removed.
            group["facebook_visible_items"] = [
                {"text": row["item_text"], "source_url": row["source_url"], "observed_at": row["observed_at"]}
                for row in visible_items if str(row["group_id"]) == group_id
            ][:20]
            now = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")
            week_start = (now.timestamp() - 7 * 24 * 60 * 60)
            events = [row for row in post_events if str(row["group_id"]) == group_id]
            recent_week = 0
            for event in events:
                try:
                    if datetime.fromisoformat(str(event["posted_at"]).replace("Z", "+00:00")).timestamp() >= week_start:
                        recent_week += 1
                except ValueError:
                    continue
            detected_rule = _posting_rule(group.get("rules_text"))
            limit = int(group.get("posting_limit") or detected_rule["limit"] or 0)
            period = str(group.get("posting_limit_period") or detected_rule["period"] or "")
            local_active_posts = sum(1 for row in targets if str(row["group_id"]) == group_id and str(row["status"]) == "posted")
            facebook_visible_items = int(group.get("facebook_visible_items_count") or -1)
            active_posts = max(local_active_posts, facebook_visible_items, int(group.get("manual_active_posts") or 0))
            tracked_count = {"per_day": sum(1 for row in events if str(row["posted_at"]).startswith(today)), "per_week": recent_week, "active_total": active_posts}.get(period, 0)
            remaining = max(0, limit - tracked_count) if limit and period else None
            next_available_at = ""
            if remaining == 0 and period == "per_day":
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                next_available_at = (midnight.timestamp() + 24 * 60 * 60)
                next_available_at = datetime.fromtimestamp(next_available_at, timezone.utc).isoformat().replace("+00:00", "Z")
            elif remaining == 0 and period == "per_week":
                dated = []
                for event in events:
                    try:
                        value = datetime.fromisoformat(str(event["posted_at"]).replace("Z", "+00:00"))
                        if value.timestamp() >= week_start:
                            dated.append(value)
                    except ValueError:
                        continue
                if dated:
                    next_available_at = datetime.fromtimestamp(min(dated).timestamp() + 7 * 24 * 60 * 60, timezone.utc).isoformat().replace("+00:00", "Z")
            group["post_tracking"] = {
                "active_posts": active_posts,
                "local_active_posts": local_active_posts,
                "facebook_visible_items": facebook_visible_items,
                "manual_active_posts": int(group.get("manual_active_posts") or 0),
                "count_mismatch": bool(facebook_visible_items >= 0 and facebook_visible_items != local_active_posts),
                "posts_today": sum(1 for row in events if str(row["posted_at"]).startswith(today)),
                "posts_this_week": recent_week,
                "total_recorded_posts": len(events),
                "limit": limit,
                "period": period,
                "remaining": remaining,
                "warning": bool(remaining is not None and remaining <= max(1, (limit + 4) // 5)),
                "at_limit": bool(remaining == 0),
                "next_available_at": next_available_at,
                "rule_evidence": str(detected_rule["evidence"] or ""),
            }
            group["rule_guidance"] = _group_rule_guidance(group.get("rules_text"))
            membership = str(group.get("membership_status") or group.get("facebook_access_status") or "unknown")
            if membership in {"denied", "not_joined"}:
                recommendation = {"status": "not_allowed", "reason": "Facebook does not show this account as a group member."}
            elif membership == "pending":
                recommendation = {"status": "needs_review", "reason": "Membership is still pending."}
            elif membership != "joined":
                recommendation = {"status": "needs_review", "reason": "Confirm group membership before posting."}
            elif bool(group["post_tracking"]["at_limit"]):
                recommendation = {"status": "not_allowed", "reason": "The tracked group posting limit has been reached."}
            elif str(group.get("eligibility_status") or "") != "eligible":
                recommendation = {"status": "needs_review", "reason": "Finish the saved group-rule review before posting."}
            else:
                recommendation = {"status": "ready", "reason": "Membership, review, and tracked posting limit are clear."}
            group["posting_recommendation"] = recommendation
            follow_up: Dict[str, Any] = {}
            if membership == "pending":
                due_at = datetime.fromtimestamp(now.timestamp() + 24 * 60 * 60, timezone.utc).isoformat().replace("+00:00", "Z")
                follow_up = {"kind": "membership", "due_at": due_at, "message": "Recheck this membership request tomorrow; Facebook still shows it as pending."}
            elif bool(group["post_tracking"]["at_limit"]):
                follow_up = {"kind": "quota", "due_at": str(group["post_tracking"].get("next_available_at") or ""), "message": "Do not post another item until the recorded posting limit resets or you verify an older post is no longer active."}
            elif "Admin approval may be required." in group["rule_guidance"]:
                follow_up = {"kind": "approval", "due_at": "", "message": "Before posting, confirm the saved rules' admin-approval requirement has been satisfied."}
            group["follow_up"] = follow_up
            group["post_events"] = [
                {"item_id": row["item_id"], "title": item_titles.get(str(row["item_id"]), str(row["item_id"])), "posted_at": row["posted_at"]}
                for row in events[:20]
            ]
        return groups

    def save_facebook_group(self, value: Dict[str, Any]) -> Dict[str, Any]:
        group_id = str(value.get("group_id") or "").strip() or _identifier("group")
        name = " ".join(str(value.get("name") or "").split())[:200]
        if not name:
            raise EbayRoomError("Enter a Facebook group name.")
        now = _now()
        fields = {
            "url": str(value.get("url") or "").strip()[:2000],
            "description": str(value.get("description") or "")[:4000],
            "rules_text": str(value.get("rules_text") or "")[:20000],
            "requirements_text": str(value.get("requirements_text") or "")[:10000],
            "allowed_item_types": str(value.get("allowed_item_types") or "")[:4000],
            "posting_notes": str(value.get("posting_notes") or "")[:10000],
            "eligibility_status": str(value.get("eligibility_status") or "not_reviewed").strip().lower()[:40] or "not_reviewed",
            "facebook_access_status": str(value.get("facebook_access_status") or "")[:80],
            "facebook_access_detail": str(value.get("facebook_access_detail") or "")[:1000],
            "facebook_access_checked_at": str(value.get("facebook_access_checked_at") or "")[:80],
            "privacy_text": str(value.get("privacy_text") or "")[:1000],
            "visibility_text": str(value.get("visibility_text") or "")[:1000],
            "history_text": str(value.get("history_text") or "")[:1000],
            "tags_text": str(value.get("tags_text") or "")[:2000],
            "location_text": str(value.get("location_text") or "")[:1000],
            "membership_status": str(value.get("membership_status") or "").strip().lower()[:40],
            "membership_status_source": str(value.get("membership_status_source") or "").strip().lower()[:40],
            "posting_limit": max(0, int(value.get("posting_limit") or 0)),
            "posting_limit_period": str(value.get("posting_limit_period") or "").strip().lower()[:40],
            "facebook_visible_items_count": max(-1, int(value.get("facebook_visible_items_count") if value.get("facebook_visible_items_count") is not None else -1)),
            "facebook_visible_items_detail": str(value.get("facebook_visible_items_detail") or "")[:1000],
            "facebook_visible_items_checked_at": str(value.get("facebook_visible_items_checked_at") or "")[:80],
            "manual_active_posts": max(0, int(value.get("manual_active_posts") or 0)),
        }
        allowed_statuses = {"not_reviewed", "eligible", "needs_requirements", "not_allowed", "unclear"}
        if fields["eligibility_status"] not in allowed_statuses:
            raise EbayRoomError("Choose a valid group review status.")
        if fields["membership_status"] not in {"", "unknown", "joined", "pending", "not_joined", "denied"}:
            raise EbayRoomError("Choose a valid membership status.")
        if fields["membership_status_source"] not in {"", "observed", "manual"}:
            raise EbayRoomError("Choose a valid membership status source.")
        if fields["posting_limit_period"] not in {"", "per_day", "per_week", "active_total"}:
            raise EbayRoomError("Choose a valid posting limit period.")
        detected_rule = _posting_rule(fields["rules_text"])
        if not fields["posting_limit"] and detected_rule["limit"]:
            fields["posting_limit"] = detected_rule["limit"]
        if not fields["posting_limit_period"] and detected_rule["period"]:
            fields["posting_limit_period"] = detected_rule["period"]
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO facebook_groups(group_id,name,url,description,rules_text,requirements_text,allowed_item_types,posting_notes,eligibility_status,facebook_access_status,facebook_access_detail,facebook_access_checked_at,privacy_text,visibility_text,history_text,tags_text,location_text,membership_status,membership_status_source,posting_limit,posting_limit_period,facebook_visible_items_count,facebook_visible_items_detail,facebook_visible_items_checked_at,manual_active_posts,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(group_id) DO UPDATE SET name=excluded.name,url=excluded.url,description=excluded.description,rules_text=excluded.rules_text,requirements_text=excluded.requirements_text,allowed_item_types=excluded.allowed_item_types,posting_notes=excluded.posting_notes,eligibility_status=excluded.eligibility_status,facebook_access_status=excluded.facebook_access_status,facebook_access_detail=excluded.facebook_access_detail,facebook_access_checked_at=excluded.facebook_access_checked_at,privacy_text=excluded.privacy_text,visibility_text=excluded.visibility_text,history_text=excluded.history_text,tags_text=excluded.tags_text,location_text=excluded.location_text,membership_status=excluded.membership_status,membership_status_source=excluded.membership_status_source,posting_limit=excluded.posting_limit,posting_limit_period=excluded.posting_limit_period,facebook_visible_items_count=excluded.facebook_visible_items_count,facebook_visible_items_detail=excluded.facebook_visible_items_detail,facebook_visible_items_checked_at=excluded.facebook_visible_items_checked_at,manual_active_posts=excluded.manual_active_posts,updated_at=excluded.updated_at""",
                (group_id, name, fields["url"], fields["description"], fields["rules_text"], fields["requirements_text"], fields["allowed_item_types"], fields["posting_notes"], fields["eligibility_status"], fields["facebook_access_status"], fields["facebook_access_detail"], fields["facebook_access_checked_at"], fields["privacy_text"], fields["visibility_text"], fields["history_text"], fields["tags_text"], fields["location_text"], fields["membership_status"], fields["membership_status_source"], fields["posting_limit"], fields["posting_limit_period"], fields["facebook_visible_items_count"], fields["facebook_visible_items_detail"], fields["facebook_visible_items_checked_at"], fields["manual_active_posts"], now, now),
            )
            row = connection.execute("SELECT * FROM facebook_groups WHERE group_id=?", (group_id,)).fetchone()
            observed_at = fields["facebook_visible_items_checked_at"] or now
            source_url = fields["url"]
            seen = set()
            for raw_item in value.get("facebook_visible_items") or []:
                candidate = raw_item.get("text") if isinstance(raw_item, dict) else raw_item
                item_text = " ".join(str(candidate or "").split())[:500]
                if not item_text:
                    continue
                fingerprint = hashlib.sha256(item_text.encode("utf-8")).hexdigest()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                connection.execute(
                    """INSERT INTO facebook_group_visible_items(group_id,item_fingerprint,item_text,source_url,observed_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(group_id,item_fingerprint) DO UPDATE SET item_text=excluded.item_text,source_url=excluded.source_url,observed_at=excluded.observed_at""",
                    (group_id, fingerprint, item_text, source_url, observed_at),
                )
        return dict(row)

    def set_group_target(self, item_id: str, group_id: str, *, status: str = "planned", note: str = "", post_url: str = "", remove: bool = False) -> Dict[str, Any]:
        self.intake.get_item(str(item_id or ""))
        group_id = str(group_id or "").strip()
        if not group_id:
            raise EbayRoomError("Choose a Facebook group first.")
        now = _now()
        with self._connection() as connection:
            group = connection.execute("SELECT * FROM facebook_groups WHERE group_id=?", (group_id,)).fetchone()
            if not group:
                raise EbayRoomError("That Facebook group is not saved.")
            if remove:
                connection.execute("DELETE FROM item_group_targets WHERE item_id=? AND group_id=?", (item_id, group_id))
                return {"item_id": item_id, "group_id": group_id, "targeted": False}
            status = str(status or "planned").strip().lower()[:40] or "planned"
            if status not in {"planned", "ready", "posted"}:
                raise EbayRoomError("Choose planned, ready for review, or posted.")
            post_url = str(post_url or "").strip()[:2000]
            if post_url:
                parsed = urllib.parse.urlparse(post_url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise EbayRoomError("Enter a full http(s) Facebook post link, or leave it blank.")
            if status in {"ready", "posted"}:
                required = ("url", "description", "rules_text", "requirements_text", "allowed_item_types")
                if str(group["eligibility_status"] or "") != "eligible" or any(not str(group[key] or "").strip() for key in required):
                    raise EbayRoomError("Complete the group review, rules, requirements, and allowed item types before marking an item ready or posted.")
            prior = connection.execute("SELECT status,posted_at FROM item_group_targets WHERE item_id=? AND group_id=?", (item_id, group_id)).fetchone()
            posted_at = str(prior["posted_at"] or "") if prior else ""
            if status == "posted" and not posted_at:
                detected_rule = _posting_rule(group["rules_text"])
                limit = int(group["posting_limit"] or detected_rule["limit"] or 0)
                period = str(group["posting_limit_period"] or detected_rule["period"] or "")
                if limit and period:
                    if period == "active_total":
                        local_count = int(connection.execute("SELECT COUNT(*) FROM item_group_targets WHERE group_id=? AND status='posted'", (group_id,)).fetchone()[0])
                        count = max(local_count, int(group["facebook_visible_items_count"] or -1), int(group["manual_active_posts"] or 0))
                    elif period == "per_day":
                        count = int(connection.execute("SELECT COUNT(*) FROM group_post_events WHERE group_id=? AND posted_at>=?", (group_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"))).fetchone()[0])
                    else:
                        week_start = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 7 * 24 * 60 * 60, timezone.utc).isoformat().replace("+00:00", "Z")
                        count = int(connection.execute("SELECT COUNT(*) FROM group_post_events WHERE group_id=? AND posted_at>=?", (group_id, week_start)).fetchone()[0])
                    if count >= limit:
                        readable = period.replace("per_", "per ").replace("active_total", "active total")
                        raise EbayRoomError(f"Posting limit reached: {count} of {limit} {readable} posts are already recorded for this group. Do not post another item there yet.")
                posted_at = now
                connection.execute(
                    "INSERT INTO group_post_events(event_id,group_id,item_id,posted_at,created_at) VALUES(?,?,?,?,?)",
                    (_identifier("group_post"), group_id, item_id, posted_at, now),
                )
            connection.execute(
                """INSERT INTO item_group_targets(item_id,group_id,status,note,post_url,posted_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(item_id,group_id) DO UPDATE SET status=excluded.status,note=excluded.note,post_url=excluded.post_url,posted_at=excluded.posted_at,updated_at=excluded.updated_at""",
                (item_id, group_id, status, str(note or "")[:10000], post_url, posted_at, now, now),
            )
        return {"item_id": item_id, "group_id": group_id, "status": status, "note": str(note or "")[:10000], "post_url": post_url, "targeted": True}

    def group_context(self, item_id: str) -> list[Dict[str, Any]]:
        return [
            {key: group.get(key) for key in ("group_id", "name", "url", "description", "rules_text", "requirements_text", "allowed_item_types", "posting_notes", "eligibility_status", "facebook_access_status", "facebook_access_detail", "facebook_access_checked_at", "privacy_text", "visibility_text", "history_text", "tags_text", "location_text", "membership_status", "membership_status_source", "posting_limit", "posting_limit_period", "facebook_visible_items_count", "facebook_visible_items_detail", "facebook_visible_items_checked_at", "facebook_visible_items", "manual_active_posts", "post_tracking", "rule_guidance", "posting_recommendation", "follow_up", "post_events", "targeted", "target")}
            for group in self.facebook_groups(item_id)
        ]
