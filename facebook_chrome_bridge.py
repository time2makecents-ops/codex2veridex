"""Importable interface to Veridex's dedicated Facebook Chrome bridge."""

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


def _run(action: str, *arguments: str, timeout: int = 90, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    node = shutil.which(os.environ.get("VERIDEX_NODE_COMMAND", "node"))
    if not node:
        raise FacebookChromeBridgeError("Node.js was not found; the Facebook Chrome bridge cannot run.")
    process_env = os.environ.copy()
    process_env.update({str(key): str(value) for key, value in (env or {}).items()})
    completed = subprocess.run(
        [node, str(BRIDGE), action, *[str(value) for value in arguments]],
        cwd=str(ROOT),
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


def facebook_profile_status(*, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("status", timeout=20, env=env)


def setup_facebook_profile(*, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("setup", timeout=30, env=env)


def login_facebook(*, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("login", timeout=90, env=env)


def read_facebook_profile(target: str, *, env: Dict[str, str] | None = None) -> Dict[str, Any]:
    return _invoke("profile", target, timeout=60, env=env)


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
