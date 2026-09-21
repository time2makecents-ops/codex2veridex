from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import veridex_server
from veridex_admin import AdminService
from veridex_core import VeridexStore
from veridex_rooms import ROOMS


class VeridexAdminTests(unittest.TestCase):
    def service(self, root: Path, runner=None) -> AdminService:
        return AdminService(
            root / "data",
            root,
            ROOMS,
            Path("governance/navigator_governance_v1.0.0.json"),
            program_runner=runner,
        )

    def test_room_proposal_requires_approval_and_updates_global_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            proposal = service.create_proposal(
                "room",
                "create",
                {"title": "Production Room", "default_persona": "Producer", "aliases": ["production"]},
            )
            self.assertEqual(proposal["status"], "awaiting_approval")
            self.assertNotIn("production_room", [row["id"] for row in service.rooms()])

            applied = service.approve_and_apply(
                proposal["proposal_id"], expected_version=proposal["base_version"], confirm=True
            )

            self.assertEqual(applied["status"], "verified")
            self.assertIn("production_room", [row["id"] for row in service.rooms()])
            self.assertEqual(service.versions()["room_catalog"], 2)
            self.assertEqual(service.audit_log()[-1]["event"], "proposal_verified")

    def test_existing_catalog_receives_additive_antiques_release_seed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "data"
            first = AdminService(
                data_root,
                root,
                [row for row in ROOMS if row["id"] != "antiques_department"],
                Path("governance/navigator_governance_v1.0.0.json"),
            )
            self.assertNotIn("antiques_department", [row["id"] for row in first.rooms()])
            second = self.service(root)
            self.assertIn("antiques_department", [row["id"] for row in second.rooms()])
            version = second.versions()["room_catalog"]
            third = self.service(root)
            self.assertEqual(third.versions()["room_catalog"], version)

    def test_stale_room_proposal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            first = service.create_proposal("room", "create", {"title": "First Room"})
            stale = service.create_proposal("room", "create", {"title": "Stale Room"})
            service.approve_and_apply(first["proposal_id"], expected_version=1, confirm=True)
            with self.assertRaisesRegex(ValueError, "stale"):
                service.approve_and_apply(stale["proposal_id"], expected_version=1, confirm=True)

    def test_governance_disable_requires_two_approvals_and_can_be_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            proposal = service.create_proposal(
                "rule",
                "disable",
                {"target_id": "FREE-ART-ROUTE", "reason": "Temporarily replaced by a stricter provider policy"},
            )
            first = service.approve_and_apply(
                proposal["proposal_id"], expected_version=proposal["base_version"], confirm=True
            )
            self.assertEqual(first["status"], "second_confirmation_required")
            applied = service.approve_and_apply(
                proposal["proposal_id"],
                expected_version=proposal["base_version"],
                confirm=True,
                second_confirmation_token=first["second_confirmation_token"],
            )
            disabled = next(row for row in service.governance()["core_rules"] if row["id"] == "FREE-ART-ROUTE")
            self.assertEqual(disabled["status"], "disabled")
            self.assertEqual(applied["status"], "verified")

            rolled_back = service.rollback(proposal["proposal_id"], confirm=True)
            restored = next(row for row in service.governance()["core_rules"] if row["id"] == "FREE-ART-ROUTE")
            self.assertEqual(rolled_back["status"], "rolled_back")
            self.assertNotEqual(restored.get("status"), "disabled")

    def test_safety_kernel_cannot_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            with self.assertRaisesRegex(ValueError, "safety kernel"):
                service.create_proposal(
                    "rule",
                    "disable",
                    {"target_id": "NAVIGATOR-AUTHORITY", "reason": "test"},
                )

    def test_program_change_is_path_bounded_and_runs_only_after_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            calls = []

            def runner(proposal):
                calls.append(proposal["proposal_id"])
                return {"verified": True, "changed_paths": ["web/app.js"], "rollback": {"supported": True, "manifest": []}}

            service = self.service(Path(temporary), runner=runner)
            proposal = service.create_proposal(
                "program",
                "change",
                {
                    "title": "Improve room controls",
                    "instructions": "Add an accessible room management control.",
                    "allowed_paths": ["web/app.js"],
                    "tests": ["python -m unittest test_web_ui.py"],
                },
            )
            self.assertEqual(calls, [])
            applied = service.approve_and_apply(
                proposal["proposal_id"], expected_version=0, confirm=True
            )
            self.assertEqual(calls, [proposal["proposal_id"]])
            self.assertEqual(applied["status"], "verified")

    def test_room_and_program_proposals_require_infrastructure_room(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self.service(root)
            store = VeridexStore(root / "data", service.active_governance_path)
            initial = store.ensure_default()
            workspace_id = initial["workspace"]["workspace_id"]
            session_id = initial["session"]["session_id"]
            request = {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "kind": "room",
                "action": "create",
                "payload": {"title": "Operations Room"},
            }
            with patch.object(veridex_server, "STORE", store), patch.object(veridex_server, "ADMIN", service):
                with self.assertRaisesRegex(ValueError, "Infrastructure Room"):
                    veridex_server.admin_create_response(request)
                store.set_room(workspace_id, session_id, "infrastructure_room")
                result = veridex_server.admin_create_response(request)
            self.assertEqual(result["status"], "awaiting_approval")


if __name__ == "__main__":
    unittest.main()
