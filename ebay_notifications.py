"""Workspace-scoped consumer for the Veridex eBay notification relay."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional


MAX_RESPONSE_BYTES = 8_000_000
MAX_EVENT_BYTES = 1_000_000
MAX_SYNC_EVENTS = 500
DEFAULT_POLL_SECONDS = 60
MIN_POLL_SECONDS = 15
MAX_POLL_SECONDS = 3600

_SYNC_LOCKS: dict[str, threading.Lock] = {}
_SYNC_LOCKS_GUARD = threading.Lock()


class EbayNotificationError(RuntimeError):
    """A safe-to-display notification-consumer failure."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise EbayNotificationError(f"{name} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise EbayNotificationError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _serialized_by_database(method):
    """Prevent automatic and manual consumers from draining one queue concurrently."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        key = str(self.db_path)
        with _SYNC_LOCKS_GUARD:
            lock = _SYNC_LOCKS.setdefault(key, threading.Lock())
        with lock:
            return method(self, *args, **kwargs)

    return wrapped


class EbayNotificationConsumer:
    """Pull, durably record, and then acknowledge events from one Worker queue."""

    def __init__(self, workspace_id: str, env: Dict[str, str], *, now_fn=_now_iso) -> None:
        self.workspace_id = str(workspace_id or "").strip()
        self.env = dict(env or {})
        self.now_fn = now_fn
        if not self.workspace_id:
            raise EbayNotificationError("workspace_id is required.")
        self.worker_url = str(self.env.get("VERIDEX_EBAY_WORKER_URL") or "").strip().rstrip("/")
        self.shared_secret = str(self.env.get("VERIDEX_EBAY_WORKER_SHARED_SECRET") or "").strip()
        self.worker_workspace_id = str(self.env.get("VERIDEX_EBAY_WORKER_WORKSPACE_ID") or "").strip()
        self.expected_username = str(self.env.get("VERIDEX_EBAY_USERNAME") or "").strip()
        database = str(self.env.get("VERIDEX_EBAY_NOTIFICATIONS_DB_PATH") or "").strip()
        if not database:
            raise EbayNotificationError("The workspace eBay notification database path is not configured.")
        self.db_path = Path(database).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise EbayNotificationError("The workspace eBay notification store is unavailable.") from exc
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ebay_notification_events (
                    notification_id TEXT PRIMARY KEY,
                    remote_event_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    acknowledged_at TEXT NOT NULL DEFAULT '',
                    seen_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ebay_notification_events_received "
                "ON ebay_notification_events(received_at DESC)"
            )

    def configured(self) -> bool:
        parsed = urllib.parse.urlparse(self.worker_url)
        return bool(
            parsed.scheme == "https"
            and parsed.netloc
            and self.shared_secret
            and self.worker_workspace_id == self.workspace_id
        )

    def _require_configuration(self) -> None:
        parsed = urllib.parse.urlparse(self.worker_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise EbayNotificationError("The eBay notification Worker URL is missing or is not HTTPS.")
        if not self.shared_secret:
            raise EbayNotificationError("The eBay notification Worker shared secret is missing.")
        if not self.worker_workspace_id:
            raise EbayNotificationError("The eBay notification Worker workspace binding is missing.")
        if self.worker_workspace_id != self.workspace_id:
            raise EbayNotificationError("The eBay notification Worker is assigned to a different workspace.")

    def _request_json(self, method: str, path: str) -> Dict[str, Any]:
        self._require_configuration()
        request = urllib.request.Request(
            f"{self.worker_url}{path}",
            data=b"" if method.upper() != "GET" else None,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.shared_secret}",
                "User-Agent": "VeridexEbayNotificationConsumer/1.0",
            },
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(4096).decode("utf-8", errors="replace")).get("error")
            except (AttributeError, json.JSONDecodeError):
                detail = ""
            raise EbayNotificationError(
                f"The eBay notification relay rejected the request ({exc.code})"
                + (f": {detail}" if detail else ".")
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise EbayNotificationError("The eBay notification relay could not be reached.") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise EbayNotificationError("The eBay notification relay response was too large.")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EbayNotificationError("The eBay notification relay returned invalid JSON.") from exc
        if not isinstance(value, dict):
            raise EbayNotificationError("The eBay notification relay returned an invalid response.")
        return value

    @staticmethod
    def _notification_data(payload: Dict[str, Any]) -> Dict[str, Any]:
        notification = payload.get("notification") if isinstance(payload.get("notification"), dict) else {}
        data = notification.get("data") if isinstance(notification.get("data"), dict) else {}
        return data

    def _event_record(self, event: Dict[str, Any]) -> Dict[str, Any]:
        try:
            remote_id = int(event.get("id"))
        except (TypeError, ValueError) as exc:
            raise EbayNotificationError("An eBay queue event has an invalid remote ID.") from exc
        if remote_id < 1:
            raise EbayNotificationError("An eBay queue event has an invalid remote ID.")
        if str(event.get("workspace_id") or "").strip() != self.workspace_id:
            raise EbayNotificationError("An eBay queue event belongs to a different workspace.")
        notification_id = str(event.get("notification_id") or "").strip()
        topic = str(event.get("topic") or "").strip().upper()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else None
        if not notification_id or not topic or payload is None:
            raise EbayNotificationError("An eBay queue event is missing required notification fields.")
        payload_json = _compact_json(payload)
        payload_bytes = payload_json.encode("utf-8")
        if len(payload_bytes) > MAX_EVENT_BYTES:
            raise EbayNotificationError("An eBay queue event exceeded the local safety limit.")
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        event_date = str(event.get("event_date") or "").strip()
        received_at = str(event.get("received_at") or "").strip()
        data = self._notification_data(payload)
        now = self.now_fn()

        if topic == "MARKETPLACE_ACCOUNT_DELETION":
            incoming_username = str(data.get("username") or "").strip()
            account_match = bool(
                incoming_username
                and self.expected_username
                and incoming_username.casefold() == self.expected_username.casefold()
            )
            summary = {
                "kind": "compliance",
                "title": "Marketplace account deletion processed",
                "message": (
                    "The deletion request matches the seller assigned to this workspace and requires account cleanup review."
                    if account_match
                    else "Veridex stores no data keyed to the deleted marketplace account."
                ),
                "matching_workspace_seller": account_match,
            }
            return {
                "notification_id": notification_id,
                "remote_event_id": remote_id,
                "topic": topic,
                "event_date": event_date,
                "received_at": received_at,
                "kind": "compliance",
                "disposition": "manual_review_required" if account_match else "no_matching_local_user_data",
                "summary": summary,
                "payload_json": "",
                "payload_sha256": payload_hash,
                "first_seen_at": now,
                "updated_at": now,
            }

        summary = self._seller_event_summary(topic, data)
        return {
            "notification_id": notification_id,
            "remote_event_id": remote_id,
            "topic": topic,
            "event_date": event_date,
            "received_at": received_at,
            "kind": str(summary.get("kind") or "notification"),
            "disposition": "alert_ready",
            "summary": summary,
            "payload_json": "",
            "payload_sha256": payload_hash,
            "first_seen_at": now,
            "updated_at": now,
        }

    @staticmethod
    def _seller_event_summary(topic: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if topic == "ORDER_CONFIRMATION":
            order = data.get("order") if isinstance(data.get("order"), dict) else {}
            line_items = order.get("orderLineItems") if isinstance(order.get("orderLineItems"), list) else []
            listing_ids = [
                str(row.get("listingId") or "").strip()
                for row in line_items
                if isinstance(row, dict) and str(row.get("listingId") or "").strip()
            ]
            return {
                "kind": "sold",
                "title": "eBay order confirmed",
                "message": "A buyer completed checkout and payment cleared.",
                "order_id": str(order.get("orderId") or "").strip(),
                "listing_ids": list(dict.fromkeys(listing_ids)),
            }
        if topic in {"BUYER_QUESTION", "NEW_MESSAGE"}:
            body = " ".join(str(data.get("messageBody") or "").split())[:500]
            subject = " ".join(str(data.get("subject") or "").split())[:200]
            return {
                "kind": "message",
                "title": "Buyer question" if topic == "BUYER_QUESTION" else "New eBay message",
                "message": body or subject or "A new eBay communication is available.",
                "subject": subject,
                "message_id": str(data.get("messageId") or "").strip(),
                "conversation_id": str(data.get("conversationId") or "").strip(),
                "listing_id": str(data.get("listingId") or "").strip(),
            }
        return {
            "kind": "notification",
            "title": f"eBay notification: {topic.replace('_', ' ').title()}",
            "message": "A verified eBay notification was received.",
        }

    def _persist(self, record: Dict[str, Any]) -> bool:
        summary_json = _compact_json(record["summary"])
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT notification_id FROM ebay_notification_events WHERE notification_id = ?",
                (record["notification_id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO ebay_notification_events (
                    notification_id, remote_event_id, topic, event_date, received_at,
                    kind, disposition, summary_json, payload_json, payload_sha256,
                    first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(notification_id) DO UPDATE SET
                    remote_event_id = excluded.remote_event_id,
                    updated_at = excluded.updated_at
                """,
                (
                    record["notification_id"],
                    record["remote_event_id"],
                    record["topic"],
                    record["event_date"],
                    record["received_at"],
                    record["kind"],
                    record["disposition"],
                    summary_json,
                    record["payload_json"],
                    record["payload_sha256"],
                    record["first_seen_at"],
                    record["updated_at"],
                ),
            )
        return existing is None

    def _mark_acknowledged(self, notification_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE ebay_notification_events SET acknowledged_at = ?, updated_at = ? WHERE notification_id = ?",
                (self.now_fn(), self.now_fn(), notification_id),
            )

    @_serialized_by_database
    def sync(self, *, max_events: int = 100) -> Dict[str, Any]:
        target = _bounded_int(
            max_events,
            default=100,
            minimum=1,
            maximum=MAX_SYNC_EVENTS,
            name="max_events",
        )
        processed = 0
        new_events = 0
        acknowledged = 0
        compliance = 0
        alerts: list[Dict[str, Any]] = []
        errors: list[Dict[str, Any]] = []

        while processed < target:
            page_size = min(100, target - processed)
            query = urllib.parse.urlencode({"workspace_id": self.workspace_id, "limit": page_size})
            response = self._request_json("GET", f"/veridex/events?{query}")
            if str(response.get("workspace_id") or "").strip() != self.workspace_id:
                raise EbayNotificationError("The eBay notification relay returned the wrong workspace.")
            events = response.get("events") if isinstance(response.get("events"), list) else None
            if events is None:
                raise EbayNotificationError("The eBay notification relay response has no event list.")
            if not events:
                break
            pending_acknowledgements: list[tuple[int, str]] = []
            for event in events:
                if processed >= target:
                    break
                processed += 1
                try:
                    if not isinstance(event, dict):
                        raise EbayNotificationError("An eBay queue event is invalid.")
                    record = self._event_record(event)
                    inserted = self._persist(record)
                    if inserted:
                        new_events += 1
                        if record["kind"] == "compliance":
                            compliance += 1
                        else:
                            alerts.append({
                                "notification_id": record["notification_id"],
                                "topic": record["topic"],
                                "event_date": record["event_date"],
                                **record["summary"],
                            })
                    pending_acknowledgements.append(
                        (int(record["remote_event_id"]), str(record["notification_id"]))
                    )
                except EbayNotificationError as exc:
                    errors.append({
                        "remote_event_id": event.get("id") if isinstance(event, dict) else None,
                        "error": str(exc),
                    })
            if pending_acknowledgements:
                worker_count = min(8, len(pending_acknowledgements))
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = {
                        executor.submit(
                            self._request_json,
                            "POST",
                            f"/veridex/events/{remote_id}/ack",
                        ): (remote_id, notification_id)
                        for remote_id, notification_id in pending_acknowledgements
                    }
                    for future in as_completed(futures):
                        remote_id, notification_id = futures[future]
                        try:
                            ack = future.result()
                            if ack.get("acknowledged") is not True:
                                raise EbayNotificationError(
                                    "The eBay notification relay did not acknowledge the stored event."
                                )
                            self._mark_acknowledged(notification_id)
                            acknowledged += 1
                        except EbayNotificationError as exc:
                            errors.append({"remote_event_id": remote_id, "error": str(exc)})
            if len(events) < page_size or errors:
                break

        return {
            "status": "complete" if not errors else "partial",
            "workspace_id": self.workspace_id,
            "processed": processed,
            "new_events": new_events,
            "acknowledged": acknowledged,
            "compliance_events": compliance,
            "alerts": alerts,
            "errors": errors,
        }

    def recent(self, *, limit: int = 25, include_compliance: bool = False) -> list[Dict[str, Any]]:
        count = _bounded_int(limit, default=25, minimum=1, maximum=100, name="limit")
        where = "" if include_compliance else "WHERE kind != 'compliance'"
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT notification_id, topic, event_date, received_at, kind, disposition,
                           summary_json, acknowledged_at, seen_at
                    FROM ebay_notification_events {where}
                    ORDER BY first_seen_at DESC LIMIT ?""",
                (count,),
            ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            try:
                summary = json.loads(value.pop("summary_json"))
            except json.JSONDecodeError:
                summary = {}
            result.append({**value, "summary": summary})
        return result

    def status(self) -> Dict[str, Any]:
        with self._connection() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN kind = 'compliance' THEN 1 ELSE 0 END) AS compliance,
                          SUM(CASE WHEN kind != 'compliance' THEN 1 ELSE 0 END) AS seller_alerts,
                          SUM(CASE WHEN kind != 'compliance' AND seen_at = '' THEN 1 ELSE 0 END) AS unread,
                          MAX(updated_at) AS last_updated_at
                   FROM ebay_notification_events"""
            ).fetchone()
        return {
            "configured": self.configured(),
            "workspace_id": self.workspace_id,
            "stored_events": int(totals["total"] or 0),
            "compliance_events": int(totals["compliance"] or 0),
            "seller_alerts": int(totals["seller_alerts"] or 0),
            "unread_alerts": int(totals["unread"] or 0),
            "last_updated_at": str(totals["last_updated_at"] or ""),
        }


