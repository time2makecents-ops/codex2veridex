"""Index local ChatGPT conversation exports without modifying source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("data/conversation_index.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _title(path: Path, text: str) -> str:
    heading = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    return heading.group(1).strip() if heading else path.stem


def _record(path: Path, root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    return {
        "source": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "title": _title(path, text),
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "characters": len(text),
        "text": text,
    }


def import_conversations(source: Path, output: Path = DEFAULT_OUTPUT) -> dict[str, int]:
    source = source.resolve()
    output = output.resolve()
    files = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json"})
    records = [_record(path, source) for path in files]
    records_by_hash = {record["sha256"]: record for record in records}
    existing: dict[str, Any] = {"version": 1, "records": []}
    if output.exists():
        try:
            loaded = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("records"), list):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            pass
    prior = {record.get("sha256"): record for record in existing["records"] if isinstance(record, dict)}
    previous_hashes = set(prior)
    prior.update(records_by_hash)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"version": 1, "records": sorted(prior.values(), key=lambda item: item.get("source", ""))}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"files_seen": len(files), "records_written": len(prior), "new_records": len(set(records_by_hash) - previous_hashes)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=Path("conversation_exports"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(import_conversations(args.source, args.output)))


if __name__ == "__main__":
    main()
