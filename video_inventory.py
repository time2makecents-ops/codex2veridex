"""Local, review-first extraction of inventory images from video.

The extractor chooses useful *views*, not identified objects. Human approval (and,
when needed, a rectangle or lasso) remains the boundary before spreadsheet rows are
created. Source videos are read-only and every derived artifact records provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from batch_inventory import ItemSelection, create_inventory_workbook, render_selection


VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
MAX_VIDEO_BYTES = 20 * 1024 * 1024 * 1024
MAX_DURATION_SECONDS = 2 * 60 * 60
MAX_FRAME_PIXELS = 50_000_000
VALID_ROTATIONS = {0, 90, 180, 270}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(root: Path, value: str) -> Path:
    candidate = (root / str(value or "")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("manifest image path escapes its project directory")
    return candidate


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _rotate_clockwise(image: Image.Image, degrees: int) -> Image.Image:
    degrees = int(degrees)
    if degrees not in VALID_ROTATIONS:
        raise ValueError("rotation must be 0, 90, 180, or 270 degrees clockwise")
    if degrees == 0:
        return image.copy()
    return image.rotate(-degrees, expand=True)


def _load_verified_manifest(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "veridex.video_inventory.v1":
        raise ValueError("unsupported video inventory manifest")
    project_dir = manifest_path.parent
    source = Path(str((manifest.get("source") or {}).get("path") or "")).resolve()
    expected_source_hash = str((manifest.get("source") or {}).get("sha256") or "")
    if not source.is_file() or _sha256(source) != expected_source_hash:
        raise ValueError("source video is missing or changed")
    for candidate in manifest.get("candidates") or []:
        image_path = _safe_relative_path(project_dir, str(candidate.get("image_path") or ""))
        if not image_path.is_file() or _sha256(image_path) != str(candidate.get("image_sha256") or ""):
            raise ValueError(f"candidate image is missing or changed: {candidate.get('candidate_id')}")
    return manifest, project_dir


def _analysis_frame(frame: np.ndarray, maximum_width: int = 480) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= maximum_width:
        return frame
    scale = maximum_width / width
    return cv2.resize(frame, (maximum_width, max(1, round(height * scale))), interpolation=cv2.INTER_AREA)


def _difference_hash(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def _color_histogram(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    return cv2.normalize(histogram, histogram).flatten()


def _frame_metrics(frame: np.ndarray, previous_gray: np.ndarray | None) -> tuple[dict[str, float], np.ndarray, int, np.ndarray]:
    analysis = _analysis_frame(frame)
    gray = cv2.cvtColor(analysis, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    if previous_gray is None:
        motion = 0.0
    else:
        if previous_gray.shape != gray.shape:
            previous_gray = cv2.resize(previous_gray, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_AREA)
        motion = float(np.mean(cv2.absdiff(gray, previous_gray)) / 255.0)
    exposure_penalty = abs(brightness - 127.5) / 127.5
    score = math.log1p(sharpness) * max(0.15, 1.0 - 0.55 * exposure_penalty) / (1.0 + 4.0 * motion)
    return (
        {
            "sharpness": round(sharpness, 3),
            "brightness": round(brightness, 3),
            "motion": round(motion, 6),
            "quality_score": round(score, 6),
        },
        gray,
        _difference_hash(gray),
        _color_histogram(analysis),
    )


def _near_duplicate(left: dict[str, Any], right: dict[str, Any]) -> bool:
    hamming = int(left["difference_hash"] ^ right["difference_hash"]).bit_count()
    correlation = float(cv2.compareHist(left["histogram"], right["histogram"], cv2.HISTCMP_CORREL))
    return hamming <= 3 and correlation >= 0.995


def _even_quality_limit(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    boundaries = np.linspace(0, len(rows), limit + 1, dtype=int)
    values = []
    for index in range(limit):
        lower = int(boundaries[index])
        upper = int(boundaries[index + 1])
        values.append(max(rows[lower:upper], key=lambda row: row["quality_score"]))
    return sorted(values, key=lambda row: row["frame_index"])


def _quality_flags(row: dict[str, Any]) -> list[str]:
    flags = []
    if float(row["sharpness"]) < 35:
        flags.append("possibly_blurry")
    if float(row["brightness"]) < 35:
        flags.append("very_dark")
    elif float(row["brightness"]) > 225:
        flags.append("very_bright")
    if float(row["motion"]) > 0.18:
        flags.append("camera_motion")
    return flags


def _write_contact_sheet(project_dir: Path, candidates: Sequence[dict[str, Any]], columns: int = 4) -> Path:
    if not candidates:
        raise ValueError("video produced no review candidates")
    columns = max(1, min(6, int(columns)))
    tile_width, image_height, label_height = 360, 230, 68
    rows = math.ceil(len(candidates) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (image_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, candidate in enumerate(candidates):
        left = (index % columns) * tile_width
        top = (index // columns) * (image_height + label_height)
        image_path = _safe_relative_path(project_dir, candidate["image_path"])
        with Image.open(image_path) as opened:
            preview = ImageOps.contain(ImageOps.exif_transpose(opened).convert("RGB"), (tile_width - 16, image_height - 12))
        sheet.paste(preview, (left + (tile_width - preview.width) // 2, top + (image_height - preview.height) // 2))
        draw.rectangle((left, top, left + tile_width - 1, top + image_height + label_height - 1), outline=(115, 115, 115), width=2)
        flags = ", ".join(candidate.get("quality_flags") or []) or "review quality: clear"
        draw.text((left + 8, top + image_height + 6), f"{candidate['candidate_id']}  {candidate['timestamp_seconds']:.2f}s", fill="black")
        draw.text((left + 8, top + image_height + 28), f"score {candidate['quality_score']:.2f} · {flags}", fill=(110, 0, 0) if candidate.get("quality_flags") else (0, 80, 0))
    path = project_dir / "contact_sheet.jpg"
    sheet.save(path, format="JPEG", quality=92, optimize=True)
    return path


def extract_video_inventory_candidates(
    video_path: Path,
    project_dir: Path,
    *,
    sample_seconds: float = 0.5,
    window_seconds: float = 2.0,
    max_candidates: int = 80,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Extract sharp/stable candidate views and a numbered review contact sheet."""
    video_path = Path(video_path).resolve()
    project_dir = Path(project_dir).resolve()
    if not video_path.is_file() or video_path.suffix.casefold() not in VIDEO_EXTENSIONS:
        raise ValueError("supply an existing AVI, M4V, MKV, MOV, MP4, or WebM video")
    if video_path.stat().st_size <= 0 or video_path.stat().st_size > MAX_VIDEO_BYTES:
        raise ValueError("video is empty or exceeds the 20 GB safety limit")
    if (project_dir / "manifest.json").exists():
        raise FileExistsError("project already contains a manifest; choose a new output folder")
    sample_seconds = max(0.1, min(10.0, float(sample_seconds)))
    window_seconds = max(sample_seconds, min(30.0, float(window_seconds)))
    max_candidates = max(1, min(500, int(max_candidates)))

    source_hash = _sha256(video_path)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError("OpenCV could not open the video")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not math.isfinite(fps) or fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            raise ValueError("video metadata is incomplete")
        duration = frame_count / fps
        if duration > MAX_DURATION_SECONDS:
            raise ValueError("video exceeds the two-hour safety limit")
        if width * height > MAX_FRAME_PIXELS:
            raise ValueError("video frames exceed the 50-megapixel safety limit")

        step = max(1, round(fps * sample_seconds))
        window_frames = max(1, round(fps * window_seconds))
        indices = set(range(0, frame_count, step))
        indices.add(frame_count - 1)
        window_best: dict[int, dict[str, Any]] = {}
        previous_gray = None
        for frame_index in range(frame_count):
            if cancel_check and cancel_check():
                raise RuntimeError("video inventory extraction canceled")
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index not in indices:
                continue
            metrics, gray, difference_hash, histogram = _frame_metrics(frame, previous_gray)
            previous_gray = gray
            timestamp = frame_index / fps
            row = {
                "frame_index": frame_index,
                "timestamp_seconds": round(timestamp, 3),
                "difference_hash": difference_hash,
                "histogram": histogram,
                **metrics,
            }
            window = frame_index // window_frames
            if window not in window_best or row["quality_score"] > window_best[window]["quality_score"]:
                encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
                if not encoded:
                    raise RuntimeError(f"could not encode candidate frame {frame_index}")
                row["jpeg_bytes"] = jpeg.tobytes()
                window_best[window] = row

        candidates = sorted(window_best.values(), key=lambda row: row["frame_index"])
        unique: list[dict[str, Any]] = []
        duplicates = []
        for candidate in candidates:
            duplicate = next((row for row in reversed(unique[-6:]) if _near_duplicate(candidate, row)), None)
            if duplicate is not None:
                duplicates.append({
                    "frame_index": candidate["frame_index"],
                    "timestamp_seconds": candidate["timestamp_seconds"],
                    "duplicate_of_frame": duplicate["frame_index"],
                })
                if candidate["quality_score"] > duplicate["quality_score"]:
                    unique[unique.index(duplicate)] = candidate
                continue
            unique.append(candidate)
        unique = _even_quality_limit(sorted(unique, key=lambda row: row["frame_index"]), max_candidates)

        project_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = project_dir / "candidate_frames"
        frames_dir.mkdir(parents=True, exist_ok=False)
        manifest_candidates = []
        for number, candidate in enumerate(unique, start=1):
            candidate_id = f"view_{number:03d}"
            image_path = frames_dir / f"{candidate_id}_frame_{candidate['frame_index']:08d}.jpg"
            image_path.write_bytes(candidate["jpeg_bytes"])
            manifest_candidates.append({
                "candidate_id": candidate_id,
                "frame_index": candidate["frame_index"],
                "timestamp_seconds": candidate["timestamp_seconds"],
                "image_path": image_path.relative_to(project_dir).as_posix(),
                "image_sha256": _sha256(image_path),
                "sharpness": candidate["sharpness"],
                "brightness": candidate["brightness"],
                "motion": candidate["motion"],
                "quality_score": candidate["quality_score"],
                "quality_flags": _quality_flags(candidate),
                "review_status": "pending_human_review",
            })
    finally:
        capture.release()

    contact_sheet = _write_contact_sheet(project_dir, manifest_candidates)
    manifest = {
        "schema": "veridex.video_inventory.v1",
        "created_at": _utc_now(),
        "source": {
            "path": str(video_path),
            "sha256": source_hash,
            "byte_size": video_path.stat().st_size,
            "fps": round(fps, 6),
            "frame_count": frame_count,
            "duration_seconds": round(duration, 3),
            "width": width,
            "height": height,
        },
        "settings": {
            "sample_seconds": sample_seconds,
            "window_seconds": window_seconds,
            "max_candidates": max_candidates,
            "deduplication_policy": "near-identical full-frame views only; never treated as item identity",
        },
        "contact_sheet": contact_sheet.relative_to(project_dir).as_posix(),
        "contact_sheet_sha256": _sha256(contact_sheet),
        "candidates": manifest_candidates,
        "skipped_near_duplicates": duplicates,
        "review_required": True,
        "limitations": [
            "Candidates are video views, not automatically identified items.",
            "Approve each view and draw a rectangle or lasso when more than one item appears in it.",
            "Motion blur, occlusion, reflections, and unreadable labels require another view or photograph.",
        ],
    }
    manifest_path = project_dir / "manifest.json"
    temporary_path = project_dir / "manifest.json.tmp"
    temporary_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary_path.replace(manifest_path)
    if _sha256(video_path) != source_hash:
        raise RuntimeError("source video changed during extraction")
    return {**manifest, "manifest_path": str(manifest_path), "project_dir": str(project_dir)}


