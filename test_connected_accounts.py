import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connected_accounts import ConnectedAccountError, ConnectedAccounts


class ConnectedAccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for workspace_id in ("ws_one", "ws_two"):
            folder = self.data / "workspaces" / workspace_id
            folder.mkdir(parents=True)
            (folder / "workspace.json").write_text(json.dumps({"workspace_id": workspace_id}), encoding="utf-8")
        self.accounts = ConnectedAccounts(self.data, self.repo)

    def tearDown(self):
        self.temp.cleanup()

    def test_instagram_assignment_is_workspace_scoped_and_has_no_password(self):
        row = self.accounts.assign_instagram("ws_one", "@provenancepending")
        self.assertEqual(row["username"], "provenancepending")
        self.assertIn("ws_one", row["profile_dir"])
        stored = self.accounts.read("ws_one")
        self.assertNotIn("password", stored["instagram"])
        self.assertEqual(self.accounts.instagram_config("ws_two"), {})

    def test_same_instagram_account_cannot_be_assigned_twice(self):
        self.accounts.assign_instagram("ws_one", "provenancepending")
        with self.assertRaisesRegex(ConnectedAccountError, "already assigned"):
            self.accounts.assign_instagram("ws_two", "ProvenancePending")

    def test_gmail_database_is_unique_per_workspace(self):
        first = self.accounts.gmail_env("ws_one")
        second = self.accounts.gmail_env("ws_two")
        self.assertNotEqual(first["VERIDEX_GMAIL_DB_PATH"], second["VERIDEX_GMAIL_DB_PATH"])
        self.assertIn("ws_one", first["VERIDEX_GMAIL_DB_PATH"])

    def test_shared_gmail_is_global_and_separate_from_workspace_databases(self):
        with patch("connected_accounts._default_env", return_value={"VERIDEX_GOOGLE_ACCOUNT": "corp@example.com"}):
            shared = self.accounts.shared_gmail_env()
        workspace = self.accounts.gmail_env("ws_one")

        self.assertEqual(shared["VERIDEX_GOOGLE_ACCOUNT"], "corp@example.com")
        self.assertEqual(
            Path(shared["VERIDEX_GMAIL_DB_PATH"]).resolve(),
            (self.data / "integrations" / "gmail.db").resolve(),
        )
        self.assertNotEqual(shared["VERIDEX_GMAIL_DB_PATH"], workspace["VERIDEX_GMAIL_DB_PATH"])

    def test_shared_gmail_cannot_be_claimed_by_one_workspace(self):
        with patch("connected_accounts._default_env", return_value={"VERIDEX_GOOGLE_ACCOUNT": "corp@example.com"}):
            with self.assertRaisesRegex(ConnectedAccountError, "shared Veridex corporate account"):
                self.accounts.assign_gmail("ws_one", "Corp@Example.com")

    def test_public_status_reports_workspace_and_shared_gmail_separately(self):
        self.accounts.assign_gmail("ws_one", "workspace@example.com")
        status = self.accounts.public_status(
            "ws_one",
            shared_gmail_status={
                "configured": True,
                "connected": True,
                "account_email": "corp@example.com",
            },
        )

        self.assertEqual(status["isolation"], "workspace_accounts_plus_shared_corporate_services")
        self.assertEqual(status["gmail"]["account_email"], "workspace@example.com")
        self.assertEqual(status["shared"]["scope"], "all_workspaces")
        self.assertEqual(status["shared"]["gmail"]["account_email"], "corp@example.com")

    def test_ebay_assignment_is_workspace_scoped_and_has_no_credentials(self):
        row = self.accounts.assign_ebay("ws_one", "seller-one", environment="sandbox")
        self.assertEqual(row["username"], "seller-one")
        stored = self.accounts.read("ws_one")["ebay"]
        self.assertNotIn("client_secret", stored)
        self.assertNotIn("access_token", stored)
        first = self.accounts.ebay_env("ws_one")
        second = self.accounts.ebay_env("ws_two")
        self.assertNotEqual(first["VERIDEX_EBAY_DB_PATH"], second["VERIDEX_EBAY_DB_PATH"])
        self.assertNotEqual(
            first["VERIDEX_EBAY_NOTIFICATIONS_DB_PATH"],
            second["VERIDEX_EBAY_NOTIFICATIONS_DB_PATH"],
        )
        self.assertIn("ws_one", first["VERIDEX_EBAY_DB_PATH"])
        self.assertIn("ws_one", first["VERIDEX_EBAY_NOTIFICATIONS_DB_PATH"])

    def test_same_ebay_account_cannot_be_assigned_twice(self):
        self.accounts.assign_ebay("ws_one", "seller-one", environment="production")
        with self.assertRaisesRegex(ConnectedAccountError, "already assigned"):
            self.accounts.assign_ebay("ws_two", "Seller-One", environment="production")

    def test_assigned_ebay_workspace_ids_include_only_valid_explicit_assignments(self):
        self.accounts.assign_ebay("ws_two", "seller-two", environment="production")
        invalid = self.data / "workspaces" / "not-a-workspace"
        (invalid / "integrations").mkdir(parents=True)
        (invalid / "integrations" / "connected_accounts.json").write_text(
            json.dumps({"ebay": {"assigned": True, "username": "ignored"}}),
            encoding="utf-8",
        )

        self.assertEqual(self.accounts.assigned_ebay_workspace_ids(), ["ws_two"])
        self.assertEqual(self.accounts.automatic_ebay_workspace_ids(), ["ws_two"])
        self.assertTrue(self.accounts.ebay_automatic_notifications_enabled("ws_two"))
        self.accounts.set_ebay_automatic_notifications("ws_two", False)
        self.assertFalse(self.accounts.ebay_automatic_notifications_enabled("ws_two"))
        self.assertEqual(self.accounts.assigned_ebay_workspace_ids(), ["ws_two"])
        self.assertEqual(self.accounts.automatic_ebay_workspace_ids(), [])
        self.accounts.set_ebay_automatic_notifications("ws_two", True)
        self.assertEqual(self.accounts.automatic_ebay_workspace_ids(), ["ws_two"])

    def test_unknown_workspace_is_rejected(self):
        with self.assertRaisesRegex(ConnectedAccountError, "Unknown workspace"):
            self.accounts.read("ws_missing")


if __name__ == "__main__":
    unittest.main()
