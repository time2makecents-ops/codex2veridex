"""Low-latency text-only Gemini provider for lightweight Veridex chat."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}
DEFAULT_ENV_FILE = Path(r"C:\Office-App\.env.local")
DEFAULT_TIMEOUT_SECONDS = 45


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    model: str
    enabled: bool


def _parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _config_value(name: str, file_values: Dict[str, str]) -> str:
    value = str(os.environ.get(name) or "").strip()
    if value:
        return value
    return str(file_values.get(name) or "").strip()


def load_gemini_config(env_file: Path = DEFAULT_ENV_FILE) -> GeminiConfig:
    file_values = _parse_env_file(Path(env_file))
    api_key = _config_value("GEMINI_API_KEY", file_values)
    model = _config_value("GEMINI_MODEL", file_values)
    flag = _config_value("VERIDEX_GEMINI_ENABLED", file_values).lower()
    enabled = flag not in FALSY
    if flag and flag not in TRUTHY and flag not in FALSY:
        enabled = True
    return GeminiConfig(api_key=api_key, model=model, enabled=enabled)


def gemini_enabled(config: GeminiConfig | None = None) -> bool:
    active = config or load_gemini_config()
    return bool(active.enabled and active.api_key and active.model)


def _compact_context(context: Any, max_chars: int = 6000) -> str:
    if not isinstance(context, dict) or not context:
        return "{}"
    keep = {
        key: context.get(key)
        for key in (
            "current_room",
            "computer_access",
            "available_rooms",
            "governance",
            "recent_transcript",
            "current_local_date",
        )
        if context.get(key) not in (None, "", [], {})
    }
    encoded = json.dumps(keep or context, ensure_ascii=False, sort_keys=True, default=str)
    return encoded if len(encoded) <= max_chars else encoded[:max_chars] + '..."}'


def _resource_name(model: str) -> str:
    value = str(model or "").strip().strip("/")
    if not value:
        raise RuntimeError("GEMINI_MODEL is required")
    return value if value.startswith("models/") else f"models/{value}"


def _extract_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("Gemini completed without candidates")
    parts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content") if isinstance(candidate, dict) else {}
        for part in content.get("parts") if isinstance(content, dict) else []:
            if isinstance(part, dict) and part.get("text") not in (None, ""):
                parts.append(str(part["text"]))
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError("Gemini completed without a text response")
    return text


def invoke_gemini(request: Dict[str, Any]) -> Dict[str, Any]:
    config = load_gemini_config()
    if not gemini_enabled(config):
        raise RuntimeError("Gemini gateway is disabled or not configured")
    user_prompt = str(request.get("user_prompt") or "").strip()
    if not user_prompt:
        raise ValueError("user_prompt is required")
    if request.get("attachment_paths"):
        raise RuntimeError("Gemini gateway only supports text-only requests")

    system_prompt = str(request.get("system_prompt") or "").strip()
    context = _compact_context(request.get("context"))
    system_text = (
        f"{system_prompt}\n\n"
        "Use the governed context as local state. Do not claim searches, file operations, media generation, "
        "or durable saves. Answer briefly as the active Veridex room persona.\n\n"
        f"Governed context:\n{context}"
    ).strip()
    body = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 768},
    }
    resource = urllib.parse.quote(_resource_name(config.model), safe="/")
    url = f"https://generativelanguage.googleapis.com/v1beta/{resource}:generateContent"
    http_request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": config.api_key},
        method="POST",
    )
    timeout_seconds = max(5, int(str(os.environ.get("VERIDEX_GEMINI_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)))
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:700]
        raise RuntimeError(f"Gemini API failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini API could not be reached: {exc.reason}") from exc

    return {
        "ok": True,
        "provider": "gemini_api",
        "model": config.model,
        "reasoning_effort": "low",
        "task_type": str(request.get("task_type") or "simple"),
        "text": _extract_text(payload),
        "evidence": [],
    }