def _scene_features(image_path: Path) -> dict[str, Any]:
    frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"OpenCV could not read candidate image: {image_path}")
    analysis = _analysis_frame(frame, maximum_width=480)
    gray = cv2.cvtColor(analysis, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=500, fastThreshold=12)
    _keypoints, descriptors = orb.detectAndCompute(gray, None)
    return {
        "difference_hash": _difference_hash(gray),
        "histogram": _color_histogram(analysis),
        "descriptors": descriptors,
    }


def _orb_similarity(left: np.ndarray | None, right: np.ndarray | None) -> float:
    if left is None or right is None or len(left) < 8 or len(right) < 8:
        return 0.0
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(left, right)
    if not matches:
        return 0.0
    good = sum(1 for match in matches if match.distance <= 45)
    return good / max(1, min(len(left), len(right)))


def _same_scene(left: dict[str, Any], right: dict[str, Any]) -> bool:
    hamming = int(left["difference_hash"] ^ right["difference_hash"]).bit_count()
    histogram = float(cv2.compareHist(left["histogram"], right["histogram"], cv2.HISTCMP_CORREL))
    orb = _orb_similarity(left.get("descriptors"), right.get("descriptors"))
    return (hamming <= 18 and histogram >= 0.86) or (histogram >= 0.72 and orb >= 0.16)


