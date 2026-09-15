import json
import tempfile
import unittest
from pathlib import Path

from import_conversations import import_conversations


class ConversationImporterTests(unittest.TestCase):
    def test_indexes_supported_exports_and_deduplicates_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "exports"
            root.mkdir()
            (root / "one.md").write_text("# Museum notes\nA finding.", encoding="utf-8")
            (root / "copy.txt").write_text("# Museum notes\nA finding.", encoding="utf-8")
            (root / "ignored.png").write_bytes(b"not indexed")
            output = Path(temporary) / "data" / "index.json"

            result = import_conversations(root, output)
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["files_seen"], 2)
            self.assertEqual(len(payload["records"]), 1)
            self.assertEqual(payload["records"][0]["title"], "Museum notes")

    def test_reimport_does_not_duplicate_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "exports"
            root.mkdir()
            (root / "one.md").write_text("hello", encoding="utf-8")
            output = Path(temporary) / "index.json"

            import_conversations(root, output)
            result = import_conversations(root, output)
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["records_written"], 1)
            self.assertEqual(len(payload["records"]), 1)


if __name__ == "__main__":
    unittest.main()
