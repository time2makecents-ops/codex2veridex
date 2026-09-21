import json
import tempfile
import unittest
from pathlib import Path

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

    def test_ebay_assignment_is_workspace_scoped_and_has_no_credentials(self):
        row = self.accounts.assign_ebay("ws_one", "seller-one", environment="sandbox")
        self.assertEqual(row["username"], "seller-one")
        stored = self.accounts.read("ws_one")["ebay"]
        self.assertNotIn("client_secret", stored)
        self.assertNotIn("access_token", stored)
        first = self.accounts.ebay_env("ws_one")
        second = self.accounts.ebay_env("ws_two")
        self.assertNotEqual(first["VERIDEX_EBAY_DB_PATH"], second["VERIDEX_EBAY_DB_PATH"])
        self.assertIn("ws_one", first["VERIDEX_EBAY_DB_PATH"])

    def test_same_ebay_account_cannot_be_assigned_twice(self):
        self.accounts.assign_ebay("ws_one", "seller-one", environment="production")
        with self.assertRaisesRegex(ConnectedAccountError, "already assigned"):
            self.accounts.assign_ebay("ws_two", "Seller-One", environment="production")

    def test_unknown_workspace_is_rejected(self):
        with self.assertRaisesRegex(ConnectedAccountError, "Unknown workspace"):
            self.accounts.read("ws_missing")


if __name__ == "__main__":
    unittest.main()
