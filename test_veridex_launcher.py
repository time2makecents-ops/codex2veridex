from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class VeridexLauncherTests(unittest.TestCase):
    def test_default_browser_route_uses_dedicated_veridex_profile(self) -> None:
        launcher = (ROOT / "veridex.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$SystemBrowser", launcher)
        self.assertIn("function Open-VeridexApp", launcher)
        self.assertIn("Open-VeridexBrowser $Url", launcher)
        self.assertIn('Open-VeridexApp "http://127.0.0.1:$Port"', launcher)

    def test_system_browser_is_an_explicit_opt_out(self) -> None:
        launcher = (ROOT / "veridex.ps1").read_text(encoding="utf-8")

        self.assertIn("if ($SystemBrowser)", launcher)
        self.assertIn("Start-Process $Url", launcher)


if __name__ == "__main__":
    unittest.main()
