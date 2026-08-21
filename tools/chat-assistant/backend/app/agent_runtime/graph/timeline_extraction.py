"""Final fulfillment schedule graph (PRD Phase 6: 迁移履约日程).

The timeline used to be a black box: one publish node that ran rule
candidates, LLM enrichment and persistence inside
``contract_document_parser.extract_final_contract_timeline``. It is now an
observable DAG where each layer is its own stage:

* rule layer     — ``_extract_clause_timeline_nodes_v2`` (deterministic regex
                   candidates; relative dates resolved by code, never by the
                   LLM — Phase 6 tasks 1+4)
* LLM layer      — ``_enrich_timeline_nodes`` judges responsibility, action,
                   trigger, term and consequence on the complete clause text
                   (tasks 2+6); conditional events keep date=None + condition
                   (task 5)
* validation     — deterministic dedup, source lineage, complete citation,
                   mojibake / OCR risk flags without touching the source text
                   (tasks 3+7)
* audit / compose / persistence — coverage + per-layer durations (acceptance),
  FINAL artifact, and DB publish that replaces only non-manual nodes with
  source=AGENT_FINAL so the Java display filter keeps showing the confirmed
  schedule only (task 8). Each node records its own status/failure stage via
  ``current_node`` (task 9).

The published DB/artifact contract is unchanged from the legacy pipeline.
``extract_final_contract_timeline`` in contract_document_parser stays as the
legacy implementation (not deleted, not called by this graph anymore).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from ..contract_document_parser import (
    _enrich_timeline_nodes,
    _extract_clause_timeline_nodes_v2,
    _json,
    _timeline_date_is_grounded,
    _year_from_date,
)
from ..harness.graph_builder import build_task_graph
from ..harness.models import Role, TaskSpec
from ..persistence import new_connection
from .nodes.context import freeze_case_snapshot, load_run_context
from .versioning import stamp_artifact_versions
from .state import merge_llm_usage

logger = logging.getLogger(__name__)

TIMELINE_PROMPT_VERSION = "contract-timeline-enrich-v1"

# Classic CJK mojibake signatures (UTF-8 read as Latin-1) plus the Unicode
# replacement character. None of these appear in clean Chinese contract text.
_MOJIBAKE_PATTERN = re.compile(
    "�"                      # U+FFFD replacement character
    r"|â€"              # â€  (smart quotes misread)
    r"|Ã."                   # Ã?  (UTF-8 lead byte as Latin-1)
    r"|Â."                   # Â?  (UTF-8 lead byte as Latin-1)
    r"|ä¸"              # ä¸  (中)
    r"|åŒ"              # åŒ  (同)
    r"|çš„"        # çš„ (的)
    r"|æ˜¯"        # æ˜¯ (是)
    r"|æ­£"        # æ­£ (正)
    r"|ðŸ"              # ðŸ  (emoji)
)


# ── planner / retriever DB steps ─────────────────────────────────────────────

def _select_timeline_document(case_id: int, document_id: int | None) -> dict | None:
    """Load the MAIN READY document row + parse diagnostics (planner step)."""
    with new_connection() as conn:
        with conn.cursor() as cur:
            if document_id:
                cur.execute(
                    """SELECT id, version, parse_diagnostics_json AS parseDiagnostics
                       FROM contract_document
                       WHERE id=%s AND case_id=%s AND document_type='MAIN'
                         AND parse_status='READY' AND COALESCE(deleted,0)=0
                       LIMIT 1""",
                    (document_id, case_id),
                )
            else:
                cur.execute(
                    """SELECT id, version, parse_diagnostics_json AS parseDiagnostics
                       FROM contract_document
                       WHERE case_id=%s AND document_type='MAIN'
                         AND parse_status='READY' AND COALESCE(deleted,0)=0
                       ORDER BY version DESC, id DESC LIMIT 1""",
                    (case_id,),
                )
            return cur.fetchone()


def _load_case_effective_date(case_id: int):
    with new_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT effective_date AS effectiveDate FROM contract_case WHERE id=%s",
                (case_id,),
            )
            row = cur.fetchone() or {}
            return row.get("effectiveDate")


def _load_timeline_clause_rows(case_id: int, document_id: int) -> list[dict]:
    """Load clause evidence for the document (retriever step — no OCR or
    embedding, the snapshot already owns parsed text)."""
    with new_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, clause_number AS clauseNumber, title, content,
                          clause_type AS clauseType, page_number AS pageNumber,
                          start_offset AS startOffset, end_offset AS endOffset
                   FROM contract_clause
                   WHERE case_id=%s AND document_id=%s
                   ORDER BY id""",
                (case_id, document_id),
            )
            return list(cur.fetchall())


