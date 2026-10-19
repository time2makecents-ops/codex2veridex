"""Local, review-first iPhone media transfer and cleanup workspace.

The app inventories folder-backed Apple sources and the Windows portable-device
bridge, copies selected originals into a user-selected archive, verifies each
copy, and keeps phone deletion behind an independently verified Google Drive
copy plus an explicit preview token. Originals are never rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image, ImageOps, ImageStat


SCHEMA_VERSION = 2
MAX_JSON_BODY = 2 * 1024 * 1024
IMAGE_EXTENSIONS = {".avif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".3gp", ".avi", ".m4v", ".mov", ".mp4", ".mts", ".webm"}
AUDIO_EXTENSIONS = {".aac", ".aif", ".aiff", ".alac", ".caf", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".wma"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
SOURCE_KINDS = {"folder", "icloud_photos", "icloud_drive", "export_inbox", "iphone_usb"}
DISPOSITIONS = {"keep_on_phone", "download_keep", "download_delete"}
JOB_STATES = {"queued", "running", "completed", "failed", "cancelled"}
CLASSIFICATIONS = {"voice_memo", "meeting_interview", "personal_note", "music", "ambient_noise", "unknown"}
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.file"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_kind(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in IMAGE_EXTENSIONS:
        return "photo"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return "other"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(value).name).strip(" .")
    return cleaned or "untitled"


def safe_relative(root: Path, value: str) -> Path:
    root = root.resolve()
    candidate = (root / unquote(value or "")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("path escapes its authorized root")
    return candidate


def file_url_path(path: Path) -> str:
    return str(path.resolve())


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path.resolve()), timeout=20, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 20000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def database(database_path: Path) -> Iterator[sqlite3.Connection]:
    connection = _connect(database_path)
    try:
        yield connection
    finally:
        connection.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    path TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_scan_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_items (
    item_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_kind TEXT NOT NULL,
    source_locator_json TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    media_kind TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER NOT NULL,
    captured_at TEXT,
    modified_at TEXT,
    disposition TEXT NOT NULL DEFAULT 'keep_on_phone',
    transfer_state TEXT NOT NULL DEFAULT 'not_downloaded',
    local_path TEXT,
    local_sha256 TEXT,
    local_verified_at TEXT,
    secondary_path TEXT,
    secondary_sha256 TEXT,
    secondary_size INTEGER,
    secondary_verified_at TEXT,
    drive_file_id TEXT,
    drive_size INTEGER,
    drive_md5 TEXT,
    drive_verified_at TEXT,
    quality_flags_json TEXT NOT NULL DEFAULT '[]',
    perceptual_hash TEXT,
    deletion_state TEXT NOT NULL DEFAULT 'not_requested',
    last_seen_scan TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, relative_path, size_bytes, modified_at)
);

CREATE INDEX IF NOT EXISTS media_items_filter_idx
ON media_items(media_kind, captured_at, disposition, transfer_state);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    completed_items INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    completed_bytes INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    transcript_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES media_items(item_id),
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    model TEXT NOT NULL,
    language TEXT,
    classification TEXT NOT NULL DEFAULT 'unknown',
    text TEXT,
    sidecar_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(item_id, version)
);

CREATE TABLE IF NOT EXISTS deletion_previews (
    token TEXT PRIMARY KEY,
    item_ids_json TEXT NOT NULL,
    confirmation_text TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    item_id TEXT,
    job_id TEXT,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def create_database(database_path: Path) -> Path:
    database_path = Path(database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with database(database_path) as connection:
        connection.executescript(SCHEMA)
        existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(media_items)").fetchall()}
        for column, declaration in (
            ("secondary_path", "TEXT"),
            ("secondary_sha256", "TEXT"),
            ("secondary_size", "INTEGER"),
            ("secondary_verified_at", "TEXT"),
        ):
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE media_items ADD COLUMN {column} {declaration}")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        now = utc_now()
        connection.execute(
            "INSERT OR IGNORE INTO settings(key, value_json, updated_at) VALUES('limits', ?, ?)",
            (json.dumps({"batch_bytes": None, "file_bytes": None}), now),
        )
        connection.commit()
    return database_path


def get_setting(database_path: Path, key: str, default: Any = None) -> Any:
    with database(database_path) as connection:
        row = connection.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
    return default if row is None else json.loads(row["value_json"])


def set_setting(database_path: Path, key: str, value: Any) -> None:
    with database(database_path) as connection:
        connection.execute(
            "INSERT INTO settings(key, value_json, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, json.dumps(value, separators=(",", ":")), utc_now()),
        )
        connection.commit()


def record_event(
    connection: sqlite3.Connection,
    event_type: str,
    *,
    item_id: str | None = None,
    job_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        "INSERT INTO events(event_type, item_id, job_id, details_json, created_at) VALUES(?, ?, ?, ?, ?)",
        (event_type, item_id, job_id, json.dumps(details or {}, separators=(",", ":")), utc_now()),
    )


def add_source(database_path: Path, *, kind: str, label: str, path: str | None = None) -> dict[str, Any]:
    kind = str(kind).strip().casefold()
    if kind not in SOURCE_KINDS:
        raise ValueError("unsupported source kind")
    label = str(label).strip()
    if not label:
        raise ValueError("source label is required")
    resolved: str | None = None
    if kind != "iphone_usb":
        if not path:
            raise ValueError("source folder is required")
        folder = Path(path).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("source folder does not exist")
        resolved = str(folder)
    source_id = uuid.uuid4().hex
    now = utc_now()
    with database(database_path) as connection:
        connection.execute(
            "INSERT INTO sources(source_id, kind, label, path, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
            (source_id, kind, label, resolved, now, now),
        )
        record_event(connection, "source_added", details={"source_id": source_id, "kind": kind, "label": label})
        connection.commit()
    return {"source_id": source_id, "kind": kind, "label": label, "path": resolved, "enabled": True}


def list_sources(database_path: Path) -> list[dict[str, Any]]:
    with database(database_path) as connection:
        rows = connection.execute("SELECT * FROM sources ORDER BY created_at").fetchall()
    return [
        {
            "source_id": row["source_id"], "kind": row["kind"], "label": row["label"],
            "path": row["path"], "enabled": bool(row["enabled"]), "last_scan_at": row["last_scan_at"],
            "last_error": row["last_error"],
        }
        for row in rows
    ]


def _capture_time(path: Path, stat: os.stat_result) -> str:
    if path.suffix.casefold() in IMAGE_EXTENSIONS:
        try:
            with Image.open(path) as image:
                exif = image.getexif()
                raw = exif.get(36867) or exif.get(306)
                if raw:
                    return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    return datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")


def _item_id(source_id: str, relative_path: str, size: int, modified_at: str | None) -> str:
    value = f"{source_id}\0{relative_path.casefold()}\0{size}\0{modified_at or ''}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:32]


def _upsert_scan_items(database_path: Path, source: sqlite3.Row, records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    scan_id = uuid.uuid4().hex
    now = utc_now()
    with database(database_path) as connection:
        for record in records:
            relative = str(record["relative_path"]).replace("\\", "/")
            size = max(0, int(record.get("size_bytes") or 0))
            modified = str(record.get("modified_at") or "")
            item_id = _item_id(source["source_id"], relative, size, modified)
            filename = safe_filename(record.get("filename") or Path(relative).name)
            kind = record.get("media_kind") or media_kind(Path(filename))
            locator = record.get("source_locator") or {"path": str(Path(source["path"]) / Path(relative))}
            connection.execute(
                """INSERT INTO media_items(
                       item_id, source_id, source_kind, source_locator_json, relative_path, filename,
                       media_kind, mime_type, size_bytes, captured_at, modified_at, last_seen_scan,
                       created_at, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, relative_path, size_bytes, modified_at) DO UPDATE SET
                       source_locator_json=excluded.source_locator_json,
                       filename=excluded.filename,
                       media_kind=excluded.media_kind,
                       mime_type=excluded.mime_type,
                       captured_at=excluded.captured_at,
                       last_seen_scan=excluded.last_seen_scan,
                       updated_at=excluded.updated_at""",
                (
                    item_id, source["source_id"], source["kind"], json.dumps(locator, separators=(",", ":")),
                    relative, filename, kind, record.get("mime_type") or mimetypes.guess_type(filename)[0],
                    size, record.get("captured_at") or modified, modified, scan_id, now, now,
                ),
            )
        connection.execute(
            "UPDATE sources SET last_scan_at=?, last_error=NULL, updated_at=? WHERE source_id=?",
            (now, now, source["source_id"]),
        )
        record_event(connection, "source_scanned", details={"source_id": source["source_id"], "count": len(records)})
        connection.commit()
    return {"source_id": source["source_id"], "scan_id": scan_id, "count": len(records)}


def _scan_folder(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
        records.append({
            "relative_path": path.relative_to(root).as_posix(),
            "filename": path.name,
            "size_bytes": stat.st_size,
            "modified_at": modified,
            "captured_at": _capture_time(path, stat),
            "media_kind": media_kind(path),
            "mime_type": mimetypes.guess_type(path.name)[0],
            "source_locator": {"path": str(path.resolve())},
        })
    return records


def portable_bridge_path() -> Path:
    return Path(__file__).resolve().parent / "scripts" / "iphone_portable_bridge.ps1"


def _run_portable_bridge(action: str, *, locator: dict[str, Any] | None = None, destination: Path | None = None) -> Any:
    if os.name != "nt":
        raise RuntimeError("the iPhone USB bridge is available only on Windows")
    bridge = portable_bridge_path()
    if not bridge.is_file():
        raise RuntimeError("the iPhone USB bridge script is missing")
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(bridge), "-Action", action]
    if locator is not None:
        import base64
        encoded = base64.b64encode(json.dumps(locator).encode("utf-8")).decode("ascii")
        command.extend(["-LocatorBase64", encoded])
    if destination is not None:
        command.extend(["-Destination", str(destination.resolve())])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    if completed.returncode:
        raw_message = (completed.stderr or completed.stdout or "portable-device operation failed").strip()
        message = re.split(r"\r?\nAt\s", raw_message, maxsplit=1)[0].strip()
        raise RuntimeError(message)
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError("portable-device bridge returned invalid output") from exc


def scan_source(database_path: Path, source_id: str) -> dict[str, Any]:
    with database(database_path) as connection:
        source = connection.execute("SELECT * FROM sources WHERE source_id=? AND enabled=1", (source_id,)).fetchone()
    if source is None:
        raise ValueError("source was not found or is disabled")
    try:
        if source["kind"] == "iphone_usb":
            records = _run_portable_bridge("scan") or []
        else:
            root = Path(source["path"])
            if not root.is_dir():
                raise ValueError("source folder is unavailable")
            records = _scan_folder(root)
        return _upsert_scan_items(database_path, source, records)
    except Exception as exc:
        with database(database_path) as connection:
            connection.execute(
                "UPDATE sources SET last_error=?, updated_at=? WHERE source_id=?",
                (str(exc), utc_now(), source_id),
            )
            connection.commit()
        raise


def validate_destination(path_value: str, *, probe: bool = True) -> dict[str, Any]:
    if not str(path_value).strip():
        raise ValueError("destination folder is required")
    path = Path(path_value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("destination is not a folder")
    source_root = Path(__file__).resolve().parent
    if path == source_root or source_root in path.parents:
        raise ValueError("choose a destination outside the application source folder")
    if probe:
        probe_dir = path / f".veridex-write-test-{secrets.token_hex(4)}"
        probe_file = probe_dir / "probe.bin"
        try:
            probe_dir.mkdir()
            payload = secrets.token_bytes(32)
            probe_file.write_bytes(payload)
            if probe_file.read_bytes() != payload:
                raise ValueError("destination write verification failed")
        finally:
            if probe_file.exists():
                probe_file.unlink()
            if probe_dir.exists():
                probe_dir.rmdir()
    usage = shutil.disk_usage(path)
    return {"path": str(path), "free_bytes": usage.free, "total_bytes": usage.total, "writable": True}


def save_destination(database_path: Path, path_value: str) -> dict[str, Any]:
    result = validate_destination(path_value)
    set_setting(database_path, "archive_destination", result["path"])
    return result


def volume_identity(path_value: str | Path) -> str:
    path = Path(path_value).expanduser().resolve()
    anchor = path.anchor.rstrip("\\/").casefold()
    if not anchor:
        raise ValueError("destination volume could not be identified")
    drive_match = re.fullmatch(r"([a-z]):", anchor)
    if os.name == "nt" and drive_match:
        drive_letter = drive_match.group(1).upper()
        try:
            import ctypes
            from ctypes import wintypes

            class StorageDeviceNumber(ctypes.Structure):
                _fields_ = [
                    ("device_type", wintypes.DWORD),
                    ("device_number", wintypes.DWORD),
                    ("partition_number", wintypes.DWORD),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
            ]
            kernel32.CreateFileW.restype = wintypes.HANDLE
            kernel32.DeviceIoControl.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
            ]
            kernel32.DeviceIoControl.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.CreateFileW(
                rf"\\.\{drive_letter}:", 0, 0x00000001 | 0x00000002,
                None, 3, 0, None,
            )
            invalid_handle = ctypes.c_void_p(-1).value
            if handle != invalid_handle:
                try:
                    device = StorageDeviceNumber()
                    returned = wintypes.DWORD()
                    ok = kernel32.DeviceIoControl(
                        handle, 0x002D1080, None, 0,
                        ctypes.byref(device), ctypes.sizeof(device), ctypes.byref(returned), None,
                    )
                    if ok:
                        return f"physical-disk:{int(device.device_number)}"
                finally:
                    kernel32.CloseHandle(handle)
        except (OSError, ValueError):
            pass
    return f"volume:{anchor}"


def ensure_independent_volumes(primary: str | Path, secondary: str | Path) -> None:
    if volume_identity(primary) == volume_identity(secondary):
        raise ValueError("the second copy must be on a different physical drive or network share")


def save_secondary_destination(database_path: Path, path_value: str) -> dict[str, Any]:
    result = validate_destination(path_value)
    primary = get_setting(database_path, "archive_destination")
    if primary:
        ensure_independent_volumes(primary, result["path"])
    set_setting(database_path, "secondary_destination", result["path"])
    result["independent_from_primary"] = bool(primary)
    return result


def list_items(database_path: Path, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = filters or {}
    clauses = ["1=1"]
    values: list[Any] = []
    for field in ("media_kind", "disposition", "transfer_state", "source_id"):
        value = str(filters.get(field) or "").strip()
        if value:
            clauses.append(f"{field}=?")
            values.append(value)
    if filters.get("date_from"):
        clauses.append("COALESCE(captured_at, modified_at) >= ?")
        values.append(str(filters["date_from"]) + "T00:00:00Z")
    if filters.get("date_to"):
        clauses.append("COALESCE(captured_at, modified_at) <= ?")
        values.append(str(filters["date_to"]) + "T23:59:59Z")
    if filters.get("search"):
        clauses.append("(filename LIKE ? OR relative_path LIKE ?)")
        needle = f"%{filters['search']}%"
        values.extend([needle, needle])
    limit = min(max(int(filters.get("limit") or 250), 1), 1000)
    offset = max(int(filters.get("offset") or 0), 0)
    query = "SELECT * FROM media_items WHERE " + " AND ".join(clauses)
    with database(database_path) as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM ({query})", values).fetchone()[0]
        rows = connection.execute(
            query + " ORDER BY COALESCE(captured_at, modified_at) DESC, filename LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
    items = []
    for row in rows:
        items.append({
            "item_id": row["item_id"], "source_id": row["source_id"], "source_kind": row["source_kind"],
            "relative_path": row["relative_path"], "filename": row["filename"], "media_kind": row["media_kind"],
            "mime_type": row["mime_type"], "size_bytes": row["size_bytes"], "captured_at": row["captured_at"],
            "modified_at": row["modified_at"], "disposition": row["disposition"], "transfer_state": row["transfer_state"],
            "local_path": row["local_path"], "local_sha256": row["local_sha256"],
            "local_verified": bool(row["local_verified_at"]),
            "secondary_path": row["secondary_path"], "secondary_verified": bool(row["secondary_verified_at"]),
            "drive_verified": bool(row["drive_verified_at"]),
            "second_copy_verified": bool(row["secondary_verified_at"] or row["drive_verified_at"]),
            "deletion_state": row["deletion_state"], "quality_flags": json.loads(row["quality_flags_json"]),
            "preview_url": f"/media/{row['item_id']}",
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def update_dispositions(database_path: Path, item_ids: Sequence[str], disposition: str) -> dict[str, Any]:
    if disposition not in DISPOSITIONS:
        raise ValueError("invalid disposition")
    normalized = [str(value) for value in item_ids if str(value).strip()]
    if not normalized:
        raise ValueError("select at least one item")
    marks = ",".join("?" for _ in normalized)
    with database(database_path) as connection:
        result = connection.execute(
            f"UPDATE media_items SET disposition=?, updated_at=? WHERE item_id IN ({marks})",
            [disposition, utc_now(), *normalized],
        )
        for item_id in normalized:
            record_event(connection, "disposition_changed", item_id=item_id, details={"disposition": disposition})
        connection.commit()
    return {"updated": result.rowcount, "disposition": disposition}


def _quality_and_hash(path: Path, kind: str) -> tuple[list[str], str | None]:
    flags: list[str] = []
    perceptual: str | None = None
    if kind == "photo":
        try:
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                width, height = image.size
                if min(width, height) < 720:
                    flags.append("low_resolution")
                grayscale = image.convert("L")
                mean = ImageStat.Stat(grayscale).mean[0]
                if mean < 28:
                    flags.append("very_dark")
                elif mean > 235:
                    flags.append("very_bright")
                thumb = grayscale.resize((9, 8))
                bits = [thumb.getpixel((x, y)) > thumb.getpixel((x + 1, y)) for y in range(8) for x in range(8)]
                perceptual = f"{sum((1 << index) for index, bit in enumerate(bits) if bit):016x}"
        except Exception:
            flags.append("unreadable_image")
    elif kind in {"video", "audio"}:
        try:
            completed = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=60, check=False,
            )
            if completed.returncode:
                flags.append("unreadable_media")
            else:
                value = json.loads(completed.stdout or "{}")
                streams = value.get("streams") or []
                if kind == "video" and not any(stream.get("codec_type") == "video" for stream in streams):
                    flags.append("missing_video_stream")
                if kind == "audio" and not any(stream.get("codec_type") == "audio" for stream in streams):
                    flags.append("missing_audio_stream")
                if float((value.get("format") or {}).get("duration") or 0) <= 0:
                    flags.append("empty_media")
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
            flags.append("analysis_unavailable")
    return flags, perceptual


def _unique_target(root: Path, item: sqlite3.Row) -> Path:
    captured = parse_utc(item["captured_at"] or item["modified_at"] or utc_now())
    folder = root / f"{captured.year:04d}" / f"{captured.month:02d}" / item["media_kind"] / item["source_kind"]
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_filename(item["filename"])
    candidate = folder / name
    counter = 2
    while candidate.exists():
        candidate = folder / f"{Path(name).stem}_{counter}{Path(name).suffix}"
        counter += 1
    return candidate


def _copy_local_verified(source: Path, target: Path, expected_size: int, cancel: threading.Event | None = None) -> tuple[str, int]:
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        partial.unlink()
    digest = hashlib.sha256()
    copied = 0
    try:
        with source.open("rb") as read_handle, partial.open("xb") as write_handle:
            while True:
                if cancel and cancel.is_set():
                    raise InterruptedError("transfer cancelled")
                chunk = read_handle.read(1024 * 1024)
                if not chunk:
                    break
                write_handle.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            write_handle.flush()
            os.fsync(write_handle.fileno())
        if expected_size >= 0 and copied != expected_size:
            raise ValueError(f"copied size {copied} does not match expected size {expected_size}")
        first_hash = digest.hexdigest()
        if sha256_file(partial) != first_hash:
            raise ValueError("archive checksum reread did not match the transfer checksum")
        partial.replace(target)
        return first_hash, copied
    except Exception:
        if partial.exists():
            partial.unlink()
        raise


def google_dependencies_available() -> bool:
    try:
        import google.oauth2.credentials  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


def _google_credentials(database_path: Path) -> Any:
    if not google_dependencies_available():
        raise RuntimeError("Google Drive support is not installed; install requirements-iphone-media.txt")
    import keyring
    from google.oauth2.credentials import Credentials
    token = keyring.get_password("veridex-iphone-media", str(database_path.resolve()))
    if not token:
        raise RuntimeError("Google Drive is not connected")
    credentials = Credentials.from_authorized_user_info(json.loads(token), [GOOGLE_SCOPE])
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())
        keyring.set_password("veridex-iphone-media", str(database_path.resolve()), credentials.to_json())
    return credentials


def connect_google(database_path: Path, client_secrets_path: str) -> dict[str, Any]:
    if not google_dependencies_available():
        raise RuntimeError("Google Drive support is not installed; install requirements-iphone-media.txt")
    secrets_path = Path(client_secrets_path).expanduser().resolve()
    if not secrets_path.is_file():
        raise ValueError("Google OAuth client-secrets file was not found")
    import keyring
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), [GOOGLE_SCOPE])
    credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
    keyring.set_password("veridex-iphone-media", str(database_path.resolve()), credentials.to_json())
    set_setting(database_path, "google_client_secrets_path", str(secrets_path))
    return google_status(database_path)


def google_status(database_path: Path) -> dict[str, Any]:
    if not google_dependencies_available():
        return {"available": False, "connected": False, "reason": "optional dependencies are not installed"}
    if not get_setting(database_path, "google_client_secrets_path"):
        return {"available": True, "connected": False, "reason": "Google Drive is not connected"}
    try:
        credentials = _google_credentials(database_path)
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        about = service.about().get(fields="user(displayName,emailAddress)").execute()
        user = about.get("user") or {}
        return {"available": True, "connected": True, "email": user.get("emailAddress"), "name": user.get("displayName")}
    except Exception as exc:
        return {"available": True, "connected": False, "reason": str(exc)}


def _drive_folder(service: Any, name: str, parent_id: str | None = None) -> str:
    escaped = name.replace("'", "\\'")
    query = f"name='{escaped}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    existing = service.files().list(q=query, fields="files(id,name)", pageSize=10).execute().get("files") or []
    if existing:
        return existing[0]["id"]
    metadata: dict[str, Any] = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    return service.files().create(body=metadata, fields="id").execute()["id"]


def upload_drive_verified(database_path: Path, path: Path, relative_parent: Sequence[str]) -> dict[str, Any]:
    credentials = _google_credentials(database_path)
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    configured = get_setting(database_path, "google_destination", {}) or {}
    parent_id = configured.get("folder_id")
    root_name = configured.get("name") or "Veridex iPhone Archive"
    if not parent_id:
        parent_id = _drive_folder(service, root_name)
        set_setting(database_path, "google_destination", {"folder_id": parent_id, "name": root_name})
    for part in relative_parent:
        parent_id = _drive_folder(service, part, parent_id)
    media = MediaFileUpload(str(path), mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream", resumable=True)
    request = service.files().create(
        body={"name": path.name, "parents": [parent_id]}, media_body=media,
        fields="id,name,size,md5Checksum,sha256Checksum",
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    remote = service.files().get(fileId=response["id"], fields="id,name,size,md5Checksum,sha256Checksum").execute()
    local_md5 = md5_file(path)
    if int(remote.get("size") or -1) != path.stat().st_size:
        raise ValueError("Google Drive size verification failed")
    if str(remote.get("md5Checksum") or "").casefold() != local_md5.casefold():
        raise ValueError("Google Drive checksum verification failed")
    return {"file_id": remote["id"], "size": int(remote["size"]), "md5": remote["md5Checksum"]}


@dataclass
class JobRuntime:
    cancel: threading.Event
    thread: threading.Thread


class JobManager:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRuntime] = {}

    def start_transfer(
        self,
        item_ids: Sequence[str],
        destination: str | None,
        upload_google: bool,
        secondary_destination: str | None = None,
    ) -> str:
        normalized = list(dict.fromkeys(str(value) for value in item_ids if str(value).strip()))
        if not normalized:
            raise ValueError("select at least one item")
        destination_value = destination or get_setting(self.database_path, "archive_destination")
        validated = validate_destination(str(destination_value or ""))
        secondary_value = secondary_destination or None
        secondary_validated: dict[str, Any] | None = None
        if secondary_value:
            secondary_validated = validate_destination(str(secondary_value))
            ensure_independent_volumes(validated["path"], secondary_validated["path"])
        marks = ",".join("?" for _ in normalized)
        with database(self.database_path) as connection:
            rows = connection.execute(f"SELECT * FROM media_items WHERE item_id IN ({marks})", normalized).fetchall()
        if len(rows) != len(normalized):
            raise ValueError("one or more selected items no longer exist")
        limits = get_setting(self.database_path, "limits", {}) or {}
        file_limit = limits.get("file_bytes")
        batch_limit = limits.get("batch_bytes")
        total_bytes = sum(int(row["size_bytes"]) for row in rows)
        if file_limit and any(int(row["size_bytes"]) > int(file_limit) for row in rows):
            raise ValueError("selection contains a file above the configured per-file limit")
        if batch_limit and total_bytes > int(batch_limit):
            raise ValueError("selection exceeds the configured batch-size limit")
        if validated["free_bytes"] < total_bytes:
            raise ValueError("selected destination does not have enough free space")
        if secondary_validated and secondary_validated["free_bytes"] < total_bytes:
            raise ValueError("second-copy destination does not have enough free space")
        job_id = uuid.uuid4().hex
        now = utc_now()
        with database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO jobs(job_id,kind,status,total_items,total_bytes,details_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    job_id, "transfer", "queued", len(rows), total_bytes,
                    json.dumps({
                        "destination": validated["path"],
                        "secondary_destination": secondary_validated and secondary_validated["path"],
                        "upload_google": upload_google,
                    }),
                    now, now,
                ),
            )
            record_event(connection, "transfer_queued", job_id=job_id, details={"items": normalized, "destination": validated["path"]})
            connection.commit()
        cancel = threading.Event()
        thread = threading.Thread(
            target=self._transfer_worker,
            args=(
                job_id,
                normalized,
                Path(validated["path"]),
                Path(secondary_validated["path"]) if secondary_validated else None,
                bool(upload_google),
                cancel,
            ),
            daemon=True,
            name=f"iphone-transfer-{job_id[:8]}",
        )
        with self._lock:
            self._jobs[job_id] = JobRuntime(cancel=cancel, thread=thread)
        thread.start()
        return job_id

    def _transfer_worker(
        self,
        job_id: str,
        item_ids: Sequence[str],
        root: Path,
        secondary_root: Path | None,
        upload_google: bool,
        cancel: threading.Event,
    ) -> None:
        try:
            self._job_update(job_id, status="running")
            for item_id in item_ids:
                if cancel.is_set() or self._cancel_requested(job_id):
                    raise InterruptedError("transfer cancelled")
                with database(self.database_path) as connection:
                    item = connection.execute("SELECT * FROM media_items WHERE item_id=?", (item_id,)).fetchone()
                if item is None:
                    raise ValueError("selected item disappeared from inventory")
                target = _unique_target(root, item)
                locator = json.loads(item["source_locator_json"])
                if item["source_kind"] == "iphone_usb":
                    staging = root / ".veridex-staging" / job_id / item_id
                    staging.mkdir(parents=True, exist_ok=True)
                    result = _run_portable_bridge("copy", locator=locator, destination=staging)
                    source_path = Path(result["path"])
                else:
                    source_path = Path(locator["path"]).resolve()
                if not source_path.is_file():
                    raise FileNotFoundError(f"source file is unavailable: {item['filename']}")
                expected_size = int(item["size_bytes"])
                digest, copied = _copy_local_verified(source_path, target, expected_size if expected_size > 0 else -1, cancel)
                flags, perceptual = _quality_and_hash(target, item["media_kind"])
                with database(self.database_path) as connection:
                    connection.execute(
                        """UPDATE media_items SET transfer_state='verified_local', local_path=?, local_sha256=?,
                           local_verified_at=?, size_bytes=?, quality_flags_json=?, perceptual_hash=?, updated_at=?
                           WHERE item_id=?""",
                        (str(target), digest, utc_now(), copied, json.dumps(flags), perceptual, utc_now(), item_id),
                    )
                    record_event(
                        connection,
                        "primary_copy_verified",
                        item_id=item_id,
                        job_id=job_id,
                        details={"path": str(target), "sha256": digest},
                    )
                    connection.commit()
                secondary: dict[str, Any] | None = None
                if secondary_root:
                    relative = target.relative_to(root)
                    secondary_target = secondary_root / relative
                    secondary_target.parent.mkdir(parents=True, exist_ok=True)
                    if secondary_target.exists():
                        base = secondary_target
                        counter = 2
                        while secondary_target.exists():
                            secondary_target = base.with_name(f"{base.stem}_{counter}{base.suffix}")
                            counter += 1
                    secondary_hash, secondary_size = _copy_local_verified(target, secondary_target, copied, cancel)
                    if secondary_hash.casefold() != digest.casefold():
                        raise ValueError("second local copy checksum does not match the primary archive")
                    secondary = {"path": str(secondary_target), "sha256": secondary_hash, "size": secondary_size}
                drive: dict[str, Any] | None = None
                if upload_google:
                    relative = target.relative_to(root)
                    drive = upload_drive_verified(self.database_path, target, relative.parts[:-1])
                with database(self.database_path) as connection:
                    connection.execute(
                        """UPDATE media_items SET transfer_state=?,
                           secondary_path=COALESCE(?, secondary_path),
                           secondary_sha256=COALESCE(?, secondary_sha256),
                           secondary_size=COALESCE(?, secondary_size),
                           secondary_verified_at=COALESCE(?, secondary_verified_at),
                           drive_file_id=COALESCE(?, drive_file_id),
                           drive_size=COALESCE(?, drive_size),
                           drive_md5=COALESCE(?, drive_md5),
                           drive_verified_at=COALESCE(?, drive_verified_at), updated_at=? WHERE item_id=?""",
                        (
                            "verified_both" if (secondary or drive) else "verified_local",
                            secondary and secondary["path"], secondary and secondary["sha256"], secondary and secondary["size"],
                            utc_now() if secondary else None,
                            drive and drive["file_id"], drive and drive["size"], drive and drive["md5"],
                            utc_now() if drive else None, utc_now(), item_id,
                        ),
                    )
                    record_event(
                        connection,
                        "item_verified",
                        item_id=item_id,
                        job_id=job_id,
                        details={
                            "path": str(target), "sha256": digest,
                            "secondary_verified": bool(secondary), "drive_verified": bool(drive),
                        },
                    )
                    connection.execute(
                        "UPDATE jobs SET completed_items=completed_items+1, completed_bytes=completed_bytes+?, updated_at=? WHERE job_id=?",
                        (copied, utc_now(), job_id),
                    )
                    connection.commit()
                if item["source_kind"] == "iphone_usb":
                    shutil.rmtree(source_path.parent, ignore_errors=True)
            self._job_update(job_id, status="completed")
        except InterruptedError as exc:
            self._job_update(job_id, status="cancelled", error=str(exc))
        except Exception as exc:
            self._job_update(job_id, status="failed", error=str(exc))
        finally:
            with self._lock:
                self._jobs.pop(job_id, None)

    def start_transcription(self, item_ids: Sequence[str], model: str = "tiny.en") -> str:
        normalized = list(dict.fromkeys(str(value) for value in item_ids if str(value).strip()))
        if not normalized:
            raise ValueError("select at least one audio file")
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("optional transcription is not installed; install requirements-transcription.txt") from exc
        with database(self.database_path) as connection:
            marks = ",".join("?" for _ in normalized)
            rows = connection.execute(
                f"SELECT item_id FROM media_items WHERE item_id IN ({marks}) AND media_kind='audio' AND local_verified_at IS NOT NULL",
                normalized,
            ).fetchall()
        if len(rows) != len(normalized):
            raise ValueError("transcription requires verified archived audio files")
        job_id = uuid.uuid4().hex
        now = utc_now()
        with database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO jobs(job_id,kind,status,total_items,details_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (job_id, "transcription", "queued", len(normalized), json.dumps({"model": model}), now, now),
            )
            connection.commit()
        cancel = threading.Event()
        thread = threading.Thread(target=self._transcription_worker, args=(job_id, normalized, model, cancel), daemon=True)
        with self._lock:
            self._jobs[job_id] = JobRuntime(cancel=cancel, thread=thread)
        thread.start()
        return job_id

    def _transcription_worker(self, job_id: str, item_ids: Sequence[str], model_name: str, cancel: threading.Event) -> None:
        try:
            from faster_whisper import WhisperModel
            self._job_update(job_id, status="running")
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            for item_id in item_ids:
                if cancel.is_set() or self._cancel_requested(job_id):
                    raise InterruptedError("transcription cancelled")
                with database(self.database_path) as connection:
                    item = connection.execute("SELECT * FROM media_items WHERE item_id=?", (item_id,)).fetchone()
                    version = connection.execute("SELECT COALESCE(MAX(version),0)+1 FROM transcripts WHERE item_id=?", (item_id,)).fetchone()[0]
                path = Path(item["local_path"])
                segments, info = model.transcribe(str(path), vad_filter=True)
                text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
                sidecar = path.with_suffix(path.suffix + f".transcript-v{version}.txt")
                temporary = sidecar.with_suffix(sidecar.suffix + ".partial")
                temporary.write_text(text, encoding="utf-8")
                temporary.replace(sidecar)
                classification = classify_transcript(text, item["filename"])
                with database(self.database_path) as connection:
                    connection.execute(
                        "INSERT INTO transcripts(transcript_id,item_id,version,status,model,language,classification,text,sidecar_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (uuid.uuid4().hex, item_id, version, "completed", model_name, getattr(info, "language", None), classification, text, str(sidecar), utc_now()),
                    )
                    connection.execute("UPDATE jobs SET completed_items=completed_items+1, updated_at=? WHERE job_id=?", (utc_now(), job_id))
                    record_event(connection, "audio_transcribed", item_id=item_id, job_id=job_id, details={"version": version, "model": model_name})
                    connection.commit()
            self._job_update(job_id, status="completed")
        except InterruptedError as exc:
            self._job_update(job_id, status="cancelled", error=str(exc))
        except Exception as exc:
            self._job_update(job_id, status="failed", error=str(exc))
        finally:
            with self._lock:
                self._jobs.pop(job_id, None)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with database(self.database_path) as connection:
            row = connection.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("job was not found")
            if row["status"] not in {"queued", "running"}:
                return get_job(self.database_path, job_id)
            connection.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE job_id=?", (utc_now(), job_id))
            connection.commit()
        with self._lock:
            runtime = self._jobs.get(job_id)
            if runtime:
                runtime.cancel.set()
        return get_job(self.database_path, job_id)

    def _cancel_requested(self, job_id: str) -> bool:
        with database(self.database_path) as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def _job_update(self, job_id: str, *, status: str, error: str | None = None) -> None:
        if status not in JOB_STATES:
            raise ValueError("invalid job state")
        with database(self.database_path) as connection:
            connection.execute("UPDATE jobs SET status=?, error=?, updated_at=? WHERE job_id=?", (status, error, utc_now(), job_id))
            record_event(connection, f"job_{status}", job_id=job_id, details={"error": error} if error else {})
            connection.commit()


def classify_transcript(text: str, filename: str) -> str:
    haystack = f"{filename} {text}".casefold()
    if any(word in haystack for word in ("meeting", "agenda", "interview", "question")):
        return "meeting_interview"
    if any(word in haystack for word in ("memo", "remember", "note to self", "reminder")):
        return "personal_note"
    if any(word in haystack for word in ("song", "chorus", "verse", "melody")):
        return "music"
    return "voice_memo" if text.strip() else "ambient_noise"


def get_job(database_path: Path, job_id: str) -> dict[str, Any]:
    with database(database_path) as connection:
        row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError("job was not found")
    return {
        "job_id": row["job_id"], "kind": row["kind"], "status": row["status"],
        "total_items": row["total_items"], "completed_items": row["completed_items"],
        "total_bytes": row["total_bytes"], "completed_bytes": row["completed_bytes"],
        "details": json.loads(row["details_json"]), "error": row["error"],
        "cancel_requested": bool(row["cancel_requested"]), "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def list_jobs(database_path: Path, limit: int = 30) -> list[dict[str, Any]]:
    with database(database_path) as connection:
        ids = [row[0] for row in connection.execute("SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
    return [get_job(database_path, job_id) for job_id in ids]


def duplicate_groups(database_path: Path) -> list[dict[str, Any]]:
    with database(database_path) as connection:
        rows = connection.execute(
            """SELECT local_sha256, COUNT(*) AS count, SUM(size_bytes) AS bytes
               FROM media_items WHERE local_verified_at IS NOT NULL AND local_sha256 IS NOT NULL
               GROUP BY local_sha256 HAVING COUNT(*) > 1 ORDER BY bytes DESC"""
        ).fetchall()
        groups = []
        for row in rows:
            items = connection.execute(
                "SELECT item_id,filename,local_path,size_bytes FROM media_items WHERE local_sha256=? ORDER BY filename",
                (row["local_sha256"],),
            ).fetchall()
            groups.append({"sha256": row["local_sha256"], "count": row["count"], "bytes": row["bytes"], "items": [dict(item) for item in items]})
    return groups


def verify_deletion_copies(database_path: Path, item: sqlite3.Row) -> list[str]:
    """Return current verification failures for a prospective phone deletion."""
    reasons: list[str] = []
    local_path = Path(item["local_path"]) if item["local_path"] else None
    if local_path is None or not local_path.is_file() or local_path.stat().st_size <= 0:
        reasons.append("local archive is missing or empty")
    elif local_path.stat().st_size != int(item["size_bytes"]):
        reasons.append("local archive size changed")
    elif sha256_file(local_path).casefold() != str(item["local_sha256"] or "").casefold():
        reasons.append("local archive checksum changed")
    second_copy_valid = False
    second_copy_errors: list[str] = []
    if item["secondary_path"] and item["secondary_verified_at"]:
        secondary_path = Path(item["secondary_path"])
        if not secondary_path.is_file() or secondary_path.stat().st_size <= 0:
            second_copy_errors.append("second local copy is missing or empty")
        elif secondary_path.stat().st_size != int(item["secondary_size"] or -1):
            second_copy_errors.append("second local copy size changed")
        elif sha256_file(secondary_path).casefold() != str(item["secondary_sha256"] or "").casefold():
            second_copy_errors.append("second local copy checksum changed")
        else:
            try:
                ensure_independent_volumes(local_path, secondary_path)
                second_copy_valid = True
            except ValueError as exc:
                second_copy_errors.append(str(exc))
    if item["drive_file_id"] and item["drive_verified_at"]:
        try:
            credentials = _google_credentials(database_path)
            from googleapiclient.discovery import build
            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            remote = service.files().get(
                fileId=item["drive_file_id"], fields="id,size,md5Checksum,trashed"
            ).execute()
            if remote.get("trashed"):
                second_copy_errors.append("Google Drive copy is in trash")
            elif int(remote.get("size") or -1) != int(item["drive_size"] or -2):
                second_copy_errors.append("Google Drive copy size changed")
            elif str(remote.get("md5Checksum") or "").casefold() != str(item["drive_md5"] or "").casefold():
                second_copy_errors.append("Google Drive copy checksum changed")
            else:
                second_copy_valid = True
        except Exception as exc:
            second_copy_errors.append(f"Google Drive could not be reverified: {exc}")
    if not second_copy_valid:
        reasons.append("no current independent second copy is verified")
        reasons.extend(second_copy_errors)
    return reasons


def deletion_preview(database_path: Path, item_ids: Sequence[str]) -> dict[str, Any]:
    normalized = list(dict.fromkeys(str(value) for value in item_ids if str(value).strip()))
    if not normalized:
        raise ValueError("select at least one item")
    marks = ",".join("?" for _ in normalized)
    with database(database_path) as connection:
        rows = connection.execute(f"SELECT * FROM media_items WHERE item_id IN ({marks})", normalized).fetchall()
        if len(rows) != len(normalized):
            raise ValueError("one or more selected items were not found")
        eligible = []
        blocked = []
        for row in rows:
            reasons = []
            if row["disposition"] != "download_delete":
                reasons.append("item is not marked download and delete")
            if not row["local_verified_at"]:
                reasons.append("local archive is not verified")
            if not row["secondary_verified_at"] and not row["drive_verified_at"]:
                reasons.append("no second copy is verified")
            if row["deletion_state"] == "deleted":
                reasons.append("item is already recorded as deleted")
            if not reasons:
                reasons.extend(verify_deletion_copies(database_path, row))
            entry = {"item_id": row["item_id"], "filename": row["filename"], "source_kind": row["source_kind"], "reasons": reasons}
            (blocked if reasons else eligible).append(entry)
        if blocked:
            return {"eligible": eligible, "blocked": blocked, "token": None, "confirmation_text": None}
        token = secrets.token_urlsafe(24)
        confirmation = f"DELETE {len(eligible)} ITEMS"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        connection.execute(
            "INSERT INTO deletion_previews(token,item_ids_json,confirmation_text,expires_at,created_at) VALUES(?,?,?,?,?)",
            (token, json.dumps(normalized), confirmation, expires, utc_now()),
        )
        record_event(connection, "deletion_previewed", details={"items": normalized})
        connection.commit()
    return {"eligible": eligible, "blocked": [], "token": token, "confirmation_text": confirmation, "expires_at": expires}


def execute_deletion(database_path: Path, token: str, confirmation_text: str) -> dict[str, Any]:
    with database(database_path) as connection:
        preview = connection.execute("SELECT * FROM deletion_previews WHERE token=?", (token,)).fetchone()
        if preview is None or preview["used_at"]:
            raise ValueError("deletion preview is invalid or already used")
        if parse_utc(preview["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("deletion preview expired; create a fresh preview")
        if confirmation_text != preview["confirmation_text"]:
            raise ValueError("typed confirmation does not match")
        item_ids = json.loads(preview["item_ids_json"])
        connection.execute("UPDATE deletion_previews SET used_at=? WHERE token=?", (utc_now(), token))
        connection.commit()
    results = []
    for item_id in item_ids:
        with database(database_path) as connection:
            item = connection.execute("SELECT * FROM media_items WHERE item_id=?", (item_id,)).fetchone()
        if item is None:
            continue
        status = "guided_required"
        error = None
        if item["source_kind"] == "iphone_usb":
            try:
                response = _run_portable_bridge("delete", locator=json.loads(item["source_locator_json"]))
                status = "deleted" if response.get("deleted") else "guided_required"
                error = response.get("reason")
            except Exception as exc:
                status = "failed"
                error = str(exc)
        with database(database_path) as connection:
            connection.execute("UPDATE media_items SET deletion_state=?, updated_at=? WHERE item_id=?", (status, utc_now(), item_id))
            record_event(connection, "deletion_result", item_id=item_id, details={"status": status, "error": error})
            connection.commit()
        results.append({"item_id": item_id, "filename": item["filename"], "status": status, "error": error})
    return {"results": results, "deleted": sum(result["status"] == "deleted" for result in results)}


def app_status(database_path: Path) -> dict[str, Any]:
    with database(database_path) as connection:
        counts = connection.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN local_verified_at IS NOT NULL THEN 1 ELSE 0 END) local_verified,
                      SUM(CASE WHEN secondary_verified_at IS NOT NULL THEN 1 ELSE 0 END) secondary_verified,
                      SUM(CASE WHEN drive_verified_at IS NOT NULL THEN 1 ELSE 0 END) drive_verified,
                      SUM(CASE WHEN secondary_verified_at IS NOT NULL OR drive_verified_at IS NOT NULL THEN 1 ELSE 0 END) second_copy_verified,
                      SUM(CASE WHEN disposition='download_delete' THEN 1 ELSE 0 END) delete_selected
               FROM media_items"""
        ).fetchone()
    destination = get_setting(database_path, "archive_destination")
    secondary_destination = get_setting(database_path, "secondary_destination")
    destination_status = None
    if destination:
        try:
            destination_status = validate_destination(destination, probe=False)
        except Exception as exc:
            destination_status = {"path": destination, "writable": False, "error": str(exc)}
    secondary_status = None
    if secondary_destination:
        try:
            secondary_status = validate_destination(secondary_destination, probe=False)
            if destination:
                ensure_independent_volumes(destination, secondary_destination)
                secondary_status["independent_from_primary"] = True
        except Exception as exc:
            secondary_status = {"path": secondary_destination, "writable": False, "error": str(exc)}
    return {
        "database": str(database_path.resolve()),
        "destination": destination_status,
        "secondary_destination": secondary_status,
        "limits": get_setting(database_path, "limits", {}),
        "counts": {key: int(counts[key] or 0) for key in counts.keys()},
        "google": google_status(database_path),
        "transcription_available": _transcription_available(),
    }


