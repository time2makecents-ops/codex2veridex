from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from veridex_governance import GovernanceRegistry


class VeridexGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = GovernanceRegistry(Path("governance/navigator_governance_v1.0.0.json"))
        self.gates = self.registry.gate_defaults

    def test_navigator_is_always_present_and_rule_source_is_hashed(self) -> None:
        status = self.registry.status(self.gates)
        self.assertTrue(status["navigator"]["always_present"])
        self.assertEqual(len(status["registry_sha256"]), 64)
        self.assertIn("SAVE_GATE", status["workspace_gates"])

    def test_governance_question_returns_real_gates_and_source(self) -> None:
        self.assertTrue(self.registry.is_governance_question("describe what you do and what rules you enforce", "Navigator"))
        self.assertTrue(self.registry.is_governance_question("what hard rules and gates do you enforce?", "Receptionist"))
        answer = self.registry.governance_answer(self.gates)
        self.assertIn("navigator_governance_v1.0.0.json", answer)
        self.assertIn("GATE-PREFLIGHT", answer)
        self.assertIn("Sol/high", answer)

    def test_task_requests_that_mention_navigator_are_not_governance_questions(self) -> None:
        self.assertFalse(
            self.registry.is_governance_question(
                "create a test for me to make sure navigator is working correctly",
                "Navigator",
            )
        )
        self.assertFalse(
            self.registry.is_governance_question(
                "create a quick test for me to type in that will trigger the navigator to intervene",
                "Navigator",
            )
        )

    def test_persistence_scope_clarification_is_not_an_incident(self) -> None:
        result = self.registry.preflight("remember this preference", self.gates)
        self.assertFalse(result["allowed"])
        self.assertFalse(result["incident"])
        self.assertEqual(result["pending"]["kind"], "durability_scope")

        scope = self.registry.preflight("persistent", self.gates, result["pending"])
        self.assertFalse(scope["allowed"])
        self.assertFalse(scope["incident"])
        self.assertEqual(scope["pending"]["kind"], "save_authorization")

        save = self.registry.preflight("SAVE", self.gates, scope["pending"])
        self.assertTrue(save["allowed"])
        self.assertTrue(save["resolution"]["save_authorized"])

    def test_persistent_scope_in_original_request_still_requires_separate_save(self) -> None:
        result = self.registry.preflight("save this preference persistently", self.gates)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["pending"]["kind"], "save_authorization")

    def test_canon_mutation_and_unsupported_claim_are_hard_stops(self) -> None:
        preflight = self.registry.preflight("replace the canonical governance rule", self.gates)
        self.assertFalse(preflight["allowed"])
        self.assertTrue(preflight["incident"])
        postflight = self.registry.postflight("I saved the file.", [])
        self.assertFalse(postflight["allowed"])
        self.assertIn("GATE-VERIFY", postflight["gate_ids"])

    def test_broad_destructive_request_is_a_hard_stop(self) -> None:
        result = self.registry.preflight("delete everything on the entire drive", self.gates)
        self.assertFalse(result["allowed"])
        self.assertTrue(result["incident"])
        self.assertIn("DESTRUCTIVE-SCOPE-GATE", result["gate_ids"])

    def test_model_route_gate_matches_snapshot(self) -> None:
        self.assertTrue(self.registry.validate_model_route("coding", "gpt-5.6-sol", "high")["allowed"])
        self.assertTrue(self.registry.validate_model_route("search_deep", "gpt-5.6-sol", "high")["allowed"])
        self.assertFalse(self.registry.validate_model_route("coding", "gpt-5.6-luna", "low")["allowed"])

    def test_media_completion_is_blocked_when_only_unrelated_tool_evidence_exists(self) -> None:
        result = self.registry.postflight(
            "Created the comic-book-style ant drummer illustration using the built-in image tool.",
            [{"type": "command_execution", "status": "completed", "command": "Get-Content imagegen/SKILL.md"}],
            request_text="create an image of an ant playing drums in a comic book style",
            task_type="media",
        )
        self.assertFalse(result["allowed"])
        self.assertTrue(result["incident"])
        self.assertIn("FILE-ARTIFACT-VERIFICATION-GATE", result["gate_ids"])

    def test_media_completion_requires_and_accepts_verified_artifact_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ant.png"
            content = b"\x89PNG\r\n\x1a\nverified"
            path.write_bytes(content)
            artifact = {
                "file_id": "file_test",
                "artifact_number": 7,
                "path": str(path),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "ledgered_at": "2026-08-12T00:00:00Z",
            }
            result = self.registry.postflight(
                "Created the comic-book-style ant drummer illustration.",
                [{"type": "file_artifact", "status": "completed", **artifact}],
                request_text="create an image of an ant playing drums in a comic book style",
                task_type="media",
                generated_artifacts=[artifact],
            )
            self.assertTrue(result["allowed"])
            self.assertEqual(result["generated_artifacts"][0]["artifact_number"], 7)

    def test_png_edit_request_requires_file_artifact(self) -> None:
        self.assertTrue(
            self.registry.requires_file_artifact(
                "take the file adam.png and have the character sitting next to an animated dog",
                "media",
            )
        )

    def test_document_export_request_requires_file_artifact(self) -> None:
        self.assertTrue(self.registry.requires_file_artifact("create a DOCX resume and export it as PDF", "resume_generation"))
        self.assertTrue(self.registry.requires_file_artifact("create an Excel spreadsheet of event planners", "search_synthesis"))
        self.assertTrue(self.registry.requires_file_artifact("save the results as CSV", "search_synthesis"))

    def test_explicit_google_requires_dedicated_provider_without_substitution(self) -> None:
        missing = self.registry.postflight(
            "I found a result.",
            [],
            task_type="search_synthesis",
            current_date="2026-08-12",
            required_search_provider="google_chrome_profile",
        )
        self.assertFalse(missing["allowed"])
        self.assertIn("GOOGLE-BROWSER-PROVIDER-GATE", missing["gate_ids"])

        substituted = self.registry.postflight(
            "I found a result.",
            [
                {"type": "google_browser_search", "status": "completed", "provider": "google_chrome_profile"},
                {"type": "web_search", "status": "completed"},
            ],
            task_type="search_synthesis",
            current_date="2026-08-12",
            required_search_provider="google_chrome_profile",
        )
        self.assertFalse(substituted["allowed"])
        self.assertIn("generic web-search provider", substituted["reason"])

    def test_search_date_gate_blocks_past_dates_labeled_upcoming(self) -> None:
        result = self.registry.postflight(
            "Upcoming shows:\n- July 23, 2026: Portland\n- 8/1/2026: Eugene\n- 2026-09-01: Blairally",
            [],
            task_type="search_synthesis",
            current_date="2026-08-12",
        )
        self.assertFalse(result["allowed"])
        self.assertIn("CURRENT-DATE-SEARCH-GATE", result["gate_ids"])
        self.assertIn("July 23, 2026", result["reason"])
        self.assertIn("8/1/2026", result["reason"])
        self.assertNotIn("2026-09-01", result["reason"])

    def test_search_date_gate_allows_future_upcoming_dates(self) -> None:
        result = self.registry.postflight(
            "Upcoming shows:\n- September 1, 2026: Blairally",
            [],
            task_type="search_synthesis",
            current_date="2026-08-12",
        )
        self.assertTrue(result["allowed"])

    def test_search_date_gate_requires_year_before_labeling_date_upcoming(self) -> None:
        result = self.registry.postflight(
            "Upcoming shows:\n- September 1: Blairally\n- 9/6: Shanghai Tunnel",
            [],
            task_type="search_synthesis",
            current_date="2026-08-12",
        )
        self.assertFalse(result["allowed"])
        self.assertIn("CURRENT-DATE-SEARCH-GATE", result["gate_ids"])
        self.assertIn("without a verified year", result["reason"])

    def test_search_date_gate_allows_past_dates_explicitly_labeled_past(self) -> None:
        result = self.registry.postflight(
            "Upcoming shows:\n- September 1, 2026: Blairally\n\nPast shows:\n- June 15, 2026: Campbell Club",
            [],
            task_type="search_synthesis",
            current_date="2026-08-12",
        )
        self.assertTrue(result["allowed"])

    def test_search_date_gate_does_not_treat_not_upcoming_as_an_upcoming_section(self) -> None:
        result = self.registry.postflight(
            "As of August 12, 2026, no other upcoming dates were verified.\n\nThe July 23 show is past, not upcoming.",
            [],
            task_type="search_synthesis",
            current_date="2026-08-12",
        )
        self.assertTrue(result["allowed"])


if __name__ == "__main__":
    unittest.main()
