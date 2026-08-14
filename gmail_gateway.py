"""Small Gmail API gateway backed by the existing Office-App token store."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional


ROOT = Path(__file__).resolve().parent
OFFICE_APP_ENV = Path(r"C:\Office-App\.env.local")
OFFICE_APP_DB = Path(r"C:\Office-App\office_app\runtime\veridex.db")
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"


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
    _load_env_file(OFFICE_APP_ENV, values)
    _load_env_file(ROOT / ".env.local", values)
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


class TokenCipher:
    """Authenticated token storage compatible with Office-App."""

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
        self.db_path = Path(str(self.env.get("VERIDEX_GMAIL_DB_PATH") or OFFICE_APP_DB)).resolve()
        self.account_email = str(
            self.env.get("VERIDEX_GOOGLE_ACCOUNT")
            or self.env.get("GMAIL_ACCOUNT")
            or "veridexcorp@gmail.com"
        ).strip()
        if env is not None or self._is_repo_local_path(self.db_path):
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
            conn.execute(
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
                )
                """
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
            raise GmailGatewayError("Google Gmail is not connected. Reconnect veridexcorp@gmail.com in Office-App.")
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
                    "Google rejected the stored refresh token. Reconnect veridexcorp@gmail.com in Office-App, then try again."
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
                str(header.get("name") or "").lower(): str(header.get("value") or "")
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
                    "snippet": detail.get("snippet") or "",
                }
            )
        return results

    def send(self, to: Iterable[str], subject: str, body: str) -> Dict[str, Any]:
        recipients = [str(value).strip() for value in to if str(value).strip()]
        if not recipients:
            raise GmailGatewayError("At least one recipient is required.")
        message = EmailMessage()
        message["To"] = ", ".join(recipients)
        message["Subject"] = str(subject or "").strip() or "(no subject)"
        message.set_content(str(body or ""))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        payload = json.dumps({"raw": raw}).encode("utf-8")
        return self._json_request(
            f"{GMAIL_API}/messages/send",
            token=self._access_token(),
            method="POST",
            data=payload,
            content_type="application/json",
        )
