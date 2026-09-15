"""Local web server for standalone Codex + Veridex chat and document tools."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from art_studio import ArtJobManager, ArtProviderError, ArtStudio, validate_image_bytes
from antiques_department import AntiquesDepartment, ROOM_ID as ANTIQUES_ROOM_ID
from codex_gateway import access_mode, invoke_codex, select_model
from gemini_gateway import gemini_enabled, invoke_gemini
from gmail_gateway import GmailGateway, GmailGatewayError
from google_chrome_search import (
    GoogleChromeSearchError,
    continues_google_search,
    search_ebay_product_research,
    search_google,
    search_google_lens,
    wants_google_search,
)
from request_control import ActiveRequestRegistry, RequestCancelled
from museum_visual_analysis import MuseumVisualAnalyzer
from resume_studio import (
    ResumeStudio,
    export_bundle,
    extract_file_text,
    extract_json_object,
    fetch_job_description,
    keyword_analysis,
    normalize_draft,
    profile_from_text,
    quality_review,
    template_by_id,
    validate_export_bytes,
)
from veridex_core import VeridexStore, classify_task, transcript_context
from veridex_admin import AdminService
from veridex_governance import GovernanceRegistry, intervention_text
from veridex_rooms import ROOMS, configure_room_catalog, room_by_id, room_directory_text, rooms_payload, route_room_request, valid_room_titles


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
ANTIQUES_START_RE = re.compile(r"\b(?:leo[, ]+)?start shopping mode\b", re.IGNORECASE)
ANTIQUES_END_RE = re.compile(r"\b(?:leo[, ]+)?end shopping mode\b", re.IGNORECASE)
ANTIQUES_CONFIRM_RE = re.compile(r"\b(?:confirm|yes|go ahead)(?: the)?(?: google lens| photo upload| research)?\b", re.IGNORECASE)
ANTIQUES_RESEARCH_RE = re.compile(
    r"\b(?:identify|research|value|appraise|what is|who (?:made|painted)|signature|maker(?:'s)? mark|quick research|deep research|buy|pass)\b",
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
ADMIN = AdminService(DATA_ROOT, ROOT, ROOMS, ROOT / "governance" / "navigator_governance_v1.0.0.json")
configure_room_catalog(ADMIN.room_catalog_path)
STORE = VeridexStore(DATA_ROOT, ADMIN.active_governance_path)
RESUME = ResumeStudio(DATA_ROOT, ROOT / "resume_templates")
ART = ArtStudio(DATA_ROOT)
ANTIQUES = AntiquesDepartment(DATA_ROOT)
ART_JOBS = ArtJobManager()
MUSEUM_JOBS = ArtJobManager(workers=1, prefix="museumjob", label="Museum analysis")
MUSEUM_VISUAL = MuseumVisualAnalyzer(DATA_ROOT)
GMAIL = GmailGateway()
MAX_UPLOAD_BYTES = max(1, int(os.environ.get("VERIDEX_MAX_UPLOAD_MB", "50"))) * 1024 * 1024
MAX_GMAIL_ATTACHMENT_BYTES = max(1, int(os.environ.get("VERIDEX_GMAIL_MAX_ATTACHMENT_MB", "20"))) * 1024 * 1024
ACTIVE_REQUESTS = ActiveRequestRegistry()
REMOTE_ACCESS_PATH = DATA_ROOT / "system" / "remote_access.json"
REMOTE_COOKIE = "veridex_remote_session"


def remote_access_state() -> Dict[str, Any]:
    try:
        value = json.loads(REMOTE_ACCESS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict) or not str(value.get("pairing_token") or ""):
        value = {"pairing_token": secrets.token_urlsafe(32), "sessions": [], "created_at": datetime.now().astimezone().isoformat()}
        save_remote_access_state(value)
    return value


def save_remote_access_state(value: Dict[str, Any]) -> None:
    REMOTE_ACCESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REMOTE_ACCESS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(REMOTE_ACCESS_PATH)


def active_governance_registry() -> GovernanceRegistry:
    return GovernanceRegistry(ADMIN.active_governance_path)


def _repository_manifest() -> Dict[str, str]:
    manifest: Dict[str, str] = {}
    excluded = {".git", "data", "__pycache__", ".pytest_cache", "node_modules", ".next"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.relative_to(ROOT).parts):
            continue
        try:
            manifest[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return manifest


def _path_is_allowed(relative: str, allowed_paths: list[str]) -> bool:
    normalized = str(relative or "").replace("\\", "/").strip("/")
    return any(normalized == allowed or normalized.startswith(f"{allowed}/") for allowed in allowed_paths)


def _backup_program_paths(proposal: Dict[str, Any]) -> list[Dict[str, Any]]:
    backup_root = ADMIN.backups_root / str(proposal["proposal_id"]) / "program"
    manifest: list[Dict[str, Any]] = []
    for index, relative in enumerate(proposal["payload"].get("allowed_paths", []), start=1):
        target = (ROOT / relative).resolve()
        backup = backup_root / f"{index:03d}"
        row: Dict[str, Any] = {"path": relative, "existed": target.exists(), "backup_path": str(backup)}
        if target.is_dir():
            shutil.copytree(target, backup)
            row["kind"] = "directory"
        elif target.is_file():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            row["kind"] = "file"
        else:
            row["kind"] = "absent"
            row["backup_path"] = ""
        manifest.append(row)
    return manifest


def run_program_change(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Run one already-approved, path-bounded Veridex code change through Codex."""
    if access_mode() != "full":
        return {"verified": False, "error": "Full computer access is required for an approved program change."}
    payload = dict(proposal.get("payload") or {})
    allowed_paths = list(payload.get("allowed_paths") or [])
    rollback_manifest = _backup_program_paths(proposal)
    before = _repository_manifest()
    prompt = (
        f"Implement the approved Veridex change: {payload.get('title')}.\n\n"
        f"Instructions:\n{payload.get('instructions')}\n\n"
        f"You may edit only these repository-relative paths: {', '.join(allowed_paths)}. "
        "Preserve unrelated work. Do not restart, deploy, commit, reset, or delete outside those paths. "
        "Run the requested tests when possible and report the exact edits and test evidence."
    )
    result = invoke_codex(
        {
            "task_type": "coding",
            "access_mode": "full",
            "system_prompt": "You are Infrastructure Manager implementing an explicitly approved, Navigator-validated Veridex proposal.",
            "user_prompt": prompt,
            "context": {"proposal_id": proposal["proposal_id"], "allowed_paths": allowed_paths},
        }
    )
    after = _repository_manifest()
    changed_paths = sorted({*before, *after} - {path for path in set(before) & set(after) if before[path] == after[path]})
    unexpected = [path for path in changed_paths if not _path_is_allowed(path, allowed_paths)]
    tests: list[Dict[str, Any]] = []
    for command in payload.get("tests", []):
        completed = subprocess.run(
            str(command),
            cwd=ROOT,
            shell=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=300,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        tests.append(
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-2000:],
                "passed": completed.returncode == 0,
            }
        )
    verified = not unexpected and all(row["passed"] for row in tests)
    return {
        "verified": verified,
        "error": "Unexpected files changed outside the approved scope." if unexpected else "",
        "changed_paths": changed_paths,
        "unexpected_paths": unexpected,
        "tests": tests,
        "codex": {
            "provider": result.get("provider"),
            "model": result.get("model"),
            "reasoning_effort": result.get("reasoning_effort"),
            "summary": str(result.get("text") or "")[-6000:],
            "evidence": result.get("evidence") or [],
        },
        "activation": {"status": "restart_required", "automatic_restart": False},
        "rollback": {"supported": True, "manifest": rollback_manifest},
    }


ADMIN.program_runner = run_program_change


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
        "metadata",
    ]
    if include_path:
        keys.append("path")
    return {key: row[key] for key in keys if key in row}


def public_art_image(row: Dict[str, Any]) -> Dict[str, Any]:
    value = public_file(row)
    for key in ("source_session_id", "source_session_title", "created_at"):
        if key in row:
            value[key] = row[key]
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    art = metadata.get("art") if isinstance(metadata.get("art"), dict) else {}
    value.update({key: art[key] for key in (
        "project_id", "parent_file_ids", "provider", "model", "operation", "seed",
        "prompt", "preset_id", "width", "height",
    ) if key in art})
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
        raise ValueError("The Files library is available only in non-Lobby rooms outside Visual Design.")
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
    status = active_governance_registry().status(dict(state.get("gates") or {}), pending)
    status["latest_incident"] = incidents[-1] if incidents else None
    status["persistent_memo_count"] = len(STORE.list_governance_memos(workspace_id))
    return status


def state_response(value: Dict[str, Any]) -> Dict[str, Any]:
    workspace = value.get("workspace") if isinstance(value.get("workspace"), dict) else {}
    session = value.get("session") if isinstance(value.get("session"), dict) else {}
    workspace_id = str(workspace.get("workspace_id") or "")
    session_id = str(session.get("session_id") or "")
    governance = governance_status(workspace_id, session_id) if workspace_id else {}
    antiques = ANTIQUES.bootstrap(workspace_id, session_id, str(session.get("active_room") or "")) if workspace_id and session_id else {}
    return {**value, "runtime": runtime_status(), "governance": governance, "administration": ADMIN.bootstrap(), "antiques": antiques}


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


def resume_context(workspace_id: str, session_id: str, *, require_hr: bool = True) -> Dict[str, Any]:
    workspace = STORE.get_workspace(str(workspace_id or ""))
    session = STORE.find_session(str(session_id or ""))
    if str(session.get("workspace_id") or "") != str(workspace.get("workspace_id") or ""):
        raise KeyError("Session does not belong to workspace")
    if require_hr and str(session.get("active_room") or "") != "hr_department":
        raise ValueError("Resume Studio is available in HR Department.")
    return {"workspace": workspace, "session": session}


def resume_bootstrap(workspace_id: str, session_id: str) -> Dict[str, Any]:
    resume_context(workspace_id, session_id)
    return {
        "profile": RESUME.load_profile(workspace_id),
        "templates": RESUME.list_templates(),
        "projects": RESUME.list_projects(workspace_id),
    }


