"""Importable interface to Veridex's shared Provenance Pending Chrome bridge."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / "facebook_chrome_bridge.js"


class FacebookChromeBridgeError(RuntimeError):
    """Raised when the local Facebook browser bridge cannot complete an action."""


def _run(
    action: str,
    *arguments: str,
    timeout: int = 90,
    env: Dict[str, str] | None = None,
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    node = shutil.which(os.environ.get("VERIDEX_NODE_COMMAND", "node"))
    if not node:
        raise FacebookChromeBridgeError("Node.js was not found; the Facebook Chrome bridge cannot run.")
    process_env = os.environ.copy()
    process_env.update({str(key): str(value) for key, value in (env or {}).items()})
    completed = subprocess.run(
        [node, str(BRIDGE), action, *[str(value) for value in arguments]],
        cwd=str(ROOT),
        input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=process_env,
    )
    try:
        payload = json.loads(str(completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        detail = " ".join(str(completed.stderr or completed.stdout or "").split())[:1000]
        raise FacebookChromeBridgeError(f"Facebook Chrome bridge returned invalid output: {detail}") from exc
    if completed.returncode != 0 or not payload.get("ok"):
        raise FacebookChromeBridgeError(str(payload.get("error") or "Facebook Chrome bridge failed."))
    return payload


def _invoke(action: str, *arguments: str, timeout: int, env: Dict[str, str] | None) -> Dict[str, Any]:
    if env is None:
        return _run(action, *arguments, timeout=timeout)
    return _run(action, *arguments, timeout=timeout, env=env)


def _invoke_payload(
    action: str,
    payload: Dict[str, Any],
    *,
    timeout: int,
    env: Dict[str, str] | None,
) -> Dict[str, Any]:
    if env is None:
        return _run(action, timeout=timeout, payload=payload)
    return _run(action, timeout=timeout, env=env, payload=payload)


def facebook_profile_status(*, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("status", timeout=20, env=env)


def setup_facebook_profile(*, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("setup", timeout=30, env=env)


def login_facebook(*, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("login", timeout=90, env=env)


def read_facebook_profile(target: str, *, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("profile", target, timeout=60, env=env)


def read_facebook_group(target: str, *, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("group-info", target, timeout=90, env=env)


def draft_facebook_message(target: str, message: str, *, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("draft-message", target, message, timeout=60, env=env)


def send_facebook_message(
    target: str,
    message: str,
    *,
    confirmed: bool = False,
    env: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    if not confirmed:
        return {
            "ok": True,
            "status": "confirmation_required",
            "target": str(target or "").strip(),
            "message": str(message or "").strip(),
            "sent": False,
        }
    return _invoke("send-message", target, message, timeout=60, env=env)


def prepare_marketplace_listing(
    draft: Dict[str, Any],
    image_paths: list[str],
    *,
    env: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Fill a visible Marketplace form without activating Next or Publish."""
    return _invoke_payload(
        "marketplace-prepare",
        {"draft": dict(draft), "image_paths": [str(value) for value in image_paths]},
        timeout=120,
        env=env,
    )


def resume_marketplace_listing(
    draft: Dict[str, Any],
    *,
    env: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Look for direct visible evidence that the reviewed listing was published."""
    return _invoke_payload("marketplace-resume", {"draft": dict(draft)}, timeout=90, env=env)


def prepare_facebook_group_share(
    draft: Dict[str, Any],
    group: Dict[str, Any],
    *,
    env: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Compose a group post containing a verified listing URL, without posting it."""
    return _invoke_payload(
        "group-share-prepare",
        {"draft": dict(draft), "group": dict(group)},
        timeout=90,
        env=env,
    )
