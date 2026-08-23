"""Authoritative room registry and deterministic room request routing."""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOMS: List[Dict[str, Any]] = [
    {"id": "lobby", "title": "Lobby", "default_persona": "Receptionist", "is_active": True},
    {"id": "conference_room", "title": "Conference Room", "default_persona": "Facilitator", "is_active": True},
    {"id": "control_room", "title": "Control Room", "default_persona": "Navigator", "is_active": True},
    {"id": "infrastructure_room", "title": "Infrastructure Room", "default_persona": "Infrastructure Manager", "is_active": True},
    {"id": "sales_department", "title": "Sales Department", "default_persona": "Sales Director", "is_active": True},
    {"id": "marketing_room", "title": "Marketing & Advertising", "default_persona": "Marketing Director", "is_active": True},
    {"id": "hr_department", "title": "HR Department", "default_persona": "HR Manager", "is_active": True},
    {"id": "it_department", "title": "IT Department", "default_persona": "IT Administrator", "is_active": True},
    {"id": "art_department", "title": "Art Department", "default_persona": "Creative Director", "is_active": True},
    {"id": "law_office", "title": "Law Office", "default_persona": "Legal Counsel", "is_active": True},
    {"id": "finance_department", "title": "Finance Department", "default_persona": "Finance Director", "is_active": True},
    {"id": "my_office", "title": "My Office", "default_persona": "Nancy", "is_active": True},
    {"id": "vr_room", "title": "VR Room", "default_persona": "Simulation Guide", "is_active": True},
    {"id": "records_archive", "title": "Records Archive", "default_persona": "Archivist", "is_active": True},
    {"id": "rnd_room", "title": "Research & Development (R&D)", "default_persona": "R&D Director", "is_active": True},
    {"id": "security_room", "title": "Security Room", "default_persona": "Security Chief", "is_active": True},
    {"id": "break_room", "title": "Break Room", "default_persona": "Break Room Host", "is_active": True},
]

_ROOM_CATALOG_PATH: Optional[Path] = None


def configure_room_catalog(path: Optional[Path]) -> None:
    """Use a versioned global catalog while retaining built-ins as a safe fallback."""
    global _ROOM_CATALOG_PATH
    _ROOM_CATALOG_PATH = Path(path).resolve() if path else None


def _configured_rooms() -> List[Dict[str, Any]]:
    if _ROOM_CATALOG_PATH and _ROOM_CATALOG_PATH.is_file():
        try:
            value = json.loads(_ROOM_CATALOG_PATH.read_text(encoding="utf-8"))
            rows = value.get("rooms") if isinstance(value, dict) else None
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    return [dict(room) for room in ROOMS]


ROOM_ALIASES = {
    "lobby": ("lobby", "reception", "reception room", "receptionist"),
    "conference_room": ("conference", "conference room", "meeting room"),
    "control_room": ("control", "control room", "navigator", "navigator room"),
    "infrastructure_room": ("infrastructure", "infrastructure room"),
    "sales_department": ("sales", "sales department", "sales room"),
    "marketing_room": ("marketing", "marketing room", "marketing and advertising", "advertising"),
    "hr_department": ("hr", "h r", "hr department", "hr room", "human resources"),
    "it_department": ("it", "i t", "it department", "it room", "information technology"),
    "art_department": ("art", "art department", "art room", "creative department"),
    "law_office": ("law", "law office", "law room", "legal office"),
    "finance_department": ("finance", "finance department", "finance room"),
    "my_office": ("my office", "office"),
    "vr_room": ("vr", "v r", "vr room", "virtual reality", "virtual reality room"),
    "records_archive": ("records", "records archive", "records room", "archive"),
    "rnd_room": ("rnd", "r and d", "rnd room", "research and development", "research department"),
    "security_room": ("security", "security room"),
    "break_room": ("break", "break room"),
}


def _normalize(value: str) -> str:
    text = str(value or "").casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def rooms_payload() -> List[Dict[str, Any]]:
    return [dict(room) for room in _configured_rooms() if room.get("is_active", False)]


def room_by_id(room_id: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize(str(room_id or "").replace("_", " "))
    for room in rooms_payload():
        if _normalize(room["id"].replace("_", " ")) == normalized:
            return room
    return None


def resolve_room(value: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize(value)
    normalized = re.sub(r"^(?:the|a) ", "", normalized)
    for room in rooms_payload():
        candidates = {
            room["id"].replace("_", " "),
            room["title"],
            *ROOM_ALIASES.get(room["id"], ()),
            *(room.get("aliases") or []),
        }
        if normalized in {_normalize(candidate) for candidate in candidates}:
            return room
    return None


def route_room_request(text: str) -> Optional[Dict[str, Any]]:
    """Return a deterministic room action only for explicit room requests."""
    normalized = _normalize(text)
    directory_patterns = (
        r"^(?:please )?(?:can you |could you )?(?:list|show)(?: me)? (?:all )?(?:the )?(?:available )?(?:rooms|departments|offices|room controls)$",
        r"^(?:what|which) (?:rooms|departments|offices) (?:are there|are available|can i use)$",
        r"^(?:is there )?(?:a )?list of (?:rooms|places i can go)(?: in veridex)?$",
        r"^where can i go(?: in veridex)?$",
        r"^how (?:do|can) i (?:switch|change|move) rooms$",
        r"^can you switch rooms$",
    )
    if any(re.fullmatch(pattern, normalized) for pattern in directory_patterns):
        return {"action": "directory"}

    navigation = re.fullmatch(
        r"(?:please )?(?:go|switch|move|navigate|enter|take me|send me|route me|direct me|bring me)(?: back)?(?: to| into)? (.+?)(?: please)?",
        normalized,
    )
    if not navigation:
        return None
    requested = navigation.group(1)
    room = resolve_room(requested)
    if room is None and re.search(r"\b(?:past|bypass|around|through)\b.{0,40}\bgate\b", requested):
        return None
    return {"action": "navigate", "room": room, "requested": requested}


def room_directory_text() -> str:
    lines = [
        "Use the room selector beneath the session title, or type a direct command such as 'go to Art Department'.",
        "",
        "Available rooms:",
    ]
    lines.extend(f"- {room['title']} — {room['default_persona']}" for room in rooms_payload())
    return "\n".join(lines)


def valid_room_titles() -> str:
    return ", ".join(room["title"] for room in rooms_payload())
