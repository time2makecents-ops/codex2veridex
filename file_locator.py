"""Bounded Windows filename search helper for the standalone Veridex agent."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import string
import time
from pathlib import Path
from typing import Iterable, List


SKIP_DIRECTORIES = {
    "$recycle.bin",
    "system volume information",
    "windowsapps",
    ".git",
    "node_modules",
    "__pycache__",
}


def default_roots(include_all_drives: bool = True) -> List[Path]:
    candidates = [Path.cwd(), Path(os.environ.get("PUBLIC", r"C:\Users\Public")), Path.home()]
    if include_all_drives:
        candidates.extend(Path(f"{letter}:\\") for letter in string.ascii_uppercase)
    roots: List[Path] = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key not in seen and resolved.is_dir():
            seen.add(key)
            roots.append(resolved)
    return roots


def locate_files(pattern: str, roots: Iterable[Path], max_results: int = 20, timeout_seconds: float = 30) -> List[str]:
    query = str(pattern or "").strip()
    if not query:
        raise ValueError("filename pattern is required")
    has_wildcard = any(character in query for character in "*?[")
    wildcard = query if has_wildcard else f"*{query}*"
    wildcard = wildcard.casefold()
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    matches: List[str] = []
    seen_paths = set()
    for root in roots:
        if not has_wildcard:
            direct_match = root / query
            if direct_match.is_file():
                path = str(direct_match.resolve())
                key = path.casefold()
                if key not in seen_paths:
                    seen_paths.add(key)
                    matches.append(path)
                    if len(matches) >= max_results:
                        return matches
        for current, directories, filenames in os.walk(root, topdown=True, onerror=lambda _error: None):
            if time.monotonic() >= deadline:
                return matches
            directories[:] = [name for name in directories if name.casefold() not in SKIP_DIRECTORIES]
            for filename in filenames:
                if fnmatch.fnmatch(filename.casefold(), wildcard):
                    path = str((Path(current) / filename).resolve())
                    key = path.casefold()
                    if key not in seen_paths:
                        seen_paths.add(key)
                        matches.append(path)
                        if len(matches) >= max_results:
                            return matches
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Find local files by name with bounded traversal.")
    parser.add_argument("pattern", help="Filename or wildcard pattern")
    parser.add_argument("--root", action="append", default=[], help="Search root; repeat as needed")
    parser.add_argument("--max-results", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    roots = [Path(value).resolve() for value in args.root] if args.root else default_roots()
    matches = locate_files(args.pattern, roots, max(1, args.max_results), max(1, args.timeout))
    print(json.dumps({"pattern": args.pattern, "matches": matches, "count": len(matches)}, ensure_ascii=False))
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
