from __future__ import annotations

import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from art_studio import (
    ArtJobManager,
    ArtProviderError,
    ArtStudio,
    LocalFinishPlugin,
    PollinationsArtProvider,
    validate_image_bytes,
)


def sample_image(color: str = "#336644", size: tuple[int, int] = (96, 64)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


class ArtStudioTests(unittest.TestCase):
    def test_image_validation_reads_real_dimensions_and_rejects_garbage(self) -> None:
        facts = validate_image_bytes(sample_image(size=(120, 80)))
        self.assertEqual((facts["width"], facts["height"]), (120, 80))
        self.assertEqual(facts["content_type"], "image/png")
        with self.assertRaises(ValueError):
            validate_image_bytes(b"not an image")

    def test_local_finish_creates_new_resize_text_and_collage_images(self) -> None:
        plugin = LocalFinishPlugin()
        source = {"file_id": "one", "name": "one.png", "content_type": "image/png", "content": sample_image()}
        resized = plugin.apply("resize", [source], {"width": 200, "height": 100, "format": "PNG"})
        self.assertEqual((validate_image_bytes(resized["content"])["width"], validate_image_bytes(resized["content"])["height"]), (200, 100))
        captioned = plugin.apply("add_text", [source], {"text": "VERIDEX", "format": "PNG"})
        self.assertEqual(validate_image_bytes(captioned["content"])["format"], "PNG")
        second = {**source, "file_id": "two", "content": sample_image("#884433")}
        collage = plugin.apply("collage", [source, second], {"format": "JPEG"})
        self.assertEqual(validate_image_bytes(collage["content"])["format"], "JPEG")

    def test_projects_are_explicitly_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            studio = ArtStudio(Path(temporary))
            first = studio.save_project("ws_test", {"name": "Launch art", "prompt": "first", "file_ids": ["a"]})
            second = studio.save_project("ws_test", {**first, "prompt": "second", "file_ids": ["a", "b"]})
            self.assertEqual(first["version"], 1)
            self.assertEqual(second["version"], 2)
            self.assertEqual(studio.list_projects("ws_test")[0]["prompt"], "second")
            self.assertEqual(len(list((Path(temporary) / "workspaces" / "ws_test" / "art_studio" / "versions").glob("*.json"))), 2)

    def test_cloudflare_failure_uses_only_free_pollinations_fallback(self) -> None:
        studio = ArtStudio(Path("."))
        content = sample_image()
        with patch.object(studio.cloudflare, "generate", side_effect=ArtProviderError("cloudflare", "quota", quota=True)), patch.object(
            studio.pollinations, "generate", return_value=content
        ) as fallback:
            result = studio.generate({"prompt": "green workshop", "preset_id": "photography", "model_id": "fast"}, [])
        self.assertEqual(result[0]["metadata"]["provider"], "pollinations")
        self.assertIn(fallback.call_args.args[1], {"flux", "zimage"})

    def test_pollinations_blocks_nonfree_model_before_network(self) -> None:
        provider = PollinationsArtProvider()
        with patch.dict("os.environ", {"VERIDEX_POLLINATIONS_API_KEY": "test"}, clear=False):
            with self.assertRaises(ArtProviderError):
                provider.generate("test", "gptimage", 512, 512, 1, [])

    def test_jobs_report_completion_and_cancellation(self) -> None:
        manager = ArtJobManager(workers=1)
        completed = manager.submit({"operation": "generate"}, lambda _id, progress, _cancelled: (progress(80, "Verifying"), {"kind": "text", "text": "done"})[1])
        for _ in range(100):
            completed = manager.get(completed["job_id"])
            if completed["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(completed["result"]["text"], "done")


if __name__ == "__main__":
    unittest.main()