def resume_source_import(workspace_id: str, session_id: str, file_id: str) -> Dict[str, Any]:
    resume_context(workspace_id, session_id)
    rows = STORE.resolve_files(workspace_id, session_id, [str(file_id or "")])
    if not rows:
        raise KeyError("The selected resume file is unavailable in this session")
    row = rows[0]
    text = extract_file_text(Path(str(row.get("path") or "")))
    source = {
        "file_id": str(row.get("file_id") or ""),
        "artifact_number": int(row.get("artifact_number") or 0),
        "name": str(row.get("name") or ""),
        "sha256": str(row.get("sha256") or ""),
        "imported_at": datetime.now().astimezone().isoformat(),
    }
    return {"text": text, "profile": profile_from_text(text, source), "source": source}


def resume_model_draft(payload: Dict[str, Any]) -> Dict[str, Any]:
    workspace_id = str(payload.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    resume_context(workspace_id, session_id)
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else RESUME.load_profile(workspace_id)
    target_job = payload.get("target_job") if isinstance(payload.get("target_job"), dict) else {}
    if str(target_job.get("url") or "").strip() and not str(target_job.get("description") or "").strip():
        target_job = {**target_job, "description": fetch_job_description(str(target_job.get("url") or ""))}
    resume_type = "federal" if payload.get("resume_type") == "federal" else "private"
    if not str((profile.get("contact") or {}).get("name") or "").strip() and not str(profile.get("career_history") or "").strip():
        raise ValueError("Add or import career information before generating a resume.")
    system_prompt = (
        "You are the HR Manager in Veridex Resume Studio. Produce outstanding, truthful, ATS-readable application materials. "
        "Return only one valid JSON object, with no markdown or commentary. Never invent an employer, role, date, credential, skill, duty, accomplishment, or metric. "
        "You may improve phrasing and organization. If a useful metric is missing, put a coaching suggestion in unconfirmed_claims; do not insert the estimate into a resume bullet. "
        "Every statement in the finished resume must be directly supported by the supplied career profile. Tailor naturally to the job description without keyword stuffing. "
        "For private resumes prefer concise one- or two-page content. For federal resumes retain detailed duties, hours, grades, eligibility, and accomplishments when supplied. "
        "The JSON must use this shape: contact{name,email,phone,location,links[]}, target_title, summary, skills[], "
        "experience[{title,employer,location,start_date,end_date,bullets[]}], education[{credential,school,location,date}], "
        "certifications[], projects[], awards[], federal_details[], cover_letter, linkedin_headline, linkedin_about, "
        "recruiter_email_subject, recruiter_email, interview_talking_points[], unconfirmed_claims[{claim_id,text,reason}]."
    )
    model_input = {
        "resume_type": resume_type,
        "career_profile": profile,
        "target_job": target_job,
        "current_draft": payload.get("current_draft") if isinstance(payload.get("current_draft"), dict) else None,
        "instructions": str(payload.get("instructions") or ""),
    }
    result = invoke_codex({
        "task_type": "resume_generation",
        "system_prompt": system_prompt,
        "user_prompt": json.dumps(model_input, ensure_ascii=False),
        "context": {
            "current_room": {"id": "hr_department", "title": "HR Department", "active_persona": "HR Manager"},
            "governance": governance_status(workspace_id, session_id),
            "artifact_storage_policy": {"owner": "veridex", "rule": "Return structured content only. Veridex owns rendering and export."},
        },
        "attachment_paths": [],
        "artifact_output_dir": "",
    })
    draft = normalize_draft(extract_json_object(str(result.get("text") or "")))
    review = quality_review(draft, str(target_job.get("description") or ""), federal=resume_type == "federal")
    return {
        "draft": draft,
        "review": review,
        "model": result.get("model"),
        "reasoning_effort": result.get("reasoning_effort"),
        "task_type": result.get("task_type"),
    }


def save_resume_exports(payload: Dict[str, Any]) -> Dict[str, Any]:
    workspace_id = str(payload.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    resume_context(workspace_id, session_id)
    draft = normalize_draft(payload.get("draft") or {})
    resume_type = "federal" if payload.get("resume_type") == "federal" else "private"
    templates = RESUME.list_templates()
    template_id = str(payload.get("template_id") or ("federal" if resume_type == "federal" else "ats_classic"))
    template = template_by_id(templates, template_id)
    if not template:
        raise ValueError("Unknown resume template")
    if resume_type not in (template.get("resume_types") or []):
        raise ValueError("The selected template does not support this resume type")
    bundle = export_bundle(draft, resume_type=resume_type, template=template)
    contact_name = str((draft.get("contact") or {}).get("name") or "resume")
    target_title = str(draft.get("target_title") or "resume")
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", f"{contact_name}_{target_title}").strip("_")[:90] or "resume"
    saved: list[Dict[str, Any]] = []
    verification: list[Dict[str, Any]] = []
    content_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
    }
    for generic_name, content in bundle.items():
        suffix = Path(generic_name).suffix.lower()
        part = re.sub(r"[^A-Za-z0-9]+", "_", Path(generic_name).stem).strip("_")
        filename = f"{prefix}_{part}{suffix}"
        facts = validate_export_bytes(generic_name, content)
        saved_row = STORE.save_file(
            workspace_id,
            session_id,
            filename,
            content,
            content_types[suffix],
            source="generated",
            kind="generated_document",
            scope="room",
            scope_ref="hr_department",
            description=f"Resume Studio {resume_type} export using {template.get('name')}.",
            uploaded_by_session_id=session_id,
        )
        saved.append(saved_row)
        verification.append({"file_id": saved_row["file_id"], "name": saved_row["name"], **facts})
    return {"files": [public_file(row, include_path=True) for row in saved], "verification": verification, "review": quality_review(draft, str(payload.get("job_description") or ""), federal=resume_type == "federal")}


def art_context(workspace_id: str, session_id: str) -> Dict[str, Any]:
    workspace = STORE.get_workspace(str(workspace_id or ""))
    session = STORE.find_session(str(session_id or ""))
    if str(session.get("workspace_id") or "") != str(workspace.get("workspace_id") or ""):
        raise KeyError("Session does not belong to workspace")
    if str(session.get("active_room") or "") != "art_department":
        raise ValueError("Art Studio is available only in Visual Design.")
    return {"workspace": workspace, "session": session}


def art_bootstrap(workspace_id: str, session_id: str) -> Dict[str, Any]:
    art_context(workspace_id, session_id)
    value = ART.bootstrap(workspace_id)
    value["providers"] = [codex_art_provider(), *(value.get("providers") or [])]
    return value


def codex_art_provider() -> Dict[str, Any]:
    enabled = str(os.environ.get("VERIDEX_CODEX_ENABLED") or "true").strip().casefold() in {"1", "true", "yes", "on"}
    command = str(os.environ.get("VERIDEX_CODEX_COMMAND") or "codex").strip()
    writable = bool(runtime_status().get("can_write_computer"))
    available = enabled and bool(shutil.which(command))
    if not available:
        detail = "Codex CLI unavailable"
    elif not writable:
        detail = "Requires Full computer access to save verified images"
    else:
        detail = "Existing ChatGPT account route; no API key"
    return {
        "id": "codex",
        "name": "Codex image tools",
        "configured": available and writable,
        "free_only": False,
        "quota_label": detail,
    }


def codex_art_text(prompt: str, *, system_prompt: str, attachment_paths: list[str] | None = None) -> str:
    if not codex_art_provider()["configured"]:
        raise ArtProviderError("codex", codex_art_provider()["quota_label"])
    result = invoke_codex({
        "task_type": "media" if attachment_paths else "conversation",
        "system_prompt": system_prompt,
        "user_prompt": str(prompt or "").strip(),
        "context": {
            "current_room": {"id": "art_department", "title": "Visual Design", "active_persona": "Creative Director"},
            "computer_access": runtime_status(),
        },
        "attachment_paths": list(attachment_paths or []),
        "artifact_output_dir": "",
    })
    text = str(result.get("text") or "").strip()
    if not text:
        raise ArtProviderError("codex", "Codex returned no Art Studio text")
    return text


def codex_art_assets(
    workspace_id: str,
    session_id: str,
    job_id: str,
    payload: Dict[str, Any],
    sources: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    provider = codex_art_provider()
    if not provider["configured"]:
        raise ArtProviderError("codex", str(provider["quota_label"]))
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Describe the image to create")
    variants = max(1, min(4, int(payload.get("variants") or 1)))
    preset_id = str(payload.get("preset_id") or "photography")
    expanded = ART.expanded_prompt(prompt, preset_id)
    aspect = str(payload.get("aspect") or "square")
    operation = str(payload.get("operation") or "generate")
    negative = str(payload.get("negative_prompt") or "").strip()
    output_dir = STORE.prepare_generated_output_dir(workspace_id, session_id, job_id)
    reference_instruction = (
        f"Use the {len(sources)} attached reference image(s) as the source material and follow the requested edit precisely."
        if sources else
        "Create the image from the written direction without requiring reference files."
    )
    user_prompt = (
        f"Create exactly {variants} finished image variant{'s' if variants != 1 else ''} for this Art Studio request.\n"
        f"Direction: {expanded}\n"
        f"Canvas: {aspect}.\n"
        f"Operation: {operation}.\n"
        f"{reference_instruction}\n"
        + (f"Avoid: {negative}.\n" if negative else "")
        + "Return only finished image files through the required artifact handoff."
    )
    result = invoke_codex({
        "task_type": "media",
        "system_prompt": (
            "You are the Art Studio production renderer in Visual Design. "
            "Use the built-in image generation tool and honor the requested subject, style, canvas, variant count, and references. "
            "Do not merely describe an image; create the requested files."
        ),
        "user_prompt": user_prompt,
        "context": {
            "current_room": {"id": "art_department", "title": "Visual Design", "active_persona": "Creative Director"},
            "computer_access": runtime_status(),
            "required_artifact_output_dir": str(output_dir),
            "artifact_storage_policy": {
                "handoff_dir": str(output_dir),
                "canonical_dir": str(STORE.generated_files_dir(workspace_id, "art_department")),
                "kind": "generated_image",
                "scope": "room",
                "scope_ref": "art_department",
                "owner": "veridex",
                "rule": "Write final generated images to handoff_dir only; Veridex validates and stores them.",
            },
        },
        "attachment_paths": [str(row.get("path") or "") for row in sources if str(row.get("path") or "")],
        "artifact_output_dir": str(output_dir),
    })
    assets: list[Dict[str, Any]] = []
    for candidate in sorted(output_dir.rglob("*")):
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_bytes()
            facts = validate_image_bytes(content)
        except (OSError, ValueError):
            continue
        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[facts["format"]]
        assets.append({
            "content": content,
            "extension": extension,
            "content_type": facts["content_type"],
            "metadata": {
                "provider": "codex",
                "model": str(result.get("model") or "Codex image tools"),
                "operation": operation,
                "seed": int(payload.get("seed") or 0) or None,
                "prompt": expanded,
                "preset_id": preset_id,
                "width": facts["width"],
                "height": facts["height"],
                "parent_file_ids": [str(row.get("file_id") or "") for row in sources],
            },
        })
        if len(assets) >= variants:
            break
    if not assets:
        detail = str(result.get("text") or "").strip()
        raise ArtProviderError("codex", detail[:500] or "Codex did not return a verified image file")
    return assets


def art_sources(workspace_id: str, session_id: str, file_ids: list[Any]) -> list[Dict[str, Any]]:
    requested = [str(value or "").strip() for value in file_ids if str(value or "").strip()][:4]
    if not requested:
        return []
    candidates = {
        str(row.get("file_id") or ""): row
        for row in [
            *STORE.list_files(workspace_id, session_id),
            *STORE.list_generated_images(workspace_id, "art_department"),
        ]
    }
    rows: list[Dict[str, Any]] = []
    for file_id in requested:
        row = candidates.get(file_id)
        if not row:
            raise KeyError(f"Unknown Art Studio source image: {file_id}")
        path = Path(str(row.get("path") or ""))
        if not path.is_file():
            raise KeyError(f"Art Studio source image is unavailable: {file_id}")
        content = path.read_bytes()
        facts = validate_image_bytes(content)
        rows.append({
            **row,
            "content": content,
            "content_type": str(row.get("content_type") or facts["content_type"]),
        })
    return rows


def submit_art_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    workspace_id = str(payload.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    art_context(workspace_id, session_id)
    source_ids = payload.get("source_file_ids") if isinstance(payload.get("source_file_ids"), list) else []
    sources = art_sources(workspace_id, session_id, source_ids)
    safe_payload = dict(payload)
    safe_payload.pop("workspace_id", None)
    safe_payload.pop("session_id", None)

    def runner(job_id: str, progress: Any, canceled: Any) -> Dict[str, Any]:
        operation = str(safe_payload.get("operation") or "generate")
        if canceled():
            return {}
        if operation == "improve_prompt":
            progress(35, "Directing prompt")
            prompt = str(safe_payload.get("prompt") or "").strip()
            preset_id = str(safe_payload.get("preset_id") or "photography")
            try:
                text = ART.improve_prompt(prompt, preset_id)
            except ArtProviderError:
                text = codex_art_text(
                    ART.expanded_prompt(prompt, preset_id),
                    system_prompt=(
                        "You are an art director. Rewrite the request as one precise image-generation prompt. "
                        "Preserve every requested subject and constraint; add composition, lighting, material, palette, and camera or medium detail. "
                        "Do not name living artists. Return only the improved prompt."
                    ),
                )
            return {"kind": "text", "text": text}
        if operation == "critique":
            if not sources:
                raise ValueError("Choose an image to critique")
            progress(35, "Reviewing image")
            try:
                text = ART.critique(sources[0])
            except ArtProviderError:
                text = codex_art_text(
                    "Evaluate composition, hierarchy, lighting and color, legibility, visible anatomy or object defects, and professional suitability. Give the three most useful improvements.",
                    system_prompt="You are a concise Art Studio visual critic. Inspect the attached image and report only evidence visible in it.",
                    attachment_paths=[str(sources[0].get("path") or "")],
                )
            return {"kind": "critique", "text": text}
        progress(20, "Preparing image operation")
        if operation in {"remove_background", "resize", "upscale", "crop", "add_text", "collage", "convert"}:
            asset = ART.local.apply(operation, sources, safe_payload.get("options") if isinstance(safe_payload.get("options"), dict) else {})
            assets = [{**asset, "metadata": {
                "provider": "local",
                "model": str(asset.get("model") or "pillow"),
                "operation": operation,
                "parent_file_ids": [str(row.get("file_id") or "") for row in sources],
            }}]
        else:
            progress(35, "Generating variants")
            generation_payload = dict(safe_payload)
            if generation_payload.get("improve_prompt") and not ART.cloudflare.configured() and codex_art_provider()["configured"]:
                if not str(generation_payload.get("prompt") or "").strip():
                    raise ValueError("Describe the image to create")
                generation_payload["prompt"] = codex_art_text(
                    ART.expanded_prompt(str(generation_payload.get("prompt") or ""), str(generation_payload.get("preset_id") or "photography")),
                    system_prompt=(
                        "You are an art director. Rewrite the request as one precise image-generation prompt. "
                        "Preserve every requested subject and constraint; add composition, lighting, material, palette, and camera or medium detail. "
                        "Return only the improved prompt."
                    ),
                )
                generation_payload["improve_prompt"] = False
            try:
                assets = ART.generate(generation_payload, sources)
            except ArtProviderError:
                fallback_model = str(generation_payload.get("model_id") or "auto")
                if fallback_model not in {"auto", "edit"}:
                    raise
                progress(45, "Generating with Codex image tools")
                assets = codex_art_assets(workspace_id, session_id, job_id, generation_payload, sources)
        progress(78, "Verifying outputs")
        files: list[Dict[str, Any]] = []
        prompt_slug = re.sub(r"[^A-Za-z0-9]+", "_", str(safe_payload.get("prompt") or operation)).strip("_")[:50] or "artwork"
        for index, asset in enumerate(assets, start=1):
            if canceled():
                return {}
            content = bytes(asset["content"])
            facts = validate_image_bytes(content)
            art_metadata = {
                **(asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}),
                "project_id": str(safe_payload.get("project_id") or ""),
                "width": facts["width"],
                "height": facts["height"],
                "job_id": job_id,
            }
            filename = f"{prompt_slug}_{index}{str(asset.get('extension') or '.png')}"
            saved = STORE.save_file(
                workspace_id,
                session_id,
                filename,
                content,
                str(asset.get("content_type") or facts["content_type"]),
                source="generated",
                kind="generated_image",
                scope="room",
                scope_ref="art_department",
                description=f"Art Studio {operation} output via {art_metadata.get('provider', 'local')}.",
                uploaded_by_session_id=session_id,
                metadata={"art": art_metadata},
            )
            files.append({**public_art_image(saved), "source_session_id": session_id})
        progress(96, "Updating Visual Design")
        return {"kind": "images", "files": files}

    return ART_JOBS.submit(safe_payload, runner)


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
    if transition["previous_room"] == ANTIQUES_ROOM_ID and transition["active_room"] != ANTIQUES_ROOM_ID:
        ANTIQUES.end_shopping_mode(workspace_id, session_id, "room_exit")
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


def antiques_context(workspace_id: str, session_id: str) -> Dict[str, Any]:
    session = STORE.find_session(session_id)
    if str(session.get("workspace_id") or "") != workspace_id:
        raise KeyError("Session does not belong to workspace")
    if str(session.get("active_room") or "") != ANTIQUES_ROOM_ID:
        raise ValueError("Museum tools are available only in Museum")
    return session


def _antiques_json_result(result: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        value = extract_json_object(str(result.get("text") or ""))
    except Exception:
        value = {}
    return value if isinstance(value, dict) and value else fallback


def _antiques_model_analysis(prompt: str, attachments: list[Dict[str, Any]], task_type: str = "media") -> tuple[Dict[str, Any], Dict[str, Any]]:
    request = {
        "task_type": task_type,
        "system_prompt": (
            "You are Leo, director of the Veridex Museum. Analyze thrift-store art, jewelry, pottery, "
            "vintage kitchenware, and service items conservatively. Separate observation from inference. Never claim "
            "authentication, appraisal, gemstone identity, or precious-metal content from photographs alone. Return only JSON."
        ),
        "user_prompt": prompt,
        "context": {"current_room": {"id": ANTIQUES_ROOM_ID, "title": "Museum", "active_persona": "Leo"}},
        "attachment_paths": [str(row.get("path") or "") for row in attachments],
        "artifact_output_dir": "",
    }
    result = invoke_codex(request)
    return _antiques_json_result(result, {}), result


def _museum_unique_strings(values: Any, limit: int = 30) -> list[str]:
    if not isinstance(values, list):
        return []
    rows = []
    for value in values:
        text = " ".join(str(value or "").split())[:1000]
        if text and text not in rows:
            rows.append(text)
    return rows[:limit]


def _museum_assessment(value: Any, allowed: set[str] | None = None) -> Dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    assessment = " ".join(str(row.get("assessment") or "undetermined").split())[:500]
    if allowed and assessment not in allowed:
        assessment = "undetermined"
    confidence = str(row.get("confidence") or "low").lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    return {
        "assessment": assessment,
        "confidence": confidence,
        "evidence": _museum_unique_strings(row.get("evidence"), 12),
        "limitations": _museum_unique_strings(row.get("limitations"), 12),
    }


def _museum_interpretation(prompt_context: Dict[str, Any], attachments: list[Dict[str, Any]]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    prompt = (
        "Examine the attached original and derived views using the deterministic evidence below. Derived edge, threshold, "
        "and contrast images are processing aids and must not be described as physical details by themselves. Return JSON with: "
        "identification, category, confidence (low|medium|high), observations (array of directly visible facts), interpretations "
        "(array of cautious inferences), medium {assessment,confidence,evidence,limitations}, support with the same shape, "
        "production_method {assessment one of original_hand_applied|print_or_reproduction|mixed_or_embellished|undetermined,"
        "confidence,evidence,limitations}, signature {application one of hand_applied|printed_or_reproduced|obscured|undetermined,"
        "transcription_candidates array,confidence,evidence,limitations}, frame {assessment,confidence,evidence,limitations}, "
        "limitations array, and recommended_next_photos array. Never authenticate, attribute authorship, appraise value, or "
        "infer medium from color alone. A flat frontal photograph cannot establish surface relief.\n\nEvidence:\n"
        + json.dumps(prompt_context, ensure_ascii=False)[:45000]
    )
    value, route = _antiques_model_analysis(prompt, attachments, "media")
    return value if isinstance(value, dict) else {}, route


def submit_museum_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    session = STORE.find_session(session_id)
    workspace_id = str(payload.get("workspace_id") or session.get("workspace_id") or "").strip()
    antiques_context(workspace_id, session_id)
    attachment_ids = list(dict.fromkeys(str(value) for value in payload.get("attachment_ids", []) if str(value).strip()))[:12]
    attachments = STORE.resolve_files(workspace_id, session_id, attachment_ids)
    if not attachments or len(attachments) != len(attachment_ids):
        raise ValueError("Select at least one available Museum photograph")
    if any(not str(row.get("content_type") or "").startswith("image/") for row in attachments):
        raise ValueError("Museum visual analysis accepts image attachments only")
    safe_payload = {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "attachment_ids": attachment_ids,
        "mode": "detailed" if str(payload.get("mode") or "").lower() in {"deep", "detailed"} else "quick",
        "focus": str(payload.get("focus") or "all"),
        "photo_roles": payload.get("photo_roles") if isinstance(payload.get("photo_roles"), dict) else {},
        "regions": payload.get("regions") if isinstance(payload.get("regions"), dict) else {},
        "comparison_pairs": payload.get("comparison_pairs") if isinstance(payload.get("comparison_pairs"), list) else [],
        "notes": str(payload.get("notes") or "")[:4000],
        "case_id": str(payload.get("case_id") or ""),
        "operation": "visual_analysis",
    }

    def runner(job_id: str, progress: Any, cancelled: Any) -> Dict[str, Any]:
        progress(10, "Preparing local visual evidence")
        core = MUSEUM_VISUAL.analyze(
            attachments,
            mode=safe_payload["mode"],
            focus=safe_payload["focus"],
            photo_roles=safe_payload["photo_roles"],
            regions=safe_payload["regions"],
            comparison_pairs=safe_payload["comparison_pairs"],
            progress=progress,
            cancelled=cancelled,
        )
        progress(62, "Saving derived evidence")
        evidence_files = []
        artifact_paths = []
        for artifact in core.pop("artifacts", []):
            if cancelled():
                raise RuntimeError("Museum analysis canceled")
            saved = STORE.save_file(
                workspace_id,
                session_id,
                str(artifact["name"]),
                bytes(artifact["content"]),
                str(artifact["content_type"]),
                source="generated",
                kind="generated_image",
                scope="room",
                scope_ref=ANTIQUES_ROOM_ID,
                description=f"Museum derived evidence: {artifact['label']}",
                uploaded_by_session_id=session_id,
                metadata={"museum_analysis": {
                    "job_id": job_id,
                    "derived": True,
                    "kind": artifact["kind"],
                    "label": artifact["label"],
                    "source_file_id": artifact["source_file_id"],
                    "region_normalized": artifact.get("region_normalized"),
                    "region_pixels": artifact.get("region_pixels"),
                }},
            )
            evidence_files.append(public_file(saved))
            if artifact["kind"] in {"normalized_overview", "region_01", "region_01_contrast", "adaptive_threshold", "local_contrast"}:
                artifact_paths.append({**saved, "path": saved["path"]})
        progress(78, "Interpreting visible evidence")
        model_context = {**core, "notes": safe_payload["notes"]}
        model_attachments = attachments[:4] + artifact_paths[:max(0, 8 - min(4, len(attachments)))]
        route: Dict[str, Any] = {}
        try:
            interpreted, route = _museum_interpretation(model_context, model_attachments)
        except Exception as exc:
            interpreted = {"limitations": [f"Model interpretation was unavailable: {str(exc)[:300]}"]}
        confidence = str(interpreted.get("confidence") or "low").lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = "low"
        signature_value = interpreted.get("signature") if isinstance(interpreted.get("signature"), dict) else {}
        signature_application = str(signature_value.get("application") or "undetermined")
        if signature_application not in {"hand_applied", "printed_or_reproduced", "obscured", "undetermined"}:
            signature_application = "undetermined"
        report = {
            "analysis_version": 1,
            "identification": " ".join(str(interpreted.get("identification") or "Unidentified artwork or object").split())[:500],
            "category": " ".join(str(interpreted.get("category") or "unknown").split())[:120],
            "confidence": confidence,
            "analysis_mode": core["mode"],
            "focus": core["focus"],
            "evidence": {"photos": core["photos"], "matches": core["matches"]},
            "observations": _museum_unique_strings(interpreted.get("observations")),
            "interpretations": _museum_unique_strings(interpreted.get("interpretations")),
            "medium": _museum_assessment(interpreted.get("medium")),
            "support": _museum_assessment(interpreted.get("support")),
            "production_method": _museum_assessment(interpreted.get("production_method"), {"original_hand_applied", "print_or_reproduction", "mixed_or_embellished", "undetermined"}),
            "signature": {
                "application": signature_application,
                "transcription_candidates": _museum_unique_strings(signature_value.get("transcription_candidates"), 10),
                "confidence": str(signature_value.get("confidence") or "low") if str(signature_value.get("confidence") or "low") in {"low", "medium", "high"} else "low",
                "evidence": _museum_unique_strings(signature_value.get("evidence"), 12),
                "limitations": _museum_unique_strings(signature_value.get("limitations"), 12),
            },
            "frame": _museum_assessment(interpreted.get("frame")),
            "recommended_next_photos": core["recommended_next_photos"] + _museum_unique_strings(interpreted.get("recommended_next_photos"), 12),
            "limitations": core["limitations"] + _museum_unique_strings(interpreted.get("limitations"), 20),
            "evidence_artifacts": evidence_files,
            "visual_disclaimer": "Visual evidence only; not authentication, authorship attribution, appraisal, or conservation treatment advice.",
        }
        progress(94, "Saving Museum case revision")
        case = ANTIQUES.save_case(
            workspace_id,
            session_id,
            attachment_ids,
            report,
            core["mode"],
            safe_payload["notes"],
            safe_payload["case_id"],
        )
        return {
            "status": "completed",
            "case": case,
            "report": report,
            "route": {key: route.get(key) for key in ("provider", "model", "reasoning_effort", "task_type")},
        }

    return MUSEUM_JOBS.submit(safe_payload, runner)


def _antiques_source_excerpt(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider": row.get("provider"),
        "query": row.get("query"),
        "searched_at": row.get("searched_at"),
        "page_url": row.get("page_url"),
        "result_text": str(row.get("result_text") or "")[:10000],
        "links": list(row.get("links") or [])[:20],
        "opened_sources": list(row.get("opened_sources") or [])[:5],
    }


def _money(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number >= 0 and number < 100_000_000 else None
    except (TypeError, ValueError):
        return None


def antiques_report_text(case: Dict[str, Any]) -> str:
    report = case.get("latest_report") if isinstance(case.get("latest_report"), dict) else {}
    valuation = report.get("valuation") if isinstance(report.get("valuation"), dict) else {}
    buying = report.get("buying") if isinstance(report.get("buying"), dict) else {}
    frame = report.get("frame") if isinstance(report.get("frame"), dict) else {}
    confidence = str(report.get("confidence") or "low").title()
    lines = [
        f"Antiques case {case.get('case_id')}: {report.get('identification') or case.get('title') or 'Unidentified item'}",
        f"Confidence: {confidence}",
    ]
    if report.get("artist_or_maker"):
        lines.append(f"Artist or maker: {report['artist_or_maker']}")
    if report.get("signature_or_mark"):
        lines.append(f"Signature or mark: {report['signature_or_mark']}")
    if report.get("medium_or_material"):
        lines.append(f"Medium or material: {report['medium_or_material']}")
    low, high = valuation.get("conservative_low"), valuation.get("likely_high")
    if low is not None or high is not None:
        lines.append(f"Resale estimate: {valuation.get('currency', 'USD')} {low if low is not None else '?'}–{high if high is not None else '?'}")
    if buying.get("recommended_max_buy") is not None:
        lines.append(f"Conservative maximum buy: {buying.get('currency', 'USD')} {buying['recommended_max_buy']}")
    if frame:
        lines.append(
            "Frame: " + str(frame.get("assessment") or "Insufficient detail")
            + (f"; estimated resale {frame.get('currency', 'USD')} {frame.get('resale_low')}–{frame.get('resale_high')}" if frame.get("resale_low") is not None else "")
        )
    if report.get("missing_photos"):
        lines.append("Helpful additional photos: " + ", ".join(str(value) for value in report["missing_photos"][:6]))
    lines.append("This is research-supported guidance, not authentication or a professional appraisal.")
    return "\n".join(lines)


def antiques_research(payload: Dict[str, Any], cancel_event: Any = None) -> Dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    session = STORE.find_session(session_id)
    workspace_id = str(payload.get("workspace_id") or session.get("workspace_id") or "").strip()
    antiques_context(workspace_id, session_id)
    attachment_ids = [str(value) for value in payload.get("attachment_ids", []) if str(value).strip()]
    attachments = STORE.resolve_files(workspace_id, session_id, attachment_ids)
    if not attachments or len(attachments) != len(set(attachment_ids)):
        raise ValueError("Attach at least one available item photo for Leo to research")
    if any(not str(row.get("content_type") or "").startswith("image/") for row in attachments):
        raise ValueError("Antiques research currently accepts image attachments only")
    mode = "deep" if str(payload.get("mode") or "").lower() == "deep" else "quick"
    confirmed = bool(payload.get("confirm_external"))
    allowed, consent_basis = ANTIQUES.may_upload_photo(workspace_id, session_id, ANTIQUES_ROOM_ID, confirmed)
    if not allowed:
        pending = ANTIQUES.save_pending_research(workspace_id, session_id, {
            "attachment_ids": attachment_ids,
            "mode": mode,
            "notes": payload.get("notes"),
            "case_id": payload.get("case_id"),
        })
        return {
            "status": "confirmation_required",
            "message": "Leo is ready to send sanitized copies of the selected photos to Google Lens. Confirm this research run, or start shopping mode for continuing consent until you finish.",
            "pending": pending,
            "shopping_mode": ANTIQUES.shopping_status(workspace_id, session_id, ANTIQUES_ROOM_ID),
        }
    ANTIQUES.clear_pending_research(workspace_id, session_id)
    if consent_basis == "shopping_mode":
        ANTIQUES.touch_shopping_mode(workspace_id, session_id, ANTIQUES_ROOM_ID)

    visual_prompt = (
        "Inspect every attached photo. Return JSON with: identification, category, observed_features (array), "
        "artist_or_maker_candidates (array), signature_or_mark, medium_or_material, likely_period, condition_notes "
        "(array), frame_observations (array), missing_photos (array), search_query, and confidence. Do not estimate value yet. "
        f"User notes: {str(payload.get('notes') or '')[:2000]}"
    )
    visual, visual_route = _antiques_model_analysis(visual_prompt, attachments, "media")
    query = " ".join(str(visual.get(key) or "") for key in ("search_query", "identification", "signature_or_mark", "medium_or_material"))
    query = " ".join(query.split())[:500] or "antique vintage item identification sold comparables"
    source_results: list[Dict[str, Any]] = []
    source_errors: list[Dict[str, str]] = []
    lens_limit = min(len(attachments), 4 if mode == "deep" else 2)
    for row in attachments[:lens_limit]:
        sanitized = ANTIQUES.prepare_external_image(workspace_id, str(row["file_id"]), Path(str(row["path"])))
        audit = ANTIQUES.log_external_upload(workspace_id, session_id, "Google Lens", [str(row["file_id"])], consent_basis)
        try:
            lens = search_google_lens(sanitized, cancel_event=cancel_event)
            source_results.append({**_antiques_source_excerpt(lens), "source_id": "google_lens", "upload_id": audit["upload_id"]})
        except GoogleChromeSearchError as exc:
            source_errors.append({"source_id": "google_lens", "error": str(exc), "manual_url": "https://lens.google.com/"})
    searches = [("google", query), ("ebay", query)]
    if mode == "deep":
        searches.extend([
            ("liveauctioneers", f"{query} site:liveauctioneers.com auction results"),
            ("kovels", f"{query} site:kovels.com mark"),
            ("marks_project", f"{query} site:themarksproject.org mark artist"),
            ("smithsonian", f"{query} site:si.edu OR site:americanart.si.edu"),
            ("worthpoint", f"{query} site:worthpoint.com sold price"),
        ])
    for source_id, source_query in searches:
        try:
            found = (
                search_ebay_product_research(source_query, cancel_event=cancel_event)
                if source_id == "ebay"
                else search_google(f"Google search for {source_query}", cancel_event=cancel_event)
            )
            source_results.append({**_antiques_source_excerpt(found), "source_id": source_id})
        except GoogleChromeSearchError as exc:
            manual = {
                "ebay": "https://www.ebay.com/sh/research",
                "liveauctioneers": "https://www.liveauctioneers.com/price-result/",
                "kovels": "https://kovels.com/marks-identification-guide/",
                "marks_project": "https://www.themarksproject.org/search-marks",
                "smithsonian": "https://www.si.edu/collections",
                "worthpoint": "https://www.worthpoint.com/",
            }.get(source_id, "https://www.google.com/")
            source_errors.append({"source_id": source_id, "error": str(exc), "manual_url": manual})

    synthesis_prompt = (
        "Synthesize the visual observations and browser evidence. Sold evidence is stronger than asking prices. Reject mismatched "
        "comparables and explain uncertainty. Return JSON with: identification, category, artist_or_maker, signature_or_mark, "
        "medium_or_material, likely_period, observed_facts (array), sourced_matches (array of objects with claim,url,source), "
        "inferences (array), condition_notes (array), missing_photos (array), confidence (low|medium|high), valuation "
        "{currency,conservative_low,likely_high,comparable_notes}, frame {assessment,currency,resale_low,resale_high,replacement_cost_low,"
        "replacement_cost_high,contribution_notes}, warnings (array). Never claim definitive authentication or appraisal.\n\n"
        + json.dumps({"visual": visual, "sources": source_results, "source_errors": source_errors}, ensure_ascii=False)[:50000]
    )
    report, synthesis_route = _antiques_model_analysis(synthesis_prompt, [], "search_deep")
    if not report:
        report = {
            "identification": visual.get("identification") or "Item requires additional research",
            "category": visual.get("category") or "unknown",
            "artist_or_maker": "",
            "signature_or_mark": visual.get("signature_or_mark") or "",
            "medium_or_material": visual.get("medium_or_material") or "",
            "observed_facts": visual.get("observed_features") or [],
            "condition_notes": visual.get("condition_notes") or [],
            "missing_photos": visual.get("missing_photos") or [],
            "confidence": "low",
            "valuation": {"currency": "USD", "conservative_low": None, "likely_high": None},
            "frame": {"assessment": "; ".join(str(value) for value in visual.get("frame_observations") or [])},
            "warnings": ["Research synthesis was unavailable; no value conclusion was produced."],
        }
    valuation = report.get("valuation") if isinstance(report.get("valuation"), dict) else {}
    valuation["currency"] = str(valuation.get("currency") or ANTIQUES.settings(workspace_id)["currency"])
    report["valuation"] = valuation
    conservative = _money(valuation.get("conservative_low"))
    report["buying"] = (
        ANTIQUES.calculate_max_buy(conservative, payload.get("valuation_overrides") or {}, workspace_id)
        if conservative is not None
        else {"recommended_max_buy": None, "reason": "Insufficient reliable sold-comparable evidence"}
    )
    report["source_errors"] = source_errors
    report["research_mode"] = mode
    report["research_disclaimer"] = "Research-supported estimate only; not authentication or a professional appraisal."
    case = ANTIQUES.save_case(
        workspace_id,
        session_id,
        attachment_ids,
        report,
        mode,
        str(payload.get("notes") or ""),
        str(payload.get("case_id") or ""),
    )
    return {
        "status": "completed",
        "case": case,
        "report": report,
        "sources": source_results,
        "source_errors": source_errors,
        "shopping_mode": ANTIQUES.shopping_status(workspace_id, session_id, ANTIQUES_ROOM_ID),
        "route": {
            "visual": {key: visual_route.get(key) for key in ("provider", "model", "reasoning_effort", "task_type")},
            "synthesis": {key: synthesis_route.get(key) for key in ("provider", "model", "reasoning_effort", "task_type")},
        },
    }


ADMIN_APPROVE_RE = re.compile(r"^\s*(?:approve|confirm)\s+(proposal_[A-Za-z0-9_-]+)(?:\s+again)?\s*$", re.IGNORECASE)
ADMIN_REJECT_RE = re.compile(r"^\s*reject\s+(proposal_[A-Za-z0-9_-]+)(?:\s+because\s+(.+))?\s*$", re.IGNORECASE | re.DOTALL)
ADMIN_ROLLBACK_RE = re.compile(r"^\s*rollback\s+(proposal_[A-Za-z0-9_-]+)\s*$", re.IGNORECASE)
ROOM_CREATE_RE = re.compile(
    r"\b(?:create|add|make)\s+(?:a\s+)?(?:new\s+)?room(?:\s+(?:called|named))?\s+(.+?)(?:\s+with\s+(?:the\s+)?persona\s+(.+))?$",
    re.IGNORECASE,
)
GOVERNANCE_ADD_RE = re.compile(r"\badd\s+(?:a\s+)?(?:new\s+)?(rule|gate)(?:\s+that|\s*:)?\s+(.+)$", re.IGNORECASE | re.DOTALL)
GOVERNANCE_DISABLE_RE = re.compile(r"\bdisable\s+(?:the\s+)?(rule|gate)\s+([A-Za-z0-9_-]+)(?:\s+because\s+(.+))?$", re.IGNORECASE | re.DOTALL)
PROGRAM_MUTATION_RE = re.compile(
    r"\b(?:change|modify|update|fix|edit|implement|refactor|add)\b.{0,100}\b(?:veridex|program|application|app|code|source)\b|"
    r"\b(?:veridex|program|application|app|code|source)\b.{0,100}\b(?:change|modify|update|fix|edit|implement|refactor|add)\b",
    re.IGNORECASE | re.DOTALL,
)


def admin_create_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    if session_id:
        session = STORE.find_session(session_id)
        workspace_id = workspace_id or str(session.get("workspace_id") or "")
        if workspace_id != session.get("workspace_id"):
            raise ValueError("Session does not belong to workspace")
    else:
        session = None
    kind = str(payload.get("kind") or "").lower()
    if kind in {"room", "program"}:
        if not session:
            raise ValueError("session_id is required for Infrastructure administration")
        if str(session.get("active_room") or "") != "infrastructure_room":
            raise ValueError("Room and program proposals must be prepared in Infrastructure Room")
    proposal = ADMIN.create_proposal(
        kind,
        str(payload.get("action") or ""),
        payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        requested_by=str(payload.get("requested_by") or "Local User"),
        workspace_id=workspace_id,
        session_id=session_id,
    )
    return {"status": "awaiting_approval", "proposal": proposal, "administration": ADMIN.bootstrap()}


def admin_apply_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = ADMIN.approve_and_apply(
        str(payload.get("proposal_id") or ""),
        expected_version=int(payload.get("expected_version") or 0),
        confirm=bool(payload.get("confirm")),
        second_confirmation_token=str(payload.get("second_confirmation_token") or ""),
    )
    if result.get("status") in {"confirmation_required", "second_confirmation_required"} and isinstance(result.get("proposal"), dict):
        proposal = dict(result["proposal"])
        proposal.pop("second_confirmation_token", None)
        return {**result, "proposal": proposal, "administration": ADMIN.bootstrap()}
    proposal = dict(result)
    proposal.pop("second_confirmation_token", None)
    return {"status": proposal.get("status"), "proposal": proposal, "administration": ADMIN.bootstrap()}


def maybe_admin_chat_response(
    workspace_id: str,
    session_id: str,
    user_message: Dict[str, Any],
    text: str,
    active_room: str,
    active_persona: str,
) -> Dict[str, Any] | None:
    approve = ADMIN_APPROVE_RE.fullmatch(text)
    if approve:
        proposal = ADMIN.get_proposal(approve.group(1))
        token = str(proposal.get("second_confirmation_token") or "") if proposal.get("status") == "awaiting_second_approval" else ""
        result = ADMIN.approve_and_apply(
            proposal["proposal_id"],
            expected_version=int(proposal.get("base_version") or 0),
            confirm=True,
            second_confirmation_token=token,
        )
        if result.get("status") == "second_confirmation_required":
            message = (
                f"Navigator recorded the first approval for {proposal['proposal_id']}. This change can weaken active governance. "
                f"Review the impact and type `confirm {proposal['proposal_id']} again` to apply it."
            )
        else:
            message = f"Infrastructure applied and verified {proposal['proposal_id']}. The result and rollback evidence are in Administration."
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            message,
            "Navigator" if proposal.get("kind") in {"rule", "gate"} else "Infrastructure Manager",
            "administration_apply",
            response_provider="veridex_admin",
            governance=governance_status(workspace_id, session_id),
            administration=ADMIN.bootstrap(),
        )
    reject = ADMIN_REJECT_RE.fullmatch(text)
    if reject:
        proposal = ADMIN.reject(reject.group(1), reject.group(2) or "User rejected proposal")
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            f"Rejected {proposal['proposal_id']}. No proposed change was applied.",
            "Navigator",
            "administration_reject",
            response_provider="veridex_admin",
            governance=governance_status(workspace_id, session_id),
            administration=ADMIN.bootstrap(),
        )
    rollback = ADMIN_ROLLBACK_RE.fullmatch(text)
    if rollback:
        proposal = ADMIN.rollback(rollback.group(1), confirm=True)
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            f"Rolled back {proposal['proposal_id']}. The rollback was recorded in the administration audit log.",
            "Navigator",
            "administration_rollback",
            response_provider="veridex_admin",
            governance=governance_status(workspace_id, session_id),
            administration=ADMIN.bootstrap(),
        )
    if active_room == "infrastructure_room":
        create_room = ROOM_CREATE_RE.search(text)
        if create_room:
            title = " ".join(create_room.group(1).split()).strip(" .")
            persona = " ".join((create_room.group(2) or "Room Steward").split()).strip(" .")
            proposal = ADMIN.create_proposal(
                "room",
                "create",
                {"title": title, "default_persona": persona},
                workspace_id=workspace_id,
                session_id=session_id,
            )
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                f"Infrastructure prepared {proposal['proposal_id']} to create {title} globally with {persona} as its persona. Review and approve it in Administration, or type `approve {proposal['proposal_id']}`.",
                "Infrastructure Manager",
                "administration_proposal",
                response_provider="veridex_admin",
                governance=governance_status(workspace_id, session_id),
                administration=ADMIN.bootstrap(),
            )
        if PROGRAM_MUTATION_RE.search(text):
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                "Infrastructure can implement that after approval. Open Administration and create a Program proposal with the exact allowed paths and verification commands; Navigator will validate the preview before any code is edited.",
                "Infrastructure Manager",
                "administration_scope_required",
                response_provider="veridex_admin",
                governance=governance_status(workspace_id, session_id),
                administration=ADMIN.bootstrap(),
            )
    elif re.search(r"\b(?:create|add|make)\b.{0,40}\b(?:new\s+)?room\b", text, re.IGNORECASE):
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            "Infrastructure Room owns room creation. Enter Infrastructure Room, then describe the room or open Administration to prepare the governed proposal.",
            "Navigator",
            "administration_handoff",
            response_provider="veridex_admin",
            governance=governance_status(workspace_id, session_id),
            administration=ADMIN.bootstrap(),
        )
    if active_persona == "Navigator" or active_room == "control_room" or re.search(r"\bnavigator\b", text, re.IGNORECASE):
        add = GOVERNANCE_ADD_RE.search(text)
        if add:
            kind = add.group(1).lower()
            statement = " ".join(add.group(2).split()).strip(" .")
            proposal = ADMIN.create_proposal(
                kind,
                "add",
                {"text" if kind == "rule" else "definition": statement},
                workspace_id=workspace_id,
                session_id=session_id,
            )
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                f"Navigator validated {proposal['proposal_id']} to add {proposal['payload']['id']}. Type `approve {proposal['proposal_id']}` to activate the new governance snapshot.",
                "Navigator",
                "governance_proposal",
                response_provider="veridex_admin",
                governance=governance_status(workspace_id, session_id),
                administration=ADMIN.bootstrap(),
            )
        disable = GOVERNANCE_DISABLE_RE.search(text)
        if disable:
            kind = disable.group(1).lower()
            target_id = disable.group(2)
            reason = " ".join((disable.group(3) or "Disabled by explicit user request").split())
            proposal = ADMIN.create_proposal(
                kind,
                "disable",
                {"target_id": target_id, "reason": reason},
                workspace_id=workspace_id,
                session_id=session_id,
            )
            return local_chat_response(
                workspace_id,
                session_id,
                user_message,
                f"Navigator prepared high-risk proposal {proposal['proposal_id']} to disable {proposal['payload']['target_id']}. It requires two separate approvals and remains fully reversible.",
                "Navigator",
                "governance_proposal",
                response_provider="veridex_admin",
                governance=governance_status(workspace_id, session_id),
                administration=ADMIN.bootstrap(),
            )
    return None