def _parse_diagnostics(raw) -> dict:
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


# ── nodes ────────────────────────────────────────────────────────────────────

def select_timeline_scope(state: dict[str, Any]) -> dict[str, Any]:
    """Planner: pick the MAIN document, the date basis and the quality gate."""
    analysis_workflow = state.get("analysis_workflow") or {}
    case_id = int(state.get("subject_id") or 0)
    document_id = int(analysis_workflow.get("documentId") or 0) or None
    document = _select_timeline_document(case_id, document_id)
    if not document:
        raise ValueError("合同正文尚未解析完成，无法生成正式履约日程")
    document_id = int(document["id"])
    effective_date = _load_case_effective_date(case_id)
    diagnostics = _parse_diagnostics(document.get("parseDiagnostics"))
    quality = (diagnostics or {}).get("quality") or {}
    scope = {
        "caseId": case_id,
        "documentId": document_id,
        "documentVersion": int(document.get("version") or 1),
        "effectiveDate": effective_date,
        "inferredYear": _year_from_date(effective_date),
        "quality": quality,
        "requireLlm": True,
    }
    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "select_timeline_scope",
        "timeline_scope": scope,
        "observations": [{
            "callId": f"timeline-scope-{state.get('run_id', 0)}",
            "planStepId": "select_timeline_scope",
            "toolName": "selectTimelineScope",
            "arguments": {
                "caseId": case_id,
                "documentId": document_id,
            },
            "output": {
                "documentId": document_id,
                "documentVersion": scope["documentVersion"],
                "effectiveDateKnown": effective_date is not None,
                "qualityLevel": quality.get("level"),
            },
            "status": "DONE",
        }],
    }