def _group_scene_candidates(manifest: dict[str, Any], project_dir: Path) -> list[dict[str, Any]]:
    candidates = list(manifest.get("candidates") or [])
    if not candidates:
        raise ValueError("video manifest contains no candidates")
    enriched = []
    for candidate in candidates:
        image_path = _safe_relative_path(project_dir, str(candidate.get("image_path") or ""))
        enriched.append({"candidate": candidate, "features": _scene_features(image_path)})

    groups: list[list[dict[str, Any]]] = []
    for row in enriched:
        if not groups:
            groups.append([row])
            continue
        previous = groups[-1][-1]
        gap = float(row["candidate"].get("timestamp_seconds") or 0) - float(
            previous["candidate"].get("timestamp_seconds") or 0
        )
        if gap <= 6.0 and _same_scene(previous["features"], row["features"]):
            groups[-1].append(row)
        else:
            groups.append([row])

    results = []
    for number, group in enumerate(groups, start=1):
        representative = max(
            group,
            key=lambda row: float(row["candidate"].get("quality_score") or 0)
            - (0.7 if "camera_motion" in (row["candidate"].get("quality_flags") or []) else 0.0),
        )["candidate"]
        results.append({
            "scene_id": f"scene_{number:03d}",
            "representative_candidate_id": representative["candidate_id"],
            "candidate_ids": [row["candidate"]["candidate_id"] for row in group],
            "start_seconds": min(float(row["candidate"].get("timestamp_seconds") or 0) for row in group),
            "end_seconds": max(float(row["candidate"].get("timestamp_seconds") or 0) for row in group),
        })
    return results