class EbayNotificationPoller:
    """Periodically drain configured workspace queues while the Veridex service runs."""

    def __init__(
        self,
        workspace_ids: Callable[[], Iterable[str]],
        consumer: Callable[[str], EbayNotificationConsumer],
        *,
        enabled: bool = True,
        interval_seconds: int = DEFAULT_POLL_SECONDS,
        max_events: int = 100,
        now_fn: Callable[[], str] = _now_iso,
    ) -> None:
        self._workspace_ids = workspace_ids
        self._consumer = consumer
        self.enabled = bool(enabled)
        self.interval_seconds = _bounded_int(
            interval_seconds,
            default=DEFAULT_POLL_SECONDS,
            minimum=MIN_POLL_SECONDS,
            maximum=MAX_POLL_SECONDS,
            name="interval_seconds",
        )
        self.max_events = _bounded_int(
            max_events,
            default=100,
            minimum=1,
            maximum=MAX_SYNC_EVENTS,
            name="max_events",
        )
        self.now_fn = now_fn
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._workspace_state: dict[str, Dict[str, Any]] = {}

    def start(self) -> bool:
        if not self.enabled:
            return False
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="veridex-ebay-notifications",
                daemon=True,
            )
            self._thread.start()
        return True

    def stop(self, timeout: float = 35.0) -> bool:
        self._stop.set()
        self._wake.set()
        with self._state_lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        return thread is None or not thread.is_alive()

    def wake(self) -> None:
        """Request an early poll, for example after enabling a workspace toggle."""
        if self.enabled:
            self._wake.set()

    def _record(self, workspace_id: str, **values: Any) -> None:
        with self._state_lock:
            current = dict(self._workspace_state.get(workspace_id) or {})
            current.update(values)
            self._workspace_state[workspace_id] = current

    def poll_once(self) -> Dict[str, Any]:
        checked = 0
        failures = 0
        alerts = 0
        for raw_workspace_id in self._workspace_ids():
            if self._stop.is_set():
                break
            workspace_id = str(raw_workspace_id or "").strip()
            if not workspace_id:
                continue
            checked += 1
            started_at = self.now_fn()
            self._record(workspace_id, status="checking", last_started_at=started_at, error="")
            try:
                consumer = self._consumer(workspace_id)
                if not consumer.configured():
                    self._record(
                        workspace_id,
                        status="not_configured",
                        last_completed_at=self.now_fn(),
                        error="The eBay notification relay is not configured for this workspace.",
                    )
                    failures += 1
                    continue
                result = consumer.sync(max_events=self.max_events)
                workspace_alerts = len(result.get("alerts") or [])
                alerts += workspace_alerts
                errors = result.get("errors") if isinstance(result.get("errors"), list) else []
                if errors:
                    failures += 1
                self._record(
                    workspace_id,
                    status=str(result.get("status") or "complete"),
                    last_completed_at=self.now_fn(),
                    processed=int(result.get("processed") or 0),
                    new_events=int(result.get("new_events") or 0),
                    acknowledged=int(result.get("acknowledged") or 0),
                    alerts=workspace_alerts,
                    error=str(errors[0].get("error") or "") if errors and isinstance(errors[0], dict) else "",
                )
            except Exception as exc:
                failures += 1
                self._record(
                    workspace_id,
                    status="failed",
                    last_completed_at=self.now_fn(),
                    error=str(exc)[:1000],
                )
        return {"checked": checked, "failures": failures, "alerts": alerts}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                # Workspace discovery failures are retried on the next interval. Per-workspace
                # failures are recorded by poll_once without stopping other workspaces.
                pass
            self._wake.wait(self.interval_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break

    def status(self, workspace_id: str = "") -> Dict[str, Any]:
        with self._state_lock:
            thread = self._thread
            states = {key: dict(value) for key, value in self._workspace_state.items()}
        value: Dict[str, Any] = {
            "enabled": self.enabled,
            "running": bool(thread and thread.is_alive()),
            "interval_seconds": self.interval_seconds,
            "max_events": self.max_events,
        }
        target = str(workspace_id or "").strip()
        if target:
            value.update(states.get(target) or {"status": "pending"})
        else:
            value["workspaces"] = states
        return value
