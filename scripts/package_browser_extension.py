"""Create a reproducible, credential-free review archive and local artifact ledger."""
import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def record(path: Path) -> dict:
    return {"file": path.name, "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    target = args.destination.resolve()
    target.mkdir(parents=True, exist_ok=True)
    ledger = target / "browser-companion-artifacts.json"
    previous = json.loads(ledger.read_text("utf-8")) if ledger.exists() else {"producer": "VeridexBrowserCompanion", "files": []}
    if previous.get("producer") != "VeridexBrowserCompanion":
        raise ValueError("Refusing to replace an unrelated artifact ledger")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for source in sorted((ROOT / "chrome_extension").iterdir()):
            if not source.is_file():
                continue
            info = ZipInfo("chrome_extension/" + source.name, date_time=(2026, 11, 4, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    version = json.loads((ROOT / "chrome_extension" / "manifest.json").read_text("utf-8"))["version"]
    path = target / f"veridex-browser-companion-{version}-{digest[:12]}.zip"
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError("Existing archive differs")
    else:
        with path.open("xb") as stream:
            stream.write(content)
    rows = {row["file"]: row for row in previous["files"]}
    rows[path.name] = record(path)
    if args.screenshot:
        image_digest = hashlib.sha256(args.screenshot.read_bytes()).hexdigest()
        screenshot = target / f"companion-popup-{image_digest[:12]}.png"
        if not screenshot.exists():
            shutil.copyfile(args.screenshot, screenshot)
        if hashlib.sha256(screenshot.read_bytes()).hexdigest() != image_digest:
            raise ValueError("Existing preview differs")
        rows[screenshot.name] = record(screenshot)
    for source in (ROOT / "GOOGLE_BROWSER_RESOURCES.md",):
        data = source.read_bytes()
        name = f"google-resource-shortlist-{hashlib.sha256(data).hexdigest()[:12]}.md"
        copy = target / name
        if not copy.exists():
            copy.write_bytes(data)
        rows[name] = record(copy)
    for report in target.glob("browser-diagnostics-*.json"):
        rows[report.name] = record(report)
    for row in rows.values():
        actual = record(target / row["file"])
        if actual != row or not actual["size"]:
            raise ValueError("Artifact verification failed")
    temporary = ledger.with_suffix(".tmp")
    temporary.write_text(json.dumps({"producer": "VeridexBrowserCompanion", "installed": False,
        "native_registry_changed": False, "files": list(rows.values())}, indent=2) + "\n", "utf-8")
    temporary.replace(ledger)
    print(f"Review archive: {path}")
    print(f"Verified artifact ledger: {ledger}")


if __name__ == "__main__":
    main()
