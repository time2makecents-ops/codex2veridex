from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import veridex_server
from facebook_marketplace import FacebookMarketplace
from veridex_core import VeridexStore


class FacebookMarketplaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.marketplace = FacebookMarketplace(Path(self.temporary.name))
        self.workspace_id = "ws_test"
        self.session_id = "session_test"
        self.photo = {
            "file_id": "file_one",
            "session_id": self.session_id,
            "name": "item.jpg",
            "content_type": "image/jpeg",
            "size": 12,
            "sha256": "a" * 64,
            "path": str(Path(self.temporary.name) / "private" / "item.jpg"),
        }

    def test_group_allowlist_normalizes_and_rejects_non_group_urls(self) -> None:
        group = self.marketplace.save_group(self.workspace_id, {
            "name": "Neighborhood sale",
            "url": "https://m.facebook.com/groups/neighborhood.sale/?ref=share",
        })
        self.assertEqual(group["url"], "https://www.facebook.com/groups/neighborhood.sale")
        with self.assertRaisesRegex(ValueError, "one Facebook group"):
            self.marketplace.save_group(self.workspace_id, {"url": "https://www.facebook.com/marketplace"})

    def test_draft_is_atomic_private_and_review_first(self) -> None:
        group = self.marketplace.save_group(self.workspace_id, {
            "name": "Neighborhood sale",
            "url": "https://www.facebook.com/groups/12345",
        })
        draft = self.marketplace.save_draft(
            self.workspace_id,
            self.session_id,
            {
                "title": "Oak side table",
                "description": "Solid oak table with light wear.",
                "category": "Furniture",
                "condition": "good",
                "price": "45.00",
                "group_ids": [group["group_id"], "fbgroup_not_allowed"],
            },
            [self.photo],
            price_suggestion={"amount": 48, "basis": "Two comparable sales."},
        )
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["fulfillment"], "local_pickup")
        self.assertEqual(draft["location_policy"], "facebook_existing")
        self.assertEqual(draft["group_ids"], [group["group_id"]])
        self.assertEqual(draft["price"], 45.0)
        self.assertNotIn("path", self.marketplace.public_draft(draft)["photos"][0])
        self.assertTrue(self.marketplace.drafts_path(self.workspace_id).is_file())
        self.assertGreater(self.marketplace.audit_path(self.workspace_id).stat().st_size, 0)

    def test_status_requires_known_state_and_preserves_listing_evidence(self) -> None:
        draft = self.marketplace.save_draft(
            self.workspace_id,
            self.session_id,
            {"title": "Lamp", "description": "Working lamp", "category": "Home", "condition": "good", "price": 20},
            [self.photo],
        )
        updated = self.marketplace.update_status(
            self.workspace_id,
            draft["draft_id"],
            "published_observed",
            result={"listing_url": "https://www.facebook.com/marketplace/item/123"},
        )
        self.assertEqual(updated["listing_url"], "https://www.facebook.com/marketplace/item/123")
        with self.assertRaisesRegex(ValueError, "status"):
            self.marketplace.update_status(self.workspace_id, draft["draft_id"], "published")

    def test_draft_rejects_unusable_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.marketplace.save_draft(
                self.workspace_id,
                self.session_id,
                {"title": "Lamp", "description": "Lamp", "category": "Home", "condition": "good", "price": 20},
                [],
            )
        with self.assertRaisesRegex(ValueError, "condition"):
            self.marketplace.save_draft(
                self.workspace_id,
                self.session_id,
                {"title": "Lamp", "description": "Lamp", "category": "Home", "condition": "unknown", "price": 20},
                [self.photo],
            )

    def test_server_reverifies_workspace_ledger_before_browser_handoff(self) -> None:
        store = VeridexStore(Path(self.temporary.name) / "runtime")
        workspace = store.create_workspace("Seller")
        session = store.create_session(workspace["workspace_id"], "Listings")
        saved = store.save_file(
            workspace["workspace_id"],
            session["session_id"],
            "item.jpg",
            b"\xff\xd8\xffverified-photo",
            "image/jpeg",
        )
        with patch.object(veridex_server, "STORE", store):
            verified = veridex_server._verified_marketplace_photos(workspace["workspace_id"], [saved["file_id"]])
            self.assertEqual(verified[0]["sha256"], saved["sha256"])
            self.assertEqual(verified[0]["path"], saved["path"])
            Path(saved["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "verification failed"):
                veridex_server._verified_marketplace_photos(workspace["workspace_id"], [saved["file_id"]])


if __name__ == "__main__":
    unittest.main()
