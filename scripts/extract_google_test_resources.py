"""Verify downloaded archives and extract into new resource subdirectories."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "resource-manifest.json").read_text("utf-8"))
    for row in manifest["files"]:
        if not row["file"].endswith(".zip"):
            continue
        source = root / row["file"]
        if source.stat().st_size != row["size"] or hashlib.sha256(source.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Downloaded archive integrity check failed")
        target = root / "extracted" / source.stem
        if target.exists():
            raise ValueError(f"Refusing to overwrite an existing extraction: {target}")
        with ZipFile(source) as archive:
            for entry in archive.infolist():
                path = (target / entry.filename).resolve()
                if not path.is_relative_to(target.resolve()) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unsafe archive member")
            archive.extractall(target)
        print(f"Extracted: {target}")


if __name__ == "__main__":
    main()
