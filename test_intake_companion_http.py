import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import intake_companion_server
from seller_intake import SellerIntakeCatalog


class IntakeCompanionHttpTests(unittest.TestCase):
    def request(self, base, path, *, method="GET", value=None, content_type="application/json"):
        body = None if value is None else (json.dumps(value).encode("utf-8") if content_type == "application/json" else value)
        request = urllib.request.Request(base + path, data=body, method=method)
        if body is not None:
            request.add_header("Content-Type", content_type)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()

    def test_phone_capture_keeps_raw_material_and_archives_without_deleting(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            with patch.object(intake_companion_server, "CATALOG", catalog):
                server = ThreadingHTTPServer(("127.0.0.1", 0), intake_companion_server.CompanionHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"
                try:
                    status, body = self.request(base, "/api/batches", method="POST", value={"title": "Garage"})
                    self.assertEqual(status, 201)
                    batch = json.loads(body)["batch"]
                    status, body = self.request(base, "/api/items", method="POST", value={"batch_id": batch["batch_id"], "title": "Lamp", "reference_id": "set-17"})
                    self.assertEqual(status, 201)
                    item = json.loads(body)["item"]
                    query = urllib.parse.urlencode({"name": "lamp.jpg"})
                    status, body = self.request(base, f"/api/items/{item['item_id']}/photos?{query}", method="POST", value=b"jpeg", content_type="image/jpeg")
                    self.assertEqual(status, 201)
                    asset_id = json.loads(body)["asset"]["asset_id"]
                    status, photo = self.request(base, f"/api/items/{item['item_id']}/photos?asset_id={asset_id}")
                    self.assertEqual(status, 200)
                    self.assertEqual(photo, b"jpeg")
                    status, _ = self.request(base, "/api/items/archive", method="POST", value={"item_id": item["item_id"]})
                    self.assertEqual(status, 200)
                    status, body = self.request(base, f"/api/bootstrap?batch_id={batch['batch_id']}")
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)["batch"]["items"], [])
                    self.assertEqual(catalog.get_item(item["item_id"])["status"], "archived")

                    discard = catalog.create_item({"batch_id": batch["batch_id"], "title": "Discard me"})
                    status, body = self.request(base, "/api/items/delete", method="POST", value={"item_id": discard["item_id"], "confirmation": "DELETE"})
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)["deleted"]["item_id"], discard["item_id"])
                    with self.assertRaisesRegex(KeyError, "Unknown intake item"):
                        catalog.get_item(discard["item_id"])
                finally:
                    server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
