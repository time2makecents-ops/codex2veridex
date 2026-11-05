"""Download public Google website resources without installing or signing in."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

REVISION = "af2834411a564d366f9cab63efb046d9084f4dba"


def download(url: str, path: Path, previous: dict) -> dict:
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if previous.get("url") != url or previous.get("sha256") != digest:
            raise ValueError(f"Refusing to overwrite an unverified existing file: {path.name}")
    else:
        temporary = path.with_suffix(path.suffix + ".partial")
        if temporary.exists():
            raise ValueError(f"Partial download exists; review before retrying: {temporary}")
        with urlopen(url, timeout=60) as response, temporary.open("xb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        if not temporary.stat().st_size:
            raise ValueError(f"Empty download: {path.name}")
        temporary.replace(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"file": path.name, "url": url, "size": path.stat().st_size,
            "sha256": digest, "verification": "local SHA-256; not a publisher signature"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "resource-manifest.json"
    previous = json.loads(manifest.read_text("utf-8")) if manifest.exists() else {}
    rows = {row["file"]: row for row in previous.get("files", [])}
    with urlopen("https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json", timeout=30) as response:
        stable = json.load(response)["channels"]["Stable"]
    chrome = next(row["url"] for row in stable["downloads"]["chrome"] if row["platform"] == "win64")
    resources = [
        ("libwebp-1.6.0-windows-x64.zip", "https://storage.googleapis.com/downloads.webmproject.org/releases/webp/libwebp-1.6.0-windows-x64.zip"),
        (f"chrome-for-testing-{stable['version']}-win64.zip", chrome),
        ("devtools-troubleshooting-SKILL.md", f"https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/{REVISION}/skills/troubleshooting/SKILL.md"),
        ("devtools-troubleshooting.md", f"https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/{REVISION}/docs/troubleshooting.md"),
        ("devtools-APACHE-LICENSE", f"https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/{REVISION}/LICENSE"),
    ]
    for name, url in resources:
        rows[name] = download(url, root / name, rows.get(name, {}))
        record = {"updated_utc": datetime.now(timezone.utc).isoformat(), "chrome_version": stable["version"],
                  "devtools_revision": REVISION, "installed": False, "files": list(rows.values())}
        temp = manifest.with_suffix(".tmp")
        temp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, manifest)
        print(f"Verified {name}: {rows[name]['size']} bytes", flush=True)


if __name__ == "__main__":
    main()
