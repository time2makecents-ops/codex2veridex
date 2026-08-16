"""Deterministic Navigator policy, gate checks, and response shaping."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
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
FILE_CREATION_CLAIM = re.compile(
    r"(?:^|[.!?]\s+)(?:successfully\s+)?(?:created|generated|rendered|exported|saved|produced)\b.{0,120}"
    r"\b(?:file|document|resume|cover letter|image|illustration|picture|photo|graphic|artwork|bitmap|png|jpe?g|webp|gif|pdf|docx?|txt)\b|"
    r"\b(?:i|we)\s+(?:have\s+)?(?:created|generated|rendered|exported|saved|produced)\b.{0,120}"
    r"\b(?:file|document|resume|cover letter|image|illustration|picture|photo|graphic|artwork|bitmap|png|jpe?g|webp|gif|pdf|docx?|txt)\b|"
    r"\b(?:image|illustration|picture|photo|graphic|artwork|bitmap|file)\s+(?:was|has been)\s+"
    r"(?:created|generated|rendered|exported|saved|produced)\b",
    re.IGNORECASE,
)
MEDIA_CREATION_REQUEST = re.compile(
    r"\b(?:create|generate|make|draw|render|produce|design)\b.{0,100}"
    r"\b(?:image|illustration|picture|photo|graphic|artwork|bitmap|comic|sprite)\b|"
    r"\b(?:image|illustration|picture|photo|graphic|artwork|bitmap|comic|sprite)\b.{0,100}"
    r"\b(?:create|generate|make|draw|render|produce|design)\b",
    re.IGNORECASE,
)
MEDIA_FILE_REFERENCE = re.compile(r"\.(?:png|jpe?g|webp|gif)\b", re.IGNORECASE)
MEDIA_TRANSFORM_INTENT = re.compile(
    r"\b(?:take|edit|change|modify|alter|transform|update|add|remove|replace|crop|resize|enhance|put|place|have|make)\b",
    re.IGNORECASE,
)
DOCUMENT_CREATION_REQUEST = re.compile(
    r"\b(?:create|generate|make|render|produce|export|save|write)\b.{0,120}"
    r"\b(?:document|resume|cover letter|file|pdf|docx?|word document|text file)\b|"
    r"\b(?:document|resume|cover letter|pdf|docx?|word document|text file)\b.{0,120}"
    r"\b(?:create|generate|make|render|produce|export|save|write)\b",
    re.IGNORECASE,
)
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "sept": 9, "october": 10, "november": 11, "december": 12,
}
EVENT_DATE = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
    re.IGNORECASE,
)
ISO_EVENT_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
NUMERIC_EVENT_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
NUMERIC_MONTH_DAY = re.compile(r"\b(\d{1,2})/(\d{1,2})(?!/\d{2,4})\b")
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

    @staticmethod
    def requires_file_artifact(request_text: str, task_type: str) -> bool:
        text = str(request_text or "")
        if str(task_type or "") == "media":
            return bool(MEDIA_CREATION_REQUEST.search(text) or (MEDIA_FILE_REFERENCE.search(text) and MEDIA_TRANSFORM_INTENT.search(text)))
        return bool(DOCUMENT_CREATION_REQUEST.search(text))

    def postflight(
        self,
        response_text: str,
        evidence: Iterable[Dict[str, Any]],
        *,
        request_text: str = "",
        task_type: str = "",
        generated_artifacts: Optional[Iterable[Dict[str, Any]]] = None,
        current_date: str = "",
        required_search_provider: str = "",
    ) -> Dict[str, Any]:
        evidence_rows = [row for row in evidence if isinstance(row, dict)]
        completed_evidence = [row for row in evidence_rows if str(row.get("status") or "").casefold() == "completed"]
        artifacts = [row for row in (generated_artifacts or []) if isinstance(row, dict)]

        def verified_artifact(row: Dict[str, Any]) -> bool:
            try:
                size = int(row.get("size") or 0)
                artifact_number = int(row.get("artifact_number") or 0)
                path = Path(str(row.get("path") or "")).resolve()
            except (TypeError, ValueError):
                return False
            sha256 = str(row.get("sha256") or "")
            if (
                not path.is_file()
                or size <= 0
                or path.stat().st_size != size
                or artifact_number <= 0
                or not str(row.get("ledgered_at") or "")
                or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256)
            ):
                return False
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest().casefold() == sha256.casefold()

        valid_artifacts = [row for row in artifacts if verified_artifact(row)]
        creation_claim = bool(FILE_CREATION_CLAIM.search(str(response_text or "")))
        artifact_required = self.requires_file_artifact(request_text, task_type)
        if (creation_claim or artifact_required) and not valid_artifacts:
            return self._block(
                ["FILE-ARTIFACT-VERIFICATION-GATE", "GATE-VERIFY", "TOOL-TRUTH-BOUNDARY"],
                "No generated file was verified. A creation claim requires a real local path, nonzero size, SHA-256 checksum, and artifact-ledger entry.",
                ["Generate the file, copy it into the active Veridex session, and register it before reporting completion."],
                incident=creation_claim,
            )
        if required_search_provider:
            matching_search = any(
                str(row.get("type") or "") == "google_browser_search"
                and str(row.get("provider") or "") == required_search_provider
                for row in completed_evidence
            )
            substituted_search = any(str(row.get("type") or "") == "web_search" for row in completed_evidence)
            if not matching_search or substituted_search:
                reason = (
                    "A generic web-search provider was used during an explicit Google request."
                    if substituted_search
                    else f"No completed search evidence from {required_search_provider} was present."
                )
                return self._block(
                    ["GOOGLE-BROWSER-PROVIDER-GATE", "GATE-VERIFY", "TOOL-TRUTH-BOUNDARY"],
                    reason,
                    ["Run the query through the dedicated signed-in Veridex Chrome profile and do not substitute another provider."],
                    incident=True,
                )
        if str(task_type or "") in {"search_synthesis", "search_deep"} and current_date:
            try:
                today = date.fromisoformat(current_date)
            except ValueError:
                today = None
            if today:
                upcoming_section = False
                stale_dates: List[str] = []
                unconfirmed_dates: List[str] = []
                for line in str(response_text or "").splitlines():
                    lowered = line.casefold()
                    normalized_line = re.sub(r"^[\s#>*_`-]+|[\s*_`:]+$", "", lowered).strip()
                    if re.match(r"^upcoming\b", normalized_line) and len(normalized_line) <= 100:
                        upcoming_section = True
                    elif re.match(r"^(?:past|previous|date needs confirmation|unconfirmed|other)\b", normalized_line):
                        upcoming_section = False
                    direct_upcoming_claim = "upcoming" in lowered and not re.search(
                        r"\b(?:past|previous|not upcoming|already happened)\b", lowered
                    )
                    if not upcoming_section and not direct_upcoming_claim:
                        continue
                    for match in EVENT_DATE.finditer(line):
                        if not match.group(3):
                            unconfirmed_dates.append(match.group(0))
                            continue
                        year = int(match.group(3))
                        try:
                            event_date = date(year, MONTHS[match.group(1).casefold()], int(match.group(2)))
                        except ValueError:
                            continue
                        if event_date < today:
                            stale_dates.append(match.group(0))
                    for match in ISO_EVENT_DATE.finditer(line):
                        try:
                            event_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                        except ValueError:
                            continue
                        if event_date < today:
                            stale_dates.append(match.group(0))
                    for match in NUMERIC_EVENT_DATE.finditer(line):
                        try:
                            event_date = date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
                        except ValueError:
                            continue
                        if event_date < today:
                            stale_dates.append(match.group(0))
                    for match in NUMERIC_MONTH_DAY.finditer(line):
                        unconfirmed_dates.append(match.group(0))
                if stale_dates:
                    return self._block(
                        ["CURRENT-DATE-SEARCH-GATE", "GATE-VERIFY", "TOOL-TRUTH-BOUNDARY"],
                        f"Past event dates were labeled upcoming relative to {current_date}: {', '.join(stale_dates)}.",
                        ["Move past dates out of the upcoming section and verify future dates against the current local date."],
                        incident=True,
                    )
                if unconfirmed_dates:
                    return self._block(
                        ["CURRENT-DATE-SEARCH-GATE", "GATE-VERIFY", "TOOL-TRUTH-BOUNDARY"],
                        f"Event dates without a verified year were labeled upcoming relative to {current_date}: {', '.join(unconfirmed_dates)}.",
                        ["Move yearless dates to a date-needs-confirmation section unless the year is present in the governed evidence."],
                        incident=True,
                    )
        if ACTION_CLAIM.search(str(response_text or "")) and not completed_evidence:
            return self._block(
                ["VERIFICATION", "GATE-VERIFY", "TOOL-TRUTH-BOUNDARY"],
                "The drafted response makes an operational claim without completed matching command or file evidence.",
                ["Run the operation with an evidence-producing tool, or state that the result is Unverified."],
                incident=True,
            )
        return {"allowed": True, "evidence": evidence_rows, "generated_artifacts": valid_artifacts}

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
