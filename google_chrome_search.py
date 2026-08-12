"""Explicit Google searches through Veridex's dedicated local Chrome profile."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from request_control import RequestCancelled


ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / "google_chrome_search.js"
GOOGLE_SEARCH_INTENT = re.compile(
    r"\b(?:check|search|use|try|look(?:\s+up)?|find)\b.{0,80}\bgoogle\b|\bgoogle\s+search\b",
    re.IGNORECASE,
)
GOOGLE_FOLLOWUP = re.compile(
    r"\b(?:again|same search|search results?|those results?|give me (?:the )?results?|show me (?:the )?results?)\b",
    re.IGNORECASE,
)
SEARCH_TOPIC = re.compile(
    r"\b(?:search|find|results?|dates?|shows?|concerts?|events?|musician|band|artist|venue|upcoming|past)\b",
    re.IGNORECASE,
)
QUERY_STOPWORDS = {
    "a", "an", "and", "again", "called", "check", "do", "doing", "for", "from", "give", "google",
    "in", "me", "music", "of", "search", "show", "shows", "the", "to", "use", "with",
}


class GoogleChromeSearchError(RuntimeError):
    pass


def wants_google_search(text: str) -> bool:
    return bool(GOOGLE_SEARCH_INTENT.search(str(text or "")))


def extract_google_query(text: str) -> str:
    value = " ".join(str(text or "").split()).strip()
    match = re.search(r"\bgoogle(?:\s+search)?\b(?:\s+again)?(?:\s+for)?\s*(.+)$", value, re.IGNORECASE)
    query = match.group(1) if match else value
    query = re.sub(r"^(?:and\s+)?(?:give|tell|show)\s+me\s+", "", query, flags=re.IGNORECASE)
    query = re.split(r"\b(?:and\s+)?(?:give|tell|show)\s+me\b", query, maxsplit=1, flags=re.IGNORECASE)[0]
    query = re.sub(r"^(?:for\s+)?(?:a\s+)?band\s+called\s+", "", query, flags=re.IGNORECASE)
    return query.strip(" .,:;-") or value


def _previous_google_query(messages: Iterable[Dict[str, Any]]) -> Optional[str]:
    for row in reversed(list(messages)[-8:]):
        evidence = row.get("execution_evidence") if isinstance(row.get("execution_evidence"), list) else []
        for item in reversed(evidence):
            if (
                isinstance(item, dict)
                and str(item.get("type") or "") == "google_browser_search"
                and str(item.get("provider") or "") == "google_chrome_profile"
                and str(item.get("query") or "").strip()
            ):
                return str(item["query"]).strip()
        if str(row.get("role") or "") != "user":
            continue
        value = str(row.get("text") or "")
        if wants_google_search(value):
            return extract_google_query(value)
    return None


def _topic_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(text or "").casefold())
        if len(token) > 2 and token not in QUERY_STOPWORDS
    }


def continues_google_search(text: str, messages: Iterable[Dict[str, Any]]) -> bool:
    previous = _previous_google_query(messages)
    if not previous or not SEARCH_TOPIC.search(str(text or "")):
        return False
    if GOOGLE_FOLLOWUP.search(str(text or "")):
        return True
    return len(_topic_tokens(text) & _topic_tokens(previous)) >= 2


def resolve_google_query(text: str, messages: Iterable[Dict[str, Any]] = ()) -> str:
    value = str(text or "")
    current = extract_google_query(value)
    previous = _previous_google_query(messages)
    if not previous:
        return current
    if wants_google_search(value) and not GOOGLE_FOLLOWUP.search(value):
        return current
    if not GOOGLE_FOLLOWUP.search(value) and not continues_google_search(value, messages):
        return current
    base = previous
    refinements = []
    if re.search(r"\b(?:upcoming|future|next)\b", value, re.IGNORECASE):
        refinements.append("upcoming shows")
    elif re.search(r"\b(?:past|previous)\s+(?:show|shows|concert|concerts|date|dates|event|events)\b", value, re.IGNORECASE):
        refinements.append("past shows")
    elif re.search(r"\b(?:dates?|shows|concerts?|events?)\b", value, re.IGNORECASE):
        refinements.append("show dates")
    additions = [item for item in refinements if item.casefold() not in base.casefold()]
    return " ".join([base, *additions]).strip()


def _run(action: str, *arguments: str, timeout: int = 60, cancel_event: Any = None) -> Dict[str, Any]:
    node = shutil.which(os.environ.get("VERIDEX_NODE_COMMAND", "node"))
    if not node:
        raise GoogleChromeSearchError("Node.js was not found; the Google Chrome bridge cannot run.")
    command = [node, str(BRIDGE), action, *arguments]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if cancel_event is None:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=creation_flags,
        )
    else:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                subprocess.run(
                    [node, str(BRIDGE), "cleanup"],
                    cwd=str(ROOT),
                    capture_output=True,
                    timeout=10,
                    check=False,
                    creationflags=creation_flags,
                )
                raise RequestCancelled("The active Google search was stopped by the user.")
            if time.monotonic() >= deadline:
                process.kill()
                raise GoogleChromeSearchError(f"Google Chrome search timed out after {timeout} seconds.")
            time.sleep(0.1)
        stdout, stderr = process.communicate()
        completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    try:
        payload = json.loads(str(completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        detail = " ".join(str(completed.stderr or completed.stdout or "").split())[:1000]
        raise GoogleChromeSearchError(f"Google Chrome bridge returned invalid output: {detail}") from exc
    if completed.returncode != 0 or not payload.get("ok"):
        raise GoogleChromeSearchError(str(payload.get("error") or "Google Chrome search failed."))
    return payload


def google_profile_status() -> Dict[str, Any]:
    return _run("status", timeout=10)


def search_google(text: str, messages: Iterable[Dict[str, Any]] = (), cancel_event: Any = None) -> Dict[str, Any]:
    return _run("search", resolve_google_query(text, messages), timeout=90, cancel_event=cancel_event)