def _write_orientation_sheet(
    output_dir: Path,
    project_dir: Path,
    candidate_index: dict[str, dict[str, Any]],
    scenes: Sequence[dict[str, Any]],
) -> Path:
    tile_width, image_height, label_height = 300, 190, 38
    rotations = (0, 90, 180, 270)
    sheet = Image.new("RGB", (tile_width * 4, (image_height + label_height) * len(scenes)), "white")
    draw = ImageDraw.Draw(sheet)
    for row_number, scene in enumerate(scenes):
        candidate_id = str(scene["representative_candidate_id"])
        candidate = candidate_index[candidate_id]
        image_path = _safe_relative_path(project_dir, str(candidate["image_path"]))
        with Image.open(image_path) as opened:
            original = ImageOps.exif_transpose(opened).convert("RGB")
        for column, rotation in enumerate(rotations):
            preview = ImageOps.contain(_rotate_clockwise(original, rotation), (tile_width - 12, image_height - 10))
            left = column * tile_width
            top = row_number * (image_height + label_height)
            sheet.paste(preview, (left + (tile_width - preview.width) // 2, top + (image_height - preview.height) // 2))
            draw.rectangle((left, top, left + tile_width - 1, top + image_height + label_height - 1), outline=(105, 105, 105), width=2)
            draw.text(
                (left + 7, top + image_height + 7),
                f"{scene['scene_id']} / {candidate_id} / {rotation} deg CW",
                fill="black",
            )
    path = output_dir / "orientation_review.jpg"
    sheet.save(path, format="JPEG", quality=92, optimize=True)
    return path


def _bbox_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if intersection == 0:
        return 0.0
    left_area = max(1, (left[2] - left[0]) * (left[3] - left[1]))
    right_area = max(1, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / (left_area + right_area - intersection)


def propose_item_lassos(image: Image.Image, *, maximum_proposals: int = 6) -> list[dict[str, Any]]:
    """Return conservative whole-region lasso proposals for human review.

    These are edge/color region proposals, not object recognition. Any crop touching
    a frame edge or having weak contour coverage is explicitly flagged.
    """
    rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, 960.0 / max(1, width))
    analysis = cv2.resize(rgb, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(analysis, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(analysis, cv2.COLOR_RGB2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.Canny(clahe, 45, 135)
    color_edges = np.zeros_like(edges)
    for channel in cv2.split(lab):
        gradient_x = cv2.Sobel(channel, cv2.CV_16S, 1, 0, ksize=3)
        gradient_y = cv2.Sobel(channel, cv2.CV_16S, 0, 1, ksize=3)
        magnitude = cv2.convertScaleAbs(cv2.addWeighted(cv2.convertScaleAbs(gradient_x), 0.5, cv2.convertScaleAbs(gradient_y), 0.5, 0))
        color_edges = cv2.max(color_edges, cv2.threshold(magnitude, 28, 255, cv2.THRESH_BINARY)[1])
    combined = cv2.max(edges, color_edges)
    frame_area = float(analysis.shape[0] * analysis.shape[1])
    raw = []
    shortest_side = min(analysis.shape[:2])
    for kernel_fraction in (0.005, 0.012, 0.024):
        kernel_size = max(3, int(round(shortest_side * kernel_fraction)) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        regions = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=2)
        regions = cv2.dilate(regions, np.ones((3, 3), np.uint8), iterations=1)
        contours, _hierarchy = cv2.findContours(regions, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            contour_area = float(cv2.contourArea(contour))
            x, y, box_width, box_height = cv2.boundingRect(contour)
            box_area = float(box_width * box_height)
            if contour_area < frame_area * 0.004 or box_area < frame_area * 0.012 or box_area > frame_area * 0.72:
                continue
            if box_width < 32 or box_height < 32 or box_width / max(1, box_height) > 7 or box_height / max(1, box_width) > 7:
                continue
            hull = cv2.convexHull(contour)
            epsilon = max(2.0, 0.012 * cv2.arcLength(hull, True))
            polygon = cv2.approxPolyDP(hull, epsilon, True).reshape(-1, 2)
            if len(polygon) < 3:
                continue
            coverage = contour_area / max(1.0, box_area)
            margin = max(4, round(shortest_side * 0.018))
            box = (max(0, x - margin), max(0, y - margin), min(analysis.shape[1], x + box_width + margin), min(analysis.shape[0], y + box_height + margin))
            area_fraction = box_area / frame_area
            size_score = 1.0 - min(1.0, abs(math.log(max(area_fraction, 0.001) / 0.14)) / 2.8)
            score = 0.50 * size_score + 0.35 * min(1.0, coverage / 0.55) + 0.15 * min(1.0, contour_area / (frame_area * 0.12))
            raw.append({"polygon": polygon, "box": box, "area": contour_area, "coverage": coverage, "score": score})
    raw.sort(key=lambda proposal: (proposal["score"], proposal["area"]), reverse=True)

    accepted = []
    for proposal in raw:
        if any(_bbox_iou(proposal["box"], prior["box"]) >= 0.48 for prior in accepted):
            continue
        accepted.append(proposal)
        if len(accepted) >= max(1, min(12, int(maximum_proposals))):
            break

    inverse_scale = 1.0 / scale
    results = []
    for proposal in accepted:
        polygon = tuple(
            (min(width - 1, max(0, round(float(x) * inverse_scale))), min(height - 1, max(0, round(float(y) * inverse_scale))))
            for x, y in proposal["polygon"]
        )
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        edge_margin = max(3, round(min(width, height) * 0.012))
        flags = []
        proposal_box = proposal["box"]
        box_touches_analysis_edge = (
            proposal_box[0] == 0
            or proposal_box[1] == 0
            or proposal_box[2] == analysis.shape[1]
            or proposal_box[3] == analysis.shape[0]
        )
        if box_touches_analysis_edge or min(xs) <= edge_margin or min(ys) <= edge_margin or max(xs) >= width - 1 - edge_margin or max(ys) >= height - 1 - edge_margin:
            flags.append("touches_frame_edge")
        if float(proposal["coverage"]) < 0.18:
            flags.append("fragment_or_weak_boundary_risk")
        if (max(xs) - min(xs)) * (max(ys) - min(ys)) < width * height * 0.035:
            flags.append("small_region_review")
        results.append({
            "points": polygon,
            "bounds": [min(xs), min(ys), max(xs), max(ys)],
            "quality_flags": flags,
            "proposal_score": round(float(proposal["score"]), 4),
            "review_status": "proposed_unverified",
        })
    return results


def _write_proposal_contact_sheet(output_dir: Path, scenes: Sequence[dict[str, Any]]) -> Path:
    tiles = []
    for scene in scenes:
        overlay = Path(str(scene.get("overlay_path") or ""))
        if overlay.is_file():
            tiles.append((scene, overlay))
    tile_width, image_height, label_height = 420, 250, 52
    columns = 3
    rows = max(1, math.ceil(len(tiles) / columns))
    sheet = Image.new("RGB", (columns * tile_width, rows * (image_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (scene, overlay_path) in enumerate(tiles):
        left = (index % columns) * tile_width
        top = (index // columns) * (image_height + label_height)
        with Image.open(overlay_path) as opened:
            preview = ImageOps.contain(opened.convert("RGB"), (tile_width - 12, image_height - 10))
        sheet.paste(preview, (left + (tile_width - preview.width) // 2, top + (image_height - preview.height) // 2))
        draw.rectangle((left, top, left + tile_width - 1, top + image_height + label_height - 1), outline=(90, 90, 90), width=2)
        draw.text((left + 7, top + image_height + 5), f"{scene['scene_id']} / {scene['representative_candidate_id']}", fill="black")
        draw.text((left + 7, top + image_height + 25), f"rotation {scene['rotation_degrees']} CW / {len(scene['proposals'])} proposals", fill="black")
    path = output_dir / "item_proposals_contact_sheet.jpg"
    sheet.save(path, format="JPEG", quality=92, optimize=True)
    return path


def create_video_item_proposals(
    manifest_path: Path,
    output_dir: Path,
    *,
    rotations: dict[str, int] | None = None,
    maximum_proposals_per_scene: int = 6,
) -> dict[str, Any]:
    """Group video views and create review-only rotation and lasso proposals."""
    manifest, project_dir = _load_verified_manifest(manifest_path)
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError("proposal output folder already exists")
    rotations = dict(rotations or {})
    candidate_index = {str(row["candidate_id"]): row for row in manifest["candidates"]}
    for candidate_id, rotation in rotations.items():
        if candidate_id not in candidate_index:
            raise ValueError(f"unknown rotation candidate: {candidate_id}")
        if int(rotation) not in VALID_ROTATIONS:
            raise ValueError(f"invalid rotation for {candidate_id}")

    scenes = _group_scene_candidates(manifest, project_dir)
    for scene in scenes:
        scene_rotation_values = {
            int(rotations[member_id])
            for member_id in scene["candidate_ids"]
            if member_id in rotations
        }
        if len(scene_rotation_values) > 1:
            raise ValueError(f"conflicting rotation overrides in {scene['scene_id']}")
        scene["_accepted_rotation"] = next(iter(scene_rotation_values), None)
    output_dir.mkdir(parents=True, exist_ok=False)
    overlays_dir = output_dir / "scene_overlays"
    crops_dir = output_dir / "proposal_crops"
    overlays_dir.mkdir()
    crops_dir.mkdir()
    orientation_sheet = _write_orientation_sheet(output_dir, project_dir, candidate_index, scenes)

    proposal_number = 0
    for scene in scenes:
        candidate_id = str(scene["representative_candidate_id"])
        candidate = candidate_index[candidate_id]
        accepted_rotation = scene.pop("_accepted_rotation")
        rotation = int(accepted_rotation) if accepted_rotation is not None else 0
        image_path = _safe_relative_path(project_dir, str(candidate["image_path"]))
        with Image.open(image_path) as opened:
            source = _rotate_clockwise(ImageOps.exif_transpose(opened).convert("RGB"), rotation)
        proposals = propose_item_lassos(source, maximum_proposals=maximum_proposals_per_scene)
        overlay = source.copy()
        overlay_draw = ImageDraw.Draw(overlay)
        serialized = []
        for local_number, proposal in enumerate(proposals, start=1):
            proposal_number += 1
            proposal_id = f"proposal_{proposal_number:04d}"
            points = tuple(proposal["points"])
            overlay_draw.line((*points, points[0]), fill=(255, 40, 25), width=max(3, round(min(source.size) * 0.006)))
            overlay_draw.text((points[0][0] + 5, points[0][1] + 5), str(local_number), fill=(255, 255, 0), stroke_width=2, stroke_fill=(0, 0, 0))
            selection = ItemSelection(proposal_number, points, description=f"Unverified proposal from {candidate_id}")
            rendered = render_selection(source, selection, padding=18)
            neutral_path = crops_dir / f"{proposal_id}_{scene['scene_id']}_neutral.jpg"
            isolated_path = crops_dir / f"{proposal_id}_{scene['scene_id']}_isolated.png"
            rendered["neutral"].save(neutral_path, format="JPEG", quality=94, optimize=True)
            rendered["transparent"].save(isolated_path, format="PNG", optimize=True)
            serialized.append({
                "proposal_id": proposal_id,
                "points": [list(point) for point in points],
                "bounds": proposal["bounds"],
                "quality_flags": proposal["quality_flags"],
                "proposal_score": proposal["proposal_score"],
                "review_status": proposal["review_status"],
                "neutral_path": neutral_path.relative_to(output_dir).as_posix(),
                "neutral_sha256": _sha256(neutral_path),
                "isolated_path": isolated_path.relative_to(output_dir).as_posix(),
                "isolated_sha256": _sha256(isolated_path),
            })
        overlay_path = overlays_dir / f"{scene['scene_id']}_{candidate_id}_overlay.jpg"
        overlay.save(overlay_path, format="JPEG", quality=94, optimize=True)
        scene["rotation_degrees"] = rotation
        scene["orientation_status"] = "accepted_override" if accepted_rotation is not None else "unreviewed_original"
        scene["overlay_path"] = str(overlay_path)
        scene["overlay_relative_path"] = overlay_path.relative_to(output_dir).as_posix()
        scene["overlay_sha256"] = _sha256(overlay_path)
        scene["proposals"] = serialized

    proposal_sheet = _write_proposal_contact_sheet(output_dir, scenes)
    for scene in scenes:
        scene.pop("overlay_path", None)
    result = {
        "schema": "veridex.video_inventory.item_proposals.v1",
        "created_at": _utc_now(),
        "source_manifest_path": str(Path(manifest_path).resolve()),
        "source_manifest_sha256": _sha256(Path(manifest_path).resolve()),
        "source_video_sha256": str(manifest["source"]["sha256"]),
        "settings": {
            "maximum_proposals_per_scene": max(1, min(12, int(maximum_proposals_per_scene))),
            "scene_grouping": "temporally adjacent perceptual/color/ORB similarity; groups are scenes, never item identity",
            "orientation_policy": "explicit accepted overrides only; otherwise original orientation remains unreviewed",
        },
        "orientation_review": orientation_sheet.relative_to(output_dir).as_posix(),
        "orientation_review_sha256": _sha256(orientation_sheet),
        "proposal_contact_sheet": proposal_sheet.relative_to(output_dir).as_posix(),
        "proposal_contact_sheet_sha256": _sha256(proposal_sheet),
        "scenes": scenes,
        "proposal_count": proposal_number,
        "workbook_ready": False,
        "review_required": True,
        "limitations": [
            "Scene grouping does not establish that two views show the same physical item.",
            "Lassos are edge/color proposals and must be checked for completeness before workbook use.",
            "Frame-edge, occluded, reflective, and low-contrast items may be incomplete or omitted.",
        ],
    }
    manifest_output = output_dir / "proposal_manifest.json"
    _atomic_json(manifest_output, result)
    return {**result, "manifest_path": str(manifest_output), "output_dir": str(output_dir)}


@dataclass(frozen=True)
class VideoInventorySelection:
    candidate_id: str
    points: tuple[tuple[int, int], ...] = ()
    description: str = ""
    maker: str = ""
    title: str = ""
    notes: str = ""
    rotation_degrees: int = 0


def create_workbook_from_video_candidates(
    manifest_path: Path,
    selections: Sequence[VideoInventorySelection],
    output_path: Path,
    crops_dir: Path,
) -> Path:
    """Create an inventory workbook from explicitly approved candidate views/regions."""
    manifest_path = Path(manifest_path).resolve()
    output_path = Path(output_path).resolve()
    crops_dir = Path(crops_dir).resolve()
    if output_path.exists():
        raise FileExistsError("workbook output already exists")
    if crops_dir.exists():
        raise FileExistsError("crop output folder already exists")
    manifest, project_dir = _load_verified_manifest(manifest_path)
    source = Path(str((manifest.get("source") or {}).get("path") or "")).resolve()
    candidate_index = {
        str(row.get("candidate_id")): row
        for row in manifest.get("candidates") or []
        if isinstance(row, dict) and row.get("candidate_id")
    }
    if not selections:
        raise ValueError("select at least one approved video view")

    crops_dir.mkdir(parents=True, exist_ok=False)
    items = []
    used = set()
    for item_number, approved in enumerate(selections, start=1):
        rotation = int(approved.rotation_degrees)
        if rotation not in VALID_ROTATIONS:
            raise ValueError(f"invalid rotation for {approved.candidate_id}")
        selection_key = (approved.candidate_id, tuple(approved.points), rotation)
        if selection_key in used:
            raise ValueError(f"duplicate candidate region selection: {approved.candidate_id}")
        used.add(selection_key)
        candidate = candidate_index.get(approved.candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {approved.candidate_id}")
        image_path = _safe_relative_path(project_dir, str(candidate.get("image_path") or ""))
        if not image_path.is_file() or _sha256(image_path) != str(candidate.get("image_sha256") or ""):
            raise ValueError(f"candidate image is missing or changed: {approved.candidate_id}")
        with Image.open(image_path) as opened:
            source_image = _rotate_clockwise(ImageOps.exif_transpose(opened).convert("RGB"), rotation)
        points = approved.points or ((0, 0), (source_image.width - 1, source_image.height - 1))
        selection = ItemSelection(
            item_number,
            tuple(points),
            description=approved.description or f"Video item from {approved.candidate_id}",
            maker=approved.maker,
            title=approved.title,
            confidence="Pending identification",
            review_status="Approved crop; pending research",
            notes=(
                f"Source video view {approved.candidate_id} at {float(candidate.get('timestamp_seconds') or 0):.2f}s. "
                f"Rotation {rotation} degrees clockwise. "
                + approved.notes
            ).strip(),
        )
        rendered = render_selection(source_image, selection, padding=12)
        stem = f"item_{item_number:03d}_{approved.candidate_id}"
        context_path = crops_dir / f"{stem}_context.jpg"
        transparent_path = crops_dir / f"{stem}_isolated.png"
        neutral_path = crops_dir / f"{stem}_neutral.jpg"
        rendered["context"].save(context_path, format="JPEG", quality=94, optimize=True)
        rendered["transparent"].save(transparent_path, format="PNG", optimize=True)
        rendered["neutral"].save(neutral_path, format="JPEG", quality=94, optimize=True)
        items.append({
            "selection": selection,
            "context_path": context_path,
            "transparent_path": transparent_path,
            "neutral_path": neutral_path,
        })
    return create_inventory_workbook(output_path, source, items)


def _parse_selection(value: str) -> VideoInventorySelection:
    candidate_id, separator, description = value.partition(":")
    if not candidate_id.strip():
        raise argparse.ArgumentTypeError("selection must be view_### or view_###:description")
    return VideoInventorySelection(candidate_id.strip(), description=description.strip() if separator else "")


def _parse_rotation(value: str) -> tuple[str, int]:
    candidate_id, separator, rotation = value.partition("=")
    if not separator or not candidate_id.strip():
        raise argparse.ArgumentTypeError("rotation must be view_###=0|90|180|270")
    try:
        degrees = int(rotation)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rotation must be view_###=0|90|180|270") from exc
    if degrees not in VALID_ROTATIONS:
        raise argparse.ArgumentTypeError("rotation must be view_###=0|90|180|270")
    return candidate_id.strip(), degrees


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract reviewable inventory views from a local video")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="create candidate frames, contact sheet, and manifest")
    extract.add_argument("video", type=Path)
    extract.add_argument("project_dir", type=Path)
    extract.add_argument("--sample-seconds", type=float, default=0.5)
    extract.add_argument("--window-seconds", type=float, default=2.0)
    extract.add_argument("--max-candidates", type=int, default=80)
    workbook = commands.add_parser("workbook", help="create a workbook from approved full-frame candidates")
    workbook.add_argument("manifest", type=Path)
    workbook.add_argument("output", type=Path)
    workbook.add_argument("--crops-dir", type=Path, required=True)
    workbook.add_argument("--select", action="append", type=_parse_selection, required=True)
    proposals = commands.add_parser("proposals", help="group scenes and create review-only rotation/lasso proposals")
    proposals.add_argument("manifest", type=Path)
    proposals.add_argument("output_dir", type=Path)
    proposals.add_argument("--rotate", action="append", type=_parse_rotation, default=[])
    proposals.add_argument("--maximum-proposals-per-scene", type=int, default=6)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "extract":
        result = extract_video_inventory_candidates(
            args.video,
            args.project_dir,
            sample_seconds=args.sample_seconds,
            window_seconds=args.window_seconds,
            max_candidates=args.max_candidates,
        )
        print(json.dumps({
            "manifest_path": result["manifest_path"],
            "contact_sheet": str(Path(result["project_dir"]) / result["contact_sheet"]),
            "candidate_count": len(result["candidates"]),
        }, indent=2))
        return 0
    if args.command == "proposals":
        result = create_video_item_proposals(
            args.manifest,
            args.output_dir,
            rotations=dict(args.rotate),
            maximum_proposals_per_scene=args.maximum_proposals_per_scene,
        )
        print(json.dumps({
            "manifest_path": result["manifest_path"],
            "orientation_review": str(Path(result["output_dir"]) / result["orientation_review"]),
            "proposal_contact_sheet": str(Path(result["output_dir"]) / result["proposal_contact_sheet"]),
            "scene_count": len(result["scenes"]),
            "proposal_count": result["proposal_count"],
            "workbook_ready": result["workbook_ready"],
        }, indent=2))
        return 0
    created = create_workbook_from_video_candidates(args.manifest, args.select, args.output, args.crops_dir)
    print(created)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
