"""Conservative, local-first preprocessing and optional OCR for artist signatures."""

from __future__ import annotations

import importlib
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

import cv2
import numpy as np
from PIL import Image, ImageOps


MAX_SIGNATURE_PIXELS = 25_000_000
MAX_CANDIDATES = 10
MAX_QUERY_SUGGESTIONS = 5


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def _confidence_label(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "low"
    return "high" if number >= 0.75 else "medium" if number >= 0.4 else "low"


def _encode_png(array: np.ndarray) -> bytes:
    output = BytesIO()
    Image.fromarray(array).save(output, format="PNG", optimize=True)
    return output.getvalue()


def _bbox(value: Any) -> list[int]:
    try:
        points = np.asarray(value, dtype=float).reshape(-1, 2)
    except (TypeError, ValueError):
        return []
    if not len(points):
        return []
    return [
        int(round(float(points[:, 0].min()))),
        int(round(float(points[:, 1].min()))),
        int(round(float(points[:, 0].max()))),
        int(round(float(points[:, 1].max()))),
    ]


def preprocess_signature(image: Image.Image) -> Dict[str, np.ndarray]:
    """Create OCR-oriented views without modifying the supplied image."""

    if image.width * image.height > MAX_SIGNATURE_PIXELS:
        raise ValueError("Signature crops may not exceed 25 megapixels")
    if image.width < 3 or image.height < 3:
        raise ValueError("Signature crops must be at least 3 by 3 pixels")
    original = ImageOps.exif_transpose(image).convert("RGB")
    array = np.asarray(original, dtype=np.uint8)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    autocontrast = np.asarray(ImageOps.autocontrast(Image.fromarray(gray)), dtype=np.uint8)
    gaussian = cv2.GaussianBlur(autocontrast, (5, 5), 0)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gaussian)
    adaptive = cv2.adaptiveThreshold(
        clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, 7,
    )
    _, otsu = cv2.threshold(gaussian, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    edges = cv2.Canny(clahe, 60, 160)
    return {
        "grayscale_autocontrast": autocontrast,
        "gaussian_denoised": gaussian,
        "clahe": clahe,
        "adaptive_threshold": adaptive,
        "otsu_threshold": otsu,
        "edges": edges,
    }


def _normalized_spelling(value: str) -> str:
    cleaned = re.sub(r"[^\wÀ-ÖØ-öø-ÿ.'’\- ]+", " ", value, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    return cleaned


def query_suggestions(candidates: Iterable[Dict[str, Any]], limit: int = MAX_QUERY_SUGGESTIONS) -> list[str]:
    rows: list[str] = []
    for candidate in candidates:
        text = _clean(candidate.get("text"), 120) if isinstance(candidate, dict) else ""
        if not text:
            continue
        for query in (f'"{text}" artist signature', f'"{text}" painter artist'):
            if query.casefold() not in {row.casefold() for row in rows}:
                rows.append(query)
            if len(rows) >= max(1, min(limit, MAX_QUERY_SUGGESTIONS)):
                return rows
    return rows


def normalize_model_candidates(
    values: Any,
    *,
    confidence: str = "low",
    evidence: Iterable[str] = (),
    limitations: Iterable[str] = (),
) -> list[Dict[str, Any]]:
    """Normalize vision-model readings as explicitly labeled hypotheses."""

    if not isinstance(values, list):
        return []
    rows: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        source = value if isinstance(value, dict) else {"text": value}
        text = _clean(source.get("text") or source.get("candidate"), 160)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        candidate_confidence = str(source.get("confidence") or confidence).casefold()
        if candidate_confidence not in {"low", "medium", "high"}:
            candidate_confidence = "low"
        candidate_evidence = source.get("evidence") if isinstance(source.get("evidence"), list) else list(evidence)
        candidate_limitations = source.get("limitations") if isinstance(source.get("limitations"), list) else list(limitations)
        rows.append({
            "text": text,
            "kind": "hypothesis",
            "confidence": candidate_confidence,
            "source": "vision_llm",
            "evidence": [_clean(item, 300) for item in candidate_evidence if _clean(item, 300)][:8],
            "limitations": [_clean(item, 300) for item in candidate_limitations if _clean(item, 300)][:8],
        })
        if len(rows) >= MAX_CANDIDATES:
            break
    return rows


class SignatureAnalyzer:
    def __init__(self, reader_factory: Callable[[list[str]], Any] | None = None):
        self.reader_factory = reader_factory

    @staticmethod
    def _languages() -> list[str]:
        values = [value.strip() for value in os.environ.get("VERIDEX_EASYOCR_LANGUAGES", "en").split(",")]
        rows = list(dict.fromkeys(value for value in values if re.fullmatch(r"[A-Za-z_]+", value)))[:4]
        return rows or ["en"]

    def _reader(self) -> Any:
        languages = self._languages()
        if self.reader_factory:
            return self.reader_factory(languages)
        try:
            easyocr = importlib.import_module("easyocr")
        except ImportError as exc:
            raise RuntimeError("EasyOCR is not installed") from exc
        try:
            return easyocr.Reader(languages, gpu=False, download_enabled=False, verbose=False)
        except Exception as exc:
            raise RuntimeError(f"EasyOCR or its local model files are unavailable: {_clean(exc, 180)}") from exc

    @staticmethod
    def _artifacts(variants: Dict[str, np.ndarray], file_id: str) -> list[Dict[str, Any]]:
        labels = {
            "grayscale_autocontrast": "Signature grayscale and autocontrast",
            "gaussian_denoised": "Signature Gaussian-denoised view",
            "clahe": "Signature local-contrast view",
            "adaptive_threshold": "Signature adaptive-threshold view",
            "otsu_threshold": "Signature Otsu-threshold view",
            "edges": "Signature edge view",
        }
        return [{
            "name": f"{re.sub(r'[^A-Za-z0-9_-]+', '_', file_id)[:80]}_signature_{kind}.png",
            "content": _encode_png(array),
            "content_type": "image/png",
            "kind": f"signature_{kind}",
            "label": labels[kind],
            "source_file_id": file_id,
            "derived": True,
        } for kind, array in variants.items()]

    @staticmethod
    def _fragments(reader: Any, variants: Dict[str, np.ndarray]) -> list[Dict[str, Any]]:
        rows: Dict[tuple[str, tuple[int, ...]], Dict[str, Any]] = {}
        for variant_name in ("clahe", "adaptive_threshold", "otsu_threshold"):
            for item in reader.readtext(variants[variant_name], detail=1, paragraph=False) or []:
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                text = _clean(item[1], 160)
                if not text:
                    continue
                try:
                    confidence = max(0.0, min(1.0, float(item[2])))
                except (TypeError, ValueError):
                    confidence = 0.0
                bbox = _bbox(item[0])
                key = (text.casefold(), tuple(bbox))
                previous = rows.get(key)
                if previous is None or confidence > previous["confidence"]:
                    rows[key] = {
                        "text": text,
                        "confidence": round(confidence, 4),
                        "bbox": bbox,
                        "variant": variant_name,
                    }
        return sorted(rows.values(), key=lambda row: (-row["confidence"], row["bbox"][1] if row["bbox"] else 0))[:20]

    @staticmethod
    def _candidates(fragments: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        candidates: list[Dict[str, Any]] = []
        seen: set[str] = set()

        def add(text: str, kind: str, confidence: str, source: str, evidence: list[str], limitations: list[str]) -> None:
            key = text.casefold()
            if not text or key in seen or len(candidates) >= MAX_CANDIDATES:
                return
            seen.add(key)
            candidates.append({
                "text": text,
                "kind": kind,
                "confidence": confidence,
                "source": source,
                "evidence": evidence,
                "limitations": limitations,
            })

        ordered = sorted(fragments, key=lambda row: (row["bbox"][1] if row["bbox"] else 0, row["bbox"][0] if row["bbox"] else 0))
        if len(ordered) > 1:
            joined = _clean(" ".join(row["text"] for row in ordered), 160)
            average = sum(row["confidence"] for row in ordered) / len(ordered)
            add(
                joined, "literal", _confidence_label(average), "easyocr",
                [f"Bundled {len(ordered)} OCR fragments in reading order."],
                ["Fragment order is geometric and may not match the intended cursive reading."],
            )
        for index, fragment in enumerate(fragments, start=1):
            raw = fragment["text"]
            evidence = [f"OCR fragment {index} from {fragment['variant']} at confidence {fragment['confidence']:.2f}."]
            add(raw, "literal", _confidence_label(fragment["confidence"]), "easyocr", evidence, ["Stylized lettering and canvas texture can reduce OCR accuracy."])
            normalized = _normalized_spelling(raw)
            if normalized and normalized != raw:
                add(normalized, "normalized", _confidence_label(fragment["confidence"]), "normalization", evidence, ["Only punctuation and spacing were normalized; the reading remains uncertain."])
        return candidates

    def analyze_image(self, image: Image.Image, file_id: str, *, region_normalized: Dict[str, float] | None = None) -> Dict[str, Any]:
        variants = preprocess_signature(image.copy())
        artifacts = self._artifacts(variants, file_id)
        if region_normalized:
            for artifact in artifacts:
                artifact["region_normalized"] = dict(region_normalized)
        limitations = [
            "OCR readings are search hypotheses, not authentication or authorship attribution.",
            "Canvas texture, glare, abrasion, and connected cursive strokes can produce false characters.",
        ]
        try:
            reader = self._reader()
            fragments = self._fragments(reader, variants)
            status = "completed" if fragments else "no_text"
        except RuntimeError as exc:
            fragments = []
            status = "unavailable"
            limitations.append(str(exc))
        except Exception as exc:
            fragments = []
            status = "failed"
            limitations.append(f"EasyOCR could not analyze this crop: {_clean(exc, 200)}")
        candidates = self._candidates(fragments)
        artifact_refs = [{
            "name": row["name"], "kind": row["kind"], "source_file_id": row["source_file_id"],
        } for row in artifacts]
        return {
            "application": "undetermined",
            "ocr_status": status,
            "ocr_fragments": fragments,
            "transcription_candidates": candidates,
            "query_suggestions": query_suggestions(candidates),
            "evidence_artifacts": artifact_refs,
            "limitations": limitations,
            "region_normalized": region_normalized,
            "artifacts": artifacts,
        }

    def analyze_path(self, path: Path, file_id: str = "signature") -> Dict[str, Any]:
        candidate = Path(path)
        if not candidate.is_file():
            raise ValueError("Signature image is unavailable")
        with Image.open(candidate) as opened:
            return self.analyze_image(opened.copy(), file_id)


def combine_signature_evidence(values: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    analyses = [value for value in values if isinstance(value, dict)]
    fragments: list[Dict[str, Any]] = []
    candidates: list[Dict[str, Any]] = []
    artifacts: list[Dict[str, Any]] = []
    limitations: list[str] = []
    seen_fragments: set[tuple[str, tuple[int, ...], str]] = set()
    seen_candidates: set[str] = set()
    for analysis in analyses:
        for fragment in analysis.get("ocr_fragments") or []:
            key = (str(fragment.get("text") or "").casefold(), tuple(fragment.get("bbox") or []), str(fragment.get("variant") or ""))
            if key not in seen_fragments:
                seen_fragments.add(key)
                fragments.append(fragment)
        for candidate in analysis.get("transcription_candidates") or []:
            key = str(candidate.get("text") or "").casefold()
            if key and key not in seen_candidates and len(candidates) < MAX_CANDIDATES:
                seen_candidates.add(key)
                candidates.append(candidate)
        artifacts.extend(analysis.get("evidence_artifacts") or [])
        for limitation in analysis.get("limitations") or []:
            text = _clean(limitation, 300)
            if text and text not in limitations:
                limitations.append(text)
    statuses = {str(value.get("ocr_status") or "") for value in analyses}
    status = "not_requested" if not analyses else "completed" if fragments else "failed" if "failed" in statuses else "unavailable" if "unavailable" in statuses else "no_text"
    return {
        "application": "undetermined",
        "ocr_status": status,
        "ocr_fragments": fragments[:30],
        "transcription_candidates": candidates,
        "query_suggestions": query_suggestions(candidates),
        "evidence_artifacts": artifacts[:30],
        "limitations": limitations[:20],
    }
