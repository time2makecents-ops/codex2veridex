import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class StartCodexTests(unittest.TestCase):
    def run_route(self, config_text: str, *arguments: str, profiles: dict[str, str] | None = None) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.toml"
            config.write_text(config_text, encoding="utf-8")
            for name, text in (profiles or {}).items():
                (Path(temporary) / f"{name}.config.toml").write_text(text, encoding="utf-8")
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "start_codex.ps1"),
                "-PrintRoute",
                "-RouteConfigFile",
                str(config),
                *arguments,
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_print_route_reads_top_level_config(self) -> None:
        route = self.run_route(
            'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "high"\n\n[features]\nexample = true\n'
        )
        self.assertEqual(route, {
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "source": "config.toml",
        })

    def test_print_route_reports_explicit_overrides(self) -> None:
        route = self.run_route(
            'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "high"\n',
            "--model",
            "gpt-5.6-luna",
            "--config",
            'model_reasoning_effort="low"',
        )
        self.assertEqual(route, {
            "model": "gpt-5.6-luna",
            "reasoning": "low",
            "source": "explicit CLI override",
        })

    def test_print_route_applies_named_profile_over_base_config(self) -> None:
        route = self.run_route(
            'model = "gpt-5.6-terra"\nmodel_reasoning_effort = "medium"\n',
            "--profile",
            "quality",
            profiles={"quality": 'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "high"\n'},
        )
        self.assertEqual(route, {
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "source": "profile quality",
        })

    def test_explicit_cli_override_wins_even_when_profile_argument_follows_it(self) -> None:
        route = self.run_route(
            'model = "gpt-5.6-terra"\nmodel_reasoning_effort = "medium"\n',
            "--model",
            "gpt-5.6-sol",
            "--config",
            'model_reasoning_effort="high"',
            "--profile",
            "fast",
            profiles={"fast": 'model = "gpt-5.6-luna"\nmodel_reasoning_effort = "low"\n'},
        )
        self.assertEqual(route, {
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "source": "explicit CLI override",
        })

    def test_invalid_profile_path_is_rejected(self) -> None:
        with self.assertRaises(AssertionError):
            self.run_route(
                'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "high"\n',
                "--profile",
                "../other",
            )


if __name__ == "__main__":
    unittest.main()
