from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from museum_visual_analysis import MuseumVisualAnalyzer, compare_images, image_metrics


class MuseumVisualAnalysisTests(unittest.TestCase):
    def _artwork(self, path: Path) -> None:
        image = Image.new("RGB", (900, 700), "#d8c6a0")
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 70, 820, 630), outline="#402010", width=22)
        draw.ellipse((180, 140, 520, 520), fill="#315f78", outline="white", width=10)
        draw.polygon([(560, 520), (710, 170), (790, 540)], fill="#a84932")
        draw.text((620, 570), "J. Test", fill="#201510")
        image.save(path)

    def test_metrics_are_deterministic_and_include_color_quality_evidence(self) -> None:
        image = Image.new("RGB", (200, 100), "#336699")
        first = image_metrics(image)
        second = image_metrics(image)
        self.assertEqual(first, second)
        self.assertEqual(first["width"], 200)
        self.assertEqual(first["dominant_palette"][0]["hex"], "#336699")
        self.assertIn("periodic_pattern_score", first)
        self.assertIn(first["sharpness_rating"], {"low", "usable", "high"})

    def test_detailed_analysis_creates_labeled_derived_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "art.png"
            self._artwork(path)
            analyzer = MuseumVisualAnalyzer(Path(temporary))
            result = analyzer.analyze(
                [{"file_id": "file_one", "path": str(path), "name": "art.png"}],
                mode="detailed",
                focus="signature",
                photo_roles={"file_one": "signature"},
                regions={"file_one": [{"label": "Signature", "x": 0.62, "y": 0.75, "width": 0.3, "height": 0.2}]},
            )
            kinds = {row["kind"] for row in result["artifacts"]}
            self.assertIn("normalized_overview", kinds)
            self.assertIn("adaptive_threshold", kinds)
            self.assertIn("signature_otsu_threshold", kinds)
            self.assertIn("region_01", kinds)
            self.assertTrue(all(row["derived"] for row in result["artifacts"]))
            self.assertEqual(result["photos"][0]["role"], "signature")
            self.assertIn(result["signature_evidence"]["ocr_status"], {"completed", "no_text", "unavailable", "failed"})
            self.assertTrue(result["signature_evidence"]["evidence_artifacts"])
            self.assertLessEqual(len(result["signature_evidence"]["query_suggestions"]), 5)
            self.assertTrue(result["recommended_next_photos"])

    def test_matching_accepts_perspective_variant_and_rejects_unrelated_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            transformed = root / "transformed.png"
            unrelated = root / "unrelated.png"
            self._artwork(source)
            array = cv2.imread(str(source))
            height, width = array.shape[:2]
            matrix = cv2.getPerspectiveTransform(
                np.float32([[0, 0], [width, 0], [width, height], [0, height]]),
                np.float32([[30, 20], [width - 50, 0], [width - 5, height - 25], [45, height]]),
            )
            cv2.imwrite(str(transformed), cv2.warpPerspective(array, matrix, (width, height)))
            Image.new("RGB", (900, 700), "#d8c6a0").save(unrelated)
            accepted = compare_images(source, transformed)
            rejected = compare_images(source, unrelated)
            self.assertTrue(accepted["geometry_verified"])
            self.assertIn(accepted["status"], {"possible", "strong"})
            self.assertEqual(rejected["status"], "rejected")
            self.assertFalse(rejected["geometry_verified"])


if __name__ == "__main__":
    unittest.main()