def chat_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    governance = active_governance_registry()
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
    admin_response = maybe_admin_chat_response(
        workspace_id,
        session_id,
        user_message,
        user_prompt,
        active_room,
        active_persona,
    )
    if admin_response is not None:
        return admin_response
    preflight = governance.preflight(user_prompt, active_gates, pending)
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
    if governance.is_governance_question(user_prompt, active_persona):
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            governance.governance_answer(active_gates),
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
                "gate_ids": governance.status(active_gates).get("active_gate_ids", []),
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
    if active_room == ANTIQUES_ROOM_ID and ANTIQUES_START_RE.search(governed_prompt):
        shopping = ANTIQUES.start_shopping_mode(workspace_id, session_id, active_room)
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            "Shopping mode is active. Until you end it, Leo may send sanitized copies of selected item photos to Google Lens for this Antiques session. It will end on room exit, session close, or after four hours without activity.",
            "Leo",
            "antiques_shopping_mode_start",
            response_provider="veridex_antiques_router",
            antiques={"shopping_mode": shopping},
            message_metadata={"message_kind": "antiques_shopping_mode", "antiques": {"shopping_mode": shopping}},
        )
    if active_room == ANTIQUES_ROOM_ID and ANTIQUES_END_RE.search(governed_prompt):
        shopping = ANTIQUES.end_shopping_mode(workspace_id, session_id)
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            "Shopping mode ended. Google Lens photo uploads now require confirmation for each research run.",
            "Leo",
            "antiques_shopping_mode_end",
            response_provider="veridex_antiques_router",
            antiques={"shopping_mode": shopping},
            message_metadata={"message_kind": "antiques_shopping_mode", "antiques": {"shopping_mode": shopping}},
        )
    pending_antique = ANTIQUES.pending_research(workspace_id, session_id) if active_room == ANTIQUES_ROOM_ID else {}
    if active_room == ANTIQUES_ROOM_ID and pending_antique and ANTIQUES_CONFIRM_RE.search(governed_prompt):
        antique_payload = {
            **pending_antique,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "confirm_external": True,
        }
        researched = antiques_research(antique_payload, cancel_event=cancel_event)
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            antiques_report_text(researched["case"]),
            "Leo",
            "antiques_research",
            response_provider="veridex_antiques_router",
            antiques=researched,
            message_metadata={"message_kind": "antiques_research", "antiques": researched},
        )
    if active_room == ANTIQUES_ROOM_ID and attachments and (
        ANTIQUES_RESEARCH_RE.search(governed_prompt) or all(str(row.get("content_type") or "").startswith("image/") for row in attachments)
    ):
        researched = antiques_research({
            "workspace_id": workspace_id,
            "session_id": session_id,
            "attachment_ids": attachment_ids,
            "mode": "deep" if re.search(r"\bdeep\b", governed_prompt, re.IGNORECASE) else "quick",
            "notes": governed_prompt,
            "case_id": str(payload.get("antiques_case_id") or ""),
            "confirm_external": bool(payload.get("confirm_external")),
            "valuation_overrides": payload.get("valuation_overrides") if isinstance(payload.get("valuation_overrides"), dict) else {},
        }, cancel_event=cancel_event)
        text = researched.get("message") if researched.get("status") == "confirmation_required" else antiques_report_text(researched["case"])
        return local_chat_response(
            workspace_id,
            session_id,
            user_message,
            str(text),
            "Leo",
            "antiques_research_confirmation" if researched.get("status") == "confirmation_required" else "antiques_research",
            response_provider="veridex_antiques_router",
            antiques=researched,
            message_metadata={"message_kind": "antiques_research", "antiques": researched},
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
    route_check = governance.validate_model_route(task_type, policy.model, policy.reasoning_effort)
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
    if active_room == "hr_department" and task_type == "resume_generation":
        saved_projects = RESUME.list_projects(workspace_id)
        context["resume_studio"] = {
            "saved_profile": RESUME.load_profile(workspace_id),
            "latest_saved_project": saved_projects[0] if saved_projects else None,
        }
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
    artifact_required = governance.requires_file_artifact(governed_prompt, task_type)
    artifact_output_dir = (
        STORE.prepare_generated_output_dir(workspace_id, session_id, user_message["message_id"])
        if artifact_required
        else None
    )
    if artifact_output_dir:
        artifact_kind = "generated_image" if task_type == "media" else "generated_document"
        context["required_artifact_output_dir"] = str(artifact_output_dir)
        context["artifact_storage_policy"] = {
            "handoff_dir": str(artifact_output_dir),
            "canonical_dir": str(STORE.generated_files_dir(workspace_id, active_room)),
            "kind": artifact_kind,
            "scope": "room",
            "scope_ref": active_room,
            "owner": "veridex",
            "rule": "Write final generated files to handoff_dir only. Veridex will validate, ledger, and move them to canonical_dir before reporting them to the user.",
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
            + (
                " For resume work, use only facts in attached files, the current request, or Resume Studio's explicitly saved profile/project. "
                "Never invent employers, dates, credentials, skills, accomplishments, or metrics; label useful missing metrics as questions for the user."
                if task_type == "resume_generation" else ""
            )
            + (
                " As Leo, specialize in thrift-store antiques and vintage collectables: art, jewelry, pottery, kitchenware, and service items. "
                "Separate visible observations, sourced evidence, and inference. Distinguish frame value from artwork value. Never claim definitive "
                "authentication, professional appraisal, gemstone identity, or precious-metal content from photographs alone."
                if active_room == ANTIQUES_ROOM_ID else ""
            )
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
    postflight = governance.postflight(
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
        postflight = governance.postflight(
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
    {"name": "office.admin_status", "description": "Read global room/governance versions, pending proposals, audit evidence, and rollback availability."},
    {"name": "office.room_propose", "description": "Create a global room create/update/archive/restore proposal; this never applies the change."},
    {"name": "office.governance_propose", "description": "Ask Navigator to validate a rule or gate add/amend/disable/restore proposal; this never applies the change."},
    {"name": "office.program_change_propose", "description": "Create a path-bounded Veridex program-change proposal for Infrastructure; implementation requires later approval."},
    {"name": "office.admin_apply", "description": "Apply one exact proposal only with confirm=true and its expected version; governance weakening requires a second token."},
    {"name": "office.admin_reject", "description": "Reject one pending administrative proposal without applying it."},
    {"name": "office.admin_rollback", "description": "Rollback one verified proposal only with confirm=true and record the result."},
    {"name": "office.gmail_status", "description": "Check whether Veridex's local Gmail integration is connected."},
    {"name": "office.gmail_search", "description": "Search Gmail metadata using the connected veridexcorp@gmail.com account."},
    {"name": "office.gmail_send", "description": "Send Gmail, including session attachments when provided, only when confirm=true; otherwise return a confirmation requirement."},
    {"name": "office.contact_list", "description": "List or search Nancy's local Gmail address book."},
    {"name": "office.contact_save", "description": "Create or update one local address-book contact."},
    {"name": "office.contact_sync", "description": "Import recipients from the 500 most recent Sent messages."},
    {"name": "office.gmail_delivery_check", "description": "Check returned Gmail delivery failures and create Nancy alerts."},
    {"name": "resume.profile_get", "description": "Read the saved workspace career profile."},
    {"name": "resume.profile_save", "description": "Save the career profile only when confirm=true."},
    {"name": "resume.template_list", "description": "List ATS-safe private-sector and federal resume templates."},
    {"name": "resume.job_analyze", "description": "Compare verified resume text with a target job description."},
    {"name": "resume.job_fetch", "description": "Retrieve bounded readable text from a public HTTPS job-posting URL."},
    {"name": "resume.draft", "description": "Create a governed, structured resume and optional application-kit draft."},
    {"name": "resume.review", "description": "Run deterministic ATS, completeness, claim, and keyword checks."},
    {"name": "resume.project_save", "description": "Persist a resume project only when confirm=true."},
    {"name": "resume.export", "description": "Render verified DOCX, PDF, and plain-text resume artifacts."},
    {"name": "art.studio_get", "description": "Read free-provider status, model capabilities, presets, and saved Art Studio projects."},
    {"name": "art.job_start", "description": "Start a free-only Art Studio generation, edit, critique, or local finishing job."},
    {"name": "art.job_get", "description": "Read progress or results for one Art Studio job."},
    {"name": "art.job_cancel", "description": "Request cancellation of one active Art Studio job."},
    {"name": "art.project_save", "description": "Persist an Art Studio project version only when confirm=true."},
    {"name": "antiques.shopping_mode_start", "description": "Authorize Google Lens uploads for the current Antiques session until explicitly ended or safely expired."},
    {"name": "antiques.shopping_mode_end", "description": "End Antiques shopping-mode photo-upload consent."},
    {"name": "antiques.shopping_mode_status", "description": "Read current Antiques shopping-mode consent status."},
    {"name": "antiques.research_item", "description": "Research attached item photos using Leo, Google Lens, Google, eBay, and category sources; external uploads require consent."},
    {"name": "antiques.case_list", "description": "List automatically saved Antiques research cases."},
    {"name": "antiques.case_get", "description": "Read one saved Antiques research case and its revisions."},
    {"name": "antiques.settings_get", "description": "Read Antiques valuation settings."},
    {"name": "antiques.settings_update", "description": "Update editable Antiques valuation settings."},
    {"name": "office.governance_status", "description": "Read Navigator status, rule source, gates, and pending requirements."},
    {"name": "office.governance_incident_list", "description": "List append-only governance incidents for a workspace."},
    {"name": "office.compliance_check", "description": "Run a deterministic compliance status check."},
]


class VeridexHandler(BaseHTTPRequestHandler):
    server_version = "CodexVeridex/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _is_remote_host(self) -> bool:
        host = str(self.headers.get("Host") or "").split(":", 1)[0].strip("[]").lower()
        return host not in {"", "127.0.0.1", "localhost", "::1"}

    def _remote_authorized(self) -> bool:
        if not self._is_remote_host():
            return True
        access = remote_access_state()
        cookies = {}
        for part in str(self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                cookies[key] = value
        supplied = cookies.get(REMOTE_COOKIE, "")
        return any(
            supplied and secrets.compare_digest(supplied, str(row.get("token") or ""))
            for row in access.get("sessions", [])
            if isinstance(row, dict)
        )

    def _reject_remote(self) -> None:
        self._json({"error": "This device is not paired with Veridex. Open the private pairing URL shown by .\\veridex.ps1 tailscale."}, HTTPStatus.UNAUTHORIZED)

    def _pair_remote(self, token: str) -> None:
        access = remote_access_state()
        expected = str(access.get("pairing_token") or "")
        if not expected or not secrets.compare_digest(str(token or ""), expected):
            self._json({"error": "Invalid or expired pairing token"}, HTTPStatus.UNAUTHORIZED)
            return
        session_token = secrets.token_urlsafe(32)
        sessions = [row for row in access.get("sessions", []) if isinstance(row, dict)][-9:]
        sessions.append({"token": session_token, "paired_at": datetime.now().astimezone().isoformat()})
        access.update({"pairing_token": secrets.token_urlsafe(32), "sessions": sessions})
        save_remote_access_state(access)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"{REMOTE_COOKIE}={session_token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

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
            if parsed.path == "/pair":
                self._pair_remote(str(query.get("token", [""])[0]))
                return
            if not self._remote_authorized():
                self._reject_remote()
                return
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
            elif parsed.path == "/api/resume":
                self._json(resume_bootstrap(
                    str(query.get("workspace_id", [""])[0]).strip(),
                    str(query.get("session_id", [""])[0]).strip(),
                ))
            elif parsed.path == "/api/art/studio":
                self._json(art_bootstrap(
                    str(query.get("workspace_id", [""])[0]).strip(),
                    str(query.get("session_id", [""])[0]).strip(),
                ))
            elif parsed.path == "/api/antiques":
                workspace_id = str(query.get("workspace_id", [""])[0]).strip()
                session_id = str(query.get("session_id", [""])[0]).strip()
                session = antiques_context(workspace_id, session_id)
                self._json(ANTIQUES.bootstrap(workspace_id, session_id, str(session.get("active_room") or "")))
            elif re.fullmatch(r"/api/antiques/analysis/jobs/[A-Za-z0-9_-]+", parsed.path):
                self._json(MUSEUM_JOBS.get(parsed.path.rsplit("/", 1)[-1]))
            elif re.fullmatch(r"/api/art/jobs/[A-Za-z0-9_-]+", parsed.path):
                self._json(ART_JOBS.get(parsed.path.rsplit("/", 1)[-1]))
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
            elif parsed.path == "/api/admin":
                self._json({"administration": ADMIN.bootstrap()})
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
            if not self._remote_authorized():
                self._reject_remote()
                return
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
            elif parsed.path == "/api/resume/profile/save":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                session_id = str(payload.get("session_id") or "").strip()
                resume_context(workspace_id, session_id)
                if not payload.get("confirm"):
                    self._json({"status": "confirmation_required", "message": "Confirm Save Career Profile to persist these facts."})
                else:
                    profile = RESUME.save_profile(
                        workspace_id,
                        payload.get("profile") if isinstance(payload.get("profile"), dict) else {},
                        int(payload.get("expected_version")) if payload.get("expected_version") is not None else None,
                    )
                    self._json({"status": "saved", "profile": profile})
            elif parsed.path == "/api/resume/import":
                self._json(resume_source_import(
                    str(payload.get("workspace_id") or "").strip(),
                    str(payload.get("session_id") or "").strip(),
                    str(payload.get("file_id") or "").strip(),
                ))
            elif parsed.path == "/api/resume/analyze":
                resume_context(str(payload.get("workspace_id") or ""), str(payload.get("session_id") or ""))
                self._json(keyword_analysis(str(payload.get("job_description") or ""), str(payload.get("resume_text") or "")))
            elif parsed.path == "/api/resume/job/fetch":
                resume_context(str(payload.get("workspace_id") or ""), str(payload.get("session_id") or ""))
                self._json({"url": str(payload.get("url") or ""), "description": fetch_job_description(str(payload.get("url") or ""))})
            elif parsed.path == "/api/resume/draft":
                self._json(resume_model_draft(payload))
            elif parsed.path == "/api/resume/review":
                resume_context(str(payload.get("workspace_id") or ""), str(payload.get("session_id") or ""))
                self._json(quality_review(
                    payload.get("draft") if isinstance(payload.get("draft"), dict) else {},
                    str(payload.get("job_description") or ""),
                    federal=payload.get("resume_type") == "federal",
                ))
            elif parsed.path == "/api/resume/project/save":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                resume_context(workspace_id, str(payload.get("session_id") or ""))
                if not payload.get("confirm"):
                    self._json({"status": "confirmation_required", "message": "Confirm Save Project to persist this application project."})
                else:
                    project = RESUME.save_project(workspace_id, payload.get("project") if isinstance(payload.get("project"), dict) else {})
                    self._json({"status": "saved", "project": project, "projects": RESUME.list_projects(workspace_id)})
            elif parsed.path == "/api/resume/export":
                self._json(save_resume_exports(payload), HTTPStatus.CREATED)
            elif parsed.path == "/api/art/jobs":
                self._json(submit_art_job(payload), HTTPStatus.ACCEPTED)
            elif parsed.path == "/api/antiques/analysis":
                self._json(submit_museum_analysis(payload), HTTPStatus.ACCEPTED)
            elif parsed.path == "/api/antiques/research":
                self._json(antiques_research(payload))
            elif parsed.path == "/api/antiques/shopping/start":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                session_id = str(payload.get("session_id") or "").strip()
                session = antiques_context(workspace_id, session_id)
                self._json({"shopping_mode": ANTIQUES.start_shopping_mode(workspace_id, session_id, str(session.get("active_room") or ""))})
            elif parsed.path == "/api/antiques/shopping/end":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                session_id = str(payload.get("session_id") or "").strip()
                antiques_context(workspace_id, session_id)
                self._json({"shopping_mode": ANTIQUES.end_shopping_mode(workspace_id, session_id)})
            elif parsed.path == "/api/antiques/settings":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                session_id = str(payload.get("session_id") or "").strip()
                antiques_context(workspace_id, session_id)
                self._json({"settings": ANTIQUES.update_settings(workspace_id, payload.get("settings") if isinstance(payload.get("settings"), dict) else {})})
            elif re.fullmatch(r"/api/art/jobs/[A-Za-z0-9_-]+/cancel", parsed.path):
                self._json(ART_JOBS.cancel(parsed.path.split("/")[-2]))
            elif re.fullmatch(r"/api/antiques/analysis/jobs/[A-Za-z0-9_-]+/cancel", parsed.path):
                self._json(MUSEUM_JOBS.cancel(parsed.path.split("/")[-2]))
            elif parsed.path == "/api/art/projects/save":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                art_context(workspace_id, str(payload.get("session_id") or ""))
                if not payload.get("confirm"):
                    self._json({"status": "confirmation_required", "message": "Confirm Save Project to persist this Art Studio project."})
                else:
                    project = ART.save_project(workspace_id, payload.get("project") if isinstance(payload.get("project"), dict) else {})
                    self._json({"status": "saved", "project": project, "projects": ART.list_projects(workspace_id)})
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
            elif parsed.path == "/api/admin/proposals":
                self._json(admin_create_response(payload), HTTPStatus.CREATED)
            elif parsed.path == "/api/admin/proposals/apply":
                self._json(admin_apply_response(payload))
            elif parsed.path == "/api/admin/proposals/reject":
                proposal = ADMIN.reject(str(payload.get("proposal_id") or ""), str(payload.get("reason") or ""))
                self._json({"status": "rejected", "proposal": proposal, "administration": ADMIN.bootstrap()})
            elif parsed.path == "/api/admin/proposals/rollback":
                proposal = ADMIN.rollback(str(payload.get("proposal_id") or ""), confirm=bool(payload.get("confirm")))
                self._json({"status": proposal.get("status"), "proposal": proposal, "administration": ADMIN.bootstrap()})
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
        elif tool == "office.admin_status":
            value = ADMIN.bootstrap()
        elif tool == "office.room_propose":
            value = admin_create_response({**args, "kind": "room"})
        elif tool == "office.governance_propose":
            kind = str(args.get("kind") or "").lower()
            if kind not in {"rule", "gate"}:
                raise ValueError("kind must be rule or gate")
            value = admin_create_response({**args, "kind": kind})
        elif tool == "office.program_change_propose":
            value = admin_create_response({**args, "kind": "program", "action": "change"})
        elif tool == "office.admin_apply":
            value = admin_apply_response(args)
        elif tool == "office.admin_reject":
            proposal = ADMIN.reject(str(args.get("proposal_id") or ""), str(args.get("reason") or ""))
            value = {"status": "rejected", "proposal": proposal, "administration": ADMIN.bootstrap()}
        elif tool == "office.admin_rollback":
            proposal = ADMIN.rollback(str(args.get("proposal_id") or ""), confirm=bool(args.get("confirm")))
            value = {"status": proposal.get("status"), "proposal": proposal, "administration": ADMIN.bootstrap()}
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
        elif tool == "resume.profile_get":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id)
            workspace_id = str(args.get("workspace_id") or session.get("workspace_id") or "")
            resume_context(workspace_id, session_id, require_hr=False)
            value = {"profile": RESUME.load_profile(workspace_id)}
        elif tool == "resume.profile_save":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id)
            workspace_id = str(args.get("workspace_id") or session.get("workspace_id") or "")
            resume_context(workspace_id, session_id)
            if not args.get("confirm"):
                value = {"status": "confirmation_required", "message": "Set confirm=true only after the user explicitly chooses Save Career Profile."}
            else:
                value = {"status": "saved", "profile": RESUME.save_profile(workspace_id, args.get("profile") or {}, args.get("expected_version"))}
        elif tool == "resume.template_list":
            value = {"templates": RESUME.list_templates()}
        elif tool == "resume.job_analyze":
            value = keyword_analysis(str(args.get("job_description") or ""), str(args.get("resume_text") or ""))
        elif tool == "resume.job_fetch":
            value = {"url": str(args.get("url") or ""), "description": fetch_job_description(str(args.get("url") or ""))}
        elif tool == "resume.draft":
            value = resume_model_draft(args)
        elif tool == "resume.review":
            value = quality_review(args.get("draft") or {}, str(args.get("job_description") or ""), federal=args.get("resume_type") == "federal")
        elif tool == "resume.project_save":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id)
            workspace_id = str(args.get("workspace_id") or session.get("workspace_id") or "")
            resume_context(workspace_id, session_id)
            value = (
                {"status": "saved", "project": RESUME.save_project(workspace_id, args.get("project") or {})}
                if args.get("confirm")
                else {"status": "confirmation_required", "message": "Set confirm=true only after the user explicitly chooses Save Project."}
            )
        elif tool == "resume.export":
            if not args.get("confirm"):
                value = {"status": "confirmation_required", "message": "Set confirm=true only after the user explicitly chooses Export."}
            else:
                value = save_resume_exports(args)
        elif tool == "art.studio_get":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id)
            workspace_id = str(args.get("workspace_id") or session.get("workspace_id") or "")
            value = art_bootstrap(workspace_id, session_id)
        elif tool == "art.job_start":
            value = submit_art_job(args)
        elif tool == "art.job_get":
            value = ART_JOBS.get(str(args.get("job_id") or ""))
        elif tool == "art.job_cancel":
            value = ART_JOBS.cancel(str(args.get("job_id") or ""))
        elif tool == "art.project_save":
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id)
            workspace_id = str(args.get("workspace_id") or session.get("workspace_id") or "")
            art_context(workspace_id, session_id)
            value = (
                {"status": "saved", "project": ART.save_project(workspace_id, args.get("project") or {})}
                if args.get("confirm")
                else {"status": "confirmation_required", "message": "Set confirm=true only after the user explicitly chooses Save Project."}
            )
        elif tool.startswith("antiques."):
            session_id = str(args.get("session_id") or "")
            session = STORE.find_session(session_id)
            workspace_id = str(args.get("workspace_id") or session.get("workspace_id") or "")
            antiques_context(workspace_id, session_id)
            if tool == "antiques.shopping_mode_start":
                value = {"shopping_mode": ANTIQUES.start_shopping_mode(workspace_id, session_id, ANTIQUES_ROOM_ID)}
            elif tool == "antiques.shopping_mode_end":
                value = {"shopping_mode": ANTIQUES.end_shopping_mode(workspace_id, session_id)}
            elif tool == "antiques.shopping_mode_status":
                value = {"shopping_mode": ANTIQUES.shopping_status(workspace_id, session_id, ANTIQUES_ROOM_ID)}
            elif tool == "antiques.research_item":
                value = antiques_research({**args, "workspace_id": workspace_id, "session_id": session_id})
            elif tool == "antiques.case_list":
                value = {"cases": ANTIQUES.list_cases(workspace_id)}
            elif tool == "antiques.case_get":
                value = {"case": ANTIQUES.get_case(workspace_id, str(args.get("case_id") or ""))}
            elif tool == "antiques.settings_get":
                value = {"settings": ANTIQUES.settings(workspace_id)}
            elif tool == "antiques.settings_update":
                value = {"settings": ANTIQUES.update_settings(workspace_id, args.get("settings") if isinstance(args.get("settings"), dict) else args)}
            else:
                raise ValueError(f"Unknown tool: {tool}")
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
