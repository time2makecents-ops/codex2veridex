"""Prepare a reviewable Chrome native-host package; registration is separate."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chrome_native_host import EXTENSION_ID, load_settings


def write_owned(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes().replace(b"\r\n", b"\n") != content.replace(b"\r\n", b"\n"):
            raise ValueError(f"Existing prepared file differs; review before replacing: {path.name}")
        return
    with path.open("xb") as stream:
        stream.write(content)


def prepare(root: Path, base_url: str) -> Path:
    target = root / ".runtime" / "browser-extension"
    target.mkdir(parents=True, exist_ok=True)
    settings = target / "settings.json"
    if settings.exists():
        existing = load_settings(settings)
        if existing["base_url"] != base_url:
            raise ValueError("Existing native host uses a different server; review it before changing")
    else:
        temporary = target / "settings.tmp"
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump({"base_url": base_url, "token": secrets.token_urlsafe(48)}, handle)
        os.replace(temporary, settings)
        load_settings(settings)
    interpreter = root / ".venv" / "Scripts" / "python.exe"
    if not interpreter.is_file():
        raise ValueError("Use the existing Veridex virtual environment")
    launcher = target / "native-host.cmd"
    command = f'@echo off\r\n"{interpreter}" -u "{root / "chrome_native_host.py"}" %*\r\n'
    if any(character in str(root) for character in ('%', '\n', '\r', '"')):
        raise ValueError("Unsupported launcher path")
    write_owned(launcher, command.encode("utf-8"))
    manifest = target / "com.veridex.browser.json"
    write_owned(manifest, (json.dumps({"name": "com.veridex.browser", "description": "Veridex governed browser relay",
        "path": str(launcher), "type": "stdio", "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"]}, indent=2) + "\n").encode("utf-8"))
    return manifest


def register(manifest: Path) -> None:
    if os.name != "nt":
        raise ValueError("This installer supports Windows only")
    import winreg
    key_name = r"Software\Google\Chrome\NativeMessagingHosts\com.veridex.browser"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
            existing = winreg.QueryValueEx(key, "")[0]
        if Path(existing).resolve() != manifest.resolve():
            raise ValueError("Another native-host registration exists; refusing to replace it")
    except FileNotFoundError:
        pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_name) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest.resolve()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--register", action="store_true", help="Register persistent access only after reviewing/approving this package")
    args = parser.parse_args()
    manifest = prepare(ROOT, args.base_url)
    if args.register:
        register(manifest)
    print(f"Native manifest prepared: {manifest}")
    print(f"Extension ID: {EXTENSION_ID}")
    print("Registered" if args.register else "Not registered; no Chrome profile was changed")


if __name__ == "__main__":
    main()
