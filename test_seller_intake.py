import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from seller_intake import SellerIntakeCatalog


class FakeStore:
    def __init__(self) -> None:
        self.calls = []

    def save_file(self, workspace_id, session_id, filename, content, content_type, **kwargs):
        self.calls.append({"workspace_id": workspace_id, "session_id": session_id, "name": filename, "content": content, "content_type": content_type, **kwargs})
        return {"file_id": f"file_{len(self.calls)}", "artifact_number": len(self.calls), "name": filename, "content_type": content_type, "size": len(content), "sha256": "a" * 64}


class SellerIntakeTests(unittest.TestCase):
    def test_zip_extract_keeps_archive_and_adds_item_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "ZIP intake"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Camera"})
            stream = BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("photos/front.jpg", b"jpeg")
                archive.writestr("notes/provenance.txt", b"notes")
            result = catalog.extract_zip(item["item_id"], "camera-files.zip", stream.getvalue())
            self.assertEqual(result["file_count"], 2)
            self.assertTrue(result["verified"])
            current = catalog.get_item(item["item_id"])
            self.assertEqual({asset["name"] for asset in current["assets"]}, {"camera-files.zip", "front.jpg", "provenance.txt"})
            self.assertEqual(next(asset["role"] for asset in current["assets"] if asset["name"] == "front.jpg"), "photo")

    def test_item_folder_keeps_assets_evidence_and_snapshot_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Estate find"})
            link = "https://chatgpt.com/share/example-vase-thread"
            gemini_link = "https://g.co/gemini/share/example-vase-thread"
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Blue vase", "estimated_value": 42, "tags": "glass, vintage", "chatgpt_thread_url": link, "gemini_thread_url": gemini_link})
            photo = catalog.add_asset(item["item_id"], "vase.jpg", b"jpeg", "image/jpeg", "photo")
            source = catalog.add_source_text({"item_id": item["item_id"], "title": "ChatGPT notes", "text": "The blue mark may be 1980s."})
            evidence = catalog.add_evidence({"item_id": item["item_id"], "claim": "The mark may date to the 1980s.", "source_asset_id": source["asset_id"], "source_excerpt": "may be 1980s", "observed_date": "1980s", "confidence": "low"})

            current = catalog.get_item(item["item_id"])
            self.assertEqual(current["estimated_value"], 42.0)
            self.assertEqual(current["tags"], ["glass", "vintage"])
            self.assertEqual(current["chatgpt_thread_url"], link)
            self.assertEqual(current["gemini_thread_url"], gemini_link)
            self.assertEqual({row["asset_id"] for row in current["assets"]}, {photo["asset_id"], source["asset_id"]})
            self.assertEqual(current["evidence"][0]["evidence_id"], evidence["evidence_id"])
            _, photo_path = catalog.asset_path(photo["asset_id"])
            self.assertEqual(photo_path.read_bytes(), b"jpeg")
            snapshot = next(catalog.batches_root.glob(f"{batch['batch_id']}/items/{item['item_id']}_*/item.json"))
            stored = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(stored["item_id"], item["item_id"])
            self.assertEqual(stored["chatgpt_thread_url"], link)
            self.assertEqual(stored["gemini_thread_url"], gemini_link)
            self.assertEqual(len(stored["assets"]), 2)

    def test_exports_and_veridex_handoff_preserve_source_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Saturday"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Chair", "description": "Oak chair", "research_needed": True})
            catalog.add_asset(item["item_id"], "chair.png", b"png-data", "image/png", "photo")
            exports = catalog.export_batch(batch["batch_id"])
            self.assertEqual({row["name"].rsplit(".", 1)[-1] for row in exports["exports"]}, {"csv", "xlsx"})
            self.assertTrue(all(catalog.export_path(row["relative_path"]).is_file() for row in exports["exports"]))

            store = FakeStore()
            handoff = catalog.handoff_to_veridex(item["item_id"], "ws_test", "sess_test", store)
            self.assertEqual(len(handoff["files"]), 2)
            self.assertEqual(store.calls[0]["content"], b"png-data")
            brief = json.loads(store.calls[1]["content"].decode("utf-8"))
            self.assertEqual(brief["seller_intake_item"]["item_id"], item["item_id"])
            self.assertEqual(brief["seller_intake_item"]["chatgpt_thread_url"], "")
            self.assertEqual(brief["seller_intake_item"]["gemini_thread_url"], "")
            self.assertEqual(catalog.get_item(item["item_id"])["status"], "handed_off")

    def test_evidence_cannot_reference_another_items_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Batch"})
            first = catalog.create_item({"batch_id": batch["batch_id"], "title": "First"})
            second = catalog.create_item({"batch_id": batch["batch_id"], "title": "Second"})
            source = catalog.add_source_text({"item_id": first["item_id"], "text": "source"})
            with self.assertRaisesRegex(Exception, "does not belong"):
                catalog.add_evidence({"item_id": second["item_id"], "claim": "Wrong source", "source_asset_id": source["asset_id"]})

    def test_chatgpt_thread_link_must_be_a_shared_chatgpt_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Batch"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Lamp"})
            with self.assertRaisesRegex(Exception, "chatgpt.com/share"):
                catalog.update_item({"item_id": item["item_id"], "chatgpt_thread_url": "https://example.com/thread"})
            with self.assertRaisesRegex(Exception, "public share URL"):
                catalog.update_item({"item_id": item["item_id"], "gemini_thread_url": "https://example.com/thread"})

    def test_private_ai_links_are_saved_but_only_shared_links_are_importable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "AI links"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Lamp"})
            saved = catalog.update_item({
                "item_id": item["item_id"],
                "chatgpt_thread_url": "https://chatgpt.com/c/private-conversation",
                "gemini_thread_url": "https://gemini.google.com/app/private-conversation",
            })
            self.assertEqual(saved["chatgpt_thread_url"], "https://chatgpt.com/c/private-conversation")
            self.assertEqual(saved["gemini_thread_url"], "https://gemini.google.com/app/private-conversation")
            self.assertFalse(catalog.is_shared_thread_url("chatgpt", saved["chatgpt_thread_url"]))
            self.assertFalse(catalog.is_shared_thread_url("gemini", saved["gemini_thread_url"]))
            self.assertTrue(catalog.is_shared_thread_url("chatgpt", "https://chatgpt.com/share/public-conversation"))
            self.assertTrue(catalog.is_shared_thread_url("gemini", "https://g.co/gemini/share/public-conversation"))
            self.assertTrue(catalog.is_shared_thread_url("gemini", "https://share.gemini.google/public-conversation"))
            self.assertTrue(catalog.is_shared_thread_url("gemini", "https://gemini.google.com/share/public-conversation"))

    def test_listing_photos_persist_in_order_without_moving_originals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Listing photos"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Lamp"})
            first = catalog.add_asset(item["item_id"], "front.jpg", b"front", "image/jpeg", "photo")
            second = catalog.add_asset(item["item_id"], "detail.jpg", b"detail", "image/jpeg", "photo")

            saved = catalog.set_listing_photos(item["item_id"], [second["asset_id"], first["asset_id"]])

            self.assertEqual(saved["listing_photo_asset_ids"], [second["asset_id"], first["asset_id"]])
            self.assertEqual([row["asset_id"] for row in saved["listing_photos"]], [second["asset_id"], first["asset_id"]])
            self.assertEqual({row["asset_id"] for row in saved["assets"]}, {first["asset_id"], second["asset_id"]})
            catalog.delete_asset(item["item_id"], second["asset_id"])
            self.assertEqual(catalog.get_item(item["item_id"])["listing_photo_asset_ids"], [first["asset_id"]])

    def test_delete_item_removes_its_catalog_rows_and_source_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Discard"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Blue vase"})
            catalog.add_asset(item["item_id"], "vase.jpg", b"jpeg", "image/jpeg", "photo")
            item_dir = next(catalog.batches_root.glob(f"{batch['batch_id']}/items/{item['item_id']}_*"))

            deleted = catalog.delete_item(item["item_id"])

            self.assertEqual(deleted["title"], "Blue vase")
            self.assertFalse(item_dir.exists())
            with self.assertRaisesRegex(KeyError, "Unknown intake item"):
                catalog.get_item(item["item_id"])

    def test_delete_asset_removes_only_the_selected_photo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Discard photo"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Lamp"})
            first = catalog.add_asset(item["item_id"], "first.jpg", b"first", "image/jpeg", "photo")
            second = catalog.add_asset(item["item_id"], "second.jpg", b"second", "image/jpeg", "photo")
            _, first_path = catalog.asset_path(first["asset_id"])

            deleted = catalog.delete_asset(item["item_id"], first["asset_id"])

            self.assertEqual(deleted["name"], "first.jpg")
            self.assertFalse(first_path.exists())
            self.assertEqual([row["asset_id"] for row in catalog.get_item(item["item_id"])["assets"]], [second["asset_id"]])

    def test_derived_photo_stays_with_its_source_and_preserves_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = SellerIntakeCatalog(Path(temporary))
            batch = catalog.create_batch({"title": "Touch ups"})
            item = catalog.create_item({"batch_id": batch["batch_id"], "title": "Lamp"})
            source = catalog.add_asset(item["item_id"], "lamp.jpg", b"source", "image/jpeg", "photo")
            derived = catalog.add_asset(
                item["item_id"], "lamp--auto-adjust.jpg", b"derived", "image/jpeg", "photo",
                source_asset_id=source["asset_id"], transformation={"operation": "auto_adjust", "engine": "local_pillow"},
            )

            _, derived_path = catalog.asset_path(derived["asset_id"])
            self.assertIn("derivatives", derived_path.parts)
            self.assertEqual(derived["source_asset_id"], source["asset_id"])
            self.assertEqual(derived["transformation"]["operation"], "auto_adjust")
            with self.assertRaisesRegex(Exception, "Remove derived"):
                catalog.delete_asset(item["item_id"], source["asset_id"])


if __name__ == "__main__":
    unittest.main()
