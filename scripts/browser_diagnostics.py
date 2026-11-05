"""Collect bounded local browser diagnostics without profiles, cookies or transcripts."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def collect() -> dict:
    report = {"observed_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "local bridge status and source history only; no account or transcript inspection"}
    node = shutil.which("node")
    if node:
        try:
            process = subprocess.run([node, str(ROOT / "veridex_browser.js"), "status"], cwd=ROOT,
                                     capture_output=True, text=True, timeout=10)
            value = json.loads(process.stdout)
            report["existing_bridge"] = {key: value.get(key) for key in ("ok", "connected", "profile_directory", "debug_port")}
            port = value.get("debug_port")
            if value.get("connected") and isinstance(port, int):
                with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
                    version = json.load(response)
                report["cdp_version"] = {key: version.get(key) for key in ("Browser", "Protocol-Version")}
        except Exception:
            report["existing_bridge"] = {"status": "unavailable", "detail": "Status could not be verified"}
    git = shutil.which("git") or str(Path("C:/Program Files/Git/cmd/git.exe"))
    if Path(git).is_file() or shutil.which(git):
        process = subprocess.run([git, "log", "-20", "--format=%h %aI %s", "--",
            "veridex_browser.js", "google_chrome_search.js", "veridex_mcp.py", "ISSUE_LOG.md"],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        report["relevant_source_history"] = process.stdout.splitlines() if process.returncode == 0 else []
    report["interpretation"] = [
        "A connected CDP bridge does not establish that the coding client's browser host is connected.",
        "Commit timestamps identify changes, not causation; no automatic rollback or retry is performed.",
        "Historical onset remains unknown without a reproducible failure and matching historical evidence.",
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new output path; existing diagnostic records are preserved")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collect(), indent=2) + "\n", encoding="utf-8")
    print(f"Browser diagnostic report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
