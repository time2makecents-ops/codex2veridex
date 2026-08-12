from __future__ import annotations

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
        answer = self.registry.governance_answer(self.gates)
        self.assertIn("navigator_governance_v1.0.0.json", answer)
        self.assertIn("GATE-PREFLIGHT", answer)
        self.assertIn("Sol/high", answer)

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
        self.assertFalse(self.registry.validate_model_route("coding", "gpt-5.6-luna", "low")["allowed"])


if __name__ == "__main__":
    unittest.main()
