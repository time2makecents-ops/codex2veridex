from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ebay_gateway import EbayGateway, EbayGatewayError
import veridex_server


class EbayGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = {
            "VERIDEX_EBAY_DB_PATH": str(self.root / "ebay.db"),
            "VERIDEX_INTEGRATION_ENCRYPTION_KEY": "x" * 48,
            "EBAY_CLIENT_ID": "client-id",
            "EBAY_CLIENT_SECRET": "client-secret",
            "EBAY_RUNAME": "Veridex-Test-RuName",
            "EBAY_REDIRECT_URI": "http://127.0.0.1:8079/integrations/ebay/callback",
            "EBAY_ENVIRONMENT": "sandbox",
            "EBAY_MARKETPLACE_ID": "EBAY_US",
        }
        self.gateway = EbayGateway(env=self.env, now_fn=lambda: "2026-09-19T12:00:00Z")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def listing(self) -> dict:
        return {
            "sku": "art-001",
            "title": "Vintage framed landscape",
            "description": "Framed landscape painting; artist unconfirmed.",
            "condition": "USED_GOOD",
            "quantity": 1,
            "image_urls": ["https://images.example.test/art-001.jpg"],
            "aspects": {"Type": "Painting", "Original/Licensed Reproduction": ["Original"]},
            "category_id": "551",
            "format": "FIXED_PRICE",
            "listing_duration": "GTC",
            "price": "125",
            "currency": "USD",
            "merchant_location_key": "home-studio",
            "payment_policy_id": "pay-1",
            "fulfillment_policy_id": "ship-1",
            "return_policy_id": "return-1",
        }

    def test_connection_tokens_are_encrypted_at_rest(self) -> None:
        status = self.gateway.save_connection(
            username="seller-one",
            access_token="plain-access-token",
            refresh_token="plain-refresh-token",
        )
        self.assertTrue(status["connected"])
        raw = Path(self.env["VERIDEX_EBAY_DB_PATH"]).read_bytes()
        self.assertNotIn(b"plain-access-token", raw)
        self.assertNotIn(b"plain-refresh-token", raw)

    def test_listing_preview_is_local_and_normalized(self) -> None:
        preview = self.gateway.preview_listing(self.listing())
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(preview["listing"]["price"], "125.00")
        self.assertEqual(preview["listing"]["aspects"]["Type"], ["Painting"])

    def test_listing_preview_rejects_non_https_images(self) -> None:
        values = self.listing()
        values["image_urls"] = ["http://example.test/art.jpg"]
        with self.assertRaisesRegex(EbayGatewayError, "HTTPS"):
            self.gateway.preview_listing(values)

    def test_listing_preview_rejects_unsupported_auction_format(self) -> None:
        values = self.listing()
        values["format"] = "AUCTION"
        with self.assertRaisesRegex(EbayGatewayError, "FIXED_PRICE"):
            self.gateway.preview_listing(values)

    def test_publish_requires_confirmation_without_calling_ebay(self) -> None:
        with patch.object(self.gateway, "_request") as request:
            result = self.gateway.publish_listing(self.listing(), confirmed=False)
        self.assertEqual(result["status"], "confirmation_required")
        self.assertFalse(result["published"])
        request.assert_not_called()

    def test_publish_rejects_truthy_non_boolean_confirmation(self) -> None:
        with patch.object(self.gateway, "_request") as request:
            result = self.gateway.publish_listing(self.listing(), confirmed="false")
        self.assertEqual(result["status"], "confirmation_required")
        request.assert_not_called()

    def test_confirmed_publish_records_all_three_external_steps(self) -> None:
        with patch.object(
            self.gateway,
            "_request",
            side_effect=[{}, {"offerId": "offer-1"}, {"listingId": "listing-1"}],
        ) as request:
            result = self.gateway.publish_listing(self.listing(), confirmed=True)
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["listing_id"], "listing-1")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[0].args[:2], ("PUT", "/sell/inventory/v1/inventory_item/art-001"))
        self.assertEqual(request.call_args_list[2].args[:2], ("POST", "/sell/inventory/v1/offer/offer-1/publish"))

    def test_consequential_seller_actions_require_confirmation(self) -> None:
        with patch.object(self.gateway, "_request") as request:
            withdraw = self.gateway.withdraw_listing("offer-1")
            fulfillment = self.gateway.create_fulfillment("order-1", {"trackingNumber": "123"})
            refund = self.gateway.issue_refund("order-1", {"reasonForRefund": "OTHER"})
            update = self.gateway.update_offer("offer-1", {"sku": "art-001"})
            offer = self.gateway.send_offer_to_buyers({"offeredItems": [{"listingId": "1"}]})
        self.assertEqual(withdraw["status"], "confirmation_required")
        self.assertEqual(fulfillment["status"], "confirmation_required")
        self.assertEqual(refund["status"], "confirmation_required")
        self.assertEqual(update["status"], "confirmation_required")
        self.assertEqual(offer["status"], "confirmation_required")
        request.assert_not_called()

    def test_veridex_exposes_governed_ebay_tools(self) -> None:
        names = {row["name"] for row in veridex_server.TOOLS}
        self.assertTrue({
            "ebay.status",
            "ebay.inventory_list",
            "ebay.order_list",
            "ebay.transaction_list",
            "ebay.listing_preview",
            "ebay.listing_publish",
            "ebay.offer_update",
            "ebay.listing_withdraw",
            "ebay.fulfillment_create",
            "ebay.refund_issue",
            "ebay.buyer_offer_eligible",
            "ebay.buyer_offer_send",
        }.issubset(names))

    @patch("veridex_server.workspace_from_args", return_value=("ws_test", "sess_test"))
    @patch("veridex_server.workspace_ebay")
    def test_server_publish_tool_preserves_confirmation_gate(self, workspace_ebay, _workspace) -> None:
        workspace_ebay.return_value.publish_listing.return_value = {
            "status": "confirmation_required",
            "published": False,
        }
        handler = object.__new__(veridex_server.VeridexHandler)
        result = handler._call_tool({
            "tool": "ebay.listing_publish",
            "arguments": {"listing": self.listing(), "confirm": False},
        })
        self.assertEqual(result["structuredContent"]["status"], "confirmation_required")
        workspace_ebay.return_value.publish_listing.assert_called_once_with(self.listing(), confirmed=False)

    @patch("veridex_server.workspace_from_args", return_value=("ws_test", "sess_test"))
    @patch("veridex_server.workspace_ebay")
    def test_server_publish_tool_requires_literal_true_confirmation(self, workspace_ebay, _workspace) -> None:
        workspace_ebay.return_value.publish_listing.return_value = {
            "status": "confirmation_required",
            "published": False,
        }
        handler = object.__new__(veridex_server.VeridexHandler)
        handler._call_tool({
            "tool": "ebay.listing_publish",
            "arguments": {"listing": self.listing(), "confirm": "false"},
        })
        workspace_ebay.return_value.publish_listing.assert_called_once_with(self.listing(), confirmed=False)


if __name__ == "__main__":
    unittest.main()
