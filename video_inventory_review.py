"""SQLite-backed, local review queue for video inventory proposals.

Original frames and proposal crops are immutable. Review decisions are current state
plus append-only events, while every corrected lasso creates a new image revision.
The HTTP server binds to loopback and serves only database-authorized media paths.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import mimetypes
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageOps

from batch_inventory import ItemSelection, render_selection


REVIEW_STATUSES = (
    "pending",
    "keep",
    "duplicate",
    "partial",
    "trash",
    "needs_new_crop",
    "unsure",
    "corrected_pending_review",
)
MAX_NOTE_LENGTH = 4000
MAX_JSON_BODY = 2 * 1024 * 1024
DEFAULT_BATCH_SIZE = 50
MAX_BATCH_SIZE = 100


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(root: Path, value: str) -> Path:
    root = root.resolve()
    candidate = (root / str(value or "")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("review media path escapes its project directory")
    return candidate


def _verified_file(path: Path, expected_hash: str, label: str) -> Path:
    path = path.resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} is missing or empty")
    if _sha256(path).casefold() != str(expected_hash or "").casefold():
        raise ValueError(f"{label} changed after its manifest was created")
    return path


def _rotate_clockwise(image: Image.Image, degrees: int) -> Image.Image:
    if int(degrees) not in {0, 90, 180, 270}:
        raise ValueError("rotation must be 0, 90, 180, or 270")
    return image.copy() if int(degrees) == 0 else image.rotate(-int(degrees), expand=True)


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(Path(database_path).resolve()), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


@contextmanager
def _database(database_path: Path) -> Iterable[sqlite3.Connection]:
    connection = _connect(database_path)
    try:
        yield connection
    finally:
        connection.close()


SCHEMA = """
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    imported_at TEXT NOT NULL,
    proposal_manifest_path TEXT NOT NULL UNIQUE,
    proposal_manifest_sha256 TEXT NOT NULL,
    source_manifest_path TEXT NOT NULL,
    source_manifest_sha256 TEXT NOT NULL,
    source_video_sha256 TEXT NOT NULL,
    corrections_dir TEXT NOT NULL,
    batch_size INTEGER NOT NULL CHECK(batch_size BETWEEN 1 AND 100)
);

CREATE TABLE scenes (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    scene_id TEXT NOT NULL,
    representative_candidate_id TEXT NOT NULL,
    candidate_ids_json TEXT NOT NULL,
    rotation_degrees INTEGER NOT NULL CHECK(rotation_degrees IN (0, 90, 180, 270)),
    orientation_status TEXT NOT NULL,
    source_image_path TEXT NOT NULL,
    source_image_sha256 TEXT NOT NULL,
    overlay_path TEXT NOT NULL,
    overlay_sha256 TEXT NOT NULL,
    PRIMARY KEY(project_id, scene_id)
);

CREATE TABLE proposals (
    project_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK(sequence_number > 0),
    original_points_json TEXT NOT NULL,
    current_points_json TEXT NOT NULL,
    bounds_json TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL,
    proposal_score REAL,
    original_neutral_path TEXT NOT NULL,
    original_neutral_sha256 TEXT NOT NULL,
    original_isolated_path TEXT NOT NULL,
    original_isolated_sha256 TEXT NOT NULL,
    current_neutral_path TEXT NOT NULL,
    current_neutral_sha256 TEXT NOT NULL,
    current_isolated_path TEXT NOT NULL,
    current_isolated_sha256 TEXT NOT NULL,
    crop_revision INTEGER NOT NULL DEFAULT 0 CHECK(crop_revision >= 0),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN (
        'pending', 'keep', 'duplicate', 'partial', 'trash', 'needs_new_crop',
        'unsure', 'corrected_pending_review'
    )),
    duplicate_of TEXT,
    review_note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, proposal_id),
    UNIQUE(project_id, sequence_number),
    FOREIGN KEY(project_id, scene_id) REFERENCES scenes(project_id, scene_id),
    FOREIGN KEY(project_id, duplicate_of) REFERENCES proposals(project_id, proposal_id)
);