def _transcription_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


class IphoneMediaRequestHandler(BaseHTTPRequestHandler):
    database_path: Path
    static_dir: Path
    jobs: JobManager

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[iphone-media] {self.address_string()} {format % args}")

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length <= 0 or length > MAX_JSON_BODY:
            raise ValueError("JSON body is empty or too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request JSON must be an object")
        return value

    def _static(self, relative: str) -> None:
        path = safe_relative(self.static_dir, relative or "index.html")
        if not path.is_file():
            raise FileNotFoundError("not found")
        payload = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _media(self, item_id: str) -> None:
        with database(self.database_path) as connection:
            item = connection.execute("SELECT * FROM media_items WHERE item_id=?", (item_id,)).fetchone()
        if item is None:
            raise FileNotFoundError("media item was not found")
        path: Path | None = Path(item["local_path"]) if item["local_path"] else None
        if path is None and item["source_kind"] != "iphone_usb":
            path = Path(json.loads(item["source_locator_json"])["path"])
        if path is None or not path.is_file():
            raise FileNotFoundError("preview is unavailable until this item is downloaded")
        mime = item["mime_type"] or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if item["media_kind"] == "photo":
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.thumbnail((1600, 1600))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=88)
                payload = buffer.getvalue()
            mime = "image/jpeg"
        else:
            payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/status":
                self._json(app_status(self.database_path)); return
            if parsed.path == "/api/sources":
                self._json({"sources": list_sources(self.database_path)}); return
            if parsed.path == "/api/items":
                values = {key: entries[0] for key, entries in parse_qs(parsed.query).items() if entries}
                self._json(list_items(self.database_path, values)); return
            if parsed.path == "/api/jobs":
                self._json({"jobs": list_jobs(self.database_path)}); return
            if parsed.path.startswith("/api/jobs/"):
                self._json(get_job(self.database_path, parsed.path.removeprefix("/api/jobs/").strip("/"))); return
            if parsed.path == "/api/duplicates":
                self._json({"groups": duplicate_groups(self.database_path)}); return
            if parsed.path == "/api/google/status":
                self._json(google_status(self.database_path)); return
            if parsed.path.startswith("/media/"):
                self._media(parsed.path.removeprefix("/media/").strip("/")); return
            if parsed.path == "/":
                self._static("index.html"); return
            self._static(parsed.path.lstrip("/"))
        except (ValueError, FileNotFoundError) as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_PATCH(self) -> None:
        try:
            if self.path == "/api/items/disposition":
                body = self._body()
                self._json(update_dispositions(self.database_path, body.get("item_ids") or [], str(body.get("disposition") or "")))
                return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/api/sources":
                self._json(add_source(self.database_path, kind=body.get("kind"), label=body.get("label"), path=body.get("path")), HTTPStatus.CREATED); return
            if parsed.path.startswith("/api/sources/") and parsed.path.endswith("/scan"):
                source_id = parsed.path[len("/api/sources/"):-len("/scan")].strip("/")
                self._json(scan_source(self.database_path, source_id)); return
            if parsed.path == "/api/destination":
                self._json(save_destination(self.database_path, str(body.get("path") or ""))); return
            if parsed.path == "/api/secondary-destination":
                self._json(save_secondary_destination(self.database_path, str(body.get("path") or ""))); return
            if parsed.path == "/api/destination/pick":
                self._json(self._pick_folder()); return
            if parsed.path == "/api/settings/limits":
                limits = {}
                for key in ("batch_bytes", "file_bytes"):
                    value = body.get(key)
                    limits[key] = None if value in (None, "", 0, "0") else max(1, int(value))
                set_setting(self.database_path, "limits", limits)
                self._json(limits); return
            if parsed.path == "/api/transfers":
                job_id = self.jobs.start_transfer(
                    body.get("item_ids") or [], body.get("destination"), bool(body.get("upload_google")),
                    body.get("secondary_destination"),
                )
                self._json({"job_id": job_id}, HTTPStatus.ACCEPTED); return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
                job_id = parsed.path[len("/api/jobs/"):-len("/cancel")].strip("/")
                self._json(self.jobs.cancel_job(job_id)); return
            if parsed.path == "/api/transcriptions":
                job_id = self.jobs.start_transcription(body.get("item_ids") or [], str(body.get("model") or "tiny.en"))
                self._json({"job_id": job_id}, HTTPStatus.ACCEPTED); return
            if parsed.path == "/api/google/connect":
                self._json(connect_google(self.database_path, str(body.get("client_secrets_path") or ""))); return
            if parsed.path == "/api/google/destination":
                name = str(body.get("name") or "Veridex iPhone Archive").strip()
                if not name:
                    raise ValueError("Google Drive folder name is required")
                set_setting(self.database_path, "google_destination", {"name": name, "folder_id": body.get("folder_id")})
                self._json({"name": name, "folder_id": body.get("folder_id")}); return
            if parsed.path == "/api/deletions/preview":
                self._json(deletion_preview(self.database_path, body.get("item_ids") or [])); return
            if parsed.path == "/api/deletions/execute":
                self._json(execute_deletion(self.database_path, str(body.get("token") or ""), str(body.get("confirmation_text") or ""))); return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _pick_folder(self) -> dict[str, Any]:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(title="Choose Veridex iPhone archive folder", mustexist=False)
            root.destroy()
        except Exception as exc:
            raise RuntimeError(f"Windows folder picker could not open: {exc}") from exc
        return {"path": str(Path(selected).resolve()) if selected else None, "cancelled": not bool(selected)}


