from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ebay_room import EbayRoom
from seller_intake import SellerIntakeCatalog


class FakeGateway:
    def seller_listings(self, *, page: int, per_page: int) -> dict:
        return {
            "listings": [{
                "listing_id": "137876850352",
                "title": "Signed lava photograph",
                "sku": "",
                "status": "active",
                "price": "425.00",
                "currency": "USD",
                "quantity": 1,
                "quantity_sold": 0,
                "listing_url": "https://www.ebay.com/itm/137876850352",
                "picture_urls": ["https://i.ebayimg.com/example.jpg"],
            }]
        }

    def get_item(self, listing_id: str) -> dict:
        return {
            "listing_id": listing_id,
            "seller_username": "seller",
            "title": "Signed lava photograph",
            "description": "Framed and signed in gold ink.",
            "sku": "",
            "price": "425.00",
            "currency": "USD",
            "quantity": 1,
            "quantity_sold": 0,
            "listing_url": f"https://www.ebay.com/itm/{listing_id}",
            "picture_urls": ["https://i.ebayimg.com/example.jpg"],
        }


class EbayRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.intake = SellerIntakeCatalog(self.root / "global")
        self.room = EbayRoom(self.root / "workspace", self.intake)
        self.batch = self.intake.create_batch({"title": "Inventory"})
        self.item = self.intake.create_item({"batch_id": self.batch["batch_id"], "title": "Existing photograph"})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sync_keeps_listing_unmatched_until_reviewed_link(self) -> None:
        result = self.room.sync(FakeGateway())
        self.assertEqual(result["listing_count"], 1)
        board = self.room.board()
        self.assertEqual(board["unmatched"][0]["listing_id"], "137876850352")
        self.room.link(board["unmatched"][0], self.item["item_id"])
        linked = self.room.board()
        self.assertEqual(linked["unmatched"], [])
        self.assertEqual(linked["items"][0]["board_state"], "listed")

    @patch.object(EbayRoom, "_download_photo", return_value=(b"image-bytes", "image/jpeg", ".jpg"))
    def test_confirmed_import_copies_photos_and_links_item(self, _download) -> None:
        imported = self.room.import_listing(FakeGateway(), "https://www.ebay.com/itm/137876850352")
        self.assertEqual(imported["imported_photo_count"], 1)
        self.assertEqual(imported["item"]["reference_id"], "137876850352")
        self.assertEqual(imported["item"]["assets"][0]["role"], "photo")
        self.assertEqual(self.room.board()["unmatched"], [])

    def test_channel_draft_stays_linked_to_master_item(self) -> None:
        draft = self.room.save_draft(self.item["item_id"], "facebook", {"price": 100})
        self.assertEqual(draft["channel"], "facebook")
        board_item = next(row for row in self.room.board()["items"] if row["item_id"] == self.item["item_id"])
        self.assertEqual(board_item["channel_drafts"][0]["draft_id"], draft["draft_id"])

    def test_board_can_be_scoped_to_one_named_list_without_item_photos(self) -> None:
        other_batch = self.intake.create_batch({"title": "Later listings"})
        other = self.intake.create_item({"batch_id": other_batch["batch_id"], "title": "Second item"})
        board = self.room.board(other_batch["batch_id"])
        self.assertEqual(board["batch_id"], other_batch["batch_id"])
        self.assertEqual([row["item_id"] for row in board["items"]], [other["item_id"]])
        self.assertNotIn("assets", board["items"][0])

    def test_listing_id_accepts_item_url_and_rejects_other_values(self) -> None:
        self.assertEqual(EbayRoom.listing_id("https://www.ebay.com/itm/137876850352"), "137876850352")
        with self.assertRaisesRegex(Exception, "item number"):
            EbayRoom.listing_id("not-a-listing")


if __name__ == "__main__":
    unittest.main()