CREATE TABLE crop_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL CHECK(revision_number > 0),
    points_json TEXT NOT NULL,
    neutral_path TEXT NOT NULL,
    neutral_sha256 TEXT NOT NULL,
    isolated_path TEXT NOT NULL,
    isolated_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, proposal_id, revision_number),
    FOREIGN KEY(project_id, proposal_id) REFERENCES proposals(project_id, proposal_id)
);

CREATE TABLE review_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    proposal_id TEXT,
    event_type TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id, proposal_id) REFERENCES proposals(project_id, proposal_id)
);

CREATE INDEX proposals_batch_index ON proposals(project_id, sequence_number);
CREATE INDEX proposals_status_index ON proposals(project_id, review_status);
CREATE INDEX review_events_proposal_index ON review_events(project_id, proposal_id, event_id);
"""


@dataclass(frozen=True)
class ReviewProject:
    project_id: str
    database_path: str
    proposal_count: int
    scene_count: int
    batch_size: int
    batch_count: int


def _existing_project(database_path: Path, manifest_hash: str) -> ReviewProject | None:
    if not database_path.is_file():
        return None
    with _database(database_path) as connection:
        row = connection.execute("SELECT * FROM projects LIMIT 1").fetchone()
        if row is None:
            raise ValueError("review database exists but contains no project")
        if row["proposal_manifest_sha256"].casefold() != manifest_hash.casefold():
            raise ValueError("review database belongs to a different proposal manifest")
        counts = connection.execute(
            "SELECT COUNT(*) AS proposals, COUNT(DISTINCT scene_id) AS scenes FROM proposals WHERE project_id = ?",
            (row["project_id"],),
        ).fetchone()
        return ReviewProject(
            row["project_id"],
            str(database_path.resolve()),
            int(counts["proposals"]),
            int(counts["scenes"]),
            int(row["batch_size"]),
            math.ceil(int(counts["proposals"]) / int(row["batch_size"])),
        )


def create_review_database(
    proposal_manifest_path: Path,
    database_path: Path,
    corrections_dir: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ReviewProject:
    """Create or verify one review database from a proposal manifest."""
    proposal_manifest_path = Path(proposal_manifest_path).resolve()
    database_path = Path(database_path).resolve()
    corrections_dir = Path(corrections_dir).resolve()
    if not proposal_manifest_path.is_file():
        raise FileNotFoundError(proposal_manifest_path)
    batch_size = max(1, min(MAX_BATCH_SIZE, int(batch_size)))
    manifest_hash = _sha256(proposal_manifest_path)
    existing = _existing_project(database_path, manifest_hash)
    if existing is not None:
        return existing

    proposal_root = proposal_manifest_path.parent
    manifest = json.loads(proposal_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "veridex.video_inventory.item_proposals.v1":
        raise ValueError("unsupported proposal manifest")
    source_manifest_path = Path(str(manifest.get("source_manifest_path") or "")).resolve()
    source_manifest_hash = str(manifest.get("source_manifest_sha256") or "")
    _verified_file(source_manifest_path, source_manifest_hash, "source video manifest")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("schema") != "veridex.video_inventory.v1":
        raise ValueError("unsupported source video manifest")
    if str(source_manifest.get("source", {}).get("sha256") or "") != str(manifest.get("source_video_sha256") or ""):
        raise ValueError("proposal and source manifests disagree about the source video")
    source_root = source_manifest_path.parent
    source_candidates = {str(row["candidate_id"]): row for row in source_manifest.get("candidates") or []}

    prepared_scenes = []
    prepared_proposals = []
    sequence_number = 0
    seen_proposals: set[str] = set()
    for scene in manifest.get("scenes") or []:
        scene_id = str(scene.get("scene_id") or "")
        candidate_id = str(scene.get("representative_candidate_id") or "")
        candidate = source_candidates.get(candidate_id)
        if not scene_id or candidate is None:
            raise ValueError(f"scene has an unknown representative candidate: {scene_id}")
        source_image = _verified_file(
            _safe_relative(source_root, str(candidate.get("image_path") or "")),
            str(candidate.get("image_sha256") or ""),
            f"source image for {scene_id}",
        )
        overlay = _verified_file(
            _safe_relative(proposal_root, str(scene.get("overlay_relative_path") or "")),
            str(scene.get("overlay_sha256") or ""),
            f"overlay for {scene_id}",
        )
        rotation = int(scene.get("rotation_degrees") or 0)
        if rotation not in {0, 90, 180, 270}:
            raise ValueError(f"invalid rotation for {scene_id}")
        prepared_scenes.append((
            scene_id,
            candidate_id,
            json.dumps(scene.get("candidate_ids") or [], separators=(",", ":")),
            rotation,
            str(scene.get("orientation_status") or ""),
            str(source_image),
            str(candidate.get("image_sha256") or ""),
            str(overlay),
            str(scene.get("overlay_sha256") or ""),
        ))
        for proposal in scene.get("proposals") or []:
            proposal_id = str(proposal.get("proposal_id") or "")
            if not proposal_id or proposal_id in seen_proposals:
                raise ValueError(f"missing or duplicate proposal ID: {proposal_id}")
            seen_proposals.add(proposal_id)
            sequence_number += 1
            neutral = _verified_file(
                _safe_relative(proposal_root, str(proposal.get("neutral_path") or "")),
                str(proposal.get("neutral_sha256") or ""),
                f"neutral crop {proposal_id}",
            )
            isolated = _verified_file(
                _safe_relative(proposal_root, str(proposal.get("isolated_path") or "")),
                str(proposal.get("isolated_sha256") or ""),
                f"isolated crop {proposal_id}",
            )
            points_json = json.dumps(proposal.get("points") or [], separators=(",", ":"))
            prepared_proposals.append((
                proposal_id,
                scene_id,
                sequence_number,
                points_json,
                points_json,
                json.dumps(proposal.get("bounds") or [], separators=(",", ":")),
                json.dumps(proposal.get("quality_flags") or [], separators=(",", ":")),
                proposal.get("proposal_score"),
                str(neutral),
                str(proposal.get("neutral_sha256") or ""),
                str(isolated),
                str(proposal.get("isolated_sha256") or ""),
            ))

    if sequence_number != int(manifest.get("proposal_count") or -1):
        raise ValueError("proposal manifest count does not match its rows")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    corrections_dir.mkdir(parents=True, exist_ok=True)
    temporary_database = database_path.with_name(database_path.name + ".tmp")
    if temporary_database.exists():
        raise FileExistsError(f"temporary review database already exists: {temporary_database}")
    project_id = "review_" + manifest_hash[:16]
    connection = sqlite3.connect(str(temporary_database))
    try:
        connection.executescript(SCHEMA)
        now = _utc_now()
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                now,
                str(proposal_manifest_path),
                manifest_hash,
                str(source_manifest_path),
                source_manifest_hash,
                str(manifest.get("source_video_sha256") or ""),
                str(corrections_dir),
                batch_size,
            ),
        )
        connection.executemany(
            """
            INSERT INTO scenes (
                project_id, scene_id, representative_candidate_id, candidate_ids_json,
                rotation_degrees, orientation_status, source_image_path,
                source_image_sha256, overlay_path, overlay_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(project_id, *row) for row in prepared_scenes],
        )
        connection.executemany(
            """
            INSERT INTO proposals (
                project_id, proposal_id, scene_id, sequence_number,
                original_points_json, current_points_json, bounds_json,
                quality_flags_json, proposal_score, original_neutral_path,
                original_neutral_sha256, original_isolated_path,
                original_isolated_sha256, current_neutral_path,
                current_neutral_sha256, current_isolated_path,
                current_isolated_sha256, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    project_id,
                    row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
                    row[8], row[9], row[10], row[11], row[8], row[9], row[10], row[11], now,
                )
                for row in prepared_proposals
            ],
        )
        connection.execute(
            "INSERT INTO review_events (project_id, proposal_id, event_type, before_json, after_json, created_at) VALUES (?, NULL, ?, ?, ?, ?)",
            (
                project_id,
                "project_imported",
                "{}",
                json.dumps({"scene_count": len(prepared_scenes), "proposal_count": len(prepared_proposals)}, separators=(",", ":")),
                now,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        if temporary_database.exists():
            temporary_database.unlink()
        raise
    finally:
        try:
            connection.close()
        except Exception:
            pass
    os.replace(temporary_database, database_path)
    return ReviewProject(
        project_id,
        str(database_path),
        len(prepared_proposals),
        len(prepared_scenes),
        batch_size,
        math.ceil(len(prepared_proposals) / batch_size),
    )


def _project_row(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM projects LIMIT 1").fetchone()
    if row is None:
        raise ValueError("review database contains no project")
    return row


def project_summary(database_path: Path) -> dict[str, Any]:
    with _database(database_path) as connection:
        project = _project_row(connection)
        total = int(connection.execute("SELECT COUNT(*) FROM proposals WHERE project_id = ?", (project["project_id"],)).fetchone()[0])
        scenes = int(connection.execute("SELECT COUNT(*) FROM scenes WHERE project_id = ?", (project["project_id"],)).fetchone()[0])
        status_rows = connection.execute(
            "SELECT review_status, COUNT(*) AS count FROM proposals WHERE project_id = ? GROUP BY review_status",
            (project["project_id"],),
        ).fetchall()
        statuses = {status: 0 for status in REVIEW_STATUSES}
        statuses.update({str(row["review_status"]): int(row["count"]) for row in status_rows})
        batch_size = int(project["batch_size"])
        return {
            "project_id": project["project_id"],
            "proposal_manifest_path": project["proposal_manifest_path"],
            "source_video_sha256": project["source_video_sha256"],
            "total": total,
            "scenes": scenes,
            "batch_size": batch_size,
            "batch_count": math.ceil(total / batch_size),
            "statuses": statuses,
            "reviewed": total - statuses["pending"],
        }


def list_review_batch(database_path: Path, batch_number: int) -> dict[str, Any]:
    with _database(database_path) as connection:
        project = _project_row(connection)
        batch_size = int(project["batch_size"])
        total = int(connection.execute("SELECT COUNT(*) FROM proposals WHERE project_id = ?", (project["project_id"],)).fetchone()[0])
        batch_count = max(1, math.ceil(total / batch_size))
        batch_number = max(1, min(batch_count, int(batch_number)))
        lower = (batch_number - 1) * batch_size + 1
        upper = min(total, lower + batch_size - 1)
        rows = connection.execute(
            """
            SELECT p.*, s.representative_candidate_id, s.rotation_degrees,
                   s.orientation_status
            FROM proposals p
            JOIN scenes s ON s.project_id = p.project_id AND s.scene_id = p.scene_id
            WHERE p.project_id = ? AND p.sequence_number BETWEEN ? AND ?
            ORDER BY p.sequence_number
            """,
            (project["project_id"], lower, upper),
        ).fetchall()
        proposals = []
        for row in rows:
            proposals.append({
                "proposal_id": row["proposal_id"],
                "sequence_number": int(row["sequence_number"]),
                "scene_id": row["scene_id"],
                "candidate_id": row["representative_candidate_id"],
                "rotation_degrees": int(row["rotation_degrees"]),
                "quality_flags": json.loads(row["quality_flags_json"]),
                "proposal_score": row["proposal_score"],
                "review_status": row["review_status"],
                "duplicate_of": row["duplicate_of"],
                "review_note": row["review_note"],
                "crop_revision": int(row["crop_revision"]),
                "points": json.loads(row["current_points_json"]),
                "current_image_url": f"/media/{row['proposal_id']}?kind=current&v={int(row['crop_revision'])}",
                "original_image_url": f"/media/{row['proposal_id']}?kind=original",
                "source_image_url": f"/media/{row['proposal_id']}?kind=source",
                "overlay_image_url": f"/media/{row['proposal_id']}?kind=overlay",
            })
        return {
            "batch_number": batch_number,
            "batch_size": batch_size,
            "batch_count": batch_count,
            "range_start": lower,
            "range_end": upper,
            "total": total,
            "proposals": proposals,
        }


def _review_state(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "review_status": row["review_status"],
        "duplicate_of": row["duplicate_of"],
        "review_note": row["review_note"],
        "crop_revision": int(row["crop_revision"]),
    }


def update_review_decision(
    database_path: Path,
    proposal_id: str,
    *,
    review_status: str,
    duplicate_of: str | None = None,
    review_note: str = "",
) -> dict[str, Any]:
    review_status = str(review_status or "").strip()
    if review_status not in REVIEW_STATUSES:
        raise ValueError("unknown review status")
    review_note = str(review_note or "").strip()
    if len(review_note) > MAX_NOTE_LENGTH:
        raise ValueError("review note exceeds 4000 characters")
    proposal_id = str(proposal_id or "").strip()
    duplicate_of = str(duplicate_of or "").strip() or None
    with _database(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        project = _project_row(connection)
        row = connection.execute(
            "SELECT * FROM proposals WHERE project_id = ? AND proposal_id = ?",
            (project["project_id"], proposal_id),
        ).fetchone()
        if row is None:
            raise ValueError("unknown proposal")
        if review_status == "duplicate":
            if not duplicate_of or duplicate_of == proposal_id:
                raise ValueError("duplicate status requires a different retained proposal ID")
            target = connection.execute(
                "SELECT 1 FROM proposals WHERE project_id = ? AND proposal_id = ?",
                (project["project_id"], duplicate_of),
            ).fetchone()
            if target is None:
                raise ValueError("duplicate target does not exist")
        else:
            duplicate_of = None
        before = _review_state(row)
        now = _utc_now()
        connection.execute(
            """
            UPDATE proposals
            SET review_status = ?, duplicate_of = ?, review_note = ?, updated_at = ?
            WHERE project_id = ? AND proposal_id = ?
            """,
            (review_status, duplicate_of, review_note, now, project["project_id"], proposal_id),
        )
        after = {**before, "review_status": review_status, "duplicate_of": duplicate_of, "review_note": review_note}
        connection.execute(
            "INSERT INTO review_events (project_id, proposal_id, event_type, before_json, after_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                project["project_id"],
                proposal_id,
                "review_decision",
                json.dumps(before, separators=(",", ":")),
                json.dumps(after, separators=(",", ":")),
                now,
            ),
        )
        connection.commit()
        return after


def save_corrected_crop(database_path: Path, proposal_id: str, points: Sequence[Sequence[int]]) -> dict[str, Any]:
    normalized = []
    for point in points:
        if not isinstance(point, Sequence) or len(point) != 2:
            raise ValueError("each lasso point must contain x and y")
        normalized.append((int(point[0]), int(point[1])))
    if len(normalized) < 3:
        raise ValueError("corrected lasso requires at least three points")
    proposal_id = str(proposal_id or "").strip()
    with _database(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        project = _project_row(connection)
        row = connection.execute(
            """
            SELECT p.*, s.rotation_degrees, s.source_image_path, s.source_image_sha256
            FROM proposals p
            JOIN scenes s ON s.project_id = p.project_id AND s.scene_id = p.scene_id
            WHERE p.project_id = ? AND p.proposal_id = ?
            """,
            (project["project_id"], proposal_id),
        ).fetchone()
        if row is None:
            raise ValueError("unknown proposal")
        source_path = _verified_file(Path(row["source_image_path"]), row["source_image_sha256"], "source candidate image")
        with Image.open(source_path) as opened:
            source = _rotate_clockwise(ImageOps.exif_transpose(opened).convert("RGB"), int(row["rotation_degrees"]))
        if any(x < 0 or y < 0 or x >= source.width or y >= source.height for x, y in normalized):
            raise ValueError("lasso point falls outside the rotated source image")
        revision = int(row["crop_revision"]) + 1
        corrections_dir = Path(project["corrections_dir"]).resolve()
        corrections_dir.mkdir(parents=True, exist_ok=True)
        neutral_path = corrections_dir / f"{proposal_id}_revision_{revision:03d}_neutral.jpg"
        isolated_path = corrections_dir / f"{proposal_id}_revision_{revision:03d}_isolated.png"
        if neutral_path.exists() or isolated_path.exists():
            raise FileExistsError("corrected crop revision already exists")
        selection = ItemSelection(1, tuple(normalized), description=f"Corrected review crop {proposal_id}")
        rendered = render_selection(source, selection, padding=18)
        rendered["neutral"].save(neutral_path, format="JPEG", quality=94, optimize=True)
        rendered["transparent"].save(isolated_path, format="PNG", optimize=True)
        neutral_hash = _sha256(neutral_path)
        isolated_hash = _sha256(isolated_path)
        now = _utc_now()
        before = _review_state(row)
        after = {
            **before,
            "review_status": "corrected_pending_review",
            "duplicate_of": None,
            "crop_revision": revision,
        }
        connection.execute(
            """
            INSERT INTO crop_revisions (
                project_id, proposal_id, revision_number, points_json, neutral_path,
                neutral_sha256, isolated_path, isolated_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project["project_id"], proposal_id, revision,
                json.dumps(normalized, separators=(",", ":")),
                str(neutral_path), neutral_hash, str(isolated_path), isolated_hash, now,
            ),
        )
        connection.execute(
            """
            UPDATE proposals
            SET current_points_json = ?, current_neutral_path = ?, current_neutral_sha256 = ?,
                current_isolated_path = ?, current_isolated_sha256 = ?, crop_revision = ?,
                review_status = 'corrected_pending_review', duplicate_of = NULL, updated_at = ?
            WHERE project_id = ? AND proposal_id = ?
            """,
            (
                json.dumps(normalized, separators=(",", ":")),
                str(neutral_path), neutral_hash, str(isolated_path), isolated_hash,
                revision, now, project["project_id"], proposal_id,
            ),
        )
        connection.execute(
            "INSERT INTO review_events (project_id, proposal_id, event_type, before_json, after_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                project["project_id"], proposal_id, "crop_corrected",
                json.dumps(before, separators=(",", ":")),
                json.dumps({**after, "points": normalized, "neutral_sha256": neutral_hash, "isolated_sha256": isolated_hash}, separators=(",", ":")),
                now,
            ),
        )
        connection.commit()
        return {
            "proposal_id": proposal_id,
            "crop_revision": revision,
            "review_status": "corrected_pending_review",
            "neutral_path": str(neutral_path),
            "neutral_sha256": neutral_hash,
            "isolated_path": str(isolated_path),
            "isolated_sha256": isolated_hash,
            "current_image_url": f"/media/{proposal_id}?kind=current&v={revision}",
        }