def create_http_server(database_path: Path, *, host: str = "127.0.0.1", port: int = 8773) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("iPhone media manager must bind to loopback")
    database_path = create_database(database_path)
    static_dir = Path(__file__).resolve().parent / "web" / "iphone_media"
    if not (static_dir / "index.html").is_file():
        raise FileNotFoundError("iPhone media web files are missing")
    manager = JobManager(database_path)
    handler = type(
        "BoundIphoneMediaRequestHandler",
        (IphoneMediaRequestHandler,),
        {"database_path": database_path, "static_dir": static_dir, "jobs": manager},
    )
    return ThreadingHTTPServer((host, int(port)), handler)


def serve(database_path: Path, *, host: str = "127.0.0.1", port: int = 8773, open_browser: bool = False) -> None:
    server = create_http_server(database_path, host=host, port=port)
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}"
    print(f"iPhone media manager ready at {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely archive and clean up accessible iPhone media")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="create or verify the media database")
    initialize.add_argument("database", type=Path)
    server = commands.add_parser("serve", help="start the local media manager")
    server.add_argument("database", type=Path)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8773)
    server.add_argument("--open", action="store_true", dest="open_browser")
    status = commands.add_parser("status", help="print current archive status")
    status.add_argument("database", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "init":
        print(create_database(args.database))
        return 0
    if args.command == "status":
        create_database(args.database)
        print(json.dumps(app_status(args.database), indent=2))
        return 0
    serve(args.database, host=args.host, port=args.port, open_browser=args.open_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
