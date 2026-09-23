"""Canonical, bounded research-record derivation for saved Museum cases."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable


SCHEMA_VERSION = 1
IDENTITY_FIELDS = (
    "identification", "title", "category", "artist_or_maker", "date_or_period",
    "medium_or_material", "support", "dimensions", "product_code", "model",
    "pattern", "edition", "signature_or_mark", "condition", "confidence",
)


def _text(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _strings(values: Any, limit: int, text_limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    rows = []
    for value in values:
        text = _text(value, text_limit)
        if text and text not in rows:
            rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 1_000_000_000 or not number.is_integer():
        return None
    return int(number)


def _url(value: Any) -> str:
    text = _text(value, 2000)
    return text if re.match(r"^https?://", text, re.IGNORECASE) else ""


def _assessment(value: Any, limit: int = 500) -> str:
    if isinstance(value, dict):
        value = value.get("assessment") or value.get("text") or value.get("value")
    return _text(value, limit)


def _first(*values: Any, limit: int = 500) -> str:
    for value in values:
        text = _assessment(value, limit)
        if text:
            return text
    return ""


def _merge_rows(existing: Any, additions: Iterable[Dict[str, Any]], key_fields: tuple[str, ...], limit: int) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    positions: Dict[str, int] = {}
    for value in [*(existing if isinstance(existing, list) else []), *additions]:
        if not isinstance(value, dict):
            continue
        row = {key: item for key, item in value.items() if item not in (None, "", [], {})}
        identity = "|".join(str(row.get(key) or "").casefold() for key in key_fields)
        if not identity.strip("|"):
            identity = json.dumps(row, ensure_ascii=False, sort_keys=True).casefold()
        if identity in positions:
            rows[positions[identity]].update(row)
            continue
        positions[identity] = len(rows)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _notes(values: Any, *, correspondence: bool = False) -> list[Dict[str, Any]]:
    if values is None:
        return []
    candidates = values if isinstance(values, list) else [values]
    rows = []
    for value in candidates[:50]:
        if isinstance(value, str):
            statement = _text(value, 1500)
            row = {"summary" if correspondence else "statement": statement} if statement else {}
        elif isinstance(value, dict):
            statement = _first(
                value.get("summary"), value.get("statement"), value.get("claim"),
                value.get("text"), value.get("note"), value.get("history"),
                limit=1500,
            )
            row = {
                "summary" if correspondence else "statement": statement,
                "status": _text(value.get("status"), 80),
                "date": _text(value.get("date"), 80),
                "party": _text(value.get("party") or value.get("correspondent"), 200),
                "source_ref": _text(value.get("source_ref") or value.get("message_id"), 300),
                "source_url": _url(value.get("source_url") or value.get("url")),
            }
            row = {key: item for key, item in row.items() if item}
        else:
            row = {}
        if row:
            rows.append(row)
    return rows


def _identity(report: Dict[str, Any]) -> Dict[str, str]:
    proposed_record = report.get("research_record") if isinstance(report.get("research_record"), dict) else {}
    proposed = proposed_record.get("identity") if isinstance(proposed_record.get("identity"), dict) else {}
    attributes = report.get("item_attributes") if isinstance(report.get("item_attributes"), dict) else {}
    label = report.get("label") if isinstance(report.get("label"), dict) else {}
    signature = report.get("signature") if isinstance(report.get("signature"), dict) else {}
    candidates = signature.get("transcription_candidates") if isinstance(signature.get("transcription_candidates"), list) else []
    signature_text = ""
    for candidate in candidates:
        signature_text = _first(candidate.get("text") if isinstance(candidate, dict) else candidate)
        if signature_text:
            break
    condition_notes = report.get("condition_notes") if isinstance(report.get("condition_notes"), list) else []
    condition_text = "; ".join(_strings(condition_notes, 12, 300))
    values = {
        "identification": _first(proposed.get("identification"), report.get("identification"), report.get("title")),
        "title": _first(proposed.get("title"), report.get("title"), report.get("identification")),
        "category": _first(proposed.get("category"), report.get("category"), limit=120),
        "artist_or_maker": _first(proposed.get("artist_or_maker"), report.get("artist_or_maker"), report.get("artist"), report.get("maker")),
        "date_or_period": _first(proposed.get("date_or_period"), report.get("date_or_period"), report.get("likely_period"), report.get("date")),
        "medium_or_material": _first(proposed.get("medium_or_material"), report.get("medium_or_material"), report.get("medium")),
        "support": _first(proposed.get("support"), report.get("support")),
        "dimensions": _first(proposed.get("dimensions"), report.get("dimensions"), attributes.get("dimensions")),
        "product_code": _first(proposed.get("product_code"), report.get("product_code"), report.get("item_number"), report.get("catalog_number"), label.get("product_code")),
        "model": _first(proposed.get("model"), report.get("model"), attributes.get("model")),
        "pattern": _first(proposed.get("pattern"), report.get("pattern"), attributes.get("pattern")),
        "edition": _first(proposed.get("edition"), report.get("edition"), attributes.get("edition")),
        "signature_or_mark": _first(proposed.get("signature_or_mark"), report.get("signature_or_mark"), signature_text),
        "condition": _first(proposed.get("condition"), report.get("condition"), condition_text),
        "confidence": _first(proposed.get("confidence"), report.get("confidence"), limit=40),
    }
    return {field: values[field] for field in IDENTITY_FIELDS if values.get(field)}


def _artifact_refs(report: Dict[str, Any]) -> list[Dict[str, Any]]:
    candidates = list(report.get("evidence_artifacts") or [])
    signature = report.get("signature") if isinstance(report.get("signature"), dict) else {}
    candidates.extend(signature.get("evidence_artifacts") or [])
    rows = []
    for value in candidates[:100]:
        if not isinstance(value, dict):
            continue
        row = {
            "file_id": _text(value.get("file_id"), 160),
            "artifact_number": _count(value.get("artifact_number")),
            "name": _text(value.get("name"), 300),
            "scope_ref": _text(value.get("scope_ref"), 120),
            "sha256": _text(value.get("sha256"), 64),
        }
        row = {key: item for key, item in row.items() if item not in (None, "")}
        if row.get("file_id") or row.get("artifact_number"):
            rows.append(row)
    return rows


def _source_refs(report: Dict[str, Any]) -> list[Dict[str, Any]]:
    candidates = list(report.get("sourced_matches") or [])
    price_evaluation = report.get("price_evaluation") if isinstance(report.get("price_evaluation"), dict) else {}
    for key in ("observations", "exact_results", "similar_candidates"):
        candidates.extend(price_evaluation.get(key) or [])
    if isinstance(price_evaluation.get("last_sold"), dict):
        candidates.append(price_evaluation["last_sold"])
    rows = []
    for value in candidates[:200]:
        if not isinstance(value, dict):
            continue
        row = {
            "source_id": _text(value.get("source_id") or value.get("provider"), 120),
            "source_url": _url(value.get("source_url") or value.get("url")),
            "listing_or_lot_id": _text(value.get("listing_or_lot_id") or value.get("listing_id"), 160),
            "summary": _first(value.get("claim"), value.get("title"), value.get("summary"), limit=600),
            "evidence_status": _text(value.get("evidence_status"), 40),
        }
        row = {key: item for key, item in row.items() if item}
        if row.get("source_url") or row.get("listing_or_lot_id"):
            rows.append(row)
    return rows


def build_research_record(
    case_id: str,
    report: Dict[str, Any],
    attachment_ids: Iterable[str],
    revision_id: str,
    updated_at: str,
    existing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build the canonical identity and evidence view for one saved case."""
    prior = existing if isinstance(existing, dict) else {}
    prior_identity = prior.get("identity") if isinstance(prior.get("identity"), dict) else {}
    identity = {field: _text(prior_identity.get(field), 1500) for field in IDENTITY_FIELDS if _text(prior_identity.get(field), 1500)}
    identity.update(_identity(report))

    proposed = report.get("research_record") if isinstance(report.get("research_record"), dict) else {}
    provenance = _merge_rows(
        prior.get("provenance"),
        [*_notes(proposed.get("provenance")), *_notes(report.get("provenance"))],
        ("statement", "source_ref", "source_url"),
        100,
    )
    correspondence = _merge_rows(
        prior.get("correspondence"),
        [*_notes(proposed.get("correspondence"), correspondence=True), *_notes(report.get("correspondence"), correspondence=True)],
        ("summary", "party", "date", "source_ref"),
        100,
    )

    prior_evidence = prior.get("evidence") if isinstance(prior.get("evidence"), dict) else {}
    attachments = list(dict.fromkeys([*_strings(prior_evidence.get("attachment_ids"), 100, 160), *_strings(list(attachment_ids), 100, 160)]))[:100]
    artifacts = _merge_rows(prior_evidence.get("artifacts"), _artifact_refs(report), ("file_id", "artifact_number", "sha256"), 200)
    sources = _merge_rows(prior_evidence.get("sources"), _source_refs(report), ("source_id", "source_url", "listing_or_lot_id"), 300)
    price_evaluation = report.get("price_evaluation") if isinstance(report.get("price_evaluation"), dict) else {}
    observation_ids = list(dict.fromkeys([
        *_strings(prior_evidence.get("price_observation_ids"), 500, 160),
        *_strings(price_evaluation.get("observation_ids"), 500, 160),
        *[_text(row.get("observation_id"), 160) for row in price_evaluation.get("observations") or [] if isinstance(row, dict) and _text(row.get("observation_id"), 160)],
    ]))[:500]
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "artwork_or_object",
        "case_id": case_id,
        "identity": identity,
        "provenance": provenance,
        "correspondence": correspondence,
        "evidence": {
            "attachment_ids": attachments,
            "artifacts": artifacts,
            "sources": sources,
            "price_observation_ids": observation_ids,
        },
        "latest_revision_id": revision_id,
        "updated_at": updated_at,
    }
