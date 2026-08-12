"""Deterministic Navigator policy, gate checks, and response shaping."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


GOVERNANCE_QUESTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwhat (?:hard )?(?:rules? and gates?|rules?|gates?) (?:do|does) (?:you|navigator|veridex|the app) (?:enforce|follow|apply)\b",
        r"\b(?:list|show|describe|explain)(?: me)? (?:the )?(?:navigator(?:'s)? (?:role|rules?|gates?)|governance(?: rules?|gates?|policy)?|hard rules?|system rules?|model policy|persistence rules?)\b",
        r"\b(?:what is|what's|how does) (?:the )?(?:navigator|veridex governance|governance system)(?: do| work)?\b",
        r"\b(?:navigator|governance) (?:status|rules?|gates?|policy)\b",
        r"\bwhat model (?:codes|plans|tests)(?: veridex| the app)?\b",
    )
)
ROLE_QUESTION = re.compile(r"\b(describe what you do|what do you do|what can you do|describe your role)\b", re.IGNORECASE)
PERSISTENCE_INTENT = re.compile(
    r"\b(?:remember|persist)\s+(?:this|that|it|these|those|my|the)\b|"
    r"\bmake\s+(?:this|that|it|these|those|my|the).{0,80}\b(?:persistent|durable|permanent)\b|"
    r"\bsave\s+(?:this|that|it|these|those|my preferences?|the rules?|the policy|to memory)\b",
    re.IGNORECASE,
)
SESSION_SCOPE = re.compile(r"\b(session[- ]only|this session|temporary|until (?:the )?session ends)\b", re.IGNORECASE)
PERSISTENT_SCOPE = re.compile(
    r"\b(persist(?:ent(?:ly)?)|permanent(?:ly)?|global(?:ly)?|across sessions|future sessions)\b",
    re.IGNORECASE,
)
CANON_MUTATION = re.compile(
    r"\b(replace|amend|merge|delete|deprecate|rewrite|change)\b.{0,80}\b(canon|canonical|governance|gate|hard rule|registry)\b|"
    r"\b(canon|canonical|governance|gate|hard rule|registry)\b.{0,80}\b(replace|amend|merge|delete|deprecate|rewrite|change)\b",
    re.IGNORECASE,
)
ACTION_CLAIM = re.compile(
    r"\b(?:i|we)\s+(?:have\s+)?(?:found\s+(?:it\s+at|the\s+(?:file|path|folder|directory))|searched\s+(?:the\s+)?(?:computer|drive|files?|folders?|directories))\b|"
    r"\b(?:i|we)\s+(?:have\s+)?(?:saved|created|edited|changed|moved|deleted|removed|sent|uploaded|downloaded)\s+(?:the\s+|a\s+|your\s+)?(?:file|folder|directory|document|image|video|repository|repo)\b|"
    r"\b(?:i|we)\s+(?:have\s+)?(?:ran|executed)\s+(?:the\s+|a\s+|your\s+)?(?:command|script|tests?|program|build)\b|"
    r"\bverified (?:the\s+)?(?:file|path|result|command|test)\b",
    re.IGNORECASE,
)
DESTRUCTIVE_INTENT = re.compile(
    r"\b(?:delete|remove|wipe|erase|format)\b.{0,100}\b(?:all files|everything|entire drive|whole drive|system files|windows folder|user profile|home directory)\b|"
    r"\b(?:all files|everything|entire drive|whole drive|system files|windows folder|user profile|home directory)\b.{0,100}\b(?:delete|remove|wipe|erase|format)\b",
    re.IGNORECASE,
)


class GovernanceRegistry:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.raw = self.path.read_bytes()
        self.data = json.loads(self.raw.decode("utf-8"))
        self.sha256 = hashlib.sha256(self.raw).hexdigest()

    @property
    def version(self) -> str:
        return str(self.data.get("snapshot", {}).get("version") or "unknown")

    @property
    def gate_defaults(self) -> Dict[str, bool]:
        rows = self.data.get("workspace_gate_defaults") or {}
        return {str(key): bool(value) for key, value in rows.items()}

    def gates(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.data.get("gates", []) if isinstance(row, dict)]

    def status(self, active_gates: Dict[str, bool], pending: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        gates = self.gates()
        return {
            "navigator": dict(self.data.get("navigator") or {}),
            "registry_path": str(self.path),
            "registry_version": self.version,
            "registry_sha256": self.sha256,
            "provenance": list(self.data.get("snapshot", {}).get("provenance") or []),
            "core_rules": list(self.data.get("core_rules") or []),
            "workspace_gates": dict(active_gates),
            "gates": gates,
            "active_gate_ids": [row["id"] for row in gates if row.get("status") == "active"],
            "non_applicable_gate_ids": [
                row["id"] for row in gates if "guarded_until" in str(row.get("applicability") or "")
            ],
            "runtime_model_policy": dict(self.data.get("runtime_model_policy") or {}),
            "terminal_development_policy": dict(self.data.get("terminal_development_policy") or {}),
            "pending": dict(pending or {}),
        }

    def is_governance_question(self, text: str, active_persona: str = "") -> bool:
        return bool(
            any(pattern.search(text) for pattern in GOVERNANCE_QUESTION_PATTERNS)
            or (active_persona == "Navigator" and ROLE_QUESTION.search(text))
        )

    def governance_answer(self, active_gates: Dict[str, bool]) -> str:
        enabled = [name for name, value in active_gates.items() if value]
        gate_lines = [
            f"- {row['id']} ({row.get('applicability', 'unknown')}): {row.get('definition', '')}"
            for row in self.gates()
            if row.get("status") == "active"
        ]
        core_lines = [f"- {row['id']}: {row['text']}" for row in self.data.get("core_rules", [])]
        return "\n".join(
            [
                "I’m Navigator, Veridex’s always-present governance authority. I monitor every room without changing the active room. I answer governance questions, run preflight and verification checks, and visibly hard-stop actions that would breach an active rule.",
                "",
                f"Rule source: {self.path}",
                f"Snapshot: v{self.version} · SHA-256 {self.sha256}",
                f"Active workspace gates: {', '.join(enabled) or 'none'}",
                "",
                "Core hard rules:",
                *core_lines,
                "",
                "Gate registry:",
                *gate_lines,
                "",
                "For Veridex development in this Codex terminal: Sol/high plans, codes, diagnoses, and approves releases; Luna/low only runs routine completed tests; any test failure returns to Sol/high.",
            ]
        )

    def preflight(
        self,
        text: str,
        active_gates: Dict[str, bool],
        pending: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        value = str(text or "").strip()
        pending = dict(pending or {})
        if pending:
            kind = str(pending.get("kind") or "")
            if kind == "durability_scope":
                if SESSION_SCOPE.search(value) or PERSISTENT_SCOPE.search(value):
                    scope = "session_only" if SESSION_SCOPE.search(value) else "persistent"
                    if scope == "persistent":
                        next_pending = {
                            "kind": "save_authorization",
                            "original_request": str(pending.get("original_request") or ""),
                            "durability_scope": "persistent",
                        }
                        return self._block(
                            ["SAVE_GATE", "SAVE-APP-COMMIT-VERIFICATION-GATE"],
                            "Persistent local governance requires a separate explicit SAVE authorization; ChatGPT product-memory commit cannot be assumed.",
                            ["Reply exactly 'SAVE' for local GOV-SAVE, or 'DON'T SAVE' to cancel."],
                            pending=next_pending,
                        )
                    return {
                        "allowed": True,
                        "resolved_pending": True,
                        "effective_text": f"{pending.get('original_request', '')}\n\nGovernance resolution: durability_scope={scope}.",
                        "resolution": {"durability_scope": scope},
                    }
                return self._block(
                    ["SAVE-SCOPE-DISAMBIGUATION-GATE"],
                    "The durability scope is still unresolved.",
                    ["Reply 'session-only' or 'persistent'."],
                    pending=pending,
                )
            if kind == "save_authorization":
                if re.fullmatch(r"\s*save\s*", value, re.IGNORECASE):
                    return {
                        "allowed": True,
                        "resolved_pending": True,
                        "effective_text": f"{pending.get('original_request', '')}\n\nGovernance resolution: explicit SAVE authorized for local GOV-SAVE only; APP-COMMIT remains unverified.",
                        "resolution": {"save_authorized": True, "app_commit_verified": False},
                    }
                if re.fullmatch(r"\s*(?:don't save|do not save|cancel)\s*", value, re.IGNORECASE):
                    return {
                        "allowed": True,
                        "resolved_pending": True,
                        "effective_text": "The user cancelled the pending persistent save. Confirm that nothing was persisted beyond the existing session transcript.",
                        "resolution": {"save_authorized": False, "cancelled": True},
                    }
                return self._block(
                    ["SAVE_GATE", "SAVE-APP-COMMIT-VERIFICATION-GATE"],
                    "Explicit SAVE authorization is still required.",
                    ["Reply exactly 'SAVE' to authorize local GOV-SAVE, or 'DON'T SAVE' to cancel."],
                    pending=pending,
                )

        if CANON_MUTATION.search(value):
            return self._block(
                ["GATE-PREFLIGHT", "GATE-CONFLICT"],
                "Standalone canon mutation is unavailable, so changing canonical governance here would bypass conflict and version discipline.",
                ["Use the governed snapshot import/update workflow with an explicit REPLACE, AMEND, or DISCARD decision."],
                incident=True,
            )

        if DESTRUCTIVE_INTENT.search(value):
            return self._block(
                ["DESTRUCTIVE-SCOPE-GATE"],
                "The request describes a broad destructive computer action without a narrow verified target.",
                ["Name the exact file or project-scoped directory and the intended deletion boundary."],
                incident=True,
            )

        if PERSISTENCE_INTENT.search(value):
            has_session_scope = bool(SESSION_SCOPE.search(value))
            has_persistent_scope = bool(PERSISTENT_SCOPE.search(value))
            if not has_session_scope and not has_persistent_scope:
                next_pending = {"kind": "durability_scope", "original_request": value}
                return self._block(
                    ["SAVE-SCOPE-DISAMBIGUATION-GATE", "GATE-PREFLIGHT"],
                    "The request asks for persistence without choosing its durability scope.",
                    ["Reply 'session-only' or 'persistent'."],
                    pending=next_pending,
                )
            if has_persistent_scope:
                next_pending = {"kind": "save_authorization", "original_request": value}
                return self._block(
                    ["SAVE_GATE", "SAVE-APP-COMMIT-VERIFICATION-GATE"],
                    "Persistent local governance requires explicit SAVE authorization; ChatGPT product-memory commit cannot be assumed.",
                    ["Reply exactly 'SAVE' for local GOV-SAVE, or 'DON'T SAVE' to cancel."],
                    pending=next_pending,
                )
        return {"allowed": True, "effective_text": value}

    def validate_model_route(self, task_type: str, model: str, reasoning: str) -> Dict[str, Any]:
        expected = dict((self.data.get("runtime_model_policy") or {}).get(task_type) or {})
        if not expected:
            return {"allowed": True}
        allowed = expected.get("model") == model and expected.get("reasoning") == reasoning
        return {
            "allowed": allowed,
            "expected": expected,
            "actual": {"model": model, "reasoning": reasoning},
            "gate_ids": [] if allowed else ["MODEL-ROUTE-GATE"],
        }

    def postflight(self, response_text: str, evidence: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        evidence_rows = [row for row in evidence if isinstance(row, dict)]
        if ACTION_CLAIM.search(str(response_text or "")) and not evidence_rows:
            return self._block(
                ["VERIFICATION", "GATE-VERIFY", "TOOL-TRUTH-BOUNDARY"],
                "The drafted response makes an operational claim without captured command or file evidence.",
                ["Run the operation with an evidence-producing tool, or state that the result is Unverified."],
                incident=True,
            )
        return {"allowed": True, "evidence": evidence_rows}

    @staticmethod
    def _block(
        gate_ids: List[str],
        reason: str,
        requirements: List[str],
        *,
        pending: Optional[Dict[str, Any]] = None,
        incident: bool = False,
    ) -> Dict[str, Any]:
        return {
            "allowed": False,
            "gate_ids": gate_ids,
            "reason": reason,
            "requirements": requirements,
            "pending": dict(pending or {}),
            "incident": incident,
        }


def intervention_text(result: Dict[str, Any], incident_id: str = "") -> str:
    lines = [
        "NAVIGATOR HARD STOP",
        f"Gates: {', '.join(result.get('gate_ids') or [])}",
        f"Blocked: {result.get('reason') or 'The request conflicts with active governance.'}",
    ]
    requirements = result.get("requirements") or []
    if requirements:
        lines.extend(["Required to continue:", *[f"- {item}" for item in requirements]])
    if incident_id:
        lines.append(f"Incident: {incident_id}")
    return "\n".join(lines)
