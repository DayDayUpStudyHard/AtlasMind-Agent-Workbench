"""Shared evidence and document-snapshot utilities for Agent graphs."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any


def normalize_document_text(value: object) -> str:
    """Normalize extraction layout without rewriting contract wording."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def compact_evidence_text(value: object) -> str:
    return re.sub(r"\s+", "", normalize_document_text(value))


def content_hash(value: object) -> str:
    return hashlib.sha256(normalize_document_text(value).encode("utf-8")).hexdigest()


def quote_supported(quote: object, source: object, minimum_chars: int = 6) -> bool:
    """Check that a citation is a contiguous span of canonical source text."""
    compact_quote = compact_evidence_text(quote)
    compact_source = compact_evidence_text(source)
    return len(compact_quote) >= minimum_chars and compact_quote in compact_source


def citation_support(
    citation_id: str,
    citation: dict[str, Any] | None,
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate one citation's existence and source text deterministically."""
    item = evidence_by_id.get(str(citation_id))
    if not item:
        return {
            "citationId": str(citation_id),
            "status": "MISSING_RETRIEVAL",
            "supported": False,
            "reasons": ["引用 ID 不在本次检索结果中"],
        }

    source_text = (
        item.get("clauseText")
        or item.get("content")
        or item.get("fullText")
        or item.get("snippet")
        or ""
    )
    reasons: list[str] = []
    if not str(source_text).strip():
        reasons.append("检索结果没有可核验的原文")

    legacy_citation = citation if isinstance(citation, dict) else {}
    quote = legacy_citation.get("snippet") or legacy_citation.get("quote") or ""
    if quote and not quote_supported(quote, source_text):
        reasons.append("引用片段不是来源原文的连续片段")

    status = "SUPPORTED" if not reasons else "UNSUPPORTED"
    return {
        "citationId": str(citation_id),
        "status": status,
        "supported": status == "SUPPORTED",
        "sourceType": item.get("sourceType"),
        "documentId": item.get("documentId"),
        "documentVersion": item.get("documentVersion"),
        "contentHash": item.get("contentHash"),
        "retrievalAgreement": item.get("retrievalAgreement"),
        "reasons": reasons,
    }


def summarize_document_quality(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a stable quality summary from parsed document snapshots."""
    levels = {str(doc.get("parseQuality") or "UNKNOWN").upper() for doc in documents}
    low = [doc for doc in documents if str(doc.get("parseQuality") or "").upper() == "LOW"]
    medium = [doc for doc in documents if str(doc.get("parseQuality") or "").upper() == "MEDIUM"]
    if low:
        status = "LOW"
    elif medium:
        status = "REVIEW"
    elif documents and all(level in {"HIGH", "UNKNOWN"} for level in levels):
        status = "PASS"
    else:
        status = "UNKNOWN"
    return {
        "status": status,
        "documentCount": len(documents),
        "lowQualityDocumentIds": [doc.get("id") for doc in low],
        "reviewDocumentIds": [doc.get("id") for doc in medium],
        "requiresHumanReview": bool(low or medium),
    }
