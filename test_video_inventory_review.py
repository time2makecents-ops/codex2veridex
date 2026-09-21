import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from contextlib import closing
from pathlib import Path

from PIL import Image, ImageDraw

from video_inventory_review import (
    create_review_database,
    create_review_http_server,
    list_review_batch,
    project_summary,
    save_corrected_crop,
    update_review_decision,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VideoInventoryReviewTests(unittest.TestCase):
    def _project(self, root: Path) -> tuple[Path, Path, Path]:
        source_root = root / "source"
        proposal_root = root / "proposals"
        source_root.mkdir()
        (proposal_root / "scene_overlays").mkdir(parents=True)
        (proposal_root / "proposal_crops").mkdir()

        source_image = source_root / "view_001.jpg"
        image = Image.new("RGB", (200, 120), "#d9d3c4")
        draw = ImageDraw.Draw(image)
        draw.rectangle((18, 20, 82, 104), fill="#a83f35")
        draw.ellipse((108, 24, 184, 102), fill="#3c7d66")
        image.save(source_image, format="JPEG", quality=95)
        source_manifest = source_root / "manifest.json"
        source_value = {
            "schema": "veridex.video_inventory.v1",
            "source": {"path": str(root / "source.mp4"), "sha256": "video-hash"},
            "candidates": [{
                "candidate_id": "view_001",
                "image_path": "view_001.jpg",
                "image_sha256": sha256(source_image),
            }],
        }
        source_manifest.write_text(json.dumps(source_value), encoding="utf-8")

        overlay = proposal_root / "scene_overlays" / "scene_001.jpg"
        image.save(overlay, format="JPEG", quality=95)
        proposals = []
        for index in range(1, 4):
            proposal_id = f"proposal_{index:04d}"
            neutral = proposal_root / "proposal_crops" / f"{proposal_id}_neutral.jpg"
            isolated = proposal_root / "proposal_crops" / f"{proposal_id}_isolated.png"
            crop = image.crop((10 * index, 10, 90 + 10 * index, 110))
            crop.save(neutral, format="JPEG", quality=95)
            crop.convert("RGBA").save(isolated, format="PNG")
            proposals.append({
                "proposal_id": proposal_id,
                "points": [[10, 10], [100, 10], [100, 90], [10, 90]],
                "bounds": [10, 10, 100, 90],
                "quality_flags": ["small_region_review"] if index == 1 else [],
                "proposal_score": 0.7,
                "neutral_path": neutral.relative_to(proposal_root).as_posix(),
                "neutral_sha256": sha256(neutral),
                "isolated_path": isolated.relative_to(proposal_root).as_posix(),
                "isolated_sha256": sha256(isolated),
            })
        proposal_manifest = proposal_root / "proposal_manifest.json"
        proposal_value = {
            "schema": "veridex.video_inventory.item_proposals.v1",
            "source_manifest_path": str(source_manifest),
            "source_manifest_sha256": sha256(source_manifest),
            "source_video_sha256": "video-hash",
            "proposal_count": 3,
            "scenes": [{
                "scene_id": "scene_001",
                "representative_candidate_id": "view_001",
                "candidate_ids": ["view_001"],
                "rotation_degrees": 90,
                "orientation_status": "accepted_override",
                "overlay_relative_path": overlay.relative_to(proposal_root).as_posix(),
                "overlay_sha256": sha256(overlay),
                "proposals": proposals,
            }],
        }
        proposal_manifest.write_text(json.dumps(proposal_value), encoding="utf-8")
        return proposal_manifest, root / "review" / "review.sqlite3", root / "review" / "corrected_crops"

    def test_database_batches_decisions_duplicates_and_crop_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, database, corrections = self._project(root)
            created = create_review_database(manifest, database, corrections, batch_size=2)
            self.assertEqual(created.proposal_count, 3)
            self.assertEqual(created.batch_count, 2)
            self.assertEqual(project_summary(database)["statuses"]["pending"], 3)
            self.assertEqual(len(list_review_batch(database, 1)["proposals"]), 2)
            self.assertEqual(len(list_review_batch(database, 2)["proposals"]), 1)
            self.assertEqual(create_review_database(manifest, database, corrections).project_id, created.project_id)

            kept = update_review_decision(database, "proposal_0001", review_status="keep", review_note="Complete object")
            self.assertEqual(kept["review_status"], "keep")
            duplicate = update_review_decision(
                database,
                "proposal_0002",
                review_status="duplicate",
                duplicate_of="proposal_0001",
                review_note="Same item",
            )
            self.assertEqual(duplicate["duplicate_of"], "proposal_0001")
            with self.assertRaisesRegex(ValueError, "different retained"):
                update_review_decision(database, "proposal_0002", review_status="duplicate", duplicate_of="proposal_0002")

            source_hash = sha256(root / "source" / "view_001.jpg")
            corrected = save_corrected_crop(
                database,
                "proposal_0003",
                [(8, 12), (108, 12), (108, 175), (8, 175)],
            )
            self.assertEqual(corrected["crop_revision"], 1)
            self.assertEqual(corrected["review_status"], "corrected_pending_review")
            self.assertTrue(Path(corrected["neutral_path"]).is_file())
            self.assertEqual(sha256(root / "source" / "view_001.jpg"), source_hash)
            summary = project_summary(database)
            self.assertEqual(summary["reviewed"], 3)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM review_events").fetchone()[0], 4)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM crop_revisions").fetchone()[0], 1)

    def test_loopback_api_serves_batches_static_ui_and_oriented_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, database, corrections = self._project(root)
            create_review_database(manifest, database, corrections, batch_size=2)
            server = create_review_http_server(database, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urllib.request.urlopen(base + "/api/project", timeout=5) as response:
                    summary = json.loads(response.read())
                self.assertEqual(summary["total"], 3)
                with urllib.request.urlopen(base + "/api/proposals?batch=1", timeout=5) as response:
                    batch = json.loads(response.read())
                self.assertEqual(len(batch["proposals"]), 2)
                with urllib.request.urlopen(base + "/media/proposal_0001?kind=source", timeout=5) as response:
                    with Image.open(io.BytesIO(response.read())) as oriented:
                        self.assertEqual(oriented.size, (120, 200))
                payload = json.dumps({"review_status": "unsure", "review_note": "Check later"}).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/proposals/proposal_0001",
                    data=payload,
                    method="PATCH",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    updated = json.loads(response.read())
                self.assertEqual(updated["review_status"], "unsure")
                with urllib.request.urlopen(base + "/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Item review", html)
                self.assertIn("review-grid", html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
