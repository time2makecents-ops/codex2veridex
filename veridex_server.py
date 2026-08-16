"""Dependency-free local web server for standalone Codex + Veridex chat."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from codex_gateway import access_mode, invoke_codex, select_model
from gemini_gateway import gemini_enabled, invoke_gemini
from gmail_gateway import GmailGateway, GmailGatewayError
from google_chrome_search import GoogleChromeSearchError, continues_google_search, search_google, wants_google_search
from request_control import ActiveRequestRegistry, RequestCancelled
from veridex_core import VeridexStore, classify_task, transcript_context
from veridex_governance import GovernanceRegistry, intervention_text
from veridex_rooms import room_by_id, room_directory_text, rooms_payload, route_room_request, valid_room_titles


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
LOCAL_ROOM_QUERY = re.compile(
    r"\b(?:where am i|what(?:'s| is) (?:my |the |current |active )?room|current room|active room)\b",
    re.IGNORECASE,
)
LOCAL_PERSONA_QUERY = re.compile(
    r"\b(?:who (?:are you|is active)|what(?:'s| is) (?:my |the |current |active )?persona|current persona|active persona)\b",
    re.IGNORECASE,
)
LOCAL_ACCESS_QUERY = re.compile(
    r"\b(?:access mode|computer access|read-only|read only|full computer access|can you write files)\b",
    re.IGNORECASE,
)
LOCAL_FILES_QUERY = re.compile(
    r"\b(?:what files? (?:are )?(?:attached|uploaded)|list (?:the )?(?:attached|uploaded) files|current files?)\b",
    re.IGNORECASE,
)
LOCAL_STATUS_QUERY = re.compile(
    r"\b(?:governance status|navigator status|system status|veridex status|room status)\b",
    re.IGNORECASE,
)
CODEX_ONLY_INTENT = re.compile(
    r"\b(?:code|coding|python|javascript|typescript|react|api|function|class|bug|debug|refactor|compile|"
    r"repository|repo|git|sql|html|css|file|folder|directory|path|desktop|drive|save|edit|delete|move|"
    r"run|execute|install|download|upload|image|photo|picture|video|graphic|render|search|research|"
    r"latest|current|look up|find online|web|google|plan|planning|architecture|roadmap|legal|medical|"
    r"financial|investment|security audit|vulnerabilit)\w*\b",
    re.IGNORECASE,
)
EMAIL_ADDRESS_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
GMAIL_CHECK_RE = re.compile(
    r"\b(?:nance|nancy)\b.{0,80}\b(?:email|gmail|inbox|mail|messages?)\b|"
    r"\b(?:check|read|show|search|scan|look at)\b.{0,80}\b(?:email|gmail|inbox|mail|messages?)\b|"
    r"\b(?:email|gmail|inbox|mail)\b.{0,80}\b(?:check|read|show|search|scan)\b",
    re.IGNORECASE,
)
GMAIL_SEND_RE = re.compile(
    r"\b(?:nance|nancy)?[,\s]*(?:please\s+)?(?:send|compose)\s+(?:an\s+)?email\s+to\s+"
    r"(?P<to>.+?)\s+subject\s+(?P<subject>.+?)\s+body\s+(?P<body>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
GMAIL_STRUCTURED_SEND_RE = re.compile(
    r"\b(?:nance|nancy)?[,\s]*(?:please\s+)?(?:send|compose)\s+(?:an\s+)?email\s+to\s+"
    r"(?P<to>[^\r\n]+)\r?\nsubject:\s*(?P<subject>[^\r\n]+)\r?\nbody:\s*\r?\n(?P<body>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
GMAIL_CONFIRM_RE = re.compile(
    r"\b(?:confirm send|send it|yes send|go ahead and send|send that email|confirm and send)\b",
    re.IGNORECASE,
)


def load_env(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env(ROOT / ".env.local")
DATA_ROOT = Path(os.environ.get("VERIDEX_DATA_DIR", str(ROOT / "data"))).resolve()
STORE = VeridexStore(DATA_ROOT)
GMAIL = GmailGateway()
MAX_UPLOAD_BYTES = max(1, int(os.environ.get("VERIDEX_MAX_UPLOAD_MB", "50"))) * 1024 * 1024
MAX_GMAIL_ATTACHMENT_BYTES = max(1, int(os.environ.get("VERIDEX_GMAIL_MAX_ATTACHMENT_MB", "20"))) * 1024 * 1024
GOVERNANCE = GovernanceRegistry(ROOT / "governance" / "navigator_governance_v1.0.0.json")
ACTIVE_REQUESTS = ActiveRequestRegistry()


def public_file(row: Dict[str, Any], *, include_path: bool = False) -> Dict[str, Any]:
    keys = [
        "file_id",
        "artifact_number",
        "name",
        "content_type",
        "size",
        "sha256",
        "source",
        "kind",
        "scope",
        "scope_ref",
        "room_id",
        "created_at",
        "linked_at",
        "ledgered_at",
    ]
    if include_path:
        keys.append("path")
    return {key: row[key] for key in keys if key in row}


def public_art_image(row: Dict[str, Any]) -> Dict[str, Any]:
    value = public_file(row)
    for key in ("source_session_id", "source_session_title", "created_at"):
        if key in row:
            value[key] = row[key]
    return value


def public_room_file(row: Dict[str, Any]) -> Dict[str, Any]:
    value = public_file(row)
    for key in ("source_session_id", "source_session_title"):
        if key in row:
            value[key] = row[key]
    return value


def room_file_library_id(value: Any) -> str:
    room_id = str(value or "").strip()
    room = room_by_id(room_id)
    if not room or room_id in {"lobby", "art_department"}:
        raise ValueError("The Files library is available only in non-Lobby rooms outside Art Department.")
    return room_id


def generated_artifact_report(artifacts: list[Dict[str, Any]]) -> str:
    lines = ["Verified generated file:" if len(artifacts) == 1 else "Verified generated files:"]
    for row in artifacts:
        lines.extend(
            [
                f"- {row['name']}",
                f"  Path: {row['path']}",
                f"  Size: {row['size']} bytes",
                f"  SHA-256: {row['sha256']}",
                f"  Artifact: #{row['artifact_number']}",
            ]
        )
    return "\n".join(lines)


def runtime_status() -> Dict[str, Any]:
    mode = access_mode()
    return {
        "access_mode": mode,
        "access_label": "Full computer access" if mode == "full" else "Read-only computer access",
        "can_write_computer": mode == "full",
    }


def local_fact_text(
    prompt: str,
    active_room: str,
    room_title: str,
    active_persona: str,
    attachments: list[Dict[str, Any]],
    workspace_id: str,
    session_id: str,
) -> str:
    value = str(prompt or "")
    if LOCAL_ROOM_QUERY.search(value):
        return f"You are in {room_title}. {active_persona} is active."
    if LOCAL_PERSONA_QUERY.search(value):
        return f"{active_persona} is active in {room_title}."
    if LOCAL_ACCESS_QUERY.search(value):
        status = runtime_status()
        return f"Access mode: {status['access_label']}."
    if LOCAL_FILES_QUERY.search(value):
        if not attachments:
            return "No files are attached to this message."
        names = ", ".join(str(row.get("name") or "unnamed") for row in attachments)
        return f"Attached files: {names}."
    if LOCAL_STATUS_QUERY.search(value):
        status = runtime_status()
        governance = governance_status(workspace_id, session_id)
        gates = ", ".join(governance.get("active_gate_ids") or []) or "none"
        return f"Room: {room_title}. Persona: {active_persona}. Access: {status['access_label']}. Active governance gates: {gates}."
    return ""


def should_use_gemini_route(
    *,
    active_room: str,
    active_persona: str,
    task_type: str,
    prompt: str,
    attachments: list[Dict[str, Any]],
    explicit_google_search: bool,
) -> bool:
    if active_room != "lobby" or active_persona != "Receptionist":
        return False
    if attachments or explicit_google_search:
        return False
    if str(task_type or "") not in {"simple", "conversation"}:
        return False
    if CODEX_ONLY_INTENT.search(str(prompt or "")):
        return False
    return gemini_enabled()


def governance_status(workspace_id: str, session_id: str = "") -> Dict[str, Any]:
    state = STORE.ensure_governance_state(workspace_id)
    pending = STORE.pending_governance(workspace_id, session_id) if session_id else {}
    incidents = STORE.list_governance_incidents(workspace_id, limit=1)
    status = GOVERNANCE.status(dict(state.get("gates") or {}), pending)
    status["latest_incident"] = incidents[-1] if incidents else None
    status["persistent_memo_count"] = len(STORE.list_governance_memos(workspace_id))
    return status


def state_response(value: Dict[str, Any]) -> Dict[str, Any]:
    workspace = value.get("workspace") if isinstance(value.get("workspace"), dict) else {}
    session = value.get("session") if isinstance(value.get("session"), dict) else {}
    workspace_id = str(workspace.get("workspace_id") or "")
    session_id = str(session.get("session_id") or "")
    governance = governance_status(workspace_id, session_id) if workspace_id else {}
    return {**value, "runtime": runtime_status(), "governance": governance}


def public_delivery_alert(
    row: Dict[str, Any],
    workspace_id: str = "",
    session_id: str = "",
) -> Dict[str, Any]:
    original_to = row.get("to") if isinstance(row.get("to"), list) else []
    failed_recipient = str(row.get("recipient") or "").strip()
    retry_to = [failed_recipient] if failed_recipient else [str(value) for value in original_to]
    attachments: list[Dict[str, Any]] = []
    unavailable: list[str] = []
    stored = row.get("attachments") if isinstance(row.get("attachments"), list) else []
    if stored and str(row.get("workspace_id") or "") == workspace_id and str(row.get("session_id") or "") == session_id:
        available_ids = {
            str(value.get("file_id") or ""): value
            for value in STORE.list_files(workspace_id, session_id)
        }
        for attachment in stored:
            file_id = str((attachment or {}).get("file_id") or "")
            if file_id and file_id in available_ids:
                attachments.append(public_file(available_ids[file_id]))
            else:
                unavailable.append(str((attachment or {}).get("name") or "attachment"))
    else:
        unavailable.extend(str((attachment or {}).get("name") or "attachment") for attachment in stored)
    return {
        "failure_id": str(row.get("failure_id") or ""),
        "recipient": failed_recipient,
        "subject": str(row.get("subject") or "(unknown subject)"),
        "diagnostic": str(row.get("diagnostic") or "The recipient's mail system returned the message."),
        "status_code": str(row.get("status_code") or ""),
        "detected_at": str(row.get("detected_at") or ""),
        "retry": {
            "failure_id": str(row.get("failure_id") or ""),
            "to": retry_to,
            "subject": str(row.get("subject") or ""),
            "body": str(row.get("body") or ""),
            "attachments": attachments,
            "unavailable_attachments": unavailable,
        },
    }


def delivery_alerts(workspace_id: str = "", session_id: str = "") -> list[Dict[str, Any]]:
    return [
        public_delivery_alert(row, workspace_id, session_id)
        for row in GMAIL.list_delivery_failures()
    ]


def check_delivery_alerts(workspace_id: str, session_id: str) -> Dict[str, Any]:
    session = STORE.find_session(session_id)
    if str(session.get("workspace_id") or "") != workspace_id:
        raise KeyError("Session does not belong to workspace")
    result = GMAIL.check_delivery_failures()
    alerts = GMAIL.list_delivery_failures()
    if str(session.get("active_room") or "") == "my_office":
        for row in alerts:
            if str(row.get("notified_session_id") or ""):
                continue
            public = public_delivery_alert(row, workspace_id, session_id)
            recipient = public["recipient"] or "an unknown recipient"
            text = (
                f"Delivery failed for {recipient}: {public['subject']}. "
                f"{public['diagnostic']} Correct the address and resend when ready."
            )
            STORE.append_message(
                workspace_id,
                session_id,
                "assistant",
                text,
                speaker="Nancy",
                provider="veridex_gmail_router",
                model="deterministic",
                reasoning_effort="none",
                task_type="gmail_delivery_failure",
                message_kind="gmail_delivery_failure",
                gmail={"provider": "gmail_api", "status": "failed", "delivery_failure": public},
            )
            GMAIL.mark_failure_notified(str(row.get("failure_id") or ""), session_id)
    return {
        "ok": True,
        "new_failure_count": len(result.get("new_failures") or []),
        "alerts": delivery_alerts(workspace_id, session_id),
        "messages": STORE.load_messages(workspace_id, session_id),
    }


def local_chat_response(
    workspace_id: str,
    session_id: str,
    user_message: Dict[str, Any],
    text: str,
    speaker: str,
    task_type: str,
    **extra: Any,
) -> Dict[str, Any]:
    message_metadata = extra.pop("message_metadata", {})
    response_provider = str(extra.pop("response_provider", "veridex_router"))
    assistant_message = STORE.append_message(
        workspace_id,
        session_id,
        "assistant",
        text,
        speaker=speaker,
        provider=response_provider,
        model="deterministic",
        reasoning_effort="none",
        task_type=task_type,
        **(message_metadata if isinstance(message_metadata, dict) else {}),
    )
    return {
        "ok": True,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "user_message": user_message,
        "message": assistant_message,
        "provider": response_provider,
        "model": "deterministic",
        "reasoning_effort": "none",
        "task_type": task_type,
        "fallback_used": False,
        **runtime_status(),
        **extra,
    }


def parse_email_send_request(prompt: str) -> Dict[str, Any]:
    value = str(prompt or "")
    match = GMAIL_STRUCTURED_SEND_RE.search(value) or GMAIL_SEND_RE.search(value)
    if not match:
        return {}
    recipients = EMAIL_ADDRESS_RE.findall(match.group("to"))
    if not recipients:
        return {}
    return {
        "to": recipients,
        "subject": " ".join(match.group("subject").split()),
        "body": match.group("body").strip(),
    }


def normalize_email_draft(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    raw_to = value.get("to")
    recipients = EMAIL_ADDRESS_RE.findall(
        " ".join(str(item) for item in raw_to) if isinstance(raw_to, list) else str(raw_to or "")
    )
    subject = " ".join(str(value.get("subject") or "").split())
    body = str(value.get("body") or "").strip()
    if not recipients or not subject or not body:
        raise ValueError("email draft requires a recipient, subject, and message")
    attachment_ids = value.get("attachment_ids") if isinstance(value.get("attachment_ids"), list) else []
    return {
        "to": recipients,
        "subject": subject,
        "body": body,
        "attachment_ids": list(dict.fromkeys(str(file_id) for file_id in attachment_ids if str(file_id).strip())),
        "retry_failure_id": str(value.get("retry_failure_id") or "").strip(),
    }


def validate_email_attachments(attachments: list[Dict[str, Any]]) -> None:
    total = sum(max(0, int(row.get("size") or 0)) for row in attachments)
    if total > MAX_GMAIL_ATTACHMENT_BYTES:
        raise ValueError(
            f"email attachments exceed the {MAX_GMAIL_ATTACHMENT_BYTES // (1024 * 1024)} MB limit"
        )


def gmail_query_from_prompt(prompt: str) -> str:
    value = str(prompt or "").lower()
    if re.search(r"\b(?:unread|new)\b", value):
        return "in:inbox is:unread"
    if re.search(r"\b(?:sent mail|sent email|sent messages?)\b", value):
        return "in:sent"
    return "in:inbox"


def gmail_result_limit(prompt: str) -> int:
    value = str(prompt or "").lower()
    if re.search(r"\b(?:newest|latest|most recent|last received)\b", value):
        requested = re.search(r"\b(?:newest|latest|last)\s+(\d{1,2})\s+(?:emails?|messages?)\b", value)
        return max(1, min(int(requested.group(1)), 10)) if requested else 1
    requested = re.search(r"\b(?:show|check|read|get)\s+(?:me\s+)?(?:the\s+)?(?:last\s+)?(\d{1,2})\s+(?:emails?|messages?)\b", value)
    return max(1, min(int(requested.group(1)), 10)) if requested else 5


def gmail_message_metadata(messages: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    fields = ("id", "threadId", "from", "subject", "date", "snippet")
    return [
        {key: str(message.get(key) or "")[:1000] for key in fields}
        for message in messages[:10]
    ]


def wants_gmail_route(prompt: str, workspace_id: str, session_id: str) -> bool:
    if parse_email_send_request(prompt):
        return True
    if GMAIL_CONFIRM_RE.search(str(prompt or "")) and STORE.pending_email(workspace_id, session_id):
        return True
    return bool(GMAIL_CHECK_RE.search(str(prompt or "")))


def gmail_messages_text(messages: list[Dict[str, Any]]) -> str:
    count = len(messages)
    noun = "message" if count == 1 else "messages"
    if not messages:
        return "No Gmail messages matched that request."
    lines = [f"Found {count} Gmail {noun}."]
    for message in messages[:10]:
        subject = str(message.get("subject") or "(no subject)")
        sender = str(message.get("from") or "Unknown sender")
        date = str(message.get("date") or "").strip()
        snippet = str(message.get("snippet") or "").strip()
        line = f"- {subject} from {sender}"
        if date:
            line += f" ({date})"
        lines.append(line)
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines)


def gmail_chat_response(
    workspace_id: str,
    session_id: str,
    user_message: Dict[str, Any],
    prompt: str,
    *,
    draft_override: Optional[Dict[str, Any]] = None,
    attachments: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if GMAIL_CONFIRM_RE.search(str(prompt or "")):
        pending = STORE.pending_email(workspace_id, session_id)
        if not pending:
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                "Nancy has no pending email to send.",
                "Nancy",
                "gmail_send_unavailable",
                response_provider="veridex_gmail_router",
            )
        pending_ids = [str(file_id) for file_id in pending.get("attachment_ids", []) if str(file_id).strip()]
        pending_attachments = STORE.resolve_files(workspace_id, session_id, pending_ids)
        if len(pending_attachments) != len(set(pending_ids)):
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                "Gmail send could not be completed because an attached file is no longer available. Edit the draft and attach it again.",
                "Nancy",
                "gmail_unavailable",
                response_provider="veridex_gmail_router",
            )
        try:
            validate_email_attachments(pending_attachments)
            send_args = (
                [str(value) for value in pending.get("to", [])],
                str(pending.get("subject") or ""),
                str(pending.get("body") or ""),
            )
            send_context = {"workspace_id": workspace_id, "session_id": session_id}
            result = (
                GMAIL.send(*send_args, pending_attachments, context=send_context)
                if pending_attachments
                else GMAIL.send(*send_args, context=send_context)
            )
        except (GmailGatewayError, ValueError) as exc:
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                f"Gmail send could not be completed: {exc}",
                "Nancy",
                "gmail_unavailable",
                response_provider="veridex_gmail_router",
            )
        retry_failure_id = str(pending.get("retry_failure_id") or "").strip()
        if retry_failure_id:
            GMAIL.resolve_delivery_failure(retry_failure_id)
        STORE.clear_pending_email(workspace_id, session_id)
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            (
                f"Gmail accepted the email for delivery to {', '.join(str(value) for value in pending.get('to', []))}."
                + (f" {result['journal_warning']}" if result.get("journal_warning") else "")
            ),
            "Nancy",
            "gmail_send",
            response_provider="veridex_gmail_router",
            message_metadata={
                "message_kind": "gmail_send",
                "gmail": {
                    "provider": "gmail_api",
                    "status": "sent",
                    "message_id": result.get("id"),
                    "to": [str(value) for value in pending.get("to", [])],
                    "subject": str(pending.get("subject") or ""),
                    "attachments": [public_file(row) for row in pending_attachments],
                },
            },
        )

    draft = dict(draft_override or parse_email_send_request(prompt))
    if draft:
        resolved_attachments = list(attachments or [])
        validate_email_attachments(resolved_attachments)
        draft["attachment_ids"] = [str(row.get("file_id") or "") for row in resolved_attachments]
        draft["attachments"] = [public_file(row) for row in resolved_attachments]
        STORE.set_pending_email(workspace_id, session_id, draft)
        attachment_text = ""
        if draft["attachments"]:
            attachment_text = "\nAttachments: " + ", ".join(str(row.get("name") or "file") for row in draft["attachments"])
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            (
                "Review and confirm before Nancy sends this email.\n"
                f"To: {', '.join(draft['to'])}\n"
                f"Subject: {draft['subject']}\n"
                f"Body: {draft['body']}"
                f"{attachment_text}\n\n"
                "Reply `confirm send` to send it."
            ),
            "Nancy",
            "gmail_send_confirmation",
            response_provider="veridex_gmail_router",
            message_metadata={
                "message_kind": "gmail_send_confirmation",
                "gmail": {"provider": "gmail_api", "status": "pending_confirmation", "draft": draft},
            },
        )

    query = gmail_query_from_prompt(prompt)
    result_limit = gmail_result_limit(prompt)
    try:
        messages = GMAIL.search(query, max_results=result_limit)
    except GmailGatewayError as exc:
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            f"Gmail could not be checked: {exc}",
            "Nancy",
            "gmail_unavailable",
            response_provider="veridex_gmail_router",
        )
    return local_chat_response(
        workspace_id,
        session_id,
        user_message,
        gmail_messages_text(messages),
        "Nancy",
        "gmail_search",
        response_provider="veridex_gmail_router",
        message_metadata={
            "message_kind": "gmail_search",
            "gmail": {
                "provider": "gmail_api",
                "query": query,
                "result_count": len(messages),
                "requested_limit": result_limit,
                "messages": gmail_message_metadata(messages),
            },
        },
    )


def navigator_intervention_response(
    workspace_id: str,
    session_id: str,
    user_message: Dict[str, Any],
    result: Dict[str, Any],
    attempted_action: str,
    *,
    evidence: Any = None,
) -> Dict[str, Any]:
    incident = None
    if result.get("incident"):
        incident = STORE.append_governance_incident(
            workspace_id,
            session_id,
            gate_ids=result.get("gate_ids") or [],
            attempted_action=attempted_action,
            reason=str(result.get("reason") or ""),
            evidence=evidence,
        )
    pending = result.get("pending") if isinstance(result.get("pending"), dict) else {}
    if pending:
        STORE.set_pending_governance(workspace_id, session_id, pending)
    incident_id = str((incident or {}).get("incident_id") or "")
    return local_chat_response(
        workspace_id,
        session_id,
        user_message,
        intervention_text(result, incident_id),
        "Navigator",
        "governance_intervention",
        response_provider="veridex_governance",
        governance=governance_status(workspace_id, session_id),
        navigator_activation={
            "activated": True,
            "visibility": "VISIBLE",
            "mode": "intervention",
            "reason": result.get("reason"),
        },
        gate_ids=result.get("gate_ids") or [],
        blocked=True,
        requirements=result.get("requirements") or [],
        incident_id=incident_id,
        message_metadata={
            "message_kind": "navigator_intervention",
            "navigator_activation": {
                "activated": True,
                "visibility": "VISIBLE",
                "mode": "intervention",
            },
            "gate_ids": result.get("gate_ids") or [],
            "blocked": True,
            "requirements": result.get("requirements") or [],
            "incident_id": incident_id,
        },
    )


def is_date_search_correction(result: Dict[str, Any], task_type: str) -> bool:
    return (
        str(task_type or "") in {"search_synthesis", "search_deep"}
        and "CURRENT-DATE-SEARCH-GATE" in (result.get("gate_ids") or [])
    )


def date_search_retry_request(
    original_request: Dict[str, Any],
    candidate_result: Dict[str, Any],
    gate_result: Dict[str, Any],
) -> Dict[str, Any]:
    context = dict(original_request.get("context") or {})
    context["navigator_date_correction"] = {
        "prior_draft": str(candidate_result.get("text") or ""),
        "blocked_reason": str(gate_result.get("reason") or ""),
        "requirements": list(gate_result.get("requirements") or []),
    }
    return {
        **original_request,
        "system_prompt": (
            f"{str(original_request.get('system_prompt') or '').rstrip()} "
            "Navigator rejected the first draft because it placed a past date in an upcoming classification. "
            "Rewrite the answer once using the same governed evidence. Do not bypass or argue with the gate. "
            "Use a clearly labeled 'Upcoming shows' section only for dates on or after the supplied current local date. "
            "Put older dates under 'Past shows' and dates without a verified year under 'Date needs confirmation'. "
            "Preserve relevant past-show evidence unless the user's governed event_time_scope is upcoming_only. "
            "Do not infer a year that the evidence does not state. Do not describe this internal correction process."
        ),
        "context": context,
    }


def unclassified_google_result_text(search: Dict[str, Any], current_date: str, reason: str) -> str:
    lines = [line.strip() for line in str(search.get("result_text") or "").splitlines() if line.strip()]
    excerpt = "\n".join(lines)[:7000].rstrip()
    return "\n".join(
        [
            "Google search completed, but Navigator could not safely classify every event date after one correction attempt.",
            f"Current local date: {current_date}.",
            f"Classification issue: {reason}",
            "The Google-indexed excerpts below are preserved as unclassified source evidence. Dates may describe past or future shows; no date is being labeled upcoming here.",
            "",
            excerpt or "Google returned no visible result text.",
        ]
    )


def google_search_evidence(search: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "google_browser_search",
        "status": "completed",
        "provider": "google_chrome_profile",
        "query": search.get("query"),
        "searched_at": search.get("searched_at"),
        "profile_email": search.get("profile_email"),
        "result_count": len(search.get("links") or []),
        "opened_source_count": len(search.get("opened_sources") or []),
        "opened_sources": [
            {
                "url": row.get("url"),
                "title": row.get("title") or row.get("page_title"),
                "status": row.get("status"),
            }
            for row in (search.get("opened_sources") or [])[:5]
            if isinstance(row, dict)
        ],
    }


def request_cancelled_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    workspace_id = str(payload.get("workspace_id") or "")
    session_id = str(payload.get("session_id") or "")
    request_id = str(payload.get("request_id") or "")
    session = STORE.find_session(session_id)
    user_message = payload.get("_persisted_user_message")
    if not isinstance(user_message, dict):
        user_message = STORE.append_message(
            workspace_id or str(session["workspace_id"]),
            session_id,
            "user",
            str(payload.get("text") or "Stopped request"),
            speaker="You",
            request_id=request_id,
        )
    return local_chat_response(
        workspace_id or str(session["workspace_id"]),
        session_id,
        user_message,
        "Stopped by you.",
        "System",
        "request_cancelled",
        response_provider="veridex_router",
        cancelled=True,
        request_id=request_id,
        message_metadata={"message_kind": "system_notice", "cancelled": True, "request_id": request_id},
    )


def request_failed_response(payload: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
    user_message = payload.get("_persisted_user_message")
    if not isinstance(user_message, dict):
        raise exc
    workspace_id = str(payload.get("workspace_id") or user_message.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or user_message.get("session_id") or "").strip()
    request_id = str(payload.get("request_id") or user_message.get("request_id") or "").strip()
    if not workspace_id or not session_id:
        session = STORE.find_session(session_id)
        workspace_id = workspace_id or str(session["workspace_id"])
    detail = " ".join(str(exc).split())
    if len(detail) > 700:
        detail = detail[:686].rstrip() + " ... [trimmed]"
    text = f"Codex request failed before a response could be completed. Error: {detail}"
    result = local_chat_response(
        workspace_id,
        session_id,
        user_message,
        text,
        "System",
        "request_failed",
        response_provider="veridex_router",
        failed=True,
        request_id=request_id,
        message_metadata={
            "message_kind": "request_failed",
            "failed": True,
            "request_id": request_id,
            "error": detail,
        },
    )
    result["ok"] = False
    return result


def run_chat_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    request = dict(payload)
    request_id = str(request.get("request_id") or f"req_{uuid.uuid4().hex[:12]}").strip()
    session_id = str(request.get("session_id") or "").strip()
    active = ACTIVE_REQUESTS.begin(request_id, session_id)
    request["request_id"] = request_id
    request["_cancel_event"] = active.cancelled
    try:
        result = chat_response(request)
    except RequestCancelled:
        result = request_cancelled_response(request)
    except Exception as exc:
        result = request_failed_response(request, exc)
    finally:
        ACTIVE_REQUESTS.finish(request_id)
    result["request_id"] = request_id
    return result


def room_change_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    workspace_id = str(payload.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    room_id = str(payload.get("room_id") or "").strip()
    if not session_id:
        raise ValueError("session_id is required")
    session = STORE.find_session(session_id)
    workspace_id = workspace_id or str(session["workspace_id"])
    transition = STORE.set_room(workspace_id, session_id, room_id)
    if transition["previous_room"] != transition["active_room"]:
        STORE.append_message(
            workspace_id,
            session_id,
            "system",
            f"Entered {transition['room_title']}. {transition['active_persona']} is active.",
            speaker="System",
            task_type="room_navigation",
        )
    return {
        **state_response(STORE.bootstrap(workspace_id, session_id)),
        "room_transition": transition,
        "route": {
            "provider": "veridex_router",
            "model": "deterministic",
            "reasoning_effort": "none",
            "task_type": "room_navigation",
        },
    }


def chat_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    cancel_event = payload.get("_cancel_event")
    if not session_id:
        raise ValueError("session_id is required")
    session = STORE.find_session(session_id)
    workspace_id = workspace_id or str(session["workspace_id"])
    structured_email_draft = normalize_email_draft(payload.get("email_draft"))
    attachment_ids = (
        structured_email_draft.get("attachment_ids", [])
        if structured_email_draft
        else payload.get("attachment_ids") if isinstance(payload.get("attachment_ids"), list) else []
    )
    attachments = STORE.resolve_files(workspace_id, session_id, attachment_ids)
    if len(attachments) != len(set(str(file_id) for file_id in attachment_ids)):
        raise ValueError("one or more attached files are unavailable in this session")
    if structured_email_draft:
        validate_email_attachments(attachments)
    if not text and not attachments and not structured_email_draft:
        raise ValueError("text or an attached file is required")
    user_prompt = text or (
        f"Nancy, compose email to {', '.join(structured_email_draft['to'])}"
        if structured_email_draft
        else "Review the attached file or files and summarize what is important."
    )
    active_room = str(session.get("active_room") or "lobby")
    active_persona = str(session.get("active_persona") or "Receptionist")
    if structured_email_draft and (active_room != "my_office" or active_persona != "Nancy"):
        raise ValueError("structured email drafts are available only with Nancy in My Office")
    room = room_by_id(active_room) or room_by_id("lobby")
    room_title = str(room["title"] if room else "Lobby")
    previous = STORE.load_messages(workspace_id, session_id, limit=24)
    public_attachments = [public_file(row) for row in attachments]
    user_message = STORE.append_message(
        workspace_id,
        session_id,
        "user",
        user_prompt,
        speaker="You",
        attachments=public_attachments,
        request_id=request_id,
    )
    payload["_persisted_user_message"] = user_message
    if cancel_event is not None and cancel_event.is_set():
        raise RequestCancelled("The request was stopped by the user.")
    workspace_governance = STORE.ensure_governance_state(workspace_id)
    active_gates = dict(workspace_governance.get("gates") or {})
    pending = STORE.pending_governance(workspace_id, session_id)
    preflight = GOVERNANCE.preflight(user_prompt, active_gates, pending)
    if not preflight.get("allowed"):
        return navigator_intervention_response(
            workspace_id,
            session_id,
            user_message,
            preflight,
            user_prompt,
        )
    if preflight.get("resolved_pending"):
        STORE.clear_pending_governance(workspace_id, session_id)
        resolution = preflight.get("resolution") if isinstance(preflight.get("resolution"), dict) else {}
        if resolution.get("save_authorized"):
            memo = STORE.append_governance_memo(
                workspace_id,
                session_id,
                str(pending.get("original_request") or user_prompt),
            )
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                "SAVE PENDING: GOV-SAVE complete — APP-COMMIT unverified. The workspace-local memo is durable; no ChatGPT product-memory claim is being made.",
                "Navigator",
                "governance_save",
                response_provider="veridex_governance",
                governance=governance_status(workspace_id, session_id),
                memo=memo,
                message_metadata={
                    "message_kind": "navigator_governance_answer",
                    "navigator_activation": {
                        "activated": True,
                        "visibility": "VISIBLE",
                        "mode": "governance_save",
                    },
                    "gate_ids": ["SAVE_GATE", "SAVE-APP-COMMIT-VERIFICATION-GATE"],
                    "memo_id": memo["memo_id"],
                },
            )
        if resolution.get("cancelled"):
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                "Persistent save cancelled. Nothing was added to the workspace governance memo store.",
                "Navigator",
                "governance_save_cancelled",
                response_provider="veridex_governance",
                governance=governance_status(workspace_id, session_id),
                message_metadata={
                    "message_kind": "navigator_governance_answer",
                    "navigator_activation": {
                        "activated": True,
                        "visibility": "VISIBLE",
                        "mode": "governance_save_cancelled",
                    },
                    "gate_ids": ["SAVE_GATE"],
                },
            )
    if GOVERNANCE.is_governance_question(user_prompt, active_persona):
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            GOVERNANCE.governance_answer(active_gates),
            "Navigator",
            "governance",
            response_provider="veridex_governance",
            governance=governance_status(workspace_id, session_id),
            message_metadata={
                "message_kind": "navigator_governance_answer",
                "navigator_activation": {
                    "activated": True,
                    "visibility": "VISIBLE",
                    "mode": "governance_answer",
                },
                "gate_ids": GOVERNANCE.status(active_gates).get("active_gate_ids", []),
            },
        )
    governed_prompt = str(preflight.get("effective_text") or user_prompt)
    room_route = route_room_request(governed_prompt) if not attachments else None
    if room_route and room_route["action"] == "directory":
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            room_directory_text(),
            active_persona,
            "room_directory",
            rooms=rooms_payload(),
            attachments=public_attachments,
        )
    if room_route and room_route["action"] == "navigate":
        target = room_route.get("room")
        if not target:
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                f"Room not recognized. Available rooms: {valid_room_titles()}.",
                active_persona,
                "room_navigation",
                rooms=rooms_payload(),
                attachments=public_attachments,
            )
        transition = STORE.set_room(workspace_id, session_id, str(target["id"]))
        moved = transition["previous_room"] != transition["active_room"]
        response_text = (
            f"You're now in {transition['room_title']}. {transition['active_persona']} is active."
            if moved
            else f"You're already in {transition['room_title']}. {transition['active_persona']} is active."
        )
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            response_text,
            str(transition["active_persona"]),
            "room_navigation",
            room_transition=transition,
            rooms=rooms_payload(),
            attachments=public_attachments,
        )
    local_answer = local_fact_text(
        governed_prompt,
        active_room,
        room_title,
        active_persona,
        public_attachments,
        workspace_id,
        session_id,
    )
    if local_answer:
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            local_answer,
            active_persona,
            "local_status",
            attachments=public_attachments,
            governance=governance_status(workspace_id, session_id),
        )
    if structured_email_draft:
        return gmail_chat_response(
            workspace_id,
            session_id,
            user_message,
            governed_prompt,
            draft_override=structured_email_draft,
            attachments=attachments,
        )
    if wants_gmail_route(governed_prompt, workspace_id, session_id) and (
        not attachments or bool(parse_email_send_request(governed_prompt))
    ):
        return gmail_chat_response(
            workspace_id,
            session_id,
            user_message,
            governed_prompt,
            attachments=attachments,
        )
    task_type = classify_task(" ".join([governed_prompt, *[str(row.get("name") or "") for row in attachments]]))
    explicit_google_search = wants_google_search(governed_prompt) or continues_google_search(governed_prompt, previous)
    if explicit_google_search:
        task_type = "search_deep"
    policy = select_model(task_type)
    route_check = GOVERNANCE.validate_model_route(task_type, policy.model, policy.reasoning_effort)
    if not route_check.get("allowed"):
        route_block = {
            "allowed": False,
            "gate_ids": route_check.get("gate_ids") or ["MODEL-ROUTE-GATE"],
            "reason": f"The selected route {policy.model}/{policy.reasoning_effort} is below or different from the governed route.",
            "requirements": [f"Use {route_check.get('expected', {}).get('model')} with {route_check.get('expected', {}).get('reasoning')} reasoning."],
            "incident": True,
        }
        return navigator_intervention_response(workspace_id, session_id, user_message, route_block, governed_prompt)
    context = transcript_context(previous)
    context["attached_files"] = [
        {
            "file_id": row["file_id"],
            "name": row["name"],
            "content_type": row["content_type"],
            "size": row["size"],
            "local_path": row["path"],
        }
        for row in attachments
    ]
    context["computer_access"] = runtime_status()
    context["current_room"] = {
        "id": active_room,
        "title": room_title,
        "active_persona": active_persona,
    }
    context["available_rooms"] = rooms_payload()
    context["governance"] = governance_status(workspace_id, session_id)
    context["persistent_workspace_memos"] = STORE.list_governance_memos(workspace_id)
    context["current_local_date"] = datetime.now().astimezone().date().isoformat()
    context["event_time_scope"] = (
        "upcoming_only"
        if re.search(r"\b(?:upcoming|future|next)\s+(?:show|shows|concert|concerts|date|dates|event|events)\b", governed_prompt, re.IGNORECASE)
        else "all_relevant_dates"
    )
    google_browser_search: Dict[str, Any] = {}
    if explicit_google_search:
        try:
            google_browser_search = search_google(governed_prompt, previous, cancel_event=cancel_event)
        except GoogleChromeSearchError as exc:
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                f"Google browser search could not be completed: {exc} No substitute search was performed.",
                active_persona,
                "google_search_unavailable",
                response_provider="veridex_google_router",
                google_search={"provider": "google_chrome_profile", "status": "failed", "error": str(exc)},
                governance=governance_status(workspace_id, session_id),
            )
        context["google_browser_search"] = google_browser_search
    artifact_required = GOVERNANCE.requires_file_artifact(governed_prompt, task_type)
    artifact_output_dir = (
        STORE.prepare_generated_output_dir(workspace_id, session_id, user_message["message_id"])
        if artifact_required
        else None
    )
    if artifact_output_dir:
        context["required_artifact_output_dir"] = str(artifact_output_dir)
        context["artifact_storage_policy"] = {
            "handoff_dir": str(artifact_output_dir),
            "canonical_dir": str(STORE.generated_files_dir(workspace_id, active_room)),
            "kind": "generated_image",
            "scope": "room",
            "scope_ref": active_room,
            "owner": "veridex",
            "rule": "Write final generated image files to handoff_dir only. Veridex will verify, ledger, and move them to canonical_dir before reporting them to the user.",
        }
    pre_codex_file_ids = {str(row.get("file_id") or "") for row in STORE.list_files(workspace_id, session_id)}
    codex_request = {
        "task_type": task_type,
        "system_prompt": (
            f"You are the {active_persona}, the Veridex assistant in {room_title}. "
            f"The active room is {room_title}; do not claim the user is in another room. "
            "The governed context contains the complete available-room directory. Never say room controls or room names are unavailable. "
            "When asked to find local files, use the available shell tools and report only verified paths. "
            "Attached files are saved locally and their exact paths are supplied in governed context. "
            "Use the governed context for continuity, but do not claim actions that were not performed."
        ),
        "user_prompt": governed_prompt,
        "context": context,
        "attachment_paths": [row["path"] for row in attachments],
        "artifact_output_dir": str(artifact_output_dir) if artifact_output_dir else "",
        "cancel_event": cancel_event,
    }
    try:
        if should_use_gemini_route(
            active_room=active_room,
            active_persona=active_persona,
            task_type=task_type,
            prompt=governed_prompt,
            attachments=public_attachments,
            explicit_google_search=explicit_google_search,
        ):
            try:
                result = invoke_gemini({**codex_request, "task_type": "lobby_conversation"})
            except RequestCancelled:
                raise
            except Exception:
                result = invoke_codex(codex_request)
        else:
            result = invoke_codex(codex_request)
    except RequestCancelled:
        raise
    except Exception as exc:
        if not google_browser_search:
            raise
        evidence_row = google_search_evidence(google_browser_search)
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            unclassified_google_result_text(
                google_browser_search,
                context["current_local_date"],
                f"Codex synthesis was unavailable: {exc}",
            ),
            active_persona,
            "search_evidence_unclassified",
            response_provider="veridex_google_router",
            fallback_used=True,
            google_search=google_browser_search,
            governance=governance_status(workspace_id, session_id),
            message_metadata={
                "message_kind": "room_persona_response",
                "governance_checked": True,
                "execution_evidence": [evidence_row],
                "navigator_activation": {
                    "activated": True,
                    "visibility": "VISIBLE",
                    "mode": "unclassified_evidence_fallback",
                    "gate_ids": ["CURRENT-DATE-SEARCH-GATE"],
                },
                "gate_ids": ["CURRENT-DATE-SEARCH-GATE"],
            },
        )
    evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []
    if google_browser_search:
        evidence.append(google_search_evidence(google_browser_search))
    generated_rows = (
        STORE.import_generated_artifacts(workspace_id, session_id, artifact_output_dir)
        if artifact_output_dir
        else []
    )
    if artifact_output_dir:
        generated_rows.extend(
            STORE.verified_new_generated_files(
                workspace_id,
                session_id,
                pre_codex_file_ids,
                active_room,
            )
        )
    generated_rows = list({str(row.get("file_id")): row for row in generated_rows}.values())
    generated_artifacts = [public_file(row, include_path=True) for row in generated_rows]
    evidence.extend(
        {
            "type": "file_artifact",
            "status": "completed",
            **artifact,
        }
        for artifact in generated_artifacts
    )
    postflight = GOVERNANCE.postflight(
        str(result.get("text") or ""),
        evidence,
        request_text=governed_prompt,
        task_type=task_type,
        generated_artifacts=generated_artifacts,
        current_date=context["current_local_date"],
        required_search_provider="google_chrome_profile" if explicit_google_search else "",
    )
    navigator_correction: Dict[str, Any] = {}
    if not postflight.get("allowed") and is_date_search_correction(postflight, task_type):
        result = invoke_codex(date_search_retry_request(codex_request, result, postflight))
        retry_evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []
        evidence.extend(retry_evidence)
        postflight = GOVERNANCE.postflight(
            str(result.get("text") or ""),
            evidence,
            request_text=governed_prompt,
            task_type=task_type,
            generated_artifacts=generated_artifacts,
            current_date=context["current_local_date"],
            required_search_provider="google_chrome_profile" if explicit_google_search else "",
        )
        if postflight.get("allowed"):
            navigator_correction = {
                "activated": True,
                "visibility": "VISIBLE",
                "mode": "automatic_correction",
                "gate_ids": ["CURRENT-DATE-SEARCH-GATE"],
                "reason": "A past date was removed from the upcoming classification before delivery.",
            }
        elif is_date_search_correction(postflight, task_type) and google_browser_search:
            result = {
                **result,
                "provider": "veridex_google_router",
                "model": "deterministic",
                "reasoning_effort": "none",
                "task_type": "search_evidence_unclassified",
                "text": unclassified_google_result_text(
                    google_browser_search,
                    context["current_local_date"],
                    str(postflight.get("reason") or "Date classification remained inconsistent."),
                ),
            }
            postflight = {"allowed": True, "evidence": evidence, "generated_artifacts": generated_artifacts}
            navigator_correction = {
                "activated": True,
                "visibility": "VISIBLE",
                "mode": "unclassified_evidence_fallback",
                "gate_ids": ["CURRENT-DATE-SEARCH-GATE"],
                "reason": "Google evidence was preserved without assigning an unsafe past/future classification.",
            }
        if navigator_correction:
            STORE.append_message(
                workspace_id,
                session_id,
                "assistant",
                (
                    "Navigator corrected a stale event-date classification before delivery. Upcoming and past dates were reclassified using the current local date."
                    if navigator_correction["mode"] == "automatic_correction"
                    else "Navigator preserved the completed Google search as unclassified source evidence because date classification remained inconsistent."
                ),
                speaker="Navigator",
                provider="veridex_governance",
                model="deterministic",
                reasoning_effort="none",
                task_type="governance_correction",
                message_kind="navigator_correction",
                navigator_activation=navigator_correction,
                gate_ids=["CURRENT-DATE-SEARCH-GATE"],
                blocked=False,
            )
    if not postflight.get("allowed"):
        return navigator_intervention_response(
            workspace_id,
            session_id,
            user_message,
            postflight,
            governed_prompt,
            evidence={"candidate_response": result.get("text"), "execution_evidence": evidence},
        )
    response_text = str(result["text"])
    if generated_artifacts:
        response_text = f"{response_text.rstrip()}\n\n{generated_artifact_report(generated_artifacts)}"
    assistant_message = STORE.append_message(
        workspace_id,
        session_id,
        "assistant",
        response_text,
        speaker=active_persona,
        provider=result["provider"],
        model=result["model"],
        reasoning_effort=result["reasoning_effort"],
        task_type=result["task_type"],
        message_kind="room_persona_response",
        governance_checked=True,
        navigator_activation=navigator_correction,
        gate_ids=navigator_correction.get("gate_ids") if navigator_correction else [],
        execution_evidence=evidence,
        generated_artifacts=generated_artifacts,
        request_id=request_id,
    )
    return {
        "ok": True,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "user_message": user_message,
        "message": assistant_message,
        "provider": result["provider"],
        "model": result["model"],
        "reasoning_effort": result["reasoning_effort"],
        "task_type": result["task_type"],
        "fallback_used": result["task_type"] == "search_evidence_unclassified",
        "attachments": public_attachments,
        "generated_artifacts": generated_artifacts,
        "governance": governance_status(workspace_id, session_id),
        **runtime_status(),
    }


TOOLS = [
    {"name": "office.session_info", "description": "Read the active standalone session."},
    {"name": "office.workspace_list", "description": "List local workspaces."},
    {"name": "office.session_create", "description": "Create a session in a workspace."},
    {"name": "office.transcript_get", "description": "Read a session transcript."},
    {"name": "office.room_list", "description": "List available governed rooms and personas."},
    {"name": "office.room_set", "description": "Explicitly change the active room for one session."},
    {"name": "office.gmail_status", "description": "Check whether Veridex's local Gmail integration is connected."},
    {"name": "office.gmail_search", "description": "Search Gmail metadata using the connected veridexcorp@gmail.com account."},
    {"name": "office.gmail_send", "description": "Send Gmail, including session attachments when provided, only when confirm=true; otherwise return a confirmation requirement."},
    {"name": "office.contact_list", "description": "List or search Nancy's local Gmail address book."},
    {"name": "office.contact_save", "description": "Create or update one local address-book contact."},
    {"name": "office.contact_sync", "description": "Import recipients from the 500 most recent Sent messages."},
    {"name": "office.gmail_delivery_check", "description": "Check returned Gmail delivery failures and create Nancy alerts."},
    {"name": "office.governance_status", "description": "Read Navigator status, rule source, gates, and pending requirements."},
    {"name": "office.governance_incident_list", "description": "List append-only governance incidents for a workspace."},
    {"name": "office.compliance_check", "description": "Run a deterministic compliance status check."},
]


class VeridexHandler(BaseHTTPRequestHandler):
    server_version = "CodexVeridex/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _raw_body(self, maximum: int) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("file is empty")
        if length > maximum:
            raise ValueError(f"file exceeds the {maximum // (1024 * 1024)} MB upload limit")
        return self.rfile.read(length)

    def _legacy_authorized(self) -> bool:
        expected = str(os.environ.get("VERIDEX_CODEX_TOKEN") or "").strip()
        if not expected:
            return True
        return self.headers.get("Authorization") == f"Bearer {expected}"

    def _serve_asset(self, route: str) -> None:
        relative = "index.html" if route in {"/", "/chat"} else route.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._json({"ok": True, "service": "codex2veridex", "data_root": str(DATA_ROOT), **runtime_status()})
            elif parsed.path == "/api/bootstrap":
                self._json(state_response(STORE.ensure_default()))
            elif parsed.path == "/api/state":
                self._json(
                    state_response(
                        STORE.bootstrap(
                            str(query.get("workspace_id", [""])[0]),
                            str(query.get("session_id", [""])[0]),
                        )
                    )
                )
            elif parsed.path == "/api/messages":
                self._json(
                    {
                        "messages": STORE.load_messages(
                            str(query.get("workspace_id", [""])[0]),
                            str(query.get("session_id", [""])[0]),
                        )
                    }
                )
            elif parsed.path == "/api/contacts":
                self._json({
                    "contacts": GMAIL.list_contacts(str(query.get("q", [""])[0])),
                    "sync": GMAIL.contact_sync_status(),
                })
            elif parsed.path == "/api/art/images":
                workspace_id = str(query.get("workspace_id", [""])[0]).strip()
                self._json({
                    "images": [
                        public_art_image(row)
                        for row in STORE.list_generated_images(workspace_id, "art_department")
                    ]
                })
            elif parsed.path == "/api/room/files":
                workspace_id = str(query.get("workspace_id", [""])[0]).strip()
                room_id = room_file_library_id(query.get("room_id", [""])[0])
                self._json({
                    "files": [
                        public_room_file(row)
                        for row in STORE.list_room_files(workspace_id, room_id)
                    ]
                })
            elif parsed.path == "/api/mail/alerts":
                workspace_id = str(query.get("workspace_id", [""])[0]).strip()
                session_id = str(query.get("session_id", [""])[0]).strip()
                self._json({"alerts": delivery_alerts(workspace_id, session_id)})
            elif parsed.path == "/api/files/content":
                workspace_id = str(query.get("workspace_id", [""])[0]).strip()
                session_id = str(query.get("session_id", [""])[0]).strip()
                file_id = str(query.get("file_id", [""])[0]).strip()
                matches = STORE.resolve_files(workspace_id, session_id, [file_id])
                if not matches:
                    raise KeyError("Unknown file")
                row = matches[0]
                body = Path(str(row["path"])).read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", str(row.get("content_type") or "application/octet-stream"))
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", f'inline; filename="{Path(str(row.get("name") or "file")).name}"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/governance":
                workspace_id = str(query.get("workspace_id", [""])[0])
                session_id = str(query.get("session_id", [""])[0])
                self._json({"governance": governance_status(workspace_id, session_id)})
            elif parsed.path == "/api/governance/incidents":
                workspace_id = str(query.get("workspace_id", [""])[0])
                self._json({"incidents": STORE.list_governance_incidents(workspace_id)})
            elif parsed.path == "/tools":
                if not self._legacy_authorized():
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                else:
                    self._json({"tools": TOOLS})
            else:
                self._serve_asset(parsed.path)
        except KeyError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/files":
                query = parse_qs(parsed.query)
                workspace_id = str(query.get("workspace_id", [""])[0]).strip()
                session_id = str(query.get("session_id", [""])[0]).strip()
                filename = str(query.get("name", [""])[0]).strip()
                content = self._raw_body(MAX_UPLOAD_BYTES)
                saved = STORE.save_file(
                    workspace_id,
                    session_id,
                    filename,
                    content,
                    str(self.headers.get("Content-Type") or "application/octet-stream"),
                )
                self._json({"file": saved, "files": STORE.list_files(workspace_id, session_id)}, HTTPStatus.CREATED)
                return
            payload = self._body()
            if parsed.path == "/api/contacts/save":
                self._json({"contact": GMAIL.save_contact(payload), "contacts": GMAIL.list_contacts()})
            elif parsed.path == "/api/contacts/delete":
                self._json({
                    "deleted": GMAIL.delete_contact(str(payload.get("contact_id") or "")),
                    "contacts": GMAIL.list_contacts(),
                })
            elif parsed.path == "/api/art/images/attach":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                session_id = str(payload.get("session_id") or "").strip()
                linked = STORE.link_generated_image(
                    workspace_id,
                    session_id,
                    str(payload.get("file_id") or ""),
                    "art_department",
                )
                self._json({
                    "file": public_file(linked),
                    "files": [public_file(row) for row in STORE.list_files(workspace_id, session_id)],
                })
            elif parsed.path == "/api/room/files/attach":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                session_id = str(payload.get("session_id") or "").strip()
                room_id = room_file_library_id(payload.get("room_id"))
                linked = STORE.link_room_file(
                    workspace_id,
                    session_id,
                    str(payload.get("file_id") or ""),
                    room_id,
                )
                self._json({
                    "file": public_file(linked),
                    "files": [public_file(row) for row in STORE.list_files(workspace_id, session_id)],
                })
            elif parsed.path == "/api/contacts/sync":
                self._json(GMAIL.sync_contacts(max_messages=500))
            elif parsed.path == "/api/mail/check-delivery":
                self._json(
                    check_delivery_alerts(
                        str(payload.get("workspace_id") or ""),
                        str(payload.get("session_id") or ""),
                    )
                )
            elif parsed.path == "/api/mail/alerts/resolve":
                GMAIL.resolve_delivery_failure(str(payload.get("failure_id") or ""))
                self._json(
                    {
                        "ok": True,
                        "alerts": delivery_alerts(
                            str(payload.get("workspace_id") or ""),
                            str(payload.get("session_id") or ""),
                        ),
                    }
                )
            elif parsed.path == "/api/workspaces":
                workspace = STORE.create_workspace(str(payload.get("label") or "Workspace"))
                session = STORE.create_session(workspace["workspace_id"], "New session")
                self._json(state_response(STORE.bootstrap(workspace["workspace_id"], session["session_id"])), HTTPStatus.CREATED)
            elif parsed.path == "/api/sessions":
                session = STORE.create_session(
                    str(payload.get("workspace_id") or ""),
                    str(payload.get("title") or "New session"),
                )
                self._json(state_response(STORE.bootstrap(session["workspace_id"], session["session_id"])), HTTPStatus.CREATED)
            elif parsed.path == "/api/rooms":
                self._json(room_change_response(payload))
            elif parsed.path == "/api/chat/cancel":
                request_id = str(payload.get("request_id") or "").strip()
                session_id = str(payload.get("session_id") or "").strip()
                if not request_id:
                    self._json({"error": "request_id is required"}, HTTPStatus.BAD_REQUEST)
                    return
                # The stop click can race the chat POST by a few milliseconds.
                # Briefly wait for registration so the user's first click wins.
                cancelled = ACTIVE_REQUESTS.cancel(request_id, session_id, wait_seconds=0.75)
                self._json({"ok": True, "request_id": request_id, "cancel_requested": cancelled})
            elif parsed.path in {"/api/chat", "/request"}:
                if parsed.path == "/request" and not self._legacy_authorized():
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                result = run_chat_request(payload)
                if parsed.path == "/request":
                    result = {
                        "content": [{"type": "text", "text": result["message"]["text"]}],
                        "structuredContent": result,
                    }
                self._json(result)
            elif parsed.path == "/call":
                if not self._legacy_authorized():
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                self._json(self._call_tool(payload))
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _call_tool(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tool = str(payload.get("tool") or "")
        args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        if tool == "office.session_info":
            session = STORE.find_session(str(args.get("session_id") or ""))
            value = dict(session)
        elif tool == "office.workspace_list":
            value = {"workspaces": STORE.list_workspaces()}
        elif tool == "office.session_create":
            value = STORE.create_session(str(args.get("workspace_id") or ""), str(args.get("title") or "New session"))
        elif tool == "office.transcript_get":
            session = STORE.find_session(str(args.get("session_id") or ""))
            value = {
                "workspace_id": session["workspace_id"],
                "session_id": session["session_id"],
                "entries": STORE.load_messages(session["workspace_id"], session["session_id"]),
            }
        elif tool == "office.room_list":
            value = {"rooms": rooms_payload()}
        elif tool == "office.room_set":
            value = room_change_response(args)
        elif tool == "office.gmail_status":
            value = GMAIL.connection_status()
        elif tool == "office.gmail_search":
            value = {
                "query": str(args.get("query") or "in:inbox"),
                "messages": GMAIL.search(str(args.get("query") or "in:inbox"), max_results=int(args.get("max_results") or 10)),
            }
        elif tool == "office.contact_list":
            value = {"contacts": GMAIL.list_contacts(str(args.get("query") or ""))}
        elif tool == "office.contact_save":
            value = {"contact": GMAIL.save_contact(args)}
        elif tool == "office.contact_sync":
            value = GMAIL.sync_contacts(max_messages=500)
        elif tool == "office.gmail_delivery_check":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id)
            value = check_delivery_alerts(str(session.get("workspace_id") or ""), session_id)
        elif tool == "office.gmail_send":
            recipients = EMAIL_ADDRESS_RE.findall(" ".join(str(value) for value in args.get("to", []))) if isinstance(args.get("to"), list) else EMAIL_ADDRESS_RE.findall(str(args.get("to") or ""))
            subject = str(args.get("subject") or "")
            body = str(args.get("body") or "")
            attachment_ids = args.get("attachment_ids") if isinstance(args.get("attachment_ids"), list) else []
            resolved_attachments: list[Dict[str, Any]] = []
            if attachment_ids:
                session_id = str(args.get("session_id") or "")
                session = STORE.find_session(session_id)
                workspace_id = str(args.get("workspace_id") or session.get("workspace_id") or "")
                resolved_attachments = STORE.resolve_files(workspace_id, session_id, attachment_ids)
                if len(resolved_attachments) != len(set(str(file_id) for file_id in attachment_ids)):
                    raise ValueError("one or more email attachments are unavailable in this session")
                validate_email_attachments(resolved_attachments)
            if not args.get("confirm"):
                value = {
                    "status": "confirmation_required",
                    "to": recipients,
                    "subject": subject,
                    "body": body,
                    "attachments": [public_file(row) for row in resolved_attachments],
                }
            else:
                send_context = {
                    "workspace_id": str(args.get("workspace_id") or ""),
                    "session_id": str(args.get("session_id") or ""),
                }
                sent = (
                    GMAIL.send(recipients, subject, body, resolved_attachments, context=send_context)
                    if resolved_attachments
                    else GMAIL.send(recipients, subject, body, context=send_context)
                )
                value = {
                    "status": "sent",
                    "to": recipients,
                    "subject": subject,
                    "message_id": sent.get("id"),
                    "attachments": [public_file(row) for row in resolved_attachments],
                }
        elif tool == "office.governance_status":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id) if session_id else None
            workspace_id = str(args.get("workspace_id") or (session or {}).get("workspace_id") or "")
            value = governance_status(workspace_id, session_id)
        elif tool == "office.governance_incident_list":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id) if session_id else None
            workspace_id = str(args.get("workspace_id") or (session or {}).get("workspace_id") or "")
            value = {"incidents": STORE.list_governance_incidents(workspace_id)}
        elif tool == "office.compliance_check":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id) if session_id else None
            workspace_id = str(args.get("workspace_id") or (session or {}).get("workspace_id") or "")
            status = governance_status(workspace_id, session_id)
            value = {
                "compliant": not bool(status.get("pending")),
                "navigator_status": status.get("navigator", {}).get("status"),
                "active_gate_ids": status.get("active_gate_ids"),
                "pending": status.get("pending"),
                "registry_sha256": status.get("registry_sha256"),
            }
        else:
            raise ValueError(f"Unknown tool: {tool}")
        return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "structuredContent": value}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run standalone Codex + Veridex")
    parser.add_argument("--host", default=os.environ.get("VERIDEX_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VERIDEX_PORT", "8765")))
    args = parser.parse_args()
    STORE.ensure_default()
    server = ThreadingHTTPServer((args.host, args.port), VeridexHandler)
    print(f"Codex + Veridex running at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
