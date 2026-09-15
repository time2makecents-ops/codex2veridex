"""Deterministic, local-first visual evidence for Museum cases."""

from __future__ import annotations

import math
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageEnhance, ImageOps


MAX_PIXELS = 50_000_000
MAX_ANALYSIS_EDGE = 2400
TILE_SIZE = 1536
TILE_OVERLAP = 192
PHOTO_ROLES = (
    "front",
    "back",
    "signature",
    "surface_raking_light",
    "edge_support",
    "frame_front",
    "frame_back",
    "label_or_mark",
    "other",
)
FOCUS_OPTIONS = ("all", "medium", "signature", "frame", "match")


def _safe_name(value: Any, fallback: str = "image") -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "")).strip("_")[:80] or fallback


def _encode(image: Image.Image, format_name: str = "JPEG") -> bytes:
    output = BytesIO()
    if format_name == "PNG":
        image.save(output, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def _normalize_image(path: Path) -> tuple[Image.Image, Dict[str, Any]]:
    with Image.open(path) as opened:
        if opened.width * opened.height > MAX_PIXELS:
            raise ValueError("Museum images may not exceed 50 megapixels")
        metadata = {
            "original_width": opened.width,
            "original_height": opened.height,
            "original_mode": opened.mode,
            "format": opened.format or "unknown",
            "exif_orientation_applied": bool(opened.getexif().get(274)),
            "icc_profile_applied": False,
        }
        image = ImageOps.exif_transpose(opened)
        profile = image.info.get("icc_profile")
        if profile:
            try:
                source_profile = ImageCms.ImageCmsProfile(BytesIO(profile))
                image = ImageCms.profileToProfile(image, source_profile, ImageCms.createProfile("sRGB"), outputMode="RGB")
                metadata["icc_profile_applied"] = True
            except (OSError, TypeError, ValueError):
                image = image.convert("RGB")
        else:
            image = image.convert("RGB")
        return image.copy(), metadata


def _analysis_array(image: Image.Image) -> np.ndarray:
    working = image.copy()
    working.thumbnail((MAX_ANALYSIS_EDGE, MAX_ANALYSIS_EDGE), Image.Resampling.LANCZOS)
    return np.asarray(working.convert("RGB"), dtype=np.uint8)


def _dominant_palette(image: Image.Image, colors: int = 6) -> list[Dict[str, Any]]:
    sample = image.copy()
    sample.thumbnail((512, 512), Image.Resampling.LANCZOS)
    quantized = sample.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = quantized.getpalette() or []
    counts = quantized.getcolors(maxcolors=colors) or []
    total = max(1, sum(count for count, _ in counts))
    rows = []
    for count, index in sorted(counts, reverse=True):
        red, green, blue = palette[index * 3:index * 3 + 3]
        rows.append({
            "hex": f"#{red:02x}{green:02x}{blue:02x}",
            "rgb": [red, green, blue],
            "percent": round(count * 100 / total, 2),
        })
    return rows


def _periodicity_score(gray: np.ndarray) -> float:
    sample = cv2.resize(gray, (512, 512), interpolation=cv2.INTER_AREA)
    residual = sample.astype(np.float32) - cv2.GaussianBlur(sample, (0, 0), 3).astype(np.float32)
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(residual)))
    center = spectrum.shape[0] // 2
    spectrum[center - 12:center + 13, center - 12:center + 13] = 0
    baseline = float(np.median(spectrum))
    if baseline <= 0:
        return 0.0
    peak = float(np.percentile(spectrum, 99.95))
    return round(min(1.0, max(0.0, (peak / baseline - 8.0) / 32.0)), 4)


