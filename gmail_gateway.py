"""Self-contained Gmail API gateway for the local Veridex workspace."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, formataddr, getaddresses, make_msgid, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional


ROOT = Path(__file__).resolve().parent
LOCAL_ENV = ROOT / ".env.local"
DEFAULT_GMAIL_DB = ROOT / "data" / "integrations" / "gmail.db"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GmailGatewayError(Exception):
    """A safe-to-display Gmail integration failure."""


def _load_env_file(path: Path, values: Dict[str, str]) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip().strip("\"'"))


def _default_env() -> Dict[str, str]:
    values = dict(os.environ)
    _load_env_file(LOCAL_ENV, values)
    return values


def _parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now_from_value(value: str) -> datetime:
    parsed = _parse_time(value)
    return parsed or datetime.now(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decoded_header(value: Any) -> str:
    try:
        return str(make_header(decode_header(str(value or ""))))
    except (LookupError, UnicodeError):
        return str(value or "")


def _header_time(value: str, fallback: str) -> str:
    try:
        parsed = parsedate_to_datetime(str(value or ""))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        return fallback


class TokenCipher:
    """Authenticated token storage owned by Veridex."""

    def __init__(self, key: str) -> None:
        raw = str(key or "").strip().encode("utf-8")
        if len(raw) < 32:
            raise GmailGatewayError("VERIDEX_INTEGRATION_ENCRYPTION_KEY must be at least 32 characters.")
        self._key = hashlib.sha256(raw).digest()

    def _stream(self, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(
                hmac.new(
                    self._key,
                    b"veridex-token-v1" + nonce + counter.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            counter += 1
        return bytes(output[:length])

    def encrypt(self, value: str) -> str:
        nonce = secrets.token_bytes(24)
        plaintext = str(value or "").encode("utf-8")
        stream = self._stream(nonce, len(plaintext))
        ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(self._key, b"veridex-token-tag-v1" + nonce + ciphertext, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(str(value or "").encode("ascii"))
            nonce, tag, ciphertext = raw[:24], raw[24:56], raw[56:]
        except Exception as exc:
            raise GmailGatewayError("Stored Gmail credential is invalid. Reconnect the Google account.") from exc
        expected = hmac.new(self._key, b"veridex-token-tag-v1" + nonce + ciphertext, hashlib.sha256).digest()
        if len(nonce) != 24 or not hmac.compare_digest(tag, expected):
            raise GmailGatewayError("Stored Gmail credential failed integrity validation. Reconnect the Google account.")
        stream = self._stream(nonce, len(ciphertext))
        return bytes(left ^ right for left, right in zip(ciphertext, stream)).decode("utf-8")


class GmailGateway:
    def __init__(self, env: Optional[Dict[str, str]] = None, now_fn: Callable[[], str] = _now_iso) -> None:
        self.env = dict(env) if env is not None else _default_env()
        self.now_fn = now_fn
        self.db_path = Path(str(self.env.get("VERIDEX_GMAIL_DB_PATH") or DEFAULT_GMAIL_DB)).resolve()
        self.account_email = str(
            self.env.get("VERIDEX_GOOGLE_ACCOUNT")
            or self.env.get("GMAIL_ACCOUNT")
            or "veridexcorp@gmail.com"
        ).strip()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @staticmethod
    def _is_repo_local_path(path: Path) -> bool:
        try:
            resolved = path.resolve()
            return resolved == ROOT or ROOT in resolved.parents
        except OSError:
            return False

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise GmailGatewayError(f"Gmail token store is unavailable at {self.db_path}.") from exc
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_integrations (
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    access_token_ciphertext TEXT NOT NULL,
                    refresh_token_ciphertext TEXT NOT NULL,
                    access_token_expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, provider)
                );
                CREATE TABLE IF NOT EXISTS gmail_contacts (
                    contact_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    name TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    company TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'sent_mail',
                    first_contacted_at TEXT NOT NULL DEFAULT '',
                    last_contacted_at TEXT NOT NULL DEFAULT '',
                    email_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gmail_contact_messages (
                    gmail_message_id TEXT NOT NULL,
                    recipient_email TEXT NOT NULL COLLATE NOCASE,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (gmail_message_id, recipient_email)
                );
                CREATE TABLE IF NOT EXISTS gmail_outbound_messages (
                    rfc_message_id TEXT PRIMARY KEY,
                    gmail_message_id TEXT NOT NULL DEFAULT '',
                    gmail_thread_id TEXT NOT NULL DEFAULT '',
                    workspace_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    recipients_json TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'accepted',
                    sent_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gmail_delivery_checks (
                    gmail_message_id TEXT PRIMARY KEY,
                    checked_at TEXT NOT NULL,
                    parser_version INTEGER NOT NULL DEFAULT 2
                );
                CREATE TABLE IF NOT EXISTS gmail_delivery_failures (
                    failure_id TEXT PRIMARY KEY,
                    gmail_message_id TEXT NOT NULL UNIQUE,
                    rfc_message_id TEXT NOT NULL DEFAULT '',
                    recipient TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    diagnostic TEXT NOT NULL DEFAULT '',
                    status_code TEXT NOT NULL DEFAULT '',
                    detected_at TEXT NOT NULL,
                    notified_session_id TEXT NOT NULL DEFAULT '',
                    resolved_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS gmail_sync_state (
                    sync_key TEXT PRIMARY KEY,
                    sync_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            delivery_check_columns = {
                str(row["name"]) for row in conn.execute("PRAGMA table_info(gmail_delivery_checks)").fetchall()
            }
            if "parser_version" not in delivery_check_columns:
                conn.execute(
                    "ALTER TABLE gmail_delivery_checks ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1"
                )

    def _cipher(self) -> TokenCipher:
        return TokenCipher(str(self.env.get("VERIDEX_INTEGRATION_ENCRYPTION_KEY") or ""))

    def _connection_row(self) -> Dict[str, Any]:
        with self._connection() as conn:
            try:
                if self.account_email:
                    row = conn.execute(
                        """
                        SELECT * FROM user_integrations
                        WHERE provider = ? AND status = ? AND lower(account_email) = lower(?)
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        ("google", "connected", self.account_email),
                    ).fetchone()
                    if row:
                        return dict(row)
                row = conn.execute(
                    """
                    SELECT * FROM user_integrations
                    WHERE provider = ? AND status = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    ("google", "connected"),
                ).fetchone()
            except sqlite3.Error as exc:
                raise GmailGatewayError("Gmail token store is unavailable or has an unexpected schema.") from exc
        if not row:
            raise GmailGatewayError("Google Gmail is not connected. Run .\\veridex.ps1 gmail-connect, then try again.")
        return dict(row)

    def connection_status(self) -> Dict[str, Any]:
        try:
            row = self._connection_row()
        except GmailGatewayError:
            return {
                "configured": self.configured(),
                "connected": False,
                "account_email": self.account_email,
            }
        scopes = []
        try:
            parsed = json.loads(str(row.get("scopes_json") or "[]"))
            scopes = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            scopes = []
        return {
            "configured": self.configured(),
            "connected": True,
            "account_email": row.get("account_email") or self.account_email,
            "scopes": scopes,
            "user_id": row.get("user_id"),
            "updated_at": row.get("updated_at"),
        }

    def configured(self) -> bool:
        return bool(
            self.env.get("VERIDEX_INTEGRATION_ENCRYPTION_KEY")
            and self.env.get("GOOGLE_OAUTH_CLIENT_ID")
            and self.env.get("GOOGLE_OAUTH_CLIENT_SECRET")
        )

    def save_connection(
        self,
        *,
        account_email: str,
        access_token: str,
        refresh_token: str,
        expires_in: int = 3600,
        scopes: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Persist a newly authorized Google connection in Veridex's local store."""
        email = str(account_email or "").strip()
        access = str(access_token or "").strip()
        refresh = str(refresh_token or "").strip()
        if not email or not access or not refresh:
            raise GmailGatewayError("Google authorization did not return a complete Gmail connection.")
        cipher = self._cipher()
        now = _now_from_value(self.now_fn())
        expires_at = (now + timedelta(seconds=max(60, int(expires_in or 3600)))).isoformat().replace("+00:00", "Z")
        scope_values = sorted({str(value).strip() for value in (scopes or []) if str(value).strip()})
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO user_integrations (
                    user_id, provider, account_email, scopes_json, status,
                    access_token_ciphertext, refresh_token_ciphertext,
                    access_token_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, provider) DO UPDATE SET
                    account_email = excluded.account_email,
                    scopes_json = excluded.scopes_json,
                    status = excluded.status,
                    access_token_ciphertext = excluded.access_token_ciphertext,
                    refresh_token_ciphertext = excluded.refresh_token_ciphertext,
                    access_token_expires_at = excluded.access_token_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    "local",
                    "google",
                    email,
                    json.dumps(scope_values),
                    "connected",
                    cipher.encrypt(access),
                    cipher.encrypt(refresh),
                    expires_at,
                    self.now_fn(),
                    self.now_fn(),
                ),
            )
        self.account_email = email
        return self.connection_status()

    def _access_token(self) -> str:
        row = self._connection_row()
        cipher = self._cipher()
        expires_at = _parse_time(str(row.get("access_token_expires_at") or ""))
        now = _now_from_value(self.now_fn())
        if expires_at and expires_at > now + timedelta(seconds=60):
            return cipher.decrypt(str(row.get("access_token_ciphertext") or ""))
        return self._refresh_access_token(row, cipher, now)

    def _refresh_access_token(self, row: Dict[str, Any], cipher: TokenCipher, now: datetime) -> str:
        client_id = str(self.env.get("GOOGLE_OAUTH_CLIENT_ID") or "")
        client_secret = str(self.env.get("GOOGLE_OAUTH_CLIENT_SECRET") or "")
        if not client_id or not client_secret:
            raise GmailGatewayError("Google OAuth client credentials are missing.")
        refresh = cipher.decrypt(str(row.get("refresh_token_ciphertext") or ""))
        payload = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        try:
            data = self._json_request(TOKEN_URL, token="", method="POST", data=payload)
        except GmailGatewayError as exc:
            if "invalid_grant" in str(exc):
                raise GmailGatewayError(
                    "Google rejected the stored refresh token. Run .\\veridex.ps1 gmail-connect to reconnect Gmail, then try again."
                ) from exc
            raise
        access = str(data.get("access_token") or "")
        if not access:
            raise GmailGatewayError("Google did not return a refreshed access token.")
        expires_in = int(data.get("expires_in") or 3600)
        expires_at = (now + timedelta(seconds=max(60, expires_in))).isoformat().replace("+00:00", "Z")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE user_integrations
                SET access_token_ciphertext = ?, access_token_expires_at = ?, updated_at = ?
                WHERE user_id = ? AND provider = ?
                """,
                (
                    cipher.encrypt(access),
                    expires_at,
                    self.now_fn(),
                    row.get("user_id"),
                    row.get("provider"),
                ),
            )
        return access

    def _json_request(
        self,
        url: str,
        *,
        token: str,
        method: str = "GET",
        data: Optional[bytes] = None,
        content_type: str = "application/x-www-form-urlencoded",
    ) -> Dict[str, Any]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
                payload = json.loads(body)
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("status") or "")
                else:
                    description = str(payload.get("error_description") or "")
                    detail = " ".join(part for part in [str(error or ""), description] if part)
            except Exception:
                detail = exc.reason or ""
            raise GmailGatewayError(f"Gmail API request failed: HTTP {exc.code} {detail}".strip()) from exc
        except urllib.error.URLError as exc:
            raise GmailGatewayError(f"Gmail API is unavailable: {exc.reason}") from exc
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise GmailGatewayError("Gmail API returned invalid JSON.") from exc
        return value if isinstance(value, dict) else {}

    def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        token = self._access_token()
        count = max(1, min(int(max_results or 10), 25))
        params = urllib.parse.urlencode({"q": str(query or "in:inbox"), "maxResults": count})
        listing = self._json_request(f"{GMAIL_API}/messages?{params}", token=token)
        messages = listing.get("messages") if isinstance(listing.get("messages"), list) else []
        results: List[Dict[str, Any]] = []
        for item in messages[:count]:
            message_id = str((item or {}).get("id") or "")
            if not message_id:
                continue
            params = urllib.parse.urlencode({"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]}, doseq=True)
            detail = self._json_request(f"{GMAIL_API}/messages/{urllib.parse.quote(message_id)}?{params}", token=token)
            headers = {
                str(header.get("name") or "").lower(): html.unescape(str(header.get("value") or ""))
                for header in ((detail.get("payload") or {}).get("headers") or [])
                if isinstance(header, dict)
            }
            results.append(
                {
                    "id": detail.get("id") or message_id,
                    "threadId": detail.get("threadId") or (item or {}).get("threadId"),
                    "from": headers.get("from", ""),
                    "subject": headers.get("subject", "(no subject)"),
                    "date": headers.get("date", ""),
                    "snippet": html.unescape(str(detail.get("snippet") or "")),
                }
            )
        return results

    @staticmethod
    def _normalize_contact_email(value: Any) -> str:
        email = str(value or "").strip().lower()
        if not EMAIL_RE.fullmatch(email):
            raise GmailGatewayError("Enter a valid contact email address.")
        return email

    @staticmethod
    def _contact_value(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        value = dict(row)
        value["email_count"] = int(value.get("email_count") or 0)
        return value

    def list_contacts(self, query: str = "") -> List[Dict[str, Any]]:
        search = str(query or "").strip().lower()
        with self._connection() as conn:
            if search:
                wildcard = f"%{search}%"
                rows = conn.execute(
                    """
                    SELECT * FROM gmail_contacts
                    WHERE lower(name) LIKE ? OR lower(email) LIKE ? OR lower(company) LIKE ? OR lower(notes) LIKE ?
                    ORDER BY CASE WHEN name = '' THEN email ELSE name END COLLATE NOCASE, email COLLATE NOCASE
                    """,
                    (wildcard, wildcard, wildcard, wildcard),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM gmail_contacts
                    ORDER BY CASE WHEN name = '' THEN email ELSE name END COLLATE NOCASE, email COLLATE NOCASE
                    """
                ).fetchall()
        return [self._contact_value(row) for row in rows]

    def contact_sync_status(self) -> Dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT sync_value, updated_at FROM gmail_sync_state WHERE sync_key = 'contacts_recent_500'"
            ).fetchone()
        return {
            "completed": bool(row),
            "messages_scanned": int(row["sync_value"] or 0) if row else 0,
            "updated_at": str(row["updated_at"] or "") if row else "",
        }

    def save_contact(self, value: Dict[str, Any]) -> Dict[str, Any]:
        email = self._normalize_contact_email(value.get("email"))
        contact_id = str(value.get("contact_id") or "").strip()
        name = str(value.get("name") or "").strip()[:200]
        phone = str(value.get("phone") or "").strip()[:100]
        company = str(value.get("company") or "").strip()[:200]
        notes = str(value.get("notes") or "").strip()[:4000]
        now = self.now_fn()
        with self._connection() as conn:
            existing = None
            if contact_id:
                existing = conn.execute("SELECT * FROM gmail_contacts WHERE contact_id = ?", (contact_id,)).fetchone()
                if not existing:
                    raise GmailGatewayError("That address-book contact no longer exists.")
            if not existing:
                existing = conn.execute("SELECT * FROM gmail_contacts WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
            if existing:
                contact_id = str(existing["contact_id"])
                try:
                    conn.execute(
                        """
                        UPDATE gmail_contacts
                        SET email = ?, name = ?, phone = ?, company = ?, notes = ?, source = 'manual', updated_at = ?
                        WHERE contact_id = ?
                        """,
                        (email, name, phone, company, notes, now, contact_id),
                    )
                except sqlite3.IntegrityError as exc:
                    raise GmailGatewayError("That email address is already assigned to another contact.") from exc
            else:
                contact_id = f"contact_{secrets.token_hex(6)}"
                conn.execute(
                    """
                    INSERT INTO gmail_contacts (
                        contact_id, email, name, phone, company, notes, source,
                        first_contacted_at, last_contacted_at, email_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'manual', '', '', 0, ?, ?)
                    """,
                    (contact_id, email, name, phone, company, notes, now, now),
                )
            row = conn.execute("SELECT * FROM gmail_contacts WHERE contact_id = ?", (contact_id,)).fetchone()
        return self._contact_value(row)

    def _record_contact_event(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        email: str,
        name: str,
        contacted_at: str,
    ) -> bool:
        normalized = str(email or "").strip().lower()
        if normalized == self.account_email.lower() or not EMAIL_RE.fullmatch(normalized):
            return False
        inserted = conn.execute(
            "INSERT OR IGNORE INTO gmail_contact_messages (gmail_message_id, recipient_email, recorded_at) VALUES (?, ?, ?)",
            (event_id, normalized, self.now_fn()),
        ).rowcount
        if not inserted:
            return False
        now = self.now_fn()
        contact_id = f"contact_{secrets.token_hex(6)}"
        conn.execute(
            """
            INSERT INTO gmail_contacts (
                contact_id, email, name, source, first_contacted_at, last_contacted_at,
                email_count, created_at, updated_at
            ) VALUES (?, ?, ?, 'sent_mail', ?, ?, 1, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name = CASE WHEN gmail_contacts.name = '' THEN excluded.name ELSE gmail_contacts.name END,
                first_contacted_at = CASE
                    WHEN gmail_contacts.first_contacted_at = '' OR excluded.first_contacted_at < gmail_contacts.first_contacted_at
                    THEN excluded.first_contacted_at ELSE gmail_contacts.first_contacted_at END,
                last_contacted_at = CASE
                    WHEN excluded.last_contacted_at > gmail_contacts.last_contacted_at
                    THEN excluded.last_contacted_at ELSE gmail_contacts.last_contacted_at END,
                email_count = gmail_contacts.email_count + 1,
                updated_at = excluded.updated_at
            """,
            (contact_id, normalized, str(name or "").strip()[:200], contacted_at, contacted_at, now, now),
        )
        return True

    def sync_contacts(self, max_messages: int = 500) -> Dict[str, Any]:
        token = self._access_token()
        limit = max(1, min(int(max_messages or 500), 500))
        params = urllib.parse.urlencode({"q": "in:sent", "maxResults": limit})
        listing = self._json_request(f"{GMAIL_API}/messages?{params}", token=token)
        messages = listing.get("messages") if isinstance(listing.get("messages"), list) else []
        imported = 0
        headers_to_read = ["To", "Cc", "Bcc", "Date"]
        for item in messages[:limit]:
            message_id = str((item or {}).get("id") or "")
            if not message_id:
                continue
            metadata = urllib.parse.urlencode(
                {"format": "metadata", "metadataHeaders": headers_to_read},
                doseq=True,
            )
            detail = self._json_request(
                f"{GMAIL_API}/messages/{urllib.parse.quote(message_id)}?{metadata}",
                token=token,
            )
            headers: Dict[str, List[str]] = {}
            for header in ((detail.get("payload") or {}).get("headers") or []):
                if not isinstance(header, dict):
                    continue
                headers.setdefault(str(header.get("name") or "").lower(), []).append(
                    _decoded_header(header.get("value"))
                )
            contacted_at = _header_time(" ".join(headers.get("date", [])), self.now_fn())
            addresses = getaddresses(headers.get("to", []) + headers.get("cc", []) + headers.get("bcc", []))
            unique = {(str(email).strip().lower(), str(name).strip()) for name, email in addresses if str(email).strip()}
            with self._connection() as conn:
                for email, name in unique:
                    if self._record_contact_event(
                        conn,
                        event_id=message_id,
                        email=email,
                        name=name,
                        contacted_at=contacted_at,
                    ):
                        imported += 1
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO gmail_sync_state (sync_key, sync_value, updated_at)
                VALUES ('contacts_recent_500', ?, ?)
                ON CONFLICT(sync_key) DO UPDATE SET sync_value = excluded.sync_value, updated_at = excluded.updated_at
                """,
                (str(min(len(messages), limit)), self.now_fn()),
            )
        return {
            "messages_scanned": min(len(messages), limit),
            "contact_events_added": imported,
            "contacts": self.list_contacts(),
            "sync": self.contact_sync_status(),
        }

    @staticmethod
    def _public_attachment_record(value: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value[key]
            for key in ("file_id", "name", "path", "content_type", "size")
            if key in value
        }

    def _record_outbound(
        self,
        *,
        rfc_message_id: str,
        result: Dict[str, Any],
        recipients: List[str],
        subject: str,
        body: str,
        attachments: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> None:
        now = self.now_fn()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO gmail_outbound_messages (
                    rfc_message_id, gmail_message_id, gmail_thread_id, workspace_id, session_id,
                    recipients_json, subject, body, attachments_json, status, sent_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'accepted', ?, ?)
                """,
                (
                    rfc_message_id,
                    str(result.get("id") or ""),
                    str(result.get("threadId") or ""),
                    str(context.get("workspace_id") or ""),
                    str(context.get("session_id") or ""),
                    json.dumps(recipients, ensure_ascii=False),
                    subject,
                    body,
                    json.dumps([self._public_attachment_record(row) for row in attachments], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            for name, email in getaddresses(recipients):
                self._record_contact_event(
                    conn,
                    event_id=f"outbound:{str(result.get('id') or rfc_message_id)}",
                    email=email,
                    name=name,
                    contacted_at=now,
                )

    def _outbound_rows(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM gmail_outbound_messages ORDER BY sent_at DESC LIMIT 1000"
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            try:
                value["recipients"] = json.loads(str(value.pop("recipients_json") or "[]"))
            except json.JSONDecodeError:
                value["recipients"] = []
            try:
                value["attachments"] = json.loads(str(value.pop("attachments_json") or "[]"))
            except json.JSONDecodeError:
                value["attachments"] = []
            values.append(value)
        return values

    @staticmethod
    def _delivery_text(raw_bytes: bytes) -> tuple[str, str, Dict[str, str]]:
        message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        parts = [raw_bytes.decode("utf-8", errors="replace")]
        original_headers: Dict[str, str] = {}
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    parts.append(str(part.get_content()))
                except (LookupError, UnicodeError, KeyError):
                    continue
            elif part.get_content_type() == "text/rfc822-headers":
                try:
                    original_text = str(part.get_content())
                    parts.append(original_text)
                    original = BytesParser(policy=policy.default).parsebytes(original_text.encode("utf-8"))
                    original_headers = {
                        name.lower(): _decoded_header(original.get(name))
                        for name in ("Message-ID", "To", "Subject", "Date")
                        if original.get(name)
                    }
                except (LookupError, UnicodeError, KeyError):
                    continue
        return _decoded_header(message.get("Subject")), "\n".join(parts), original_headers

    @staticmethod
    def _delivery_field(text: str, name: str) -> str:
        match = re.search(rf"(?im)^{re.escape(name)}:\s*(?:rfc822;\s*)?([^\r\n]+)", text)
        return str(match.group(1)).strip() if match else ""

    def _parse_delivery_failure(self, gmail_message_id: str, raw_bytes: bytes) -> Optional[Dict[str, Any]]:
        bounce_subject, text, original_headers = self._delivery_text(raw_bytes)
        action = self._delivery_field(text, "Action").lower()
        status_code = self._delivery_field(text, "Status")
        looks_failed = action == "failed" or status_code.startswith("5") or bool(
            re.search(r"delivery status notification\s*\(failure\)|undeliver(?:ed|able)|delivery failure", bounce_subject, re.I)
        )
        if not looks_failed:
            return None
        recipient = self._delivery_field(text, "Final-Recipient") or self._delivery_field(text, "Original-Recipient")
        recipient_match = re.search(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}", recipient)
        recipient = recipient_match.group(0).lower() if recipient_match else ""
        diagnostic = self._delivery_field(text, "Diagnostic-Code")
        outbound = None
        lowered = text.lower()
        rows = self._outbound_rows()
        for row in rows:
            if str(row.get("rfc_message_id") or "").lower() in lowered:
                outbound = row
                break
        if not outbound:
            original_subject = str(original_headers.get("subject") or "").strip().lower()
            original_recipients = {
                str(address or "").strip().lower()
                for _, address in getaddresses([str(original_headers.get("to") or "")])
                if str(address or "").strip()
            }
            if recipient:
                original_recipients.add(recipient)
            outbound = next(
                (
                    row for row in rows
                    if original_subject
                    and str(row.get("subject") or "").strip().lower() == original_subject
                    and bool(original_recipients.intersection(
                        str(value or "").strip().lower() for value in row.get("recipients", [])
                    ))
                ),
                None,
            )
        if not outbound:
            return None
        return {
            "failure_id": f"failure_{secrets.token_hex(6)}",
            "gmail_message_id": gmail_message_id,
            "rfc_message_id": str((outbound or {}).get("rfc_message_id") or ""),
            "recipient": recipient,
            "subject": str((outbound or {}).get("subject") or bounce_subject or "(unknown subject)"),
            "diagnostic": diagnostic or "The recipient's mail system returned the message.",
            "status_code": status_code,
        }

    def check_delivery_failures(self, max_results: int = 50) -> Dict[str, Any]:
        token = self._access_token()
        query = (
            "in:anywhere newer_than:30d "
            "(from:mailer-daemon@googlemail.com OR from:mailer-daemon@gmail.com OR from:postmaster)"
        )
        params = urllib.parse.urlencode(
            {"q": query, "maxResults": max(1, min(int(max_results or 50), 100)), "includeSpamTrash": "true"}
        )
        listing = self._json_request(f"{GMAIL_API}/messages?{params}", token=token)
        messages = listing.get("messages") if isinstance(listing.get("messages"), list) else []
        new_failures: List[Dict[str, Any]] = []
        for item in messages:
            message_id = str((item or {}).get("id") or "")
            if not message_id:
                continue
            with self._connection() as conn:
                checked = conn.execute(
                    "SELECT parser_version FROM gmail_delivery_checks WHERE gmail_message_id = ?", (message_id,)
                ).fetchone()
            if checked and int(checked["parser_version"] or 0) >= 2:
                continue
            detail = self._json_request(
                f"{GMAIL_API}/messages/{urllib.parse.quote(message_id)}?format=raw",
                token=token,
            )
            raw = str(detail.get("raw") or "")
            raw += "=" * (-len(raw) % 4)
            try:
                raw_bytes = base64.urlsafe_b64decode(raw.encode("ascii"))
            except (ValueError, UnicodeEncodeError) as exc:
                raise GmailGatewayError("Gmail returned an unreadable delivery-status message.") from exc
            failure = self._parse_delivery_failure(message_id, raw_bytes)
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO gmail_delivery_checks (gmail_message_id, checked_at, parser_version)
                    VALUES (?, ?, 2)
                    ON CONFLICT(gmail_message_id) DO UPDATE SET
                        checked_at = excluded.checked_at,
                        parser_version = excluded.parser_version
                    """,
                    (message_id, self.now_fn()),
                )
                if failure:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO gmail_delivery_failures (
                            failure_id, gmail_message_id, rfc_message_id, recipient, subject,
                            diagnostic, status_code, detected_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            failure["failure_id"], failure["gmail_message_id"], failure["rfc_message_id"],
                            failure["recipient"], failure["subject"], failure["diagnostic"],
                            failure["status_code"], self.now_fn(),
                        ),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0]:
                        if failure["rfc_message_id"]:
                            conn.execute(
                                "UPDATE gmail_outbound_messages SET status = 'failed', updated_at = ? WHERE rfc_message_id = ?",
                                (self.now_fn(), failure["rfc_message_id"]),
                            )
                        new_failures.append(failure)
        return {"new_failures": new_failures, "alerts": self.list_delivery_failures()}

    def list_delivery_failures(self, unresolved_only: bool = True) -> List[Dict[str, Any]]:
        where = "WHERE failure.resolved_at = ''" if unresolved_only else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT failure.*, outbound.recipients_json, outbound.body, outbound.attachments_json,
                       outbound.workspace_id, outbound.session_id
                FROM gmail_delivery_failures AS failure
                LEFT JOIN gmail_outbound_messages AS outbound
                    ON outbound.rfc_message_id = failure.rfc_message_id
                {where}
                ORDER BY failure.detected_at DESC
                """
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            for source, target in (("recipients_json", "to"), ("attachments_json", "attachments")):
                try:
                    value[target] = json.loads(str(value.pop(source) or "[]"))
                except json.JSONDecodeError:
                    value[target] = []
            values.append(value)
        return values

    def mark_failure_notified(self, failure_id: str, session_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE gmail_delivery_failures SET notified_session_id = ? WHERE failure_id = ? AND notified_session_id = ''",
                (str(session_id or ""), str(failure_id or "")),
            )

    def resolve_delivery_failure(self, failure_id: str) -> Dict[str, Any]:
        now = self.now_fn()
        with self._connection() as conn:
            conn.execute(
                "UPDATE gmail_delivery_failures SET resolved_at = ? WHERE failure_id = ? AND resolved_at = ''",
                (now, str(failure_id or "")),
            )
            row = conn.execute(
                "SELECT * FROM gmail_delivery_failures WHERE failure_id = ?", (str(failure_id or ""),)
            ).fetchone()
        if not row:
            raise GmailGatewayError("That delivery alert no longer exists.")
        return dict(row)

    def _gmail_rfc_message_id(self, gmail_message_id: str, token: str) -> str:
        if not gmail_message_id:
            return ""
        params = urllib.parse.urlencode(
            {"format": "metadata", "metadataHeaders": ["Message-ID"]},
            doseq=True,
        )
        detail = self._json_request(
            f"{GMAIL_API}/messages/{urllib.parse.quote(gmail_message_id)}?{params}",
            token=token,
        )
        for header in ((detail.get("payload") or {}).get("headers") or []):
            if isinstance(header, dict) and str(header.get("name") or "").lower() == "message-id":
                return str(header.get("value") or "").strip()
        return ""

    def send(
        self,
        to: Iterable[str],
        subject: str,
        body: str,
        attachments: Optional[Iterable[Dict[str, Any]]] = None,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        recipients = [str(value).strip() for value in to if str(value).strip()]
        if not recipients:
            raise GmailGatewayError("At least one recipient is required.")
        message = EmailMessage()
        sender_name = str(self.env.get("VERIDEX_GOOGLE_FROM_NAME") or "").strip()
        message["From"] = formataddr((sender_name, self.account_email)) if sender_name else self.account_email
        message["To"] = ", ".join(recipients)
        message["Subject"] = str(subject or "").strip() or "(no subject)"
        message["Date"] = format_datetime(_now_from_value(self.now_fn()))
        domain = self.account_email.rsplit("@", 1)[-1] if "@" in self.account_email else None
        rfc_message_id = make_msgid(domain=domain)
        message["Message-ID"] = rfc_message_id
        body_text = str(body or "")
        message.set_content(body_text)
        html_body = html.escape(body_text).replace("\n", "<br>\n")
        message.add_alternative(f"<div>{html_body}</div>", subtype="html")
        maximum_attachments = max(1, int(self.env.get("VERIDEX_GMAIL_MAX_ATTACHMENT_MB", "20"))) * 1024 * 1024
        attachment_bytes = 0
        attachment_rows = [dict(row) for row in (attachments or [])]
        for attachment in attachment_rows:
            path = Path(str(attachment.get("path") or ""))
            filename = Path(str(attachment.get("name") or path.name or "attachment")).name
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise GmailGatewayError(f"Email attachment is unavailable: {filename}.") from exc
            attachment_bytes += len(content)
            if attachment_bytes > maximum_attachments:
                raise GmailGatewayError(
                    f"Email attachments exceed the {maximum_attachments // (1024 * 1024)} MB limit."
                )
            content_type = str(attachment.get("content_type") or "").split(";", 1)[0].strip().lower()
            if "/" not in content_type:
                content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            maintype, subtype = content_type.split("/", 1)
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
        message_bytes = message.as_bytes()
        maximum_message = max(1, int(self.env.get("VERIDEX_GMAIL_MAX_MESSAGE_MB", "25"))) * 1024 * 1024
        if len(message_bytes) > maximum_message:
            raise GmailGatewayError(f"The complete email exceeds the {maximum_message // (1024 * 1024)} MB limit.")
        raw = base64.urlsafe_b64encode(message_bytes).decode("ascii").rstrip("=")
        payload = json.dumps({"raw": raw}).encode("utf-8")
        access_token = self._access_token()
        result = self._json_request(
            f"{GMAIL_API}/messages/send",
            token=access_token,
            method="POST",
            data=payload,
            content_type="application/json",
        )
        try:
            rfc_message_id = self._gmail_rfc_message_id(str(result.get("id") or ""), access_token) or rfc_message_id
        except GmailGatewayError:
            # The message is already accepted. Keep the generated ID and allow
            # recipient/subject fallback correlation rather than report a false send failure.
            pass
        result["rfc_message_id"] = rfc_message_id
        try:
            self._record_outbound(
                rfc_message_id=rfc_message_id,
                result=result,
                recipients=recipients,
                subject=str(message["Subject"]),
                body=body_text,
                attachments=attachment_rows,
                context=dict(context or {}),
            )
        except (GmailGatewayError, sqlite3.Error) as exc:
            result["journal_warning"] = f"The email was accepted, but Veridex could not save delivery tracking: {exc}"
        return result
