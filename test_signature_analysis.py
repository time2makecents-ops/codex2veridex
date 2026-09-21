from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from signature_analysis import (
    SignatureAnalyzer,
    normalize_model_candidates,
    preprocess_signature,
    query_suggestions,
)


class FakeReader:
    def readtext(self, _image, detail=1, paragraph=False):
        self.options = (detail, paragraph)
        return [
            ([[5, 5], [65, 5], [65, 30], [5, 30]], "J. Test", 0.82),
            ([[70, 6], [120, 6], [120, 30], [70, 30]], "'72", 0.31),
        ]


class SignatureAnalysisTests(unittest.TestCase):
    @staticmethod
    def _image() -> Image.Image:
        image = Image.new("RGB", (240, 90), "#d3bb91")
        draw = ImageDraw.Draw(image)
        draw.line((10, 55, 220, 25), fill="#25180f", width=4)
        draw.text((20, 30), "J. Test", fill="#25180f")
        return image

    def test_preprocessing_produces_expected_ocr_views_without_changing_source(self) -> None:
        image = self._image()
        before = np.asarray(image).copy()
        variants = preprocess_signature(image)
        self.assertEqual(
            set(variants),
            {"grayscale_autocontrast", "gaussian_denoised", "clahe", "adaptive_threshold", "otsu_threshold", "edges"},
        )
        self.assertTrue(all(value.shape == (90, 240) for value in variants.values()))
        self.assertTrue(np.array_equal(before, np.asarray(image)))

    def test_optional_easyocr_unavailable_returns_artifacts_and_limitations(self) -> None:
        analyzer = SignatureAnalyzer()
        with patch("signature_analysis.importlib.import_module", side_effect=ImportError("missing")):
            result = analyzer.analyze_image(self._image(), "file_one")
        self.assertEqual(result["ocr_status"], "unavailable")
        self.assertEqual(result["ocr_fragments"], [])
        self.assertEqual(len(result["artifacts"]), 6)
        self.assertTrue(any("not installed" in value for value in result["limitations"]))

    def test_fragments_candidates_and_queries_retain_provenance(self) -> None:
        analyzer = SignatureAnalyzer(reader_factory=lambda languages: FakeReader())
        result = analyzer.analyze_image(self._image(), "file_one")
        self.assertEqual(result["ocr_status"], "completed")
        self.assertTrue(result["ocr_fragments"])
        self.assertTrue(all(set(("text", "confidence", "bbox")) <= set(row) for row in result["ocr_fragments"]))
        self.assertTrue(all(row["kind"] in {"literal", "normalized"} for row in result["transcription_candidates"]))
        self.assertTrue(all(row["source"] in {"easyocr", "normalization"} for row in result["transcription_candidates"]))
        self.assertLessEqual(len(result["query_suggestions"]), 5)
        self.assertTrue(all("artist" in query for query in result["query_suggestions"]))

    def test_model_readings_are_hypotheses_not_attributions(self) -> None:
        candidates = normalize_model_candidates(
            ["Jane Test", {"text": "J. Tess", "confidence": "medium"}],
            evidence=["Letter shapes may support this reading."],
            limitations=["Final letter is unclear."],
        )
        self.assertEqual({row["kind"] for row in candidates}, {"hypothesis"})
        self.assertEqual({row["source"] for row in candidates}, {"vision_llm"})
        self.assertNotIn("attribution", candidates[0])
        self.assertLessEqual(len(query_suggestions(candidates)), 5)

    def test_path_validation_rejects_missing_signature_crop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                SignatureAnalyzer().analyze_path(Path(temporary) / "missing.png")


if __name__ == "__main__":
    unittest.main()
