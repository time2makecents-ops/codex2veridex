from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ebay_room import EbayRoom, EbayRoomError
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

    @patch.object(EbayRoom, "_download_photo", return_value=(b"image-bytes", "image/jpeg", ".jpg"))
    def test_workspace_listing_lookup_populates_item_and_extracts_media(self, _download) -> None:
        applied = self.room.populate_item_from_listing(
            FakeGateway(), self.item["item_id"], "https://www.ebay.com/itm/137876850352", extract_media=True
        )
        self.assertEqual(applied["listing"]["listing_id"], "137876850352")
        self.assertEqual(applied["item"]["title"], "Signed lava photograph")
        self.assertEqual(applied["item"]["reference_id"], "137876850352")
        self.assertEqual(applied["imported_photo_count"], 1)
        self.assertEqual(self.room.board()["unmatched"], [])

    def test_channel_draft_stays_linked_to_master_item(self) -> None:
        draft = self.room.save_draft(self.item["item_id"], "facebook", {"price": 100})
        self.assertEqual(draft["channel"], "facebook")
        board_item = next(row for row in self.room.board()["items"] if row["item_id"] == self.item["item_id"])
        self.assertEqual(board_item["channel_drafts"][0]["draft_id"], draft["draft_id"])

    def test_item_markets_include_defaults_and_added_preset_or_custom_tabs(self) -> None:
        defaults = self.room.item_markets(self.item["item_id"])
        self.assertEqual([row["market_id"] for row in defaults], ["craigslist", "facebook", "ebay", "etsy"])
        preset = self.room.add_item_market(self.item["item_id"], preset="mercari")
        custom = self.room.add_item_market(self.item["item_id"], name="My Local Auction")
        self.assertEqual(preset["market_id"], "mercari")
        self.assertEqual(custom["market_id"], "custom-my-local-auction")
        self.assertEqual(len(self.room.item_markets(self.item["item_id"])), 6)

    def test_added_market_can_save_a_photo_bound_draft(self) -> None:
        self.room.add_item_market(self.item["item_id"], preset="offerup")
        draft = self.room.save_draft(self.item["item_id"], "offerup", {"title": "OfferUp title"})
        self.assertEqual(draft["channel"], "offerup")
        self.assertEqual(draft["payload"]["title"], "OfferUp title")

    def test_facebook_groups_store_rules_and_item_targets(self) -> None:
        group = self.room.save_facebook_group({
            "name": "Hawaii Vintage Collectors", "rules_text": "No commercial spam.", "eligibility_status": "needs_requirements",
            "facebook_access_status": "joined", "facebook_access_detail": "Facebook shows the account as joined.",
            "facebook_access_checked_at": "2026-10-30T13:00:00Z",
            "privacy_text": "Private\nOnly members can see posts.", "visibility_text": "Visible\nAnyone can find this group.",
            "history_text": "Group created on July 11, 2012", "tags_text": "Fashion\nKids Clothing & Accessories", "location_text": "Eugene, Oregon",
            "membership_status": "pending", "membership_status_source": "manual",
        })
        self.assertEqual(group["eligibility_status"], "needs_requirements")
        self.assertEqual(group["facebook_access_status"], "joined")
        target = self.room.set_group_target(self.item["item_id"], group["group_id"], status="planned", note="Ask admin before posting")
        self.assertTrue(target["targeted"])
        saved = self.room.facebook_groups(self.item["item_id"])[0]
        self.assertTrue(saved["targeted"])
        self.assertEqual(saved["target"]["note"], "Ask admin before posting")
        self.assertEqual(saved["facebook_access_detail"], "Facebook shows the account as joined.")
        self.assertEqual(saved["location_text"], "Eugene, Oregon")
        self.assertEqual(saved["membership_status"], "pending")
        self.assertEqual(saved["membership_status_source"], "manual")
        self.assertEqual(saved["target_items"][0]["title"], "Existing photograph")
        self.assertIn("rules_text", self.room.group_context(self.item["item_id"])[0])

    def test_group_cannot_be_marked_ready_without_completed_eligibility_review(self) -> None:
        group = self.room.save_facebook_group({"name": "Unreviewed group", "url": "https://www.facebook.com/groups/example/"})
        with self.assertRaisesRegex(EbayRoomError, "Complete the group review"):
            self.room.set_group_target(self.item["item_id"], group["group_id"], status="ready")

        complete = self.room.save_facebook_group({
            "group_id": group["group_id"], "name": "Unreviewed group", "url": "https://www.facebook.com/groups/example/",
            "description": "Local collectors.", "rules_text": "No spam.", "requirements_text": "Add a price.",
            "allowed_item_types": "Collectibles only.", "eligibility_status": "eligible",
        })
        target = self.room.set_group_target(self.item["item_id"], complete["group_id"], status="ready")
        self.assertEqual(target["status"], "ready")

    def test_group_post_tracker_records_manual_post_status_changes(self) -> None:
        group = self.room.save_facebook_group({
            "name": "Quota group", "url": "https://www.facebook.com/groups/quota/", "description": "Local group.",
            "rules_text": "Price required.", "requirements_text": "One post per day.", "allowed_item_types": "Collectibles.",
            "eligibility_status": "eligible", "posting_limit": 1, "posting_limit_period": "per_day",
        })
        self.room.set_group_target(self.item["item_id"], group["group_id"], status="posted")
        tracked = next(row for row in self.room.facebook_groups(self.item["item_id"]) if row["group_id"] == group["group_id"])
        self.assertEqual(tracked["post_tracking"]["active_posts"], 1)
        self.assertEqual(tracked["post_tracking"]["posts_today"], 1)
        self.assertEqual(tracked["post_tracking"]["limit"], 1)
        self.assertEqual(tracked["post_events"][0]["title"], "Existing photograph")
        self.room.set_group_target(self.item["item_id"], group["group_id"], status="planned")
        tracked = next(row for row in self.room.facebook_groups(self.item["item_id"]) if row["group_id"] == group["group_id"])
        self.assertEqual(tracked["post_tracking"]["active_posts"], 0)
        self.assertEqual(tracked["post_tracking"]["posts_today"], 1)
        another = self.intake.create_item({"batch_id": self.batch["batch_id"], "title": "Second photograph"})
        with self.assertRaisesRegex(EbayRoomError, "Posting limit reached"):
            self.room.set_group_target(another["item_id"], group["group_id"], status="posted")

    def test_group_target_retains_an_optional_post_link(self) -> None:
        group = self.room.save_facebook_group({"name": "Linked post group"})
        target = self.room.set_group_target(
            self.item["item_id"], group["group_id"], status="planned", post_url="https://www.facebook.com/groups/example/posts/123/"
        )
        self.assertEqual(target["post_url"], "https://www.facebook.com/groups/example/posts/123/")
        saved = next(row for row in self.room.facebook_groups(self.item["item_id"]) if row["group_id"] == group["group_id"])
        self.assertEqual(saved["target"]["post_url"], target["post_url"])
        self.assertEqual(saved["target_items"][0]["post_url"], target["post_url"])

    def test_explicit_rule_limit_is_detected_when_saved(self) -> None:
        group = self.room.save_facebook_group({"name": "Rule group", "rules_text": "No more than 2 posts per day. Include a firm price. No bidding. Delete sold posts."})
        self.assertEqual(group["posting_limit"], 2)
        self.assertEqual(group["posting_limit_period"], "per_day")
        saved = next(row for row in self.room.facebook_groups() if row["group_id"] == group["group_id"])
        self.assertIn("Include a price.", saved["rule_guidance"])
        self.assertIn("Do not use bidding language.", saved["rule_guidance"])
        self.assertEqual(saved["posting_recommendation"]["status"], "needs_review")

    def test_group_visible_items_and_follow_ups_are_retained(self) -> None:
        group = self.room.save_facebook_group({
            "name": "Pending group", "membership_status": "pending", "membership_status_source": "observed",
            "facebook_visible_items_count": 2, "facebook_visible_items": ["Lamp — $15", "Chair — $20", "Lamp — $15"],
        })
        saved = next(row for row in self.room.facebook_groups() if row["group_id"] == group["group_id"])
        self.assertEqual(len(saved["facebook_visible_items"]), 2)
        self.assertEqual(saved["follow_up"]["kind"], "membership")

    def test_manual_active_posts_enforce_an_active_total_limit(self) -> None:
        group = self.room.save_facebook_group({
            "name": "Active quota", "url": "https://www.facebook.com/groups/activequota/", "description": "Local.", "rules_text": "One active post at a time.",
            "requirements_text": "Price.", "allowed_item_types": "Collectibles.", "eligibility_status": "eligible",
            "posting_limit": 1, "posting_limit_period": "active_total", "manual_active_posts": 1,
        })
        with self.assertRaisesRegex(EbayRoomError, "Posting limit reached"):
            self.room.set_group_target(self.item["item_id"], group["group_id"], status="posted")

    def test_ebay_draft_uses_the_ordered_listing_photo_set(self) -> None:
        first = self.intake.add_asset(self.item["item_id"], "front.jpg", b"front", "image/jpeg", "photo")
        second = self.intake.add_asset(self.item["item_id"], "detail.jpg", b"detail", "image/jpeg", "photo")
        self.intake.set_listing_photos(self.item["item_id"], [second["asset_id"], first["asset_id"]])

        draft = self.room.save_draft(self.item["item_id"], "ebay", {})

        self.assertEqual(draft["payload"]["photo_asset_ids"], [second["asset_id"], first["asset_id"]])

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