def _media_record(database_path: Path, proposal_id: str, kind: str) -> tuple[Path, str, int]:
    with _database(database_path) as connection:
        project = _project_row(connection)
        row = connection.execute(
            """
            SELECT p.*, s.rotation_degrees, s.source_image_path, s.source_image_sha256,
                   s.overlay_path, s.overlay_sha256
            FROM proposals p
            JOIN scenes s ON s.project_id = p.project_id AND s.scene_id = p.scene_id
            WHERE p.project_id = ? AND p.proposal_id = ?
            """,
            (project["project_id"], proposal_id),
        ).fetchone()
        if row is None:
            raise FileNotFoundError("unknown proposal")
        fields = {
            "current": ("current_neutral_path", "current_neutral_sha256"),
            "isolated": ("current_isolated_path", "current_isolated_sha256"),
            "original": ("original_neutral_path", "original_neutral_sha256"),
            "source": ("source_image_path", "source_image_sha256"),
            "overlay": ("overlay_path", "overlay_sha256"),
        }
        if kind not in fields:
            raise FileNotFoundError("unknown media kind")
        path_field, hash_field = fields[kind]
        return Path(row[path_field]).resolve(), str(row[hash_field]), int(row["rotation_degrees"])


class ReviewRequestHandler(BaseHTTPRequestHandler):
    database_path: Path
    static_dir: Path

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[video-review] {self.address_string()} {format % args}")

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
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

    def _serve_static(self, relative: str) -> None:
        relative = relative or "index.html"
        try:
            path = _safe_relative(self.static_dir, relative)
        except ValueError:
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        if not path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        payload = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/project":
                self._json(project_summary(self.database_path))
                return
            if parsed.path == "/api/proposals":
                values = parse_qs(parsed.query)
                batch = int((values.get("batch") or ["1"])[0])
                self._json(list_review_batch(self.database_path, batch))
                return
            if parsed.path.startswith("/media/"):
                proposal_id = parsed.path.removeprefix("/media/").strip("/")
                kind = (parse_qs(parsed.query).get("kind") or ["current"])[0]
                path, expected_hash, rotation = _media_record(self.database_path, proposal_id, kind)
                _verified_file(path, expected_hash, f"{kind} media")
                if kind == "source" and rotation:
                    with Image.open(path) as opened:
                        oriented = _rotate_clockwise(ImageOps.exif_transpose(opened).convert("RGB"), rotation)
                    buffer = io.BytesIO()
                    oriented.save(buffer, format="JPEG", quality=94)
                    payload = buffer.getvalue()
                    mime = "image/jpeg"
                else:
                    payload = path.read_bytes()
                    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "private, max-age=3600")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/":
                self._serve_static("index.html")
                return
            self._serve_static(parsed.path.lstrip("/"))
        except (ValueError, FileNotFoundError) as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/proposals/"):
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        proposal_id = parsed.path.removeprefix("/api/proposals/").strip("/")
        try:
            body = self._body()
            result = update_review_decision(
                self.database_path,
                proposal_id,
                review_status=str(body.get("review_status") or ""),
                duplicate_of=body.get("duplicate_of"),
                review_note=str(body.get("review_note") or ""),
            )
            self._json(result)
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        prefix = "/api/proposals/"
        suffix = "/crop"
        if not parsed.path.startswith(prefix) or not parsed.path.endswith(suffix):
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        proposal_id = parsed.path[len(prefix):-len(suffix)].strip("/")
        try:
            body = self._body()
            result = save_corrected_crop(self.database_path, proposal_id, body.get("points") or [])
            self._json(result, HTTPStatus.CREATED)
        except (ValueError, FileExistsError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def create_review_http_server(
    database_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8771,
) -> ThreadingHTTPServer:
    database_path = Path(database_path).resolve()
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("video review server must bind to loopback")
    project_summary(database_path)
    static_dir = Path(__file__).resolve().parent / "web" / "video_review"
    if not (static_dir / "index.html").is_file():
        raise FileNotFoundError("video review web files are missing")
    handler = type(
        "BoundReviewRequestHandler",
        (ReviewRequestHandler,),
        {"database_path": database_path, "static_dir": static_dir},
    )
    return ThreadingHTTPServer((host, int(port)), handler)


def serve_review(database_path: Path, *, host: str = "127.0.0.1", port: int = 8771) -> None:
    server = create_review_http_server(database_path, host=host, port=port)
    actual_host, actual_port = server.server_address[:2]
    print(f"Video review ready at http://{actual_host}:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review video inventory proposals in batches of 50")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="create or verify a review database")
    initialize.add_argument("proposal_manifest", type=Path)
    initialize.add_argument("database", type=Path)
    initialize.add_argument("--corrections-dir", type=Path, required=True)
    initialize.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    serve = commands.add_parser("serve", help="serve the local review interface")
    serve.add_argument("database", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8771)
    status = commands.add_parser("status", help="show review counts")
    status.add_argument("database", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "init":
        result = create_review_database(
            args.proposal_manifest,
            args.database,
            args.corrections_dir,
            batch_size=args.batch_size,
        )
        print(json.dumps(asdict(result), indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(project_summary(args.database), indent=2))
        return 0
    serve_review(args.database, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
