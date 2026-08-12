from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class WebUiTests(unittest.TestCase):
    def test_composer_send_control_becomes_a_server_side_stop_control(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="send-button" type="button"', html)
        self.assertIn('api("/api/chat/cancel"', script)
        self.assertIn("activeRequestId", script)
        self.assertIn("stop-glyph", script)
        self.assertIn(".stop-glyph", styles)


if __name__ == "__main__":
    unittest.main()
