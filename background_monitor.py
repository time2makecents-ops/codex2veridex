"""Background health checks and Nancy's important-mail alert store."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional


IMPORTANT_MAIL_QUERY = (
    'in:inbox newer_than:7d '
    '{offer counteroffer sold "payment received" "buyer question" "question from" "new message from" '
    '"security alert" "critical security alert" "new sign-in" "sign-in attempt" "new device" '
    '"password changed" "password reset" "suspicious activity" "unusual activity" '
    '"verification code" "security code" "2-step verification" "account recovery" '
    'from:(no-reply@accounts.google.com) from:(accounts-noreply@google.com)}'
)

_BUYER_QUESTION_RE = re.compile(
    r"\b(?:buyer question|question from|asked (?:a |you )?question|new message from|buyer message)\b",
    re.IGNORECASE,
)
_SOLD_RE = re.compile(
    r"\b(?:you sold|item sold|has sold|payment received|sale confirmed|order confirmed)\b",
    re.IGNORECASE,
)
_OFFER_RE = re.compile(r"\b(?:counteroffer|best offer|new offer|sent you an offer|offer received)\b", re.IGNORECASE)
_SECURITY_ALERT_RE = re.compile(
    r"\b(?:critical security alert|security alert|new sign[ -]in|sign[ -]in attempt|"
    r"blocked sign[ -]in|new (?:device|login)|password (?:was )?(?:changed|reset)|"
    r"suspicious (?:activity|sign[ -]in|login)|unusual (?:activity|sign[ -]in|login)|"
    r"verification code|security code|2[ -]step verification|two[ -]factor authentication|"
    r"account recovery|recovery (?:email|phone)(?: was)? changed)\b",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def important_mail_category(message: Dict[str, Any]) -> str:
    """Classify only the marketplace mail categories requested by the operator."""
    value = " ".join(
        str(message.get(key) or "")
        for key in ("subject", "snippet")
    )
    if _SECURITY_ALERT_RE.search(value):
        return "security"
    if _BUYER_QUESTION_RE.search(value):
        return "buyer_question"
    if _SOLD_RE.search(value):
        return "sold"
    if _OFFER_RE.search(value):
        return "offer"
    return ""


class MonitorStore:
    """Workspace-local monitor evidence and Nancy alert persistence."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.path = self.workspace_dir / "integrations" / "background_monitor.db"
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS health_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    issue_signature TEXT NOT NULL,
                    issues_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mail_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    discovered INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS important_mail_alerts (
                    alert_id TEXT PRIMARY KEY,
                    account_scope TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    seen_at TEXT,
                    dismissed_at TEXT,
                    UNIQUE(account_scope, account_email, message_id)
                );
                CREATE INDEX IF NOT EXISTS important_mail_visible
                ON important_mail_alerts(dismissed_at, seen_at, discovered_at);
                """
            )

    def record_health(self, started_at: str, issues: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = [
            {
                "service": str(issue.get("service") or "Veridex")[:80],
                "summary": str(issue.get("summary") or "A check needs attention.")[:500],
            }
            for issue in issues
        ]
        signature_source = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest() if normalized else ""
        row = {
            "run_id": f"health_{uuid.uuid4().hex}",
            "started_at": started_at,
            "completed_at": utc_now(),
            "status": "attention" if normalized else "healthy",
            "issue_signature": signature,
            "issues": normalized,
        }
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO health_runs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["run_id"], row["started_at"], row["completed_at"], row["status"],
                    row["issue_signature"], json.dumps(row["issues"], ensure_ascii=False),
                ),
            )
            connection.commit()
        return row

    def record_mail_run(self, started_at: str, errors: Iterable[str], discovered: int) -> Dict[str, Any]:
        bounded_errors = [str(value)[:500] for value in errors if str(value).strip()]
        row = {
            "run_id": f"mail_{uuid.uuid4().hex}",
            "started_at": started_at,
            "completed_at": utc_now(),
            "status": "limited" if bounded_errors else "complete",
            "errors": bounded_errors,
            "discovered": int(discovered),
        }
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO mail_runs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["run_id"], row["started_at"], row["completed_at"], row["status"],
                    json.dumps(row["errors"], ensure_ascii=False), row["discovered"],
                ),
            )
            connection.commit()
        return row

    def add_messages(
        self,
        account_scope: str,
        account_email: str,
        messages: Iterable[Dict[str, Any]],
    ) -> int:
        discovered = 0
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            for message in messages:
                category = important_mail_category(message)
                message_id = str(message.get("id") or "").strip()
                if not category or not message_id:
                    continue
                identity = f"{account_scope}\0{account_email.lower()}\0{message_id}"
                alert_id = "mail_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO important_mail_alerts (
                        alert_id, account_scope, account_email, message_id, category, sender,
                        subject, received_at, snippet, discovered_at, seen_at, dismissed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        alert_id, str(account_scope), str(account_email)[:254], message_id[:256], category,
                        str(message.get("from") or "Unknown sender")[:500],
                        str(message.get("subject") or "(no subject)")[:500],
                        str(message.get("date") or "")[:200],
                        str(message.get("snippet") or "")[:1000], now,
                    ),
                )
                discovered += int(cursor.rowcount or 0)
            connection.commit()
        return discovered

    def mark_seen(self, alert_ids: Iterable[str]) -> int:
        ids = sorted({str(value).strip() for value in alert_ids if str(value).strip()})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                f"UPDATE important_mail_alerts SET seen_at = COALESCE(seen_at, ?) WHERE dismissed_at IS NULL AND alert_id IN ({placeholders})",
                [utc_now(), *ids],
            )
            connection.commit()
            return int(cursor.rowcount or 0)

    def dismiss(self, alert_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE important_mail_alerts SET dismissed_at = ?, seen_at = COALESCE(seen_at, ?) WHERE alert_id = ? AND dismissed_at IS NULL",
                (utc_now(), utc_now(), str(alert_id or "").strip()),
            )
            connection.commit()
            return bool(cursor.rowcount)

    @staticmethod
    def _json_list(value: str) -> list[Any]:
        try:
            parsed = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            parsed = []
        return parsed if isinstance(parsed, list) else []

    def status(self) -> Dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            health = connection.execute("SELECT * FROM health_runs ORDER BY completed_at DESC LIMIT 1").fetchone()
            mail = connection.execute("SELECT * FROM mail_runs ORDER BY completed_at DESC LIMIT 1").fetchone()
            alerts = connection.execute(
                "SELECT * FROM important_mail_alerts WHERE dismissed_at IS NULL ORDER BY discovered_at DESC, alert_id DESC"
            ).fetchall()
        public_alerts = [
            {
                "alert_id": row["alert_id"],
                "account_scope": row["account_scope"],
                "account_email": row["account_email"],
                "category": row["category"],
                "from": row["sender"],
                "subject": row["subject"],
                "date": row["received_at"],
                "snippet": row["snippet"],
                "discovered_at": row["discovered_at"],
                "seen": bool(row["seen_at"]),
            }
            for row in alerts
        ]
        return {
            "health": {
                "status": str(health["status"] if health else "pending"),
                "checked_at": str(health["completed_at"] if health else ""),
                "issue_signature": str(health["issue_signature"] if health else ""),
                "issues": self._json_list(health["issues_json"]) if health else [],
            },
            "mail": {
                "status": str(mail["status"] if mail else "pending"),
                "checked_at": str(mail["completed_at"] if mail else ""),
                "errors": self._json_list(mail["errors_json"]) if mail else [],
                "unseen_count": sum(1 for row in public_alerts if not row["seen"]),
                "alerts": public_alerts,
            },
        }


class BackgroundMonitor:
    """Run bounded provider checks without blocking the browser UI."""

    def __init__(
        self,
        *,
        data_root: Path,
        workspace_rows: Callable[[], Iterable[Dict[str, Any]]],
        accounts: Any,
        shared_gmail: Callable[[], Any],
        facebook_status: Callable[[], Dict[str, Any]],
        instagram_status: Callable[..., Dict[str, Any]],
        ebay_poller_status: Callable[[str], Dict[str, Any]],
        core_check: Callable[[str], Iterable[Dict[str, Any]]],
        mail_interval_seconds: int = 3600,
        health_interval_seconds: int = 1800,
        now_fn: Callable[[], str] = utc_now,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.workspace_rows = workspace_rows
        self.accounts = accounts
        self.shared_gmail = shared_gmail
        self.facebook_status = facebook_status
        self.instagram_status = instagram_status
        self.ebay_poller_status = ebay_poller_status
        self.core_check = core_check
        self.mail_interval_seconds = max(60, int(mail_interval_seconds))
        self.health_interval_seconds = max(60, int(health_interval_seconds))
        self.now_fn = now_fn
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()

    def _workspace_ids(self) -> list[str]:
        return [
            str(row.get("workspace_id") or "").strip()
            for row in self.workspace_rows()
            if str(row.get("workspace_id") or "").strip()
        ]

    def store(self, workspace_id: str) -> MonitorStore:
        workspace_dir = (self.data_root / "workspaces" / str(workspace_id or "")).resolve()
        if self.data_root not in workspace_dir.parents or not (workspace_dir / "workspace.json").is_file():
            raise KeyError("Unknown workspace")
        return MonitorStore(workspace_dir)

    @staticmethod
    def _issue(service: str, summary: str) -> Dict[str, str]:
        return {"service": str(service), "summary": str(summary)[:500]}

    @staticmethod
    def _probe_gmail(gmail: Any, label: str) -> list[Dict[str, str]]:
        status = gmail.connection_status()
        if not status.get("configured"):
            return [BackgroundMonitor._issue(label, "Gmail is not configured.")]
        if not status.get("connected"):
            return [BackgroundMonitor._issue(label, "Gmail authorization needs attention.")]
        try:
            gmail.search("in:inbox newer_than:1d", max_results=1)
        except Exception as exc:
            return [BackgroundMonitor._issue(label, f"Gmail read check failed: {exc}")]
        return []

    def poll_health_once(self) -> Dict[str, int]:
        workspace_ids = self._workspace_ids()
        shared_issues: list[Dict[str, str]] = []
        try:
            shared_issues = self._probe_gmail(self.shared_gmail(), "VeridexCorp Gmail")
        except Exception as exc:
            shared_issues = [self._issue("VeridexCorp Gmail", f"Gmail check failed: {exc}")]
        facebook_issues: list[Dict[str, str]] = []
        try:
            facebook = self.facebook_status()
            if facebook.get("configured") and not facebook.get("chrome_debugging"):
                facebook_issues.append(self._issue("Facebook", "The dedicated Facebook browser session is not running."))
            elif facebook.get("configured") and not facebook.get("signed_in"):
                facebook_issues.append(self._issue("Facebook", "The dedicated Facebook session is not signed in."))
        except Exception as exc:
            facebook_issues.append(self._issue("Facebook", f"Facebook status check failed: {exc}"))

        attention = 0
        for workspace_id in workspace_ids:
            started_at = self.now_fn()
            issues = list(self.core_check(workspace_id)) + shared_issues + facebook_issues
            try:
                config = self.accounts.read(workspace_id)
                gmail_config = config.get("gmail") if isinstance(config.get("gmail"), dict) else {}
                if gmail_config.get("assigned"):
                    issues.extend(self._probe_gmail(self.accounts.gmail(workspace_id), "Workspace Gmail"))
                ebay_config = config.get("ebay") if isinstance(config.get("ebay"), dict) else {}
                if ebay_config.get("assigned"):
                    ebay = self.accounts.ebay(workspace_id)
                    status = ebay.connection_status()
                    if not status.get("connected"):
                        issues.append(self._issue("eBay", "The assigned eBay account needs authorization."))
                    else:
                        try:
                            ebay.seller_listings(page=1, per_page=1)
                        except Exception as exc:
                            issues.append(self._issue("eBay", f"Seller read check failed: {exc}"))
                    poller = self.ebay_poller_status(workspace_id)
                    if poller.get("error"):
                        issues.append(self._issue("eBay notifications", str(poller.get("error"))))
                instagram_config = config.get("instagram") if isinstance(config.get("instagram"), dict) else {}
                if instagram_config.get("assigned"):
                    try:
                        instagram = self.instagram_status(env=self.accounts.instagram_env(workspace_id))
                        if not instagram.get("chrome_debugging"):
                            issues.append(self._issue("Instagram", "The dedicated Instagram browser session is not running."))
                        elif not instagram.get("signed_in"):
                            issues.append(self._issue("Instagram", "The dedicated Instagram session is not signed in."))
                        elif instagram.get("account_matches") is False:
                            issues.append(self._issue("Instagram", "Instagram is signed in to a different account."))
                    except Exception as exc:
                        issues.append(self._issue("Instagram", f"Instagram status check failed: {exc}"))
            except Exception as exc:
                issues.append(self._issue("Connected accounts", f"Account health check failed: {exc}"))
            self.store(workspace_id).record_health(started_at, issues)
            attention += int(bool(issues))
        return {"workspaces": len(workspace_ids), "attention": attention}

    @staticmethod
    def _read_important(gmail: Any) -> tuple[str, list[Dict[str, Any]]]:
        status = gmail.connection_status()
        if not status.get("connected"):
            raise RuntimeError("Gmail authorization needs attention.")
        return str(status.get("account_email") or ""), gmail.search(IMPORTANT_MAIL_QUERY, max_results=25)

    def poll_mail_once(self) -> Dict[str, int]:
        workspace_ids = self._workspace_ids()
        shared_email = ""
        shared_messages: list[Dict[str, Any]] = []
        shared_error = ""
        try:
            shared_email, shared_messages = self._read_important(self.shared_gmail())
        except Exception as exc:
            shared_error = f"VeridexCorp Gmail: {exc}"
        total_discovered = 0
        for workspace_id in workspace_ids:
            started_at = self.now_fn()
            store = self.store(workspace_id)
            errors = [shared_error] if shared_error else []
            discovered = store.add_messages("shared", shared_email, shared_messages) if shared_messages else 0
            try:
                config = self.accounts.read(workspace_id)
                gmail_config = config.get("gmail") if isinstance(config.get("gmail"), dict) else {}
                if gmail_config.get("assigned"):
                    email, messages = self._read_important(self.accounts.gmail(workspace_id))
                    discovered += store.add_messages("workspace", email, messages)
            except Exception as exc:
                errors.append(f"Workspace Gmail: {exc}")
            store.record_mail_run(started_at, errors, discovered)
            total_discovered += discovered
        return {"workspaces": len(workspace_ids), "discovered": total_discovered}

    def status(self, workspace_id: str) -> Dict[str, Any]:
        return self.store(workspace_id).status()

    def mark_seen(self, workspace_id: str, alert_ids: Iterable[str]) -> Dict[str, Any]:
        self.store(workspace_id).mark_seen(alert_ids)
        return self.status(workspace_id)

    def dismiss(self, workspace_id: str, alert_id: str) -> Dict[str, Any]:
        if not self.store(workspace_id).dismiss(alert_id):
            raise KeyError("Unknown mail alert")
        return self.status(workspace_id)

    def start(self) -> bool:
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(target=self._run, name="veridex-background-monitor", daemon=True)
            self._thread.start()
        return True

    def stop(self, timeout: float = 35.0) -> bool:
        self._stop.set()
        self._wake.set()
        with self._thread_lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        return thread is None or not thread.is_alive()

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        next_mail = 0.0
        next_health = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_mail:
                try:
                    self.poll_mail_once()
                except Exception:
                    pass
                next_mail = time.monotonic() + self.mail_interval_seconds
            if self._stop.is_set():
                break
            now = time.monotonic()
            if now >= next_health:
                try:
                    self.poll_health_once()
                except Exception:
                    pass
                next_health = time.monotonic() + self.health_interval_seconds
            timeout = max(1.0, min(next_mail, next_health) - time.monotonic())
            woke = self._wake.wait(timeout)
            self._wake.clear()
            if woke:
                next_mail = 0.0
                next_health = 0.0
