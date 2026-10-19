"""Governed Animation Studio project storage and local tool orchestration."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable
from xml.sax.saxutils import escape as xml_escape


ROOM_ID = "animation_studio"
SCHEMA_VERSION = 11
SUPPORTED_AUDIO = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}
SUPPORTED_IMAGES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
SUPPORTED_SYNFIG_DOCUMENTS = {".sif", ".sifz", ".sfg"}
SUPPORTED_RENDERS = {".avi", ".gif", ".jpeg", ".jpg", ".mkv", ".mov", ".mp4", ".png", ".webm", ".webp"}
MAX_SHOT_PACKAGE_BYTES = 250 * 1024 * 1024
MOUTH_SHAPES = {"A", "B", "C", "D", "E", "F", "G", "H", "X"}
JAW_FLAP_AMOUNTS = {"X": 0.0, "A": 0.18, "B": 0.12, "C": 0.18, "D": 0.24, "E": 0.12, "F": 0.08, "G": 0.12, "H": 0.18}
ASSET_ROLES = {"background", "set", "character", "prop", "overlay"}
AUDIO_TRACK_TYPES = {"dialogue", "music", "sound_effect"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _slug(value: Any, fallback: str = "animation-project") -> str:
    result = re.sub(r"[^a-z0-9]+", "-", _clean(value, 120).lower()).strip("-")
    return result[:70] or fallback


def _text_rows(value: Any, defaults: Iterable[str]) -> list[str]:
    rows = value if isinstance(value, list) else str(value or "").splitlines()
    cleaned = [_clean(row, 160) for row in rows]
    result = list(dict.fromkeys(row for row in cleaned if row))[:24]
    return result or list(defaults)


def _bounded_number(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(min(maximum, max(minimum, number)), 2)


def _safe_id(value: Any, fallback: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))[:100]
    return result or fallback


def _project_assets(value: Any) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    assets: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows[:48], start=1):
        if not isinstance(row, dict):
            continue
        file_id = _safe_id(row.get("file_id"), "")
        if not file_id:
            continue
        asset_id = _safe_id(row.get("asset_id"), f"asset-{index}")
        if asset_id in seen:
            asset_id = f"{asset_id}-{index}"
        seen.add(asset_id)
        role = str(row.get("role") or "prop").lower()
        assets.append({
            "asset_id": asset_id,
            "file_id": file_id,
            "source_session_id": _safe_id(row.get("source_session_id"), ""),
            "name": _clean(row.get("name"), 240) or f"Image {index}",
            "role": role if role in ASSET_ROLES else "prop",
            "width_percent": _bounded_number(row.get("width_percent"), 35, 2, 250),
            "x_percent": _bounded_number(row.get("x_percent"), 50, -100, 200),
            "y_percent": _bounded_number(row.get("y_percent"), 60, -100, 200),
            "opacity_percent": _bounded_number(row.get("opacity_percent"), 100, 0, 100),
        })
    return assets


def _storyboard_shots(value: Any, asset_ids: set[str]) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    shots: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows[:120], start=1):
        if not isinstance(row, dict):
            continue
        shot_id = _safe_id(row.get("shot_id"), f"shot-{index}")
        if shot_id in seen:
            shot_id = f"{shot_id}-{index}"
        seen.add(shot_id)
        asset_id = _safe_id(row.get("asset_id"), "")
        shots.append({
            "shot_id": shot_id,
            "title": _clean(row.get("title"), 160) or f"Shot {index}",
            "asset_id": asset_id if asset_id in asset_ids else "",
            "description": str(row.get("description") or "").replace("\x00", "")[:5_000].strip(),
            "camera_notes": str(row.get("camera_notes") or "").replace("\x00", "")[:3_000].strip(),
            "editing_notes": str(row.get("editing_notes") or "").replace("\x00", "")[:3_000].strip(),
            "duration_seconds": _bounded_number(row.get("duration_seconds"), 5, 0.1, 3_600),
        })
    return shots


def _audio_tracks(value: Any, shot_ids: set[str]) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    tracks: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows[:96], start=1):
        if not isinstance(row, dict):
            continue
        file_id = _safe_id(row.get("file_id"), "")
        if not file_id:
            continue
        track_id = _safe_id(row.get("track_id"), f"track-{index}")
        if track_id in seen:
            track_id = f"{track_id}-{index}"
        seen.add(track_id)
        track_type = str(row.get("track_type") or "dialogue").lower()
        shot_id = _safe_id(row.get("shot_id"), "")
        tracks.append({
            "track_id": track_id,
            "file_id": file_id,
            "source_session_id": _safe_id(row.get("source_session_id"), ""),
            "name": _clean(row.get("name"), 240) or f"Audio {index}",
            "track_type": track_type if track_type in AUDIO_TRACK_TYPES else "dialogue",
            "character": _clean(row.get("character"), 160),
            "shot_id": shot_id if shot_id in shot_ids else "",
            "start_seconds": _bounded_number(row.get("start_seconds"), 0, 0, 86_400),
            "trim_in_seconds": _bounded_number(row.get("trim_in_seconds"), 0, 0, 86_400),
            "trim_out_seconds": _bounded_number(row.get("trim_out_seconds"), 0, 0, 86_400),
            "volume_db": _bounded_number(row.get("volume_db"), 0, -60, 12),
            "pan_percent": _bounded_number(row.get("pan_percent"), 0, -100, 100),
            "fade_in_seconds": _bounded_number(row.get("fade_in_seconds"), 0, 0, 600),
            "fade_out_seconds": _bounded_number(row.get("fade_out_seconds"), 0, 0, 600),
            "muted": bool(row.get("muted")),
            "solo": bool(row.get("solo")),
        })
    return tracks


def _cue_rows(value: Any) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    cues: list[Dict[str, Any]] = []
    last_end = 0.0
    for row in rows[:20_000]:
        if not isinstance(row, dict):
            continue
        start = _bounded_number(row.get("start"), 0, 0, 86_400)
        end = _bounded_number(row.get("end"), start, start, 86_400)
        shape = str(row.get("value") or "X").upper()
        if start < last_end - 0.001 or shape not in MOUTH_SHAPES:
            continue
        cues.append({"start": start, "end": end, "value": shape})
        last_end = end
    return cues


def _manual_jaw_points(value: Any) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    points: list[Dict[str, Any]] = []
    last_time = -0.001
    for row in rows[:30_000]:
        if not isinstance(row, dict):
            continue
        time_seconds = _bounded_number(row.get("time"), 0, 0, 86_400)
        opening_percent = _bounded_number(row.get("opening_percent"), 0, 0, 100)
        if time_seconds < last_time:
            continue
        points.append({"time": round(time_seconds, 3), "opening_percent": round(opening_percent, 3)})
        last_time = time_seconds
    return points


def _manual_jaw_segments(value: Any) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    segments: list[Dict[str, Any]] = []
    for row in rows[:120]:
        if not isinstance(row, dict):
            continue
        start = _bounded_number(row.get("start"), 0, 0, 86_400)
        end = _bounded_number(row.get("end"), start, start, 86_400)
        points = _manual_jaw_points(row.get("points"))
        if end - start < 0.001 or not points:
            continue
        segments.append({"start": round(start, 3), "end": round(end, 3), "points": points})
    return sorted(segments, key=lambda row: (row["start"], row["end"]))


def _manual_jaw_corrections(value: Any) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    corrections: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows[:500], start=1):
        if not isinstance(row, dict):
            continue
        correction_id = _safe_id(row.get("correction_id"), f"jaw-correction-{index}")
        if correction_id in seen:
            correction_id = f"{correction_id}-{index}"
        seen.add(correction_id)
        corrections.append({
            "correction_id": correction_id,
            "time": round(_bounded_number(row.get("time"), 0, 0, 86_400), 3),
            "opening_percent": round(_bounded_number(row.get("opening_percent"), 0, 0, 100), 3),
            "blend_seconds": round(_bounded_number(row.get("blend_seconds"), 0.12, 0.03, 1.0), 3),
        })
    return sorted(corrections, key=lambda row: (row["time"], row["correction_id"]))


def _mouth_rigs(value: Any, asset_ids: set[str]) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    rigs: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows[:24], start=1):
        if not isinstance(row, dict):
            continue
        rig_id = _safe_id(row.get("rig_id"), f"mouth-rig-{index}")
        if rig_id in seen:
            rig_id = f"{rig_id}-{index}"
        seen.add(rig_id)
        raw_shapes = row.get("shapes") if isinstance(row.get("shapes"), dict) else {}
        shapes = {}
        for shape in sorted(MOUTH_SHAPES):
            asset_id = _safe_id(raw_shapes.get(shape), "")
            shapes[shape] = asset_id if asset_id in asset_ids else ""
        base_asset_id = _safe_id(row.get("base_asset_id"), "")
        raw_registrations = row.get("mouth_asset_registrations") if isinstance(row.get("mouth_asset_registrations"), dict) else {}
        registrations = {}
        for raw_asset_id, raw_registration in list(raw_registrations.items())[:24]:
            asset_id = _safe_id(raw_asset_id, "")
            if asset_id not in asset_ids or not isinstance(raw_registration, dict):
                continue
            registrations[asset_id] = {
                "left_percent": _bounded_number(raw_registration.get("left_percent"), 0, -200, 200),
                "top_percent": _bounded_number(raw_registration.get("top_percent"), 0, -200, 200),
                "width_percent": _bounded_number(raw_registration.get("width_percent"), 100, 1, 300),
            }
        registration_master_asset_id = _safe_id(row.get("registration_master_asset_id"), "")
        character = _clean(row.get("character"), 160) or f"Character {index}"
        is_skeletor = character.casefold() == "skeletor"
        rigs.append({
            "rig_id": rig_id,
            "character": character,
            "base_asset_id": base_asset_id if base_asset_id in asset_ids else "",
            "animation_mode": "jaw_flap" if row.get("animation_mode") == "jaw_flap" else "mouth_shapes",
            "shapes": shapes,
            "mouth_x_percent": _bounded_number(row.get("mouth_x_percent"), 50, -100, 200),
            "mouth_y_percent": _bounded_number(row.get("mouth_y_percent"), 58, -100, 200),
            "mouth_width_percent": _bounded_number(row.get("mouth_width_percent"), 16, 1, 100),
            "mouth_height_percent": _bounded_number(row.get("mouth_height_percent"), 100, 25, 200),
            "mouth_anchor_x_percent": _bounded_number(row.get("mouth_anchor_x_percent"), 50, 0, 100),
            "mouth_anchor_y_percent": _bounded_number(row.get("mouth_anchor_y_percent"), 50, 0, 100),
            "jaw_open_strength_percent": _bounded_number(row.get("jaw_open_strength_percent"), 200 if is_skeletor else 100, 25, 400),
            "stage_x_percent": _bounded_number(row.get("stage_x_percent"), 80.97 if is_skeletor else 50, -100, 200),
            "stage_y_percent": _bounded_number(row.get("stage_y_percent"), 43.12 if is_skeletor else 60, -100, 200),
            "stage_width_percent": _bounded_number(row.get("stage_width_percent"), 22 if is_skeletor else 34, 2, 250),
            "stage_placement_preset": _clean(row.get("stage_placement_preset"), 80) or ("desk_host" if is_skeletor else ""),
            "placement_calibrated": bool(row.get("placement_calibrated", False)),
            "registration_master_asset_id": registration_master_asset_id if registration_master_asset_id in asset_ids else "",
            "registration_canvas_width": _bounded_number(row.get("registration_canvas_width"), 1, 1, 20_000),
            "registration_canvas_height": _bounded_number(row.get("registration_canvas_height"), 1, 1, 20_000),
            "mouth_asset_registrations": registrations,
        })
    return rigs


def _lipsync_takes(value: Any, track_ids: set[str], rig_ids: set[str]) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    takes: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows[:100], start=1):
        if not isinstance(row, dict):
            continue
        take_id = _safe_id(row.get("take_id"), f"lipsync-take-{index}")
        if take_id in seen:
            take_id = f"{take_id}-{index}"
        seen.add(take_id)
        track_id = _safe_id(row.get("track_id"), "")
        rig_id = _safe_id(row.get("rig_id"), "")
        cues = _cue_rows(row.get("mouth_cues"))
        if track_id not in track_ids or rig_id not in rig_ids or not cues:
            continue
        recognizer = str(row.get("recognizer") or "pocketSphinx")
        takes.append({
            "take_id": take_id,
            "track_id": track_id,
            "rig_id": rig_id,
            "cue_file_id": _safe_id(row.get("cue_file_id"), ""),
            "cue_source_session_id": _safe_id(row.get("cue_source_session_id"), ""),
            "recognizer": recognizer if recognizer in {"pocketSphinx", "phonetic"} else "pocketSphinx",
            "extended_shapes": "".join(shape for shape in "GHX" if shape in str(row.get("extended_shapes") or "")),
            "duration": _bounded_number(row.get("duration"), cues[-1]["end"], 0, 86_400),
            "mouth_cues": cues,
            "manual_jaw_points": _manual_jaw_points(row.get("manual_jaw_points")),
            "manual_jaw_segments": _manual_jaw_segments(row.get("manual_jaw_segments")),
            "manual_jaw_corrections": _manual_jaw_corrections(row.get("manual_jaw_corrections")),
            "created_at": _clean(row.get("created_at"), 100),
        })
    return takes


def _rendered_shots(value: Any, shot_ids: set[str]) -> list[Dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    renders: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows[:120], start=1):
        if not isinstance(row, dict):
            continue
        file_id = _safe_id(row.get("file_id"), "")
        shot_id = _safe_id(row.get("shot_id"), "")
        if not file_id or shot_id not in shot_ids:
            continue
        render_id = _safe_id(row.get("render_id"), f"render-{index}")
        if render_id in seen:
            render_id = f"{render_id}-{index}"
        seen.add(render_id)
        renders.append({
            "render_id": render_id,
            "shot_id": shot_id,
            "file_id": file_id,
            "source_session_id": _safe_id(row.get("source_session_id"), ""),
            "name": _clean(row.get("name"), 240) or f"Rendered shot {index}",
            "format": _clean(row.get("format"), 40).lower(),
            "status": "imported",
            "imported_at": _clean(row.get("imported_at"), 100),
        })
    return renders


def default_project() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": "eternia-late-night",
        "title": "Eternia Late Night",
        "format": "Animated late-night talk show",
        "visual_style": "2.5D cut-out",
        "release_intent": "Commercial-safe",
        "width": 1920,
        "height": 1080,
        "frame_rate": 24,
        "sets": ["Main desk set", "Band stage"],
        "characters": ["Host", "Co-host", "Guest template", "Band member template"],
        "reusable_actions": ["Idle breathing", "Blink", "Head turn", "Desk gesture", "Applause", "Instrument loop"],
        "pipeline": ["Storyboard", "Voice-over", "Lip sync", "Blocking", "Render shots", "Video Production handoff"],
        "assets": [],
        "storyboard": [],
        "audio_tracks": [],
        "mouth_rigs": [],
        "lipsync_takes": [],
        "rendered_shots": [],
        "notes": "",
        "saved": False,
        "project_version": 0,
        "revision_id": "",
        "created_at": "",
        "updated_at": "",
    }


def normalize_project(value: Dict[str, Any]) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    project = default_project()
    project["title"] = _clean(source.get("title"), 200) or project["title"]
    project["project_id"] = _slug(source.get("project_id") or project["title"], project["project_id"])
    project["format"] = _clean(source.get("format"), 300) or project["format"]
    project["visual_style"] = "2.5D cut-out"
    project["release_intent"] = "Commercial-safe"
    project["width"] = min(7680, max(640, int(source.get("width") or project["width"])))
    project["height"] = min(4320, max(360, int(source.get("height") or project["height"])))
    frame_rate = int(source.get("frame_rate") or project["frame_rate"])
    project["frame_rate"] = frame_rate if frame_rate in {12, 24, 25, 30, 60} else 24
    project["sets"] = _text_rows(source.get("sets"), project["sets"])
    project["characters"] = _text_rows(source.get("characters"), project["characters"])
    project["reusable_actions"] = _text_rows(source.get("reusable_actions"), project["reusable_actions"])
    project["assets"] = _project_assets(source.get("assets"))
    project["storyboard"] = _storyboard_shots(source.get("storyboard"), {row["asset_id"] for row in project["assets"]})
    project["audio_tracks"] = _audio_tracks(source.get("audio_tracks"), {row["shot_id"] for row in project["storyboard"]})
    project["mouth_rigs"] = _mouth_rigs(source.get("mouth_rigs"), {row["asset_id"] for row in project["assets"]})
    project["lipsync_takes"] = _lipsync_takes(
        source.get("lipsync_takes"),
        {row["track_id"] for row in project["audio_tracks"]},
        {row["rig_id"] for row in project["mouth_rigs"]},
    )
    project["rendered_shots"] = _rendered_shots(
        source.get("rendered_shots"),
        {row["shot_id"] for row in project["storyboard"]},
    )
    project["notes"] = str(source.get("notes") or "").replace("\x00", "")[:20_000].strip()
    project["saved"] = bool(source.get("saved"))
    project["project_version"] = max(0, int(source.get("project_version") or 0))
    project["revision_id"] = _safe_id(source.get("revision_id"), "")
    project["created_at"] = _clean(source.get("created_at"), 100)
    project["updated_at"] = _clean(source.get("updated_at"), 100)
    return project


class AnimationStudio:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()

    def _workspace_root(self, workspace_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "", str(workspace_id or ""))
        if not safe_id or safe_id != str(workspace_id or ""):
            raise ValueError("Invalid workspace")
        return self.data_root / "workspaces" / safe_id / ROOM_ID

    def _project_path(self, workspace_id: str, project_id: str) -> Path:
        return self._workspace_root(workspace_id) / "projects" / f"{_slug(project_id)}.json"

    def _revision_path(self, workspace_id: str, project_id: str, version: int) -> Path:
        return self._workspace_root(workspace_id) / "projects" / f"{_slug(project_id)}-v{int(version)}.json"

    @staticmethod
    def _write_json(path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def tools() -> Dict[str, Dict[str, Any]]:
        repository_root = Path(__file__).resolve().parent
        local_programs = Path(os.environ.get("LOCALAPPDATA") or "") / "Programs"
        program_files = Path(os.environ.get("ProgramFiles") or "C:/Program Files")
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)") or "C:/Program Files (x86)")
        commands = {
            "rhubarb": (
                ("rhubarb",),
                (repository_root / ".runtime/tools/rhubarb/1.14.0/app/Rhubarb-Lip-Sync-1.14.0-Windows/rhubarb.exe",),
                "Rhubarb Lip Sync",
                "Automatic mouth-cue generation from recorded speech",
            ),
            "ffmpeg": (
                ("ffmpeg",),
                tuple(local_programs.glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*/**/bin/ffmpeg.exe")),
                "FFmpeg",
                "Temporary WAV conversion for Rhubarb-compatible analysis",
            ),
            "gimp": (
                ("gimp-3", "gimp-3.0", "gimp"),
                (local_programs / "GIMP 3/bin/gimp-3.exe", program_files / "GIMP 3/bin/gimp-3.exe"),
                "GIMP 3",
                "Cutouts, cleanup, transparency, layers, and production sizing",
            ),
            "audacity": (
                ("audacity",),
                (program_files / "Audacity/audacity.exe", program_files_x86 / "Audacity/audacity.exe"),
                "Audacity",
                "Voice recording, cleanup, timing, and multitrack audio preparation",
            ),
            "synfig": (
                ("synfigstudio", "synfig"),
                (program_files / "Synfig/bin/synfigstudio.exe", program_files_x86 / "Synfig/bin/synfigstudio.exe"),
                "Synfig Studio",
                "Bitmap cut-out movement, scene compositing, and character timing",
            ),
            "kdenlive": (("kdenlive",), (), "Kdenlive", "Final edit, audio, captions, and delivery"),
            "glaxnimate": (("glaxnimate",), (), "Glaxnimate", "Vector titles, bumpers, and overlays"),
        }
        result: Dict[str, Dict[str, Any]] = {}
        for key, (names, candidates, label, purpose) in commands.items():
            path = ""
            for name in names:
                path = shutil.which(name) or ""
                if path:
                    break
            if not path:
                path = next((str(candidate) for candidate in candidates if candidate.is_file()), "")
            result[key] = {"name": label, "available": bool(path), "path": path or "", "purpose": purpose}
        return result

    def launch_editor(self, tool_key: str, source_path: Path) -> Dict[str, Any]:
        key = str(tool_key or "").lower()
        if key not in {"gimp", "audacity", "synfig"}:
            raise ValueError("Only GIMP, Audacity, and Synfig can be launched from Animation Studio.")
        source = Path(source_path).resolve()
        allowed = SUPPORTED_IMAGES if key == "gimp" else SUPPORTED_SYNFIG_DOCUMENTS if key == "synfig" else SUPPORTED_AUDIO
        if not source.is_file() or source.suffix.lower() not in allowed:
            raise ValueError(f"The selected file is not supported by {key.title()}.")
        tool = self.tools().get(key) or {}
        executable = str(tool.get("path") or "")
        if not executable:
            raise RuntimeError(f"{tool.get('name') or key.title()} is not installed or could not be located.")
        process = subprocess.Popen([executable, str(source)], shell=False)
        return {"status": "launched", "tool": str(tool.get("name") or key.title()), "process_id": int(process.pid)}

    @staticmethod
    def build_synfig_starter(source_path: Path, title: str = "") -> bytes:
        source = Path(source_path).resolve()
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_IMAGES:
            raise ValueError("Synfig starters require a supported image source.")
        image_path = xml_escape(source.as_posix())
        image_name = xml_escape(source.name)
        canvas_title = xml_escape(_clean(title, 160) or source.stem or "Veridex shot")
        document = f'''<?xml version="1.0" encoding="UTF-8"?>
<canvas version="0.1" width="1920" height="1080" xres="2834.645752" yres="2834.645752" view-box="-4.000000 2.250000 4.000000 -2.250000" antialias="2" fps="24.000" begin-time="0f" end-time="0f" bgcolor="0.100000 0.100000 0.100000 1.000000">
  <name>{canvas_title}</name>
  <desc>Veridex starter document. Original source remains unchanged.</desc>
  <layer type="import" active="true" exclude_from_rendering="false" version="0.1" desc="{image_name}">
    <param name="z_depth"><real value="0.0000000000"/></param>
    <param name="amount"><real value="1.0000000000"/></param>
    <param name="blend_method"><integer value="0" static="true"/></param>
    <param name="tl"><vector><x>-4.0000000000</x><y>2.2500000000</y></vector></param>
    <param name="br"><vector><x>4.0000000000</x><y>-2.2500000000</y></vector></param>
    <param name="c"><integer value="1"/></param>
    <param name="gamma_adjust"><real value="1.0000000000"/></param>
    <param name="filename"><string>{image_path}</string></param>
    <param name="time_offset"><time value="0s"/></param>
  </layer>
</canvas>
'''
        return document.encode("utf-8")

    @staticmethod
    def build_synfig_lipsync_preview(
        project: Dict[str, Any],
        source_files: Dict[str, Dict[str, Any]],
        take_id: str = "",
        audio_duration_seconds: float | None = None,
        pre_hold_seconds: float = 2.0,
        post_hold_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        """Build a complete, non-destructive Synfig proof shot for one lip-sync take."""
        normalized = normalize_project(project)
        takes = normalized["lipsync_takes"]
        take = next((row for row in takes if row["take_id"] == take_id), None) if take_id else (takes[0] if takes else None)
        if not take:
            raise ValueError("Generate and select a lip-sync take first.")
        rig = next((row for row in normalized["mouth_rigs"] if row["rig_id"] == take["rig_id"]), None)
        track = next((row for row in normalized["audio_tracks"] if row["track_id"] == take["track_id"]), None)
        if not rig or not track:
            raise ValueError("The selected lip-sync take is missing its character rig or voice track.")
        if not rig.get("placement_calibrated"):
            raise ValueError("Confirm the jaw placement before building the Synfig preview.")
        assets = {row["asset_id"]: row for row in normalized["assets"]}
        base = assets.get(str(rig.get("base_asset_id") or ""))
        jaw_id = str((rig.get("shapes") or {}).get("X") or (rig.get("shapes") or {}).get("A") or "")
        jaw = assets.get(jaw_id)
        background = next((row for row in normalized["assets"] if row.get("role") == "background"), None)
        if not base or not jaw or not background:
            raise ValueError("The Synfig preview needs a background, character/base image, and closed jaw image.")

        def source_path(row: Dict[str, Any]) -> Path:
            source = source_files.get(str(row.get("file_id") or ""))
            path = Path(str((source or {}).get("path") or "")).resolve()
            if not path.is_file():
                raise KeyError(f"Source file for {row.get('name') or row.get('file_id')} is unavailable.")
            return path

        background_path = source_path(background)
        base_path = source_path(base)
        jaw_path = source_path(jaw)
        audio_path = source_path(track)
        width = int(normalized["width"])
        height = int(normalized["height"])
        fps = int(normalized["frame_rate"])
        pre_hold = _bounded_number(pre_hold_seconds, 2, 0, 30)
        post_hold = _bounded_number(post_hold_seconds, 2, 0, 30)
        audio_duration = _bounded_number(audio_duration_seconds, take["duration"], 0.01, 86_400)
        duration = round(pre_hold + audio_duration + post_hold, 3)

        def units_x(pixel: float) -> float:
            return -4.0 + (float(pixel) / width) * 8.0

        def units_y(pixel: float) -> float:
            return 2.25 - (float(pixel) / height) * 4.5

        def raster_aspect(path: Path) -> float:
            header = path.read_bytes()[:32]
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                image_width = int.from_bytes(header[16:20], "big")
                image_height = int.from_bytes(header[20:24], "big")
                if image_width > 0 and image_height > 0:
                    return image_width / image_height
            return 1.0

        def rect_for_asset(asset: Dict[str, Any], path: Path) -> tuple[float, float, float, float]:
            asset_width = width * float(asset.get("width_percent") or 35) / 100.0
            asset_height = asset_width / raster_aspect(path)
            center_x = width * float(asset.get("x_percent") if asset.get("x_percent") is not None else 50) / 100.0
            center_y = height * float(asset.get("y_percent") if asset.get("y_percent") is not None else 50) / 100.0
            return center_x - asset_width / 2, center_y - asset_height / 2, center_x + asset_width / 2, center_y + asset_height / 2

        base_placement = {
            **base,
            "x_percent": rig.get("stage_x_percent", base.get("x_percent")),
            "y_percent": rig.get("stage_y_percent", base.get("y_percent")),
            "width_percent": rig.get("stage_width_percent", base.get("width_percent")),
        }
        base_left, base_top, base_right, base_bottom = rect_for_asset(base_placement, base_path)
        base_aspect = raster_aspect(base_path)
        canvas_aspect = width / height
        if base_aspect >= canvas_aspect:
            reference_width = float(width)
            reference_height = reference_width / base_aspect
            reference_left = 0.0
            reference_top = (height - reference_height) / 2.0
        else:
            reference_height = float(height)
            reference_width = reference_height * base_aspect
            reference_left = (width - reference_width) / 2.0
            reference_top = 0.0
        scale_to_base = (base_right - base_left) / reference_width
        mouth_anchor_x = base_left + ((width * float(rig["mouth_x_percent"]) / 100.0) - reference_left) * scale_to_base
        mouth_anchor_y = base_top + ((height * float(rig["mouth_y_percent"]) / 100.0) - reference_top) * scale_to_base
        jaw_width = width * float(rig["mouth_width_percent"]) / 100.0 * scale_to_base
        jaw_height = jaw_width * float(rig["mouth_height_percent"]) / 100.0
        jaw_left = mouth_anchor_x - jaw_width * float(rig["mouth_anchor_x_percent"]) / 100.0
        jaw_top = mouth_anchor_y - jaw_height * float(rig["mouth_anchor_y_percent"]) / 100.0
        jaw_right = jaw_left + jaw_width

        jaw_open_strength = float(rig["jaw_open_strength_percent"]) / 100.0
        max_open_amount = max(JAW_FLAP_AMOUNTS.values())

        def automatic_scale_at(time_seconds: float) -> float:
            for cue in take["mouth_cues"]:
                if float(cue["start"]) <= time_seconds < float(cue["end"]):
                    return 1.0 + (JAW_FLAP_AMOUNTS.get(str(cue["value"]), 0.12) * jaw_open_strength)
            return 1.0

        scale_points: Dict[float, float] = {0.0: 1.0, pre_hold: 1.0, pre_hold + audio_duration: 1.0, duration: 1.0}
        for cue in take["mouth_cues"]:
            start = min(audio_duration, float(cue["start"]))
            end = min(audio_duration, float(cue["end"]))
            scale_points[round(pre_hold + start, 3)] = automatic_scale_at(start)
            scale_points.setdefault(round(pre_hold + end, 3), automatic_scale_at(end))

        linear_ranges: list[tuple[float, float]] = []
        correction_groups: list[Dict[str, Any]] = []
        for correction in take.get("manual_jaw_corrections") or []:
            center = min(audio_duration, float(correction["time"]))
            blend = float(correction["blend_seconds"])
            start = max(0.0, center - blend)
            end = min(audio_duration, center + blend)
            if correction_groups and start <= float(correction_groups[-1]["end"]) + 0.001:
                correction_groups[-1]["end"] = max(float(correction_groups[-1]["end"]), end)
                correction_groups[-1]["corrections"].append(correction)
            else:
                correction_groups.append({"start": start, "end": end, "corrections": [correction]})
        for group in correction_groups:
            group_start = float(group["start"])
            group_end = float(group["end"])
            absolute_start = round(pre_hold + group_start, 3)
            absolute_end = round(pre_hold + group_end, 3)
            for key in list(scale_points):
                if absolute_start < key < absolute_end:
                    del scale_points[key]
            scale_points[absolute_start] = automatic_scale_at(group_start)
            for correction in group["corrections"]:
                center = min(audio_duration, float(correction["time"]))
                opening = float(correction["opening_percent"]) / 100.0
                scale_points[round(pre_hold + center, 3)] = 1.0 + (max_open_amount * jaw_open_strength * opening)
            scale_points[absolute_end] = automatic_scale_at(group_end)
            linear_ranges.append((absolute_start, absolute_end))

        manual_segments = take.get("manual_jaw_segments") or []
        if not manual_segments and take.get("manual_jaw_points"):
            legacy_points = take["manual_jaw_points"]
            manual_segments = [{"start": legacy_points[0]["time"], "end": legacy_points[-1]["time"], "points": legacy_points}]
        for segment in manual_segments:
            segment_start = min(audio_duration, float(segment["start"]))
            segment_end = min(audio_duration, float(segment["end"]))
            absolute_start = round(pre_hold + segment_start, 3)
            absolute_end = round(pre_hold + segment_end, 3)
            for key in list(scale_points):
                if absolute_start < key < absolute_end:
                    del scale_points[key]
            for point in segment["points"]:
                time_seconds = min(audio_duration, float(point["time"]))
                if time_seconds < segment_start or time_seconds > segment_end:
                    continue
                opening = float(point["opening_percent"]) / 100.0
                scale_points[round(pre_hold + time_seconds, 3)] = 1.0 + (max_open_amount * jaw_open_strength * opening)
            linear_ranges.append((absolute_start, absolute_end))

        def vector(x: float, y: float) -> str:
            return f"<vector><x>{x:.10f}</x><y>{y:.10f}</y></vector>"

        def import_layer(path: Path, desc: str, left: float, top: float, right: float, bottom: float, opacity: float = 1.0) -> str:
            return f'''  <layer type="import" active="true" exclude_from_rendering="false" version="0.1" desc="{xml_escape(desc)}">
    <param name="z_depth"><real value="0.0000000000"/></param>
    <param name="amount"><real value="{opacity:.10f}"/></param>
    <param name="blend_method"><integer value="0" static="true"/></param>
    <param name="tl">{vector(units_x(left), units_y(top))}</param>
    <param name="br">{vector(units_x(right), units_y(bottom))}</param>
    <param name="c"><integer value="1"/></param>
    <param name="gamma_adjust"><real value="1.0000000000"/></param>
    <param name="filename"><string>{xml_escape(path.as_posix())}</string></param>
    <param name="time_offset"><time value="0s"/></param>
  </layer>'''

        def waypoint_interpolation(time_value: float, side: str) -> str:
            if side == "before" and any(start < time_value <= end for start, end in linear_ranges):
                return "linear"
            if side == "after" and any(start <= time_value < end for start, end in linear_ranges):
                return "linear"
            return "constant"

        jaw_bottom_waypoints = "\n".join(
            f'''        <waypoint time="{time_value:.3f}s" before="{waypoint_interpolation(time_value, "before")}" after="{waypoint_interpolation(time_value, "after")}">{vector(units_x(jaw_right), units_y(jaw_top + jaw_height * scale))}</waypoint>'''
            for time_value, scale in sorted(scale_points.items())
        )
        jaw_layer = f'''  <layer type="import" active="true" exclude_from_rendering="false" version="0.1" desc="{xml_escape(rig['character'])} jaw">
    <param name="z_depth"><real value="0.0000000000"/></param>
    <param name="amount"><real value="1.0000000000"/></param>
    <param name="blend_method"><integer value="0" static="true"/></param>
    <param name="tl">{vector(units_x(jaw_left), units_y(jaw_top))}</param>
    <param name="br"><animated type="vector">
{jaw_bottom_waypoints}
      </animated></param>
    <param name="c"><integer value="1"/></param>
    <param name="gamma_adjust"><real value="1.0000000000"/></param>
    <param name="filename"><string>{xml_escape(jaw_path.as_posix())}</string></param>
    <param name="time_offset"><time value="0s"/></param>
  </layer>'''
        background_layer = import_layer(background_path, "BACKGROUND", 0, 0, width, height)
        base_layer = import_layer(base_path, str(rig["character"]), base_left, base_top, base_right, base_bottom)
        sound_layer = f'''  <layer type="sound" active="true" exclude_from_rendering="false" version="0.1" desc="VOICE REFERENCE">
    <param name="z_depth"><real value="0.0000000000"/></param>
    <param name="filename"><string>{xml_escape(audio_path.as_posix())}</string></param>
    <param name="delay"><time value="{pre_hold:.3f}s"/></param>
    <param name="volume"><real value="1.0000000000"/></param>
  </layer>'''
        title = xml_escape(f"{normalized['title']} - {rig['character']} full-audio proof")
        document = f'''<?xml version="1.0" encoding="UTF-8"?>
<canvas version="0.1" width="{width}" height="{height}" xres="2834.645752" yres="2834.645752" view-box="-4.000000 2.250000 4.000000 -2.250000" antialias="2" fps="{fps:.3f}" begin-time="0s" end-time="{duration:.3f}s" bgcolor="0.100000 0.100000 0.100000 1.000000">
  <name>{title}</name>
  <desc>Veridex full-audio Synfig proof. Two-second holds surround the unchanged voice recording.</desc>
{background_layer}
{base_layer}
{jaw_layer}
{sound_layer}
</canvas>
'''
        return {
            "filename": f"{_slug(normalized['project_id'])}-{_slug(rig['character'])}-full-audio-proof.sif",
            "content": document.encode("utf-8"),
            "duration": duration,
            "audio_duration": audio_duration,
            "pre_hold": pre_hold,
            "post_hold": post_hold,
            "take_id": take["take_id"],
            "rig_id": rig["rig_id"],
            "audio_path": str(audio_path),
        }

    def list_projects(self, workspace_id: str) -> list[Dict[str, Any]]:
        root = self._workspace_root(workspace_id) / "projects"
        if not root.is_dir():
            return []
        projects = []
        for path in sorted(root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    projects.append(normalize_project(value))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        return sorted(projects, key=lambda row: str(row.get("updated_at") or ""), reverse=True)

    def save_project(self, workspace_id: str, value: Dict[str, Any]) -> Dict[str, Any]:
        project = normalize_project(value)
        existing_path = self._project_path(workspace_id, project["project_id"])
        existing: Dict[str, Any] = {}
        if existing_path.is_file():
            try:
                loaded = json.loads(existing_path.read_text(encoding="utf-8"))
                existing = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                existing = {}
        existing_version = max(0, int(existing.get("project_version") or 0))
        if existing and existing_version:
            snapshot = normalize_project(existing)
            snapshot["revision_id"] = f"{_slug(project['project_id'])}-v{existing_version}"
            self._write_json(self._revision_path(workspace_id, project["project_id"], existing_version), snapshot)
        now = utc_now()
        project.update({
            "saved": True,
            "project_version": existing_version + 1,
            "revision_id": "",
            "created_at": str(existing.get("created_at") or now),
            "updated_at": now,
        })
        self._write_json(existing_path, project)
        return project

    def load_project(self, workspace_id: str, project_id: str) -> Dict[str, Any] | None:
        path = self._project_path(workspace_id, project_id)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return normalize_project(value) if isinstance(value, dict) else None

    def build_shot_package(
        self,
        project: Dict[str, Any],
        shot_id: str,
        source_files: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build a bounded, self-contained package for one Synfig shot.

        The package deliberately contains source media, timing metadata, and cue data,
        not a second project database or an opaque generated Synfig scene.
        """
        normalized = normalize_project(project)
        shot = next((row for row in normalized["storyboard"] if row["shot_id"] == shot_id), None)
        if not shot:
            raise KeyError("The selected storyboard shot does not exist")
        matching_tracks = [row for row in normalized["audio_tracks"] if row.get("shot_id") == shot_id]
        if not matching_tracks:
            matching_tracks = [row for row in normalized["audio_tracks"] if not row.get("shot_id")]
        track_ids = {row["track_id"] for row in matching_tracks}
        matching_takes = [row for row in normalized["lipsync_takes"] if row.get("track_id") in track_ids]
        rig_ids = {row["rig_id"] for row in matching_takes}
        matching_rigs = [row for row in normalized["mouth_rigs"] if row.get("rig_id") in rig_ids]
        asset_ids = {
            row["asset_id"]
            for row in normalized["assets"]
            if row.get("role") in {"background", "set", "character", "prop", "overlay"}
        }
        if shot.get("asset_id"):
            asset_ids.add(shot["asset_id"])
        for rig in matching_rigs:
            if rig.get("base_asset_id"):
                asset_ids.add(rig["base_asset_id"])
            asset_ids.update(value for value in (rig.get("shapes") or {}).values() if value)
        selected_assets = [row for row in normalized["assets"] if row.get("asset_id") in asset_ids]
        buffer = io.BytesIO()
        package_files: list[Dict[str, Any]] = []
        used_names: set[str] = set()
        total_bytes = 0

        def add_source(file_id: str, folder: str, preferred_name: str) -> str:
            nonlocal total_bytes
            source = source_files.get(file_id)
            if not source:
                raise KeyError(f"Source file {file_id} is unavailable for this shot")
            path = Path(str(source.get("path") or "")).resolve()
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGES | SUPPORTED_AUDIO:
                raise ValueError(f"Shot package source is not a supported media file: {path.name}")
            size = path.stat().st_size
            total_bytes += size
            if total_bytes > MAX_SHOT_PACKAGE_BYTES:
                raise ValueError("The shot package is too large; keep source media below 250 MB.")
            stem = re.sub(r"[^A-Za-z0-9._-]+", "-", preferred_name or path.name).strip(".-") or path.name
            target = f"{folder}/{stem}"
            base, suffix = Path(target).stem, Path(target).suffix
            counter = 2
            while target in used_names:
                target = f"{folder}/{base}-{counter}{suffix}"
                counter += 1
            used_names.add(target)
            with zipfile.ZipFile(buffer, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(path, target)
            package_files.append({"file_id": file_id, "path": target, "name": path.name, "size": size})
            return target

        asset_manifest = []
        for asset in selected_assets:
            target = add_source(asset["file_id"], "assets", asset.get("name") or "asset")
            asset_manifest.append({
                "asset_id": asset["asset_id"],
                "file_id": asset["file_id"],
                "name": asset["name"],
                "role": asset["role"],
                "path": target,
                "width_percent": asset["width_percent"],
                "x_percent": asset["x_percent"],
                "y_percent": asset["y_percent"],
                "opacity_percent": asset["opacity_percent"],
            })
        audio_manifest = []
        for track in matching_tracks:
            target = add_source(track["file_id"], "audio", track.get("name") or "audio")
            audio_manifest.append({**{key: track[key] for key in (
                "track_id", "file_id", "name", "track_type", "character", "shot_id",
                "start_seconds", "trim_in_seconds", "trim_out_seconds", "volume_db",
                "pan_percent", "fade_in_seconds", "fade_out_seconds", "muted", "solo",
            )}, "path": target})
        cues = [
            {
                "take_id": take["take_id"],
                "track_id": take["track_id"],
                "rig_id": take["rig_id"],
                "recognizer": take["recognizer"],
                "extended_shapes": take["extended_shapes"],
                "duration": take["duration"],
                "mouthCues": take["mouth_cues"],
                "manualJawCorrections": take["manual_jaw_corrections"],
                "manualJawSegments": take["manual_jaw_segments"],
            }
            for take in matching_takes
        ]
        manifest = {
            "schema_version": 1,
            "package_type": "veridex_synfig_shot",
            "generated_at": utc_now(),
            "tool": "Synfig Studio",
            "project": {
                "project_id": normalized["project_id"],
                "title": normalized["title"],
                "width": normalized["width"],
                "height": normalized["height"],
                "frame_rate": normalized["frame_rate"],
            },
            "shot": shot,
            "assets": asset_manifest,
            "audio_tracks": audio_manifest,
            "mouth_rigs": matching_rigs,
            "lip_sync": {"takes": cues, "cue_file": "lip-sync-cues.json" if cues else ""},
            "instructions": [
                "Import the assets from assets/ into Synfig Studio.",
                "Use the project width, height, and frame rate for the shot canvas.",
                "Use audio/ as the timing reference and lip-sync-cues.json for mouth timing.",
                "Render this shot, then import the rendered file back into Animation Studio.",
            ],
            "source_files": package_files,
        }
        readme = "\n".join([
            "Veridex Synfig shot package",
            "",
            f"Project: {normalized['title']}",
            f"Shot: {shot['title']}",
            f"Canvas: {normalized['width']}x{normalized['height']} at {normalized['frame_rate']} fps",
            "",
            "Open shot-manifest.json for placements, timing, and cue references.",
            "Import the rendered shot back through Animation Studio; do not overwrite source assets.",
            "",
        ])
        with zipfile.ZipFile(buffer, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("shot-manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            archive.writestr("lip-sync-cues.json", json.dumps({"takes": cues}, indent=2, ensure_ascii=False) + "\n")
            archive.writestr("README.txt", readme)
        filename = f"{_slug(normalized['project_id'])}-{_slug(shot['shot_id'])}-synfig-shot.zip"
        return {"filename": filename, "content": buffer.getvalue(), "manifest": manifest}

    def attach_render(self, workspace_id: str, project: Dict[str, Any], shot_id: str, file_row: Dict[str, Any]) -> Dict[str, Any]:
        normalized = normalize_project(project)
        if not any(row.get("shot_id") == shot_id for row in normalized["storyboard"]):
            raise KeyError("The selected storyboard shot does not exist")
        path = Path(str(file_row.get("path") or "")).resolve()
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_RENDERS:
            raise ValueError("Import a rendered video or supported still image.")
        renders = [row for row in normalized.get("rendered_shots", []) if row.get("file_id") != file_row.get("file_id")]
        renders.append({
            "render_id": f"render-{file_row.get('file_id')}",
            "shot_id": shot_id,
            "file_id": str(file_row.get("file_id") or ""),
            "source_session_id": str(file_row.get("source_session_id") or ""),
            "name": _clean(file_row.get("name"), 240) or path.name,
            "format": path.suffix.lower().lstrip("."),
            "status": "imported",
            "imported_at": utc_now(),
        })
        return self.save_project(workspace_id, {**normalized, "rendered_shots": renders})

    def bootstrap(self, workspace_id: str) -> Dict[str, Any]:
        projects = self.list_projects(workspace_id)
        return {
            "room_id": ROOM_ID,
            "tools": self.tools(),
            "projects": projects,
            "starter_project": projects[0] if projects else default_project(),
            "workflow": [
                "Plan one shot and bind its assets, voice-over, and lip-sync cues.",
                "Export that shot as a self-contained Synfig package.",
                "Animate and render the shot in Synfig Studio.",
                "Import the verified render back into the shot record.",
                "Link completed shot renders to Video Production for final assembly.",
            ],
        }

    def generate_lipsync(
        self,
        audio_path: Path,
        transcript: str = "",
        recognizer: str = "pocketSphinx",
        extended_shapes: str = "GHX",
    ) -> Dict[str, Any]:
        audio = Path(audio_path).resolve()
        if not audio.is_file() or audio.suffix.lower() not in SUPPORTED_AUDIO:
            raise ValueError("Select a supported audio file: WAV, M4A, MP3, FLAC, AAC, or OGG.")
        executable = str((self.tools().get("rhubarb") or {}).get("path") or "")
        if not executable:
            raise RuntimeError("Rhubarb Lip Sync is not installed or is not available on PATH.")
        with tempfile.TemporaryDirectory(prefix="veridex-rhubarb-") as temporary:
            root = Path(temporary)
            analysis_audio = audio
            if audio.suffix.lower() not in {".wav", ".ogg"}:
                ffmpeg = str((self.tools().get("ffmpeg") or {}).get("path") or "")
                if not ffmpeg:
                    raise RuntimeError("FFmpeg is required to convert this audio format for Rhubarb.")
                analysis_audio = root / "analysis.wav"
                converted = subprocess.run(
                    [ffmpeg, "-y", "-i", str(audio), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(analysis_audio)],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )
                if converted.returncode != 0 or not analysis_audio.is_file():
                    detail = _clean(converted.stderr or converted.stdout, 500)
                    raise RuntimeError(f"Audio conversion for Rhubarb failed{': ' + detail if detail else '.'}")
            output = root / "mouth-cues.json"
            recognizer_name = str(recognizer or "pocketSphinx")
            if recognizer_name not in {"pocketSphinx", "phonetic"}:
                recognizer_name = "pocketSphinx"
            shapes = "".join(shape for shape in "GHX" if shape in str(extended_shapes or "").upper())
            command = [executable, "-f", "json", "-r", recognizer_name, "--extendedShapes", shapes, "-o", str(output)]
            cleaned_transcript = str(transcript or "").replace("\x00", "").strip()[:20_000]
            if cleaned_transcript:
                dialog = root / "dialog.txt"
                dialog.write_text(cleaned_transcript, encoding="utf-8")
                command.extend(["-d", str(dialog)])
            command.append(str(analysis_audio))
            completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
            if completed.returncode != 0 or not output.is_file():
                detail = _clean(completed.stderr or completed.stdout, 500)
                raise RuntimeError(f"Rhubarb lip-sync generation failed{': ' + detail if detail else '.'}")
            value = json.loads(output.read_text(encoding="utf-8"))
        cues = value.get("mouthCues") if isinstance(value, dict) else None
        if not isinstance(cues, list) or not cues:
            raise RuntimeError("Rhubarb returned no mouth cues.")
        normalized = []
        last_end = 0.0
        for row in cues:
            start = round(float(row.get("start") or 0), 3)
            end = round(float(row.get("end") or 0), 3)
            shape = str(row.get("value") or "X").upper()
            if start < last_end - 0.001 or end < start or shape not in MOUTH_SHAPES:
                raise RuntimeError("Rhubarb returned invalid mouth-cue data.")
            normalized.append({"start": start, "end": end, "value": shape})
            last_end = end
        return {
            "schema_version": 1,
            "generator": "Rhubarb Lip Sync",
            "audio_name": audio.name,
            "recognizer": recognizer_name,
            "extended_shapes": shapes,
            "duration": last_end,
            "mouthCues": normalized,
            "generated_at": utc_now(),
        }
