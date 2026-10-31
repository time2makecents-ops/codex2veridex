import json
import base64
import io
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import veridex_server
from seller_intake import SellerIntakeCatalog


class ItemIntakeHttpTests(unittest.TestCase):
    def request(self, base, path, *, method="GET", value=None, content_type="application/json"):
        body = None if value is None else (json.dumps(value).encode("utf-8") if content_type == "application/json" else value)
        request = urllib.request.Request(base + path, data=body, method=method)
        if body is not None:
            request.add_header("Content-Type", content_type)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_paired_surface_serves_item_intake_and_item_asset_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            thread_result = {
                "thread_provider": "chatgpt",
                "page_title": "Shared lamp research",
                "text": "The lamp is likely mid-century.",
                "images": [{"content_type": "image/jpeg", "base64": base64.b64encode(b"thread-image").decode("ascii")}],
            }
            with patch.object(veridex_server, "SELLER_INTAKE", catalog), patch.object(veridex_server, "import_shared_thread", return_value=thread_result):
                server = ThreadingHTTPServer(("127.0.0.1", 0), veridex_server.VeridexHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"
                try:
                    with urllib.request.urlopen(base + "/item-intake", timeout=5) as response:
                        page = response.read().decode("utf-8")
                    self.assertIn('id="file-input"', page)
                    status, batch = self.request(base, "/api/item-intake/batches", method="POST", value={"title": "Phone batch"})
                    self.assertEqual(status, 201)
                    status, item = self.request(base, "/api/item-intake/items", method="POST", value={"batch_id": batch["batch"]["batch_id"], "title": "Lamp"})
                    self.assertEqual(status, 201)
                    item_id = item["item"]["item_id"]
                    status, item = self.request(base, "/api/item-intake/items/update", method="POST", value={"item_id": item_id, "chatgpt_thread_url": "https://chatgpt.com/share/lamp-thread", "gemini_thread_url": "https://g.co/gemini/share/lamp-thread"})
                    self.assertEqual(status, 200)
                    self.assertEqual(item["item"]["chatgpt_thread_url"], "https://chatgpt.com/share/lamp-thread")
                    self.assertEqual(item["item"]["gemini_thread_url"], "https://g.co/gemini/share/lamp-thread")
                    status, preview = self.request(base, "/api/item-intake/threads/preview", method="POST", value={"item_id": item_id, "provider": "chatgpt"})
                    self.assertEqual(status, 200)
                    self.assertEqual(preview["preview"]["text_preview"], "The lamp is likely mid-century.")
                    listing_text = """Option 1: Facebook Marketplace (Local Pickup)
Title Options: Vintage Framed Triple Berry Botanical Art Set - Signed & Numbered
Price: $55 (Leave room to haggle)
Category: Home Decor / Wall Art
Condition: Excellent vintage condition
Description:
Ready-to-hang framed botanical berry prints.
Option 2: eBay (Shipping / Nationwide Audience)
Title: Vintage Signed Limited Edition Botanical Berry Art Prints Set By Toni Framed
Buy It Now: $74.99 with Best Offer enabled
Shipping: Calculated shipping based on buyer location
Item Specifics:
Artist: Toni
Type: Print / Lithograph
Description:
Framed signed and numbered botanical berry art set.
"""
                    with patch.object(veridex_server, "import_shared_thread", return_value={**thread_result, "text": listing_text}):
                        status, plan = self.request(base, "/api/item-intake/threads/listing-plan", method="POST", value={"item_id": item_id, "provider": "chatgpt"})
                    self.assertEqual(status, 200)
                    self.assertEqual(plan["listing_plan"]["plan"]["facebook"]["price"], 55.0)
                    self.assertEqual(plan["listing_plan"]["plan"]["ebay"]["price"], 74.99)
                    self.assertIn("Toni", plan["listing_plan"]["plan"]["ebay"]["title"])
                    self.assertTrue(plan["listing_plan"]["plan"]["review_required"])
                    status, imported = self.request(base, "/api/item-intake/threads/import", method="POST", value={"item_id": item_id, "provider": "chatgpt", "confirm": True})
                    self.assertEqual(status, 201)
                    self.assertEqual(len(imported["imported"]["photos"]), 1)
                    query = urllib.parse.urlencode({"name": "lamp.jpg", "role": "photo"})
                    status, saved = self.request(base, f"/api/item-intake/items/{item_id}/assets?{query}", method="POST", value=b"image", content_type="image/jpeg")
                    self.assertEqual(status, 201)
                    self.assertEqual(saved["asset"]["name"], "lamp.jpg")
                    status, deleted = self.request(base, "/api/item-intake/assets/delete", method="POST", value={"item_id": item_id, "asset_id": saved["asset"]["asset_id"]})
                    self.assertEqual(status, 200)
                    self.assertEqual(deleted["deleted"]["name"], "lamp.jpg")
                    image = io.BytesIO()
                    Image.new("RGB", (80, 60), "#d9e8dd").save(image, format="JPEG")
                    query = urllib.parse.urlencode({"name": "source.jpg", "role": "photo"})
                    status, source = self.request(base, f"/api/item-intake/items/{item_id}/assets?{query}", method="POST", value=image.getvalue(), content_type="image/jpeg")
                    self.assertEqual(status, 201)
                    status, adjusted = self.request(base, "/api/item-intake/photos/touch-up", method="POST", value={"item_id": item_id, "asset_id": source["asset"]["asset_id"], "operation": "adjust", "options": {"brightness": 12, "exposure": 8, "contrast": 16, "saturation": 10, "warmth": 6, "shadows": 14, "highlights": -8, "definition": 9, "sharpness": 12, "rotation": 90, "left_percent": 5, "top_percent": 5, "right_percent": 95, "bottom_percent": 95}})
                    self.assertEqual(status, 201)
                    self.assertEqual(adjusted["touch_up"]["asset"]["transformation"]["operation"], "adjust")
                    self.assertEqual(adjusted["touch_up"]["asset"]["transformation"]["rotation"], 90)
                    self.assertEqual(set(adjusted["touch_up"]["asset"]["transformation"]["adjustments"]), {"brightness", "exposure", "contrast", "saturation", "warmth", "shadows", "highlights", "sharpness", "definition"})
                    status, upside_down = self.request(base, "/api/item-intake/photos/touch-up", method="POST", value={"item_id": item_id, "asset_id": source["asset"]["asset_id"], "operation": "adjust", "options": {"rotation": 180, "left_percent": 5, "top_percent": 5, "right_percent": 95, "bottom_percent": 95}})
                    self.assertEqual(status, 201)
                    self.assertEqual(upside_down["touch_up"]["asset"]["transformation"]["rotation"], 180)
                    status, touch_up = self.request(base, "/api/item-intake/photos/touch-up", method="POST", value={"item_id": item_id, "asset_id": source["asset"]["asset_id"], "operation": "auto_adjust"})
                    self.assertEqual(status, 201)
                    self.assertEqual(touch_up["touch_up"]["asset"]["source_asset_id"], source["asset"]["asset_id"])
                    self.assertEqual(touch_up["touch_up"]["asset"]["transformation"]["operation"], "auto_adjust")
                    status, marketplace = self.request(base, "/api/item-intake/photos/touch-up", method="POST", value={"item_id": item_id, "asset_id": source["asset"]["asset_id"], "operation": "marketplace_auto"})
                    self.assertEqual(status, 201)
                    self.assertEqual(marketplace["touch_up"]["asset"]["transformation"]["operation"], "marketplace_auto")
                    self.assertIn("glare_softening", marketplace["touch_up"]["asset"]["transformation"])
                    status, preset = self.request(base, "/api/item-intake/touchup-presets", method="POST", value={"name": "Glass glare", "prompt": "Remove glare from glass while preserving the item exactly."})
                    self.assertEqual(status, 201)
                    self.assertEqual(preset["preset"]["name"], "Glass glare")
                    status, presets = self.request(base, "/api/item-intake/touchup-presets")
                    self.assertEqual(status, 200)
                    self.assertEqual(presets["presets"][0]["prompt"], "Remove glare from glass while preserving the item exactly.")
                    with patch.object(veridex_server, "workspace_context", return_value={}), patch.object(veridex_server, "codex_art_provider", return_value={"configured": True, "quota_label": "ready"}), patch.object(veridex_server, "codex_art_assets", return_value=[{"content": image.getvalue(), "extension": ".jpg", "content_type": "image/jpeg", "metadata": {"provider": "codex", "operation": "edit"}}]) as codex_assets:
                        ai_touch_up = veridex_server.touch_up_intake_photo({"item_id": item_id, "asset_id": source["asset"]["asset_id"], "operation": "ai", "provider": "codex", "prompt": "Remove glare", "confirm": True, "workspace_id": "workspace_test", "session_id": "session_test"})
                    self.assertEqual(codex_assets.call_args.args[3]["timeout_seconds"], 180)
                    self.assertEqual(ai_touch_up["asset"]["source_asset_id"], source["asset"]["asset_id"])
                    self.assertEqual(ai_touch_up["asset"]["transformation"]["provider"], "codex")
                    status, loaded = self.request(base, f"/api/item-intake/bootstrap?item_id={item_id}")
                    self.assertEqual(status, 200)
                    self.assertEqual(loaded["item"]["asset_count"], 8)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
