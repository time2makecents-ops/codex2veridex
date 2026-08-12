from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from file_locator import locate_files


class FileLocatorTests(unittest.TestCase):
    def test_finds_matching_file_and_stops_at_requested_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "nested" / "Quarterly Notes.txt").write_text("proof", encoding="utf-8")
            (root / "other-quarterly.txt").write_text("proof", encoding="utf-8")
            matches = locate_files("quarterly", [root], max_results=1, timeout_seconds=5)
            self.assertEqual(len(matches), 1)
            self.assertIn("quarterly", Path(matches[0]).name.lower())


if __name__ == "__main__":
    unittest.main()
