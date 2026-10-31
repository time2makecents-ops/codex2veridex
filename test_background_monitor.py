from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from background_monitor import BackgroundMonitor, MonitorStore, important_mail_category


class FakeGmail:
    def __init__(self, email: str, messages=None, *, connected: bool = True, configured: bool = True, error: str = "") -> None:
        self.email = email
        self.messages = list(messages or [])
        self.connected = connected
        self.configured = configured
        self.error = error
        self.queries = []

    def connection_status(self):
        return {"configured": self.configured, "connected": self.connected, "account_email": self.email}

    def search(self, query: str, max_results: int = 10):
        self.queries.append((query, max_results))
        if self.error:
            raise RuntimeError(self.error)
        return self.messages[:max_results]


class FakeEbay:
    def __init__(self, *, connected: bool = True, error: str = "") -> None:
        self.connected = connected
        self.error = error
        self.reads = 0

    def connection_status(self):
        return {"configured": True, "connected": self.connected}

    def seller_listings(self, *, page: int, per_page: int):
        self.reads += 1
        if self.error:
            raise RuntimeError(self.error)
        return {"listings": []}


class FakeAccounts:
    def __init__(self, configs, gmails, ebays=None) -> None:
        self.configs = configs
        self.gmails = gmails
        self.ebays = ebays or {}

    def read(self, workspace_id):
        return self.configs.get(workspace_id, {})

    def gmail(self, workspace_id):
        return self.gmails[workspace_id]

    def ebay(self, workspace_id):
        return self.ebays[workspace_id]

    def instagram_env(self, workspace_id):
        return {"workspace_id": workspace_id}


class BackgroundMonitorTests(unittest.TestCase):
    def make_workspace(self, root: Path, workspace_id: str = "ws_test") -> Path:
        workspace = root / "workspaces" / workspace_id
        workspace.mkdir(parents=True)
        (workspace / "workspace.json").write_text('{"workspace_id":"ws_test"}', encoding="utf-8")
        return workspace

    def test_important_mail_categories_are_bounded(self) -> None:
        self.assertEqual(important_mail_category({"subject": "You received a new offer"}), "offer")
        self.assertEqual(important_mail_category({"subject": "Your item sold"}), "sold")
        self.assertEqual(important_mail_category({"snippet": "A buyer question is waiting"}), "buyer_question")
        self.assertEqual(important_mail_category({"subject": "Critical security alert"}), "security")
        self.assertEqual(important_mail_category({"subject": "New sign-in on Windows"}), "security")
        self.assertEqual(important_mail_category({"snippet": "Your password was changed"}), "security")
        self.assertEqual(important_mail_category({"subject": "Weekly newsletter"}), "")

    def test_store_deduplicates_seen_and_dismissed_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.make_workspace(Path(temporary))
            store = MonitorStore(workspace)
            message = {"id": "m1", "from": "buyer@example.com", "subject": "New offer received", "date": "today", "snippet": "$100"}
            self.assertEqual(store.add_messages("workspace", "seller@example.com", [message]), 1)
            self.assertEqual(store.add_messages("workspace", "seller@example.com", [message]), 0)
            status = store.status()
            self.assertEqual(status["mail"]["unseen_count"], 1)
            alert_id = status["mail"]["alerts"][0]["alert_id"]
            store.mark_seen([alert_id])
            self.assertEqual(store.status()["mail"]["unseen_count"], 0)
            self.assertTrue(store.dismiss(alert_id))
            self.assertEqual(store.status()["mail"]["alerts"], [])

    def test_mail_poll_checks_shared_and_workspace_gmail_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_workspace(root)
            shared = FakeGmail("veridexcorp@gmail.com", [{"id": "s1", "subject": "Your item sold", "snippet": "Payment received"}])
            workspace = FakeGmail("provenancepending@gmail.com", [{"id": "w1", "subject": "Buyer question", "snippet": "Is this available?"}])
            accounts = FakeAccounts({"ws_test": {"gmail": {"assigned": True}}}, {"ws_test": workspace})
            monitor = BackgroundMonitor(
                data_root=root,
                workspace_rows=lambda: [{"workspace_id": "ws_test"}],
                accounts=accounts,
                shared_gmail=lambda: shared,
                facebook_status=lambda: {"configured": False},
                instagram_status=lambda **_: {},
                ebay_poller_status=lambda _: {},
                core_check=lambda _: [],
            )
            self.assertEqual(monitor.mail_interval_seconds, 3600)
            self.assertEqual(monitor.poll_mail_once()["discovered"], 2)
            self.assertEqual(monitor.poll_mail_once()["discovered"], 0)
            status = monitor.status("ws_test")
            self.assertEqual(status["mail"]["unseen_count"], 2)
            self.assertEqual({row["account_scope"] for row in status["mail"]["alerts"]}, {"shared", "workspace"})
            self.assertTrue(all("newer_than:7d" in query for query, _ in shared.queries + workspace.queries))
            self.assertTrue(all('"security alert"' in query for query, _ in shared.queries + workspace.queries))

    def test_health_poll_reports_core_and_provider_failures_without_launching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_workspace(root)
            shared = FakeGmail("veridexcorp@gmail.com")
            workspace = FakeGmail("provenancepending@gmail.com", error="token expired")
            ebay = FakeEbay(error="provider unavailable")
            accounts = FakeAccounts(
                {"ws_test": {"gmail": {"assigned": True}, "ebay": {"assigned": True}, "instagram": {"assigned": True}}},
                {"ws_test": workspace},
                {"ws_test": ebay},
            )
            instagram_calls = []
            monitor = BackgroundMonitor(
                data_root=root,
                workspace_rows=lambda: [{"workspace_id": "ws_test"}],
                accounts=accounts,
                shared_gmail=lambda: shared,
                facebook_status=lambda: {"configured": True, "chrome_debugging": False, "signed_in": False},
                instagram_status=lambda **kwargs: instagram_calls.append(kwargs) or {"chrome_debugging": False, "signed_in": False},
                ebay_poller_status=lambda _: {"error": "relay unavailable"},
                core_check=lambda _: [{"service": "Navigator", "summary": "Snapshot missing"}],
            )
            result = monitor.poll_health_once()
            self.assertEqual(result["attention"], 1)
            issues = monitor.status("ws_test")["health"]["issues"]
            services = {row["service"] for row in issues}
            self.assertTrue({"Navigator", "Facebook", "Workspace Gmail", "eBay", "eBay notifications", "Instagram"}.issubset(services))
            self.assertEqual(len(instagram_calls), 1)
            self.assertEqual(ebay.reads, 1)

    def test_health_poll_accepts_passive_instagram_session_without_observed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_workspace(root)
            accounts = FakeAccounts(
                {"ws_test": {"instagram": {"assigned": True}}},
                {},
            )
            monitor = BackgroundMonitor(
                data_root=root,
                workspace_rows=lambda: [{"workspace_id": "ws_test"}],
                accounts=accounts,
                shared_gmail=lambda: FakeGmail("veridexcorp@gmail.com"),
                facebook_status=lambda: {"configured": False},
                instagram_status=lambda **_: {
                    "chrome_debugging": True,
                    "signed_in": True,
                    "account_matches": None,
                    "identity_observed": False,
                },
                ebay_poller_status=lambda _: {},
                core_check=lambda _: [],
            )
            self.assertEqual(monitor.poll_health_once()["attention"], 0)
            self.assertEqual(monitor.status("ws_test")["health"]["issues"], [])


if __name__ == "__main__":
    unittest.main()
