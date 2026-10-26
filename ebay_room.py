"""Workspace-scoped inventory coordination for the governed eBay room."""

from __future__ import annotations

import json
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


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
                CREATE INDEX IF NOT EXISTS ebay_room_item_link_idx ON item_links(item_id);
                CREATE INDEX IF NOT EXISTS ebay_room_draft_item_idx ON channel_drafts(item_id, updated_at DESC);
                """
            )

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

    def save_draft(self, item_id: str, channel: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        item = self.intake.get_item(item_id)
        target = str(channel or "").strip().lower()
        if target not in {"ebay", "facebook"}:
            raise EbayRoomError("Draft channel must be eBay or Facebook.")
        now, draft_id = _now(), _identifier("draft")
        value = dict(payload or {})
        value.setdefault("title", item.get("title") or "")
        value.setdefault("description", item.get("description") or "")
        value.setdefault("price", item.get("estimated_value"))
        value.setdefault("currency", item.get("currency") or "USD")
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO channel_drafts(draft_id,item_id,channel,status,payload_json,created_at,updated_at) VALUES(?,?,?,'draft',?,?,?)",
                (draft_id, item_id, target, json.dumps(value, ensure_ascii=False), now, now),
            )
        return {"draft_id": draft_id, "item_id": item_id, "channel": target, "status": "draft", "payload": value, "created_at": now, "updated_at": now}
