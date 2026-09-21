"""Provider-neutral normalization for bounded visual-search evidence."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable
from urllib.parse import parse_qs, unquote, urlparse, urlunparse


MAX_VISUAL_RESULTS = 12
MAX_RAW_RESULT_TEXT = 12_000
_BLOCKED_TEXT = re.compile(r"unusual traffic|not a robot|recaptcha|automated queries", re.IGNORECASE)
_NAVIGATION_TITLES = {
    "about", "all", "apps", "feedback", "help", "images", "log in", "login", "privacy",
    "search", "settings", "sign in", "terms", "tools", "videos",
}
_NAVIGATION_HOSTS = {
    "accounts.google.com", "myaccount.google.com", "policies.google.com", "support.google.com",
}


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _unwrap_google_url(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.netloc.casefold().split(":", 1)[0]
    if not (host == "google.com" or host.endswith(".google.com")):
        return value
    query = parse_qs(parsed.query)
    if parsed.path in {"/url", "/imgres"}:
        for key in ("url", "q", "imgrefurl"):
            candidate = unquote(str((query.get(key) or [""])[0])).strip()
            if candidate.startswith(("http://", "https://")):
                return candidate
    return value


def normalize_http_url(value: Any) -> str:
    candidate = _unwrap_google_url(str(value or "").strip())
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host or host in _NAVIGATION_HOSTS:
        return ""
    if (host == "google.com" or host.endswith(".google.com")) and parsed.path in {
        "", "/", "/advanced_search", "/preferences", "/search",
    }:
        return ""
    return urlunparse((parsed.scheme.casefold(), parsed.netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def normalize_visual_results(
    links: Iterable[Dict[str, Any]] | None,
    *,
    page_url: str = "",
    limit: int = MAX_VISUAL_RESULTS,
) -> list[Dict[str, Any]]:
    """Normalize visible provider links while retaining their original order."""

    normalized_page = normalize_http_url(page_url)
    rows: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for link in links or ():
        if not isinstance(link, dict):
            continue
        title = _clean(link.get("title") or link.get("text"), 300)
        if not title or title.casefold().strip(" .:-") in _NAVIGATION_TITLES:
            continue
        url = normalize_http_url(link.get("url") or link.get("href"))
        key = url.casefold()
        if not url or key in seen or (normalized_page and key == normalized_page.casefold()):
            continue
        seen.add(key)
        rows.append({
            "rank": len(rows) + 1,
            "title": title,
            "url": url,
            "snippet": _clean(link.get("snippet"), 600),
            "source": "visible_lens_result",
        })
        if len(rows) >= max(1, min(int(limit), MAX_VISUAL_RESULTS)):
            break
    return rows


def normalize_lens_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the stable Google Lens evidence contract used by Veridex."""

    row = payload if isinstance(payload, dict) else {}
    raw_text = str(row.get("raw_result_text") or row.get("result_text") or "")[:MAX_RAW_RESULT_TEXT]
    results = normalize_visual_results(
        row.get("results") if isinstance(row.get("results"), list) else row.get("links"),
        page_url=str(row.get("page_url") or ""),
    )
    requested_status = str(row.get("status") or "").casefold()
    if requested_status in {"completed", "limited", "blocked", "failed"}:
        status = requested_status
    elif not row.get("ok", True):
        status = "failed"
    elif _BLOCKED_TEXT.search(raw_text):
        status = "blocked"
    elif results:
        status = "completed"
    else:
        status = "limited"
    if status == "completed" and not results:
        status = "limited"
    return {
        **row,
        "provider": "google_lens_chrome_profile",
        "status": status,
        "page_title": _clean(row.get("page_title") or "Google Lens", 300),
        "page_url": normalize_http_url(row.get("page_url")) or "https://lens.google.com/",
        "results": results,
        "opened_sources": list(row.get("opened_sources") or [])[:5],
        "raw_result_text": raw_text,
        # Retained for existing evidence consumers during the schema transition.
        "result_text": raw_text,
        "links": [{key: result[key] for key in ("title", "url", "snippet")} for result in results],
    }