def load_timeline_clause_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Retriever: load the clause evidence the rule layer runs on."""
    scope = state.get("timeline_scope") or {}
    clauses = _load_timeline_clause_rows(
        int(scope.get("caseId") or state.get("subject_id") or 0),
        int(scope.get("documentId") or 0),
    )
    if not clauses:
        raise ValueError("合同条款证据为空，无法生成正式履约日程")
    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "load_timeline_clause_evidence",
        "timeline_clauses": clauses,
        "observations": [{
            "callId": f"timeline-clauses-{state.get('run_id', 0)}",
            "planStepId": "load_timeline_clause_evidence",
            "toolName": "loadTimelineClauseEvidence",
            "arguments": {
                "caseId": scope.get("caseId"),
                "documentId": scope.get("documentId"),
            },
            "output": {"clauseCount": len(clauses)},
            "status": "DONE",
        }],
    }


def extract_rule_timeline_candidates(state: dict[str, Any]) -> dict[str, Any]:
    """Rule layer (Phase 6, task 1): deterministic time candidates.

    Date resolution is 100% code (``_resolve_relative_date`` inside the rule
    extractor) — the LLM never computes final dates (task 4). Unresolvable
    relative terms stay conditional (task 5). Mojibake, low-quality OCR and a
    missing base date are flagged on the node, never "fixed" by rewriting the
    source text (task 7).
    """
    start = time.monotonic()
    clauses = state.get("timeline_clauses") or []
    scope = state.get("timeline_scope") or {}
    effective_date = scope.get("effectiveDate")
    inferred_year = scope.get("inferredYear") or _year_from_date(effective_date)
    quality = scope.get("quality") or {}

    nodes: list[dict] = []
    seen: set[str] = set()
    for clause in clauses:
        nodes.extend(
            _extract_clause_timeline_nodes_v2(clause, inferred_year, effective_date, seen)
        )
    candidate_count = len(nodes)

    if quality.get("level") == "LOW":
        for node in nodes:
            node["status"] = "NEEDS_REVIEW"
            node["confidence"] = min(float(node.get("confidence") or 0), 0.35)
            node["citation"]["textQuality"] = {
                **(node["citation"].get("textQuality") or {}),
                "documentQuality": quality,
                "requiresReview": True,
                "qualityNotice": "原文可能存在识别误差，日期和数字请核对合同原页",
            }

    mojibake_count = 0
    date_basis_uncertain_count = 0
    for node in nodes:
        citation = node.setdefault("citation", {})
        full_text = str(citation.get("fullQuote") or "")
        if _MOJIBAKE_PATTERN.search(full_text):
            mojibake_count += 1
            node["status"] = "NEEDS_REVIEW"
            node["confidence"] = min(float(node.get("confidence") or 0), 0.35)
            citation["textQuality"] = {
                **(citation.get("textQuality") or {}),
                "mojibakeRisk": True,
                "requiresReview": True,
                "qualityNotice": "条款原文疑似乱码或识别错误，请核对合同原页",
            }
        if not effective_date and (
            node.get("date") is None
            or citation.get("extractionMode") == "TEXT_DATE_INFERRED_YEAR"
        ):
            # 不确定基准日期：生效日期缺失时，推断年份/相对期限都不可信。
            date_basis_uncertain_count += 1
            citation["dateBasis"] = {
                **(citation.get("dateBasis") or {}),
                "effectiveDateMissing": True,
                "requiresReview": True,
            }

    duration_ms = round((time.monotonic() - start) * 1000)
    scope_with_rule_ms = {**scope, "ruleDurationMs": duration_ms}
    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "extract_rule_timeline_candidates",
        "timeline_scope": scope_with_rule_ms,
        "timeline_candidates": nodes,
        "observations": [{
            "callId": f"timeline-rule-{state.get('run_id', 0)}",
            "planStepId": "extract_rule_timeline_candidates",
            "toolName": "extractRuleTimelineCandidates",
            "arguments": {
                "caseId": scope.get("caseId"),
                "documentId": scope.get("documentId"),
                "clauseCount": len(clauses),
            },
            "output": {
                "candidateCount": candidate_count,
                "mojibakeFlaggedCount": mojibake_count,
                "dateBasisUncertainCount": date_basis_uncertain_count,
                "durationMs": duration_ms,
            },
            "status": "DONE",
        }],
    }


def enrich_timeline_candidates(state: dict[str, Any]) -> dict[str, Any]:
    """LLM layer (Phase 6, task 2): responsibility, action, trigger, term and
    consequence are judged on the complete clause text (task 6). Strict mode:
    the formal schedule is never published without LLM review (task 8)."""
    start = time.monotonic()
    nodes = list(state.get("timeline_candidates") or [])
    clauses = state.get("timeline_clauses") or []
    scope = state.get("timeline_scope") or {}
    require_llm = bool(scope.get("requireLlm", False))

    enriched, enrichment = _enrich_timeline_nodes(nodes, clauses, strict=require_llm)
    if require_llm and nodes and enrichment.get("status") != "LLM_ENRICHED":
        raise RuntimeError("正式履约日程语义复核暂不可用，请稍后重试")
    enrichment = {**enrichment, "durationMs": round((time.monotonic() - start) * 1000)}

    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "enrich_timeline_candidates",
        "timeline_candidates": enriched,
        "timeline_enrichment": enrichment,
        "llm_usage": merge_llm_usage(
            state, "enrich_timeline_candidates", enrichment.get("llmUsage") or {}
        ),
        "observations": [{
            "callId": f"timeline-llm-{state.get('run_id', 0)}",
            "planStepId": "enrich_timeline_candidates",
            "toolName": "enrichTimelineCandidates",
            "arguments": {
                "caseId": scope.get("caseId"),
                "documentId": scope.get("documentId"),
                "candidateCount": len(nodes),
            },
            "output": {
                "status": enrichment.get("status"),
                "returned": enrichment.get("returned"),
                "dropped": enrichment.get("dropped"),
                "retryCount": enrichment.get("retryCount"),
                "durationMs": enrichment.get("durationMs"),
            },
            "status": "DONE",
        }],
    }


def validate_timeline_nodes(state: dict[str, Any]) -> dict[str, Any]:
    """Validation layer (Phase 6, task 3): dedup, source lineage, complete
    citations. The original text is never rewritten — grounding problems are
    flagged, not patched (task 7)."""
    start = time.monotonic()
    nodes = list(state.get("timeline_candidates") or [])
    clauses = state.get("timeline_clauses") or []
    scope = state.get("timeline_scope") or {}
    clause_text_by_id = {
        str(clause.get("id")): str(clause.get("content") or "")
        for clause in clauses
    }

    validated: list[dict] = []
    seen_keys: set[str] = set()
    dropped_duplicates = 0
    ungrounded_quotes = 0
    repaired_citations = 0
    conditional_count = 0
    needs_review_count = 0
    for node in nodes:
        key = "|".join(str(node.get(field)) for field in (
            "clauseId", "date", "condition", "nodeType", "label",
        ))
        if key in seen_keys:
            dropped_duplicates += 1
            continue
        seen_keys.add(key)

        citation = node.setdefault("citation", {})
        full_text = clause_text_by_id.get(str(node.get("clauseId"))) or ""
        if full_text and citation.get("fullQuote") != full_text:
            # Complete citation (task 6) — additive repair of the citation,
            # never a rewrite of the clause text itself.
            citation["fullQuote"] = full_text
            repaired_citations += 1
        quote = str(citation.get("quote") or "")
        if quote and full_text and quote not in full_text:
            citation["quoteUngrounded"] = True
            node["status"] = "NEEDS_REVIEW"
            ungrounded_quotes += 1

        if node.get("date") and not _timeline_date_is_grounded(
            node.get("date"),
            full_text or quote,
            citation.get("extractionMode"),
            node.get("condition"),
            scope.get("effectiveDate"),
        ):
            # A date that cannot be quoted or deterministically reproduced is
            # never safe to publish. Keep the real condition for review, but
            # remove the fabricated date from the formal schedule.
            citation["dateUngrounded"] = True
            citation.setdefault("issues", []).append("日期未在合同原文中落地")
            node["date"] = None
            node["status"] = "NEEDS_REVIEW"

        if node.get("date") is None:
            conditional_count += 1
            if not node.get("condition"):
                node["status"] = "NEEDS_REVIEW"
                citation.setdefault("issues", []).append("无日期且无条件文本")

        # Source lineage (task 3): the rule origin and the LLM review step are
        # both kept; the row-level source becomes AGENT_FINAL at persistence.
        lineage = ["RULE_CANDIDATE"]
        if citation.get("timelineEnrichment"):
            lineage.append("LLM_ENRICHED")
        citation["sourceLineage"] = lineage

        if float(node.get("confidence") or 0) < 0.8:
            node["status"] = "NEEDS_REVIEW"
        if node.get("status") == "NEEDS_REVIEW":
            needs_review_count += 1
        validated.append(node)

    mojibake_count = len([
        node for node in validated
        if (node.get("citation") or {}).get("textQuality", {}).get("mojibakeRisk")
    ])
    date_basis_uncertain = len([
        node for node in validated
        if (node.get("citation") or {}).get("dateBasis", {}).get("effectiveDateMissing")
    ])
    duration_ms = round((time.monotonic() - start) * 1000)
    validation = {
        "workUnitId": "timeline_validation",
        "nodeCount": len(validated),
        "droppedDuplicateCount": dropped_duplicates,
        "conditionalNodeCount": conditional_count,
        "ungroundedQuoteCount": ungrounded_quotes,
        "repairedCitationCount": repaired_citations,
        "needsReviewCount": needs_review_count,
        "mojibakeFlaggedCount": mojibake_count,
        "dateBasisUncertainCount": date_basis_uncertain,
        "durationMs": duration_ms,
    }
    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "validate_timeline_nodes",
        "timeline_candidates": validated,
        "timeline_validation": validation,
        "observations": [{
            "callId": f"timeline-validation-{state.get('run_id', 0)}",
            "planStepId": "validate_timeline_nodes",
            "toolName": "validateTimelineNodes",
            "arguments": {"candidateCount": len(nodes)},
            "output": validation,
            "status": "DONE",
        }],
    }


def audit_timeline_coverage(state: dict[str, Any]) -> dict[str, Any]:
    """Coverage audit: citation support + per-layer durations (acceptance:
    规则层、LLM 层和校验层耗时可分别观测)."""
    nodes = state.get("timeline_candidates") or []
    enrichment = state.get("timeline_enrichment") or {}
    validation = state.get("timeline_validation") or {}
    scope = state.get("timeline_scope") or {}
    cited = [node for node in nodes if (node.get("citation") or {}).get("quote")]
    audit = {
        "workUnitId": "timeline_coverage_audit",
        "totalNodes": len(nodes),
        "citedNodes": len(cited),
        "citationSupportRate": round(len(cited) / len(nodes), 4) if nodes else 0.0,
        "llmReviewedCount": int(enrichment.get("returned") or 0),
        "llmDroppedCount": int(enrichment.get("dropped") or 0),
        "needsReviewCount": int(validation.get("needsReviewCount") or 0),
        "conditionalNodeCount": int(validation.get("conditionalNodeCount") or 0),
        "stageDurationsMs": {
            "ruleLayer": int(scope.get("ruleDurationMs") or 0),
            "llmLayer": int(enrichment.get("durationMs") or 0),
            "validationLayer": int(validation.get("durationMs") or 0),
        },
    }
    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "audit_timeline_coverage",
        "timeline_audit": audit,
        "observations": [{
            "callId": f"timeline-audit-{state.get('run_id', 0)}",
            "planStepId": "audit_timeline_coverage",
            "toolName": "auditTimelineCoverage",
            "arguments": {"nodeCount": len(nodes)},
            "output": audit,
            "status": "DONE",
        }],
    }


def compose_final_timeline(state: dict[str, Any]) -> dict[str, Any]:
    """Composer: the FINAL artifact. Only the reviewed, validated schedule is
    exposed (task 8) — rule-only fallbacks are never published."""
    scope = state.get("timeline_scope") or {}
    nodes = state.get("timeline_candidates") or []
    validation = state.get("timeline_validation") or {}
    audit = state.get("timeline_audit") or {}
    artifact = {
        "reportType": "TIMELINE_EXTRACTION_REPORT",
        "title": "正式履约日程",
        "summary": f"已基于合同条款证据生成 {len(nodes)} 个经语义复核的履约节点。",
        "analysisMode": "LLM_REVIEWED_TIMELINE",
        "documentId": scope.get("documentId"),
        "documentVersion": int(scope.get("documentVersion") or 1),
        "timelineNodeCount": len(nodes),
        "nodes": nodes,
        "content": {
            "timelineNodeCount": len(nodes),
            "publicationStatus": "FINAL",
            "ruleOnlyFallbackPublished": False,
            "stageDurationsMs": (audit or {}).get("stageDurationsMs") or {},
            "validation": {
                key: validation.get(key)
                for key in ("needsReviewCount", "conditionalNodeCount",
                            "mojibakeFlaggedCount", "dateBasisUncertainCount")
            },
        },
    }

    stamp_artifact_versions(state, artifact)

    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "compose_final_timeline",
        "artifact": artifact,
        "observations": [{
            "callId": f"final-timeline-{state.get('run_id', 0)}",
            "planStepId": "compose_final_timeline",
            "toolName": "publishFinalContractTimeline",
            "arguments": {
                "caseId": scope.get("caseId") or state.get("subject_id"),
                "documentId": scope.get("documentId"),
            },
            "output": {
                "timelineNodeCount": len(nodes),
                "documentId": scope.get("documentId"),
                "stageDurationsMs": (audit or {}).get("stageDurationsMs"),
            },
            "status": "DONE",
        }],
    }


def _persist_final_timeline_rows(
    cur, case_id: int, document_id: int, nodes: list[dict]
) -> list[dict]:
    """Insert the reviewed schedule rows with source=AGENT_FINAL (legacy-compatible)."""
    inserted: list[dict] = []
    for index, node in enumerate(nodes):
        for required in ("clauseId", "nodeType", "label", "citation"):
            if node.get(required) is None:
                raise ValueError(f"第 {index + 1} 个履约节点缺少必需字段 {required}")
        cur.execute(
            """INSERT INTO contract_timeline_node
               (case_id, document_id, clause_id, node_type, label, node_date,
                condition_text, responsible_party, business_meaning, citation_json,
                confidence, source, status, manual_override)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)""",
            (
                case_id,
                document_id,
                node["clauseId"],
                node["nodeType"],
                node["label"],
                node.get("date"),
                node.get("condition"),
                node["responsibleParty"],
                node["businessMeaning"],
                _json(node["citation"]),
                node["confidence"],
                "AGENT_FINAL",
                node["status"],
            ),
        )
        node["id"] = cur.lastrowid
        inserted.append(node)
    return inserted


def persist_final_timeline_nodes(state: dict[str, Any]) -> dict[str, Any]:
    """Persistence: atomically replace non-manual nodes (task 8) and mark the
    workflow complete — same DB contract as the legacy pipeline."""
    scope = state.get("timeline_scope") or {}
    nodes = state.get("timeline_candidates") or []
    case_id = int(scope.get("caseId") or state.get("subject_id") or 0)
    document_id = int(scope.get("documentId") or 0)
    run_id = int(state.get("run_id") or 0)

    with new_connection() as conn:
        with conn.cursor() as cur:
            # Manually maintained nodes stay intact; previously published
            # automatic nodes are replaced atomically by this version.
            cur.execute(
                """DELETE FROM contract_timeline_node
                   WHERE case_id=%s AND document_id=%s AND manual_override=0""",
                (case_id, document_id),
            )
            inserted = _persist_final_timeline_rows(cur, case_id, document_id, nodes)
            cur.execute(
                """UPDATE contract_analysis_workflow
                   SET timeline_run_id=%s, timeline_status='COMPLETED',
                       current_stage='RISK_REVIEW', last_error=NULL
                   WHERE case_id=%s AND document_id=%s""",
                (run_id, case_id, document_id),
            )
        conn.commit()

    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "persist_final_timeline_nodes",
        "observations": [{
            "callId": f"timeline-persist-{state.get('run_id', 0)}",
            "planStepId": "persist_final_timeline_nodes",
            "toolName": "persistFinalTimelineNodes",
            "arguments": {"caseId": case_id, "documentId": document_id},
            "output": {"timelineNodeCount": len(inserted)},
            "status": "DONE",
        }],
    }


# §4.2 role → skeleton stage mapping for the timeline (PRD Phase 6):
#   context          = load_run_context + freeze_case_snapshot
#   planner          = select_timeline_scope (document / date basis / quality)
#   retriever        = load_timeline_clause_evidence (no OCR / embedding)
#   analyzer         = extract_rule_timeline_candidates (规则层) +
#                      enrich_timeline_candidates (LLM 层)
#   validator        = validate_timeline_nodes (去重 / 来源 / 完整引用 / 风险标记)
#   coverage_auditor = audit_timeline_coverage (引用支持率 + 分层耗时)
#   composer         = compose_final_timeline
#   persistence      = persist_final_timeline_nodes
# The timeline has no interrupt stage (manual confirmation happens on the
# Java side), so human_gate is None.
TIMELINE_SPEC = TaskSpec(
    task_type="TIMELINE_EXTRACTION",
    graph_name="timeline_extraction",
    # In-place migration (same adapter name and published DB contract as the
    # legacy pipeline), so the runtime version stays v1 like extraction.
    graph_version="v1",
    prompt_version=TIMELINE_PROMPT_VERSION,
    context=Role((
        ("load_run_context", load_run_context),
        ("freeze_case_snapshot", freeze_case_snapshot),
    )),
    planner=Role((
        ("select_timeline_scope", select_timeline_scope),
    )),
    retriever=Role((
        ("load_timeline_clause_evidence", load_timeline_clause_evidence),
    )),
    analyzer=Role((
        ("extract_rule_timeline_candidates", extract_rule_timeline_candidates),
        ("enrich_timeline_candidates", enrich_timeline_candidates),
    )),
    validator=Role((
        ("validate_timeline_nodes", validate_timeline_nodes),
    )),
    coverage_auditor=Role((
        ("audit_timeline_coverage", audit_timeline_coverage),
    )),
    composer=Role((
        ("compose_final_timeline", compose_final_timeline),
    )),
    persistence=Role((
        ("persist_final_timeline_nodes", persist_final_timeline_nodes),
    )),
    edges=(
        ("select_timeline_scope", "load_timeline_clause_evidence"),
        ("load_timeline_clause_evidence", "extract_rule_timeline_candidates"),
        ("extract_rule_timeline_candidates", "enrich_timeline_candidates"),
        ("enrich_timeline_candidates", "validate_timeline_nodes"),
        ("validate_timeline_nodes", "audit_timeline_coverage"),
        ("audit_timeline_coverage", "compose_final_timeline"),
        ("compose_final_timeline", "persist_final_timeline_nodes"),
    ),
)


def build_timeline_extraction_graph(checkpointer: Any = None) -> Any:
    return build_task_graph(TIMELINE_SPEC, checkpointer=checkpointer)


def publish_final_timeline(state: dict[str, Any]) -> dict[str, Any]:
    """Legacy single-node publish path (kept per project rule — legacy code is
    not deleted). The DAG above replaced it; ``extract_final_contract_timeline``
    in contract_document_parser remains the legacy pipeline it wraps."""
    from ..contract_document_parser import extract_final_contract_timeline

    analysis_workflow = state.get("analysis_workflow") or {}
    artifact = extract_final_contract_timeline(
        int(state.get("subject_id") or 0),
        int(state.get("run_id") or 0),
        int(analysis_workflow.get("documentId") or 0) or None,
    )
    return {
        "state_revision": int(state.get("state_revision") or 0) + 1,
        "current_node": "publish_final_timeline",
        "artifact": artifact,
        "observations": [{
            "callId": f"final-timeline-{state.get('run_id', 0)}",
            "planStepId": "publish_final_timeline",
            "toolName": "publishFinalContractTimeline",
            "arguments": {
                "caseId": state.get("subject_id"),
                "documentId": analysis_workflow.get("documentId"),
                "evidenceSnapshotHash": analysis_workflow.get("evidenceSnapshotHash"),
            },
            "output": {
                "timelineNodeCount": artifact.get("timelineNodeCount", 0),
                "documentId": artifact.get("documentId"),
            },
            "status": "DONE",
        }],
    }
