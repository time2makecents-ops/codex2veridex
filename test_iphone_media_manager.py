from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from PIL import Image

from iphone_media_manager import (
    JobManager,
    add_source,
    create_database,
    create_http_server,
    database,
    deletion_preview,
    execute_deletion,
    get_job,
    list_items,
    scan_source,
    save_destination,
    save_secondary_destination,
    set_setting,
    update_dispositions,
    validate_destination,
)


class IphoneMediaManagerTests(unittest.TestCase):
    def _source(self, root: Path) -> tuple[Path, Path, str]:
        source_root = root / "source"
        source_root.mkdir()
        image = source_root / "IMG_0042.JPG"
        Image.new("RGB", (900, 1200), (78, 104, 128)).save(image, format="JPEG")
        audio = source_root / "Voice Memo.m4a"
        audio.write_bytes(b"not-real-audio-but-nonempty")
        database_path = root / "state" / "iphone.sqlite3"
        create_database(database_path)
        source = add_source(database_path, kind="export_inbox", label="Phone exports", path=str(source_root))
        return database_path, source_root, source["source_id"]

    def test_folder_scan_is_stable_and_supports_date_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path, _, source_id = self._source(Path(temporary))
            first = scan_source(database_path, source_id)
            second = scan_source(database_path, source_id)
            self.assertEqual(first["count"], 2)
            self.assertEqual(second["count"], 2)
            inventory = list_items(database_path)
            self.assertEqual(inventory["total"], 2)
            self.assertEqual({item["media_kind"] for item in inventory["items"]}, {"photo", "audio"})
            self.assertEqual(list_items(database_path, {"media_kind": "photo"})["total"], 1)

    def test_destination_probe_and_verified_transfer_preserve_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path, source_root, source_id = self._source(root)
            scan_source(database_path, source_id)
            item = list_items(database_path, {"media_kind": "photo"})["items"][0]
            update_dispositions(database_path, [item["item_id"]], "download_keep")
            archive = root / "external-drive" / "chosen-folder"
            self.assertTrue(validate_destination(str(archive))["writable"])
            manager = JobManager(database_path)
            job_id = manager.start_transfer([item["item_id"]], str(archive), False)
            deadline = time.time() + 10
            while time.time() < deadline and get_job(database_path, job_id)["status"] in {"queued", "running"}:
                time.sleep(0.05)
            job = get_job(database_path, job_id)
            self.assertEqual(job["status"], "completed", job["error"])
            transferred = list_items(database_path, {"media_kind": "photo"})["items"][0]
            self.assertTrue(transferred["local_verified"])
            self.assertTrue(Path(transferred["local_path"]).is_file())
            self.assertTrue((source_root / "IMG_0042.JPG").is_file())
            self.assertFalse(Path(str(transferred["local_path"]) + ".partial").exists())

    def test_batch_and_file_limits_are_enforced_before_job_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path, _, source_id = self._source(root)
            scan_source(database_path, source_id)
            item = list_items(database_path)["items"][0]
            set_setting(database_path, "limits", {"batch_bytes": 1, "file_bytes": 1})
            with self.assertRaisesRegex(ValueError, "per-file limit"):
                JobManager(database_path).start_transfer([item["item_id"]], str(root / "archive"), False)

    def test_second_destination_must_be_an_independent_volume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path, _, _ = self._source(root)
            save_destination(database_path, str(root / "primary"))
            with self.assertRaisesRegex(ValueError, "different physical drive"):
                save_secondary_destination(database_path, str(root / "secondary"))

    def test_transfer_creates_and_verifies_a_second_local_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path, _, source_id = self._source(root)
            scan_source(database_path, source_id)
            item = list_items(database_path, {"media_kind": "photo"})["items"][0]
            manager = JobManager(database_path)
            with mock.patch("iphone_media_manager.ensure_independent_volumes"):
                job_id = manager.start_transfer(
                    [item["item_id"]], str(root / "primary-drive"), False, str(root / "secondary-drive")
                )
            deadline = time.time() + 10
            while time.time() < deadline and get_job(database_path, job_id)["status"] in {"queued", "running"}:
                time.sleep(0.05)
            job = get_job(database_path, job_id)
            self.assertEqual(job["status"], "completed", job["error"])
            transferred = list_items(database_path, {"media_kind": "photo"})["items"][0]
            self.assertTrue(transferred["local_verified"])
            self.assertTrue(transferred["secondary_verified"])
            self.assertTrue(transferred["second_copy_verified"])
            self.assertEqual(Path(transferred["local_path"]).read_bytes(), Path(transferred["secondary_path"]).read_bytes())

    def test_deletion_gate_accepts_verified_second_drive_without_google(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path, _, source_id = self._source(root)
            scan_source(database_path, source_id)
            item = list_items(database_path, {"media_kind": "photo"})["items"][0]
            update_dispositions(database_path, [item["item_id"]], "download_delete")
            manager = JobManager(database_path)
            with mock.patch("iphone_media_manager.ensure_independent_volumes"):
                job_id = manager.start_transfer(
                    [item["item_id"]], str(root / "primary"), False, str(root / "secondary")
                )
            deadline = time.time() + 10
            while time.time() < deadline and get_job(database_path, job_id)["status"] in {"queued", "running"}:
                time.sleep(0.05)
            with mock.patch("iphone_media_manager.ensure_independent_volumes"):
                preview = deletion_preview(database_path, [item["item_id"]])
            self.assertTrue(preview["token"])
            self.assertEqual(preview["blocked"], [])

    def test_deletion_requires_two_currently_verified_copies_and_falls_back_truthfully(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path, _, source_id = self._source(root)
            scan_source(database_path, source_id)
            item = list_items(database_path, {"media_kind": "photo"})["items"][0]
            update_dispositions(database_path, [item["item_id"]], "download_delete")
            blocked = deletion_preview(database_path, [item["item_id"]])
            self.assertIsNone(blocked["token"])
            self.assertIn("local archive is not verified", blocked["blocked"][0]["reasons"])

            archive = root / "archive" / "image.jpg"
            archive.parent.mkdir()
            archive.write_bytes(b"archive-copy")
            import hashlib
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with database(database_path) as connection:
                connection.execute(
                    """UPDATE media_items SET size_bytes=?, local_path=?, local_sha256=?, local_verified_at=?,
                       drive_file_id='drive-id', drive_size=?, drive_md5='remote-md5', drive_verified_at=?
                       WHERE item_id=?""",
                    (archive.stat().st_size, str(archive), digest, "2026-01-01T00:00:00Z", archive.stat().st_size, "2026-01-01T00:00:00Z", item["item_id"]),
                )
                connection.commit()
            with mock.patch("iphone_media_manager.verify_deletion_copies", return_value=[]):
                preview = deletion_preview(database_path, [item["item_id"]])
            self.assertTrue(preview["token"])
            result = execute_deletion(database_path, preview["token"], preview["confirmation_text"])
            self.assertEqual(result["results"][0]["status"], "guided_required")
            self.assertEqual(result["deleted"], 0)

    def test_loopback_server_exposes_status_inventory_and_ui(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path, _, source_id = self._source(root)
            scan_source(database_path, source_id)
            server = create_http_server(database_path, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
                    status = json.loads(response.read())
                self.assertEqual(status["counts"]["total"], 2)
                with urllib.request.urlopen(base + "/api/items?media_kind=photo", timeout=5) as response:
                    inventory = json.loads(response.read())
                self.assertEqual(inventory["total"], 1)
                with urllib.request.urlopen(base + "/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Veridex iPhone Archive", html)
                self.assertIn('id="destination-path"', html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_non_loopback_bind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "iphone.sqlite3"
            create_database(database_path)
            with self.assertRaisesRegex(ValueError, "loopback"):
                create_http_server(database_path, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