def image_metrics(image: Image.Image) -> Dict[str, Any]:
    rgb = _analysis_array(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    highlight = float(np.mean(np.max(rgb, axis=2) >= 250) * 100)
    shadow = float(np.mean(np.max(rgb, axis=2) <= 8) * 100)
    edges = cv2.Canny(gray, 80, 180)
    means = np.mean(rgb.reshape(-1, 3), axis=0)
    return {
        "width": image.width,
        "height": image.height,
        "megapixels": round(image.width * image.height / 1_000_000, 3),
        "sharpness_laplacian_variance": round(sharpness, 2),
        "sharpness_rating": "low" if sharpness < 55 else "usable" if sharpness < 180 else "high",
        "highlight_clipping_percent": round(highlight, 3),
        "shadow_clipping_percent": round(shadow, 3),
        "glare_warning": highlight >= 2.5,
        "edge_density_percent": round(float(np.mean(edges > 0) * 100), 3),
        "mean_rgb": [round(float(value), 2) for value in means],
        "mean_lab": [round(float(value), 2) for value in np.mean(lab.reshape(-1, 3), axis=0)],
        "mean_saturation": round(float(np.mean(hsv[:, :, 1])), 2),
        "color_cast_index": round(float((max(means) - min(means)) / max(1.0, np.mean(means))), 4),
        "periodic_pattern_score": _periodicity_score(gray),
        "periodic_pattern_note": "A high score can indicate repeating print structure, fabric weave, screen pixels, or camera artifacts; it is not proof of reproduction.",
        "dominant_palette": _dominant_palette(image),
    }


def _dhash(gray: np.ndarray, size: int = 16) -> np.ndarray:
    resized = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    return (resized[:, 1:] > resized[:, :-1]).reshape(-1)


def _gradient_descriptor(gray: np.ndarray) -> np.ndarray:
    resized = cv2.resize(gray, (512, 512), interpolation=cv2.INTER_AREA).astype(np.float32)
    gx = cv2.Sobel(resized, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(resized, cv2.CV_32F, 0, 1, ksize=3)
    magnitude, angle = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    histogram, _ = np.histogram(angle, bins=18, range=(0, 360), weights=magnitude)
    norm = np.linalg.norm(histogram)
    return histogram / norm if norm else histogram


def compare_images(source_path: Path, candidate_path: Path) -> Dict[str, Any]:
    source, _ = _normalize_image(source_path)
    candidate, _ = _normalize_image(candidate_path)
    left = cv2.cvtColor(_analysis_array(source), cv2.COLOR_RGB2GRAY)
    right = cv2.cvtColor(_analysis_array(candidate), cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(nfeatures=2500, scaleFactor=1.2, nlevels=8)
    left_points, left_desc = orb.detectAndCompute(left, None)
    right_points, right_desc = orb.detectAndCompute(right, None)
    good = []
    inliers = 0
    inlier_ratio = 0.0
    if left_desc is not None and right_desc is not None and len(left_desc) >= 2 and len(right_desc) >= 2:
        for pair in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(left_desc, right_desc, k=2):
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
                good.append(pair[0])
        if len(good) >= 8:
            source_points = np.float32([left_points[match.queryIdx].pt for match in good]).reshape(-1, 1, 2)
            candidate_points = np.float32([right_points[match.trainIdx].pt for match in good]).reshape(-1, 1, 2)
            _, mask = cv2.findHomography(source_points, candidate_points, cv2.RANSAC, 5.0)
            if mask is not None:
                inliers = int(mask.sum())
                inlier_ratio = inliers / max(1, len(good))
    hash_similarity = 1.0 - float(np.mean(_dhash(left) != _dhash(right)))
    gradient_similarity = float(np.clip(np.dot(_gradient_descriptor(left), _gradient_descriptor(right)), 0, 1))
    left_hist = cv2.calcHist([cv2.cvtColor(_analysis_array(source), cv2.COLOR_RGB2HSV)], [0, 1], None, [24, 16], [0, 180, 0, 256])
    right_hist = cv2.calcHist([cv2.cvtColor(_analysis_array(candidate), cv2.COLOR_RGB2HSV)], [0, 1], None, [24, 16], [0, 180, 0, 256])
    cv2.normalize(left_hist, left_hist)
    cv2.normalize(right_hist, right_hist)
    color_similarity = float(np.clip((cv2.compareHist(left_hist, right_hist, cv2.HISTCMP_CORREL) + 1) / 2, 0, 1))
    geometry = min(1.0, inliers / 40.0) * 0.5 + min(1.0, inlier_ratio) * 0.5
    score = 0.55 * geometry + 0.20 * hash_similarity + 0.15 * gradient_similarity + 0.10 * color_similarity
    geometry_verified = inliers >= 10 and inlier_ratio >= 0.25
    if not geometry_verified:
        score = min(score, 0.49)
    status = "strong" if geometry_verified and score >= 0.75 else "possible" if geometry_verified and score >= 0.55 else "rejected"
    return {
        "status": status,
        "score": round(score, 4),
        "geometry_verified": geometry_verified,
        "keypoints": [len(left_points), len(right_points)],
        "ratio_test_matches": len(good),
        "homography_inliers": inliers,
        "inlier_ratio": round(inlier_ratio, 4),
        "hash_similarity": round(hash_similarity, 4),
        "gradient_similarity": round(gradient_similarity, 4),
        "color_similarity": round(color_similarity, 4),
        "reason": "Geometrically consistent local features support this match." if geometry_verified else "Insufficient geometrically consistent features; similarity alone was rejected.",
    }


class MuseumVisualAnalyzer:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root).resolve()

    @staticmethod
    def _artifact(image: Image.Image, file_id: str, kind: str, label: str, suffix: str = ".jpg") -> Dict[str, Any]:
        return {
            "name": f"{_safe_name(file_id)}_{_safe_name(kind)}{suffix}",
            "content": _encode(image, "PNG" if suffix == ".png" else "JPEG"),
            "content_type": "image/png" if suffix == ".png" else "image/jpeg",
            "kind": kind,
            "label": label,
            "source_file_id": file_id,
            "derived": True,
        }

    @staticmethod
    def _tiles(image: Image.Image, file_id: str) -> list[Dict[str, Any]]:
        if image.width <= TILE_SIZE and image.height <= TILE_SIZE:
            return []
        step = TILE_SIZE - TILE_OVERLAP
        xs = list(range(0, max(1, image.width - TILE_SIZE + 1), step))
        ys = list(range(0, max(1, image.height - TILE_SIZE + 1), step))
        if not xs or xs[-1] != max(0, image.width - TILE_SIZE):
            xs.append(max(0, image.width - TILE_SIZE))
        if not ys or ys[-1] != max(0, image.height - TILE_SIZE):
            ys.append(max(0, image.height - TILE_SIZE))
        artifacts = []
        for index, (left, top) in enumerate(((x, y) for y in ys for x in xs), start=1):
            if index > 16:
                break
            tile = image.crop((left, top, min(image.width, left + TILE_SIZE), min(image.height, top + TILE_SIZE)))
            artifact = MuseumVisualAnalyzer._artifact(tile, file_id, f"detail_tile_{index:02d}", f"Detail tile {index}")
            artifact["region_pixels"] = {"x": left, "y": top, "width": tile.width, "height": tile.height}
            artifacts.append(artifact)
        return artifacts

    @staticmethod
    def _region_artifacts(image: Image.Image, file_id: str, regions: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        artifacts = []
        for index, region in enumerate(regions, start=1):
            try:
                x = min(1.0, max(0.0, float(region.get("x", 0))))
                y = min(1.0, max(0.0, float(region.get("y", 0))))
                width = min(1.0 - x, max(0.01, float(region.get("width", 0))))
                height = min(1.0 - y, max(0.01, float(region.get("height", 0))))
            except (TypeError, ValueError):
                continue
            box = (round(x * image.width), round(y * image.height), round((x + width) * image.width), round((y + height) * image.height))
            crop = image.crop(box)
            label = str(region.get("label") or f"Region {index}")[:80]
            base = MuseumVisualAnalyzer._artifact(crop, file_id, f"region_{index:02d}", label)
            base["region_normalized"] = {"x": x, "y": y, "width": width, "height": height}
            artifacts.append(base)
            enhanced = ImageEnhance.Contrast(ImageOps.autocontrast(crop.convert("L"))).enhance(1.6)
            artifacts.append(MuseumVisualAnalyzer._artifact(enhanced.convert("RGB"), file_id, f"region_{index:02d}_contrast", f"{label} — contrast view"))
        return artifacts

    def analyze(
        self,
        attachments: list[Dict[str, Any]],
        *,
        mode: str = "quick",
        focus: str = "all",
        photo_roles: Dict[str, str] | None = None,
        regions: Dict[str, list[Dict[str, Any]]] | None = None,
        comparison_pairs: Iterable[Dict[str, str]] = (),
        progress: Callable[[int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> Dict[str, Any]:
        mode = "detailed" if mode in {"deep", "detailed"} else "quick"
        focus = focus if focus in FOCUS_OPTIONS else "all"
        roles = photo_roles or {}
        regions = regions or {}
        artifacts: list[Dict[str, Any]] = []
        photos: list[Dict[str, Any]] = []
        paths = {str(row.get("file_id")): Path(str(row.get("path") or "")) for row in attachments}
        for index, row in enumerate(attachments, start=1):
            if cancelled and cancelled():
                raise RuntimeError("Museum analysis canceled")
            file_id = str(row.get("file_id") or "")
            image, normalization = _normalize_image(paths[file_id])
            role = roles.get(file_id, "other")
            if role not in PHOTO_ROLES:
                role = "other"
            preview = image.copy()
            preview.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            artifacts.append(self._artifact(preview, file_id, "normalized_overview", "Normalized sRGB overview"))
            gray = ImageOps.grayscale(preview)
            artifacts.append(self._artifact(ImageOps.autocontrast(gray).convert("RGB"), file_id, "grayscale_contrast", "Grayscale contrast view"))
            array = np.asarray(preview.convert("RGB"), dtype=np.uint8)
            gray_array = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray_array)
            edges = cv2.Canny(gray_array, 80, 180)
            threshold = cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 7)
            artifacts.append(self._artifact(Image.fromarray(clahe).convert("RGB"), file_id, "local_contrast", "Local contrast view"))
            artifacts.append(self._artifact(Image.fromarray(edges).convert("RGB"), file_id, "edge_map", "Computed edge map"))
            if role in {"signature", "label_or_mark"} or focus == "signature":
                artifacts.append(self._artifact(Image.fromarray(threshold).convert("RGB"), file_id, "adaptive_threshold", "Adaptive threshold view"))
            artifacts.extend(self._region_artifacts(image, file_id, regions.get(file_id, [])))
            if mode == "detailed":
                artifacts.extend(self._tiles(image, file_id))
            metrics = image_metrics(image)
            limitations = []
            if metrics["sharpness_rating"] == "low":
                limitations.append("Low sharpness can hide brush texture, print dots, and signature stroke edges.")
            if metrics["glare_warning"]:
                limitations.append("Clipped highlights or glare can conceal surface evidence.")
            if role == "other":
                limitations.append("Assigning a photo role improves interpretation and missing-view guidance.")
            photos.append({
                "file_id": file_id,
                "name": str(row.get("name") or row.get("original_name") or file_id),
                "role": role,
                "normalization": normalization,
                "metrics": metrics,
                "limitations": limitations,
            })
            if progress:
                progress(15 + round(index * 45 / max(1, len(attachments))), f"Analyzed photo {index} of {len(attachments)}")
        matches = []
        for pair in comparison_pairs:
            source_id = str(pair.get("source_file_id") or "")
            candidate_id = str(pair.get("candidate_file_id") or "")
            if source_id in paths and candidate_id in paths and source_id != candidate_id:
                matches.append({"source_file_id": source_id, "candidate_file_id": candidate_id, **compare_images(paths[source_id], paths[candidate_id])})
        present_roles = {photo["role"] for photo in photos}
        recommended = []
        for role, reason in (
            ("front", "a straight, evenly lit full view for composition and proportions"),
            ("back", "the reverse for labels, construction, and support evidence"),
            ("signature", "a sharp macro photograph of the signature or mark"),
            ("surface_raking_light", "a low-angle light view for surface relief and brush texture"),
            ("edge_support", "an edge view showing canvas, paper, board, panel, or other support"),
            ("frame_back", "the frame reverse for joinery, hardware, labels, and alterations"),
        ):
            if role not in present_roles:
                recommended.append({"role": role, "reason": reason})
        return {
            "analysis_version": 1,
            "mode": mode,
            "focus": focus,
            "photos": photos,
            "matches": matches,
            "recommended_next_photos": recommended,
            "observations": [],
            "interpretations": [],
            "limitations": [
                "Derived contrast, threshold, and edge views are processing aids, not newly observed physical detail.",
                "Color values are camera-dependent unless a neutral reference or color target was photographed.",
                "Photographs alone cannot authenticate an artwork, prove authorship, or establish value.",
            ],
            "artifacts": artifacts,
        }
