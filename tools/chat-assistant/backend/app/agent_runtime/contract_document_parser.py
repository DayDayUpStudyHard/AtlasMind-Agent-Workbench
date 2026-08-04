"""Deterministic contract document parsing pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings
from app.services.document_parser import DocumentParser
from app.services.embedding_service import EmbeddingService
from app.services.es_service import ESService
from app.services.llm_service import LLMService

from .contract_docx_parser import parse_docx_blocks
from .persistence import _conn

logger = logging.getLogger(__name__)

_CLAUSE_HEADING = re.compile(
    r"(?m)^\s*(第[一二三四五六七八九十百千零〇0-9]+条|[0-9]+(?:\.[0-9]+)*[、.．])\s*([^\n]*)"
)
_TYPE_KEYWORDS = (
    ("DATA_PROTECTION", ("个人信息", "数据保护", "隐私", "数据出境", "数据删除")),
    ("CONFIDENTIALITY", ("保密", "商业秘密", "机密信息")),
    ("LIABILITY", ("违约", "赔偿", "责任上限", "损失", "违约金")),
    ("PAYMENT", ("付款", "支付", "价款", "费用", "发票", "预付款")),
    ("ACCEPTANCE", ("验收", "验收标准")),
    ("TERMINATION", ("终止", "解除", "到期", "续签", "续约")),
    ("IP", ("知识产权", "著作权", "专利", "商标")),
    ("DELIVERY", ("交付", "服务范围", "服务内容", "交付物")),
    ("NOTICE", ("通知", "送达")),
)
_MAX_CLAUSES = 500
_CHUNK_SIZE = 900
_CHUNK_OVERLAP = 120
_SUPPORTED_FILE_TYPES = {"DOC", "DOCX", "PDF", "TXT", "MD"}
_ABSOLUTE_DATE_PATTERN = re.compile(
    r"(20\d{2})\s*[-年./]\s*(0?[1-9]|1[0-2])\s*[-月./]\s*(0?[1-9]|[12]\d|3[01])\s*日?"
)
_MONTH_DAY_PATTERN = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])月(0?[1-9]|[12]\d|3[01])日")
_RELATIVE_TERM_PATTERN = re.compile(
    r"(合同签署之日|合同生效|生效日|服务期满|合同到期|验收通过|收到发票|交付完成|付款通知|书面通知)"
    r"(前|后|起)?\s*(\d{1,3})\s*(个)?\s*(工作日|自然日|日|天|月|年)(内|前|后)?"
)
_DURATION_TERM_PATTERN = re.compile(
    r"(提前|逾期|超过|不少于|不晚于|不迟于|每|自|在|期满|续签|终止|验收|付款|交付|通知)?"
    r"[^，。；;\n]{0,20}?(\d{1,3})\s*(个)?\s*(工作日|自然日|日|天|月|年)(内|前|后|起|届满|期)?"
)
_CHINESE_DURATION_TERM_PATTERN = re.compile(
    r"(提前|逾期|超过|不少于|不晚于|不迟于|每|自|在|期满|续签|终止|验收|付款|交付|通知)?"
    r"[^，。；;\n]{0,20}?([一二两三四五六七八九十]+)\s*(个)?\s*(工作日|自然日|日|天|月|年)(内|前|后|起|届满|期)?"
)
_CN_DATE_TEXT = r"20\d{2}\s*" + "\u5e74" + r"\s*(?:0?[1-9]|1[0-2])\s*" + "\u6708" + r"\s*(?:0?[1-9]|[12]\d|3[01])\s*" + "\u65e5"
_CN_DATE_PATTERN = re.compile(
    r"(20\d{2})\s*" + "\u5e74" + r"\s*(0?[1-9]|1[0-2])\s*" + "\u6708" + r"\s*(0?[1-9]|[12]\d|3[01])\s*" + "\u65e5"
)
_ISO_DATE_PATTERN = re.compile(
    r"(20\d{2})\s*[-/.]\s*(0?[1-9]|1[0-2])\s*[-/.]\s*(0?[1-9]|[12]\d|3[01])"
)
_CN_DATE_RANGE_PATTERN = re.compile(
    rf"(?P<prefix>[^。\n；;]{{0,42}}?)"
    rf"(?P<start>{_CN_DATE_TEXT})\s*(?:起?\s*(?:至|到)|[-—~～])\s*(?P<end>{_CN_DATE_TEXT})"
    rf"(?P<suffix>[^。\n；;]{{0,42}})"
)
_CN_RELATIVE_TERM_PATTERN = re.compile(
    r"[^\u3002\n\uff1b;]{0,54}?"
    + "(?:合同期满|本合同期满|合同到期|服务期满|签订合同|合同签订|合同生效|生效|验收通过|收到发票|收到通知|交付完成|不可抗力)"
    + r"[^\u3002\n\uff1b;]{0,54}?"
    + "(?:前|后|内|以上|超过|不少于|不晚于|不迟于)"
    + r"[^\u3002\n\uff1b;]{0,20}?\d{1,3}\s*(?:个)?(?:工作日|自然日|日|天|个月|月|年)"
    + r"[^\u3002\n\uff1b;]{0,54}?"
)
_TEMPLATE_NOISE_TERMS = (
    "\u4e2d\u534e\u4eba\u6c11\u5171\u548c\u56fd\u79d1\u5b66\u6280\u672f\u90e8\u5370\u5236",
    "\u586b\u5199\u8bf4\u660e", "\u793a\u8303\u6587\u672c", "\u6280\u672f\u5408\u540c\u767b\u8bb0\u673a\u6784",
    "\u7b7e\u8ba2\u65f6\u95f4", "\u7b7e\u8ba2\u5730\u70b9", "\u5408\u540c\u7f16\u53f7",
)


def _json(data: dict | None) -> str:
    return json.dumps(data or {}, ensure_ascii=False)


def _latest_job_id(cur, document_id: int) -> int | None:
    cur.execute(
        """SELECT id
           FROM contract_document_job
           WHERE document_id=%s
           ORDER BY id DESC
           LIMIT 1""",
        (document_id,),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None


def _append_job_trace(
    cur,
    job_id: int | None,
    stage: str,
    summary: str,
    input_data: dict | None = None,
    output_data: dict | None = None,
    error_message: str | None = None,
) -> None:
    if not job_id:
        return
    cur.execute(
        """SELECT COALESCE(MAX(sequence_no), 0) + 1 AS nextSeq
           FROM contract_document_job_trace
           WHERE job_id=%s""",
        (job_id,),
    )
    row = cur.fetchone() or {}
    sequence_no = int(row.get("nextSeq") or 1)
    cur.execute(
        """INSERT INTO contract_document_job_trace
           (job_id, stage, sequence_no, summary, input_json, output_json, error_message)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (
            job_id,
            stage,
            sequence_no,
            summary[:500],
            _json(input_data),
            _json(output_data),
            error_message[:1000] if error_message else None,
        ),
    )


def _update_job(
    cur,
    job_id: int | None,
    status: str,
    stage: str,
    progress: int,
    error_message: str | None = None,
) -> None:
    if not job_id:
        return
    if status in {"READY", "FAILED"}:
        cur.execute(
            """UPDATE contract_document_job
               SET status=%s, stage=%s, progress=%s, error_message=%s, finished_at=NOW()
               WHERE id=%s""",
            (status, stage, progress, error_message[:1000] if error_message else None, job_id),
        )
    else:
        cur.execute(
            """UPDATE contract_document_job
               SET status=%s, stage=%s, progress=%s, error_message=%s
               WHERE id=%s""",
            (status, stage, progress, error_message[:1000] if error_message else None, job_id),
        )


def classify_clause(content: str) -> str:
    for clause_type, keywords in _TYPE_KEYWORDS:
        if any(keyword in content for keyword in keywords):
            return clause_type
    return "OTHER"


def split_contract_text(text: str) -> list[dict]:
    """Split common Chinese contract headings, falling back to paragraphs."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    matches = list(_CLAUSE_HEADING.finditer(normalized))
    segments: list[tuple[int, int, str, str]] = []
    if matches:
        if matches[0].start() > 0 and normalized[:matches[0].start()].strip():
            segments.append((0, matches[0].start(), "前言", "合同前言"))
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            segments.append((start, end, match.group(1).rstrip("、.．"), match.group(2).strip()))
    else:
        for index, match in enumerate(re.finditer(r"\S(?:.*?)(?=\n\s*\n|\Z)", normalized, re.DOTALL), 1):
            segments.append((match.start(), match.end(), str(index), ""))

    clauses = []
    for start, end, number, heading in segments[:_MAX_CLAUSES]:
        content = normalized[start:end].strip()
        if not content:
            continue
        title = heading.split("：", 1)[0].split(":", 1)[0].strip()
        if not title:
            title = content.splitlines()[0][:80]
        clauses.append({
            "clauseNumber": number,
            "title": title[:256],
            "content": content,
            "clauseType": classify_clause(content),
            "startOffset": start,
            "endOffset": end,
        })
    return clauses


def parse_contract_document(document_id: int) -> dict:
    """Parse and persist one contract document; failures become document state."""
    job_id: int | None = None
    intake_ids: list[int] = []
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, case_id, content_text, file_path, file_name
                       FROM contract_document WHERE id=%s FOR UPDATE""",
                    (document_id,),
                )
                document = cur.fetchone()
                if not document:
                    raise ValueError(f"Contract document {document_id} not found")

                job_id = _latest_job_id(cur, document_id)
                cur.execute(
                    "UPDATE contract_document SET parse_status='PARSING', parse_error=NULL WHERE id=%s",
                    (document_id,),
                )

                parsed = _parse_document_content(cur, job_id, document_id, document)
                content = parsed["content"]
                if not content.strip():
                    raise ValueError("Contract document text is empty")

                clauses = split_contract_text(content)
                if not clauses:
                    raise ValueError("No contract clauses could be extracted")

                _update_job(cur, job_id, "PROCESSING", "CLAUSE_SPLITTING", 55)
                _append_job_trace(
                    cur,
                    job_id,
                    "CLAUSE_SPLITTING",
                    f"按合同标题和段落规则切分出 {len(clauses)} 个候选条款",
                    {"documentId": document_id, "parser": parsed["parser"]},
                    {
                        "clauseCount": len(clauses),
                        "sampleTitles": [clause["title"] for clause in clauses[:5]],
                    },
                )

                cur.execute("DELETE FROM contract_clause_chunk WHERE document_id=%s", (document_id,))
                cur.execute(
                    """DELETE FROM contract_timeline_node
                       WHERE document_id=%s AND manual_override=0""",
                    (document_id,),
                )
                cur.execute("DELETE FROM contract_clause WHERE document_id=%s", (document_id,))
                persisted_clauses = []
                for clause in clauses:
                    cur.execute(
                        """INSERT INTO contract_clause
                           (document_id, case_id, clause_number, title, content,
                            page_number, clause_type, start_offset, end_offset)
                           VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s)""",
                        (
                            document_id,
                            document["case_id"],
                            clause["clauseNumber"],
                            clause["title"],
                            clause["content"],
                            clause["clauseType"],
                            clause["startOffset"],
                            clause["endOffset"],
                        ),
                    )
                    clause["id"] = cur.lastrowid
                    clause["caseId"] = document["case_id"]
                    clause["documentId"] = document_id
                    persisted_clauses.append(clause)
                _update_job(cur, job_id, "PROCESSING", "CLAUSE_PERSISTING", 80)
                _append_job_trace(
                    cur,
                    job_id,
                    "CLAUSE_PERSISTING",
                    f"已写入 {len(clauses)} 个可定位条款，供后续审查 Agent 调用",
                    {"documentId": document_id},
                    {"clauseCount": len(clauses)},
                )

                chunks = _persist_contract_chunks(cur, job_id, document["case_id"], document_id, persisted_clauses)
                timeline_nodes = _persist_timeline_nodes(cur, job_id, document["case_id"], document_id, persisted_clauses)
                index_result = _index_contract_chunks(cur, job_id, document_id)

                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                cur.execute(
                    """UPDATE contract_document
                       SET parse_status='READY', parse_error=NULL, page_count=%s,
                           content_hash=%s, content_text=%s
                       WHERE id=%s""",
                    (parsed["pageCount"], content_hash, content, document_id),
                )
                cur.execute(
                    """UPDATE contract_case
                       SET status=CASE
                           WHEN status='INTAKE_PARSING' THEN 'INTAKE_CONFIRMING'
                           ELSE 'READY_FOR_REVIEW'
                       END
                       WHERE id=%s AND status IN ('DRAFT','MATERIAL_PENDING','INTAKE_PARSING') AND deleted=0""",
                    (document["case_id"],),
                )
                cur.execute(
                    """SELECT id
                       FROM contract_intake
                       WHERE case_id=%s
                         AND source_type='FILE'
                         AND status IN ('FILE_PARSING','PENDING','FAILED')""",
                    (document["case_id"],),
                )
                intake_ids = [int(row["id"]) for row in cur.fetchall()]
                if intake_ids:
                    cur.execute(
                        """UPDATE contract_intake
                           SET status='PENDING', content_text=%s, content_hash=%s,
                               error_message=NULL
                           WHERE case_id=%s
                             AND source_type='FILE'
                             AND status IN ('FILE_PARSING','PENDING','FAILED')""",
                        (content, content_hash, document["case_id"]),
                    )
                _update_job(cur, job_id, "READY", "READY", 100)
                _append_job_trace(
                    cur,
                    job_id,
                    "READY",
                    "合同文档解析完成，条款证据已可用于审查 Agent",
                    {"documentId": document_id},
                    {
                        "documentId": document_id,
                        "caseId": document["case_id"],
                        "parser": parsed["parser"],
                        "clauseCount": len(clauses),
                        "chunkCount": len(chunks),
                        "timelineNodeCount": len(timeline_nodes),
                        "indexedChunkCount": index_result["indexed"],
                        "embeddedChunkCount": index_result["embedded"],
                        "blockCount": parsed["blockCount"],
                        "contentHash": content_hash,
                    },
                )
            conn.commit()
        if intake_ids:
            from .contract_intake_extractor import extract_intake

            for intake_id in intake_ids:
                extract_intake(intake_id)
        return {
            "documentId": document_id,
            "jobId": job_id,
            "status": "READY",
            "clauseCount": len(clauses),
            "intakeIds": intake_ids,
        }
    except Exception as exc:
        logger.exception("Contract document %s parsing failed", document_id)
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    if job_id is None:
                        job_id = _latest_job_id(cur, document_id)
                    cur.execute(
                        "UPDATE contract_document SET parse_status='FAILED', parse_error=%s WHERE id=%s",
                        (str(exc)[:1000], document_id),
                    )
                    cur.execute(
                        """UPDATE contract_case c
                           JOIN contract_document d ON d.case_id=c.id
                           SET c.status='MATERIAL_PENDING'
                           WHERE d.id=%s
                             AND c.status IN ('DRAFT','READY_FOR_REVIEW','INTAKE_PARSING','INTAKE_CONFIRMING')
                             AND c.deleted=0""",
                        (document_id,),
                    )
                    cur.execute(
                        """UPDATE contract_intake i
                           JOIN contract_document d ON d.case_id=i.case_id
                           SET i.status='FAILED', i.error_message=%s
                           WHERE d.id=%s
                             AND i.source_type='FILE'
                             AND i.status IN ('FILE_PARSING','PENDING','EXTRACTING')""",
                        (str(exc)[:1000], document_id),
                    )
                    _update_job(cur, job_id, "FAILED", "FAILED", 100, str(exc))
                    _append_job_trace(
                        cur,
                        job_id,
                        "FAILED",
                        "合同文档解析失败",
                        {"documentId": document_id},
                        {},
                        str(exc),
                    )
                conn.commit()
        except Exception:
            logger.exception("Could not persist parse failure for document %s", document_id)
        return {"documentId": document_id, "jobId": job_id, "status": "FAILED", "error": str(exc)}


def parse_inline_document(document_id: int) -> dict:
    """Backward-compatible entry point used by the existing internal route."""
    return parse_contract_document(document_id)


def _persist_contract_chunks(
    cur,
    job_id: int | None,
    case_id: int,
    document_id: int,
    clauses: list[dict],
) -> list[dict]:
    _update_job(cur, job_id, "PROCESSING", "CHUNKING", 84)
    chunks: list[dict] = []
    for clause in clauses:
        for chunk_index, chunk_text in enumerate(_iter_clause_chunks(clause["content"])):
            content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            cur.execute(
                """INSERT INTO contract_clause_chunk
                   (case_id, document_id, clause_id, clause_number, chunk_index,
                    chunk_text, source_page, content_hash, embedding_status, index_status)
                   VALUES (%s,%s,%s,%s,%s,%s,1,%s,'PENDING','PENDING')""",
                (
                    case_id,
                    document_id,
                    clause["id"],
                    clause["clauseNumber"],
                    chunk_index,
                    chunk_text,
                    content_hash,
                ),
            )
            chunks.append({
                "id": cur.lastrowid,
                "case_id": case_id,
                "document_id": document_id,
                "clause_id": clause["id"],
                "clause_number": clause["clauseNumber"],
                "chunk_index": chunk_index,
                "chunk_text": chunk_text,
                "source_page": 1,
                "title": clause["title"],
                "clause_type": clause["clauseType"],
            })

    _append_job_trace(
        cur,
        job_id,
        "CHUNKING",
        f"已生成 {len(chunks)} 个合同私有证据切片",
        {"documentId": document_id, "clauseCount": len(clauses)},
        {"chunkCount": len(chunks), "chunkSize": _CHUNK_SIZE, "overlap": _CHUNK_OVERLAP},
    )
    return chunks


def _iter_clause_chunks(content: str):
    text = _normalize_text(content)
    if not text:
        return
    if len(text) <= _CHUNK_SIZE:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        yield text[start:end]
        if end >= len(text):
            break
        start = max(end - _CHUNK_OVERLAP, start + 1)


def _persist_timeline_nodes(
    cur,
    job_id: int | None,
    case_id: int,
    document_id: int,
    clauses: list[dict],
) -> list[dict]:
    _update_job(cur, job_id, "PROCESSING", "TIMELINE_EXTRACTING", 88)
    cur.execute(
        "SELECT effective_date AS effectiveDate FROM contract_case WHERE id=%s",
        (case_id,),
    )
    case_row = cur.fetchone() or {}
    inferred_year = _year_from_date(case_row.get("effectiveDate"))
    effective_date = case_row.get("effectiveDate")  # for relative date resolution
    nodes: list[dict] = []
    seen: set[str] = set()
    for clause in clauses:
        nodes.extend(_extract_clause_timeline_nodes_v2(clause, inferred_year, effective_date, seen))
    candidate_count = len(nodes)
    nodes, enrichment = _enrich_timeline_nodes(nodes, clauses)

    inserted = []
    for node in nodes:
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
                node.get("source", "RULE_CANDIDATE"),
                node["status"],
            ),
        )
        node["id"] = cur.lastrowid
        inserted.append(node)

    _append_job_trace(
        cur,
        job_id,
        "TIMELINE_EXTRACTING",
        f"时间候选提取并语义整理完成：{len(inserted)} 个可追溯节点",
        {"documentId": document_id, "ruleExtractor": "candidate-v2", "llmEnrichment": True},
        {
            "candidateCount": candidate_count,
            "timelineNodeCount": len(inserted),
            "needsReview": len([n for n in inserted if n["status"] == "NEEDS_REVIEW"]),
            "enrichment": enrichment,
            "sampleNodes": [
                {
                    "label": n["label"],
                    "date": n.get("date"),
                    "condition": n.get("condition"),
                    "clauseNumber": n["citation"].get("clauseNumber"),
                }
                for n in inserted[:5]
            ],
        },
    )
    return inserted


def _extract_clause_timeline_nodes(
    clause: dict, inferred_year: int, effective_date, seen: set[str]
) -> list[dict]:
    content = str(clause.get("content") or "")
    nodes: list[dict] = []
    for match in _ABSOLUTE_DATE_PATTERN.finditer(content):
        date = _safe_date(match.group(1), match.group(2), match.group(3))
        snippet = _snippet_around(content, match.start(), match.end())
        # Filter noisy matches: skip if snippet doesn't look like a timeline event
        if date and not _looks_like_timeline_term(snippet):
            continue
        _add_timeline_node(nodes, seen, clause, snippet, date, None, "TEXT_DATE", 0.92)

    for match in _MONTH_DAY_PATTERN.finditer(content):
        prefix = content[max(0, match.start() - 6):match.start()]
        if re.search(r"20\d{2}\s*[-年./]\s*$", prefix):
            continue
        date = _safe_date(str(inferred_year), match.group(1), match.group(2))
        snippet = _snippet_around(content, match.start(), match.end())
        if date and not _looks_like_timeline_term(snippet):
            continue
        _add_timeline_node(nodes, seen, clause, snippet, date, None, "TEXT_DATE_INFERRED_YEAR", 0.74)

    for pattern, mode, confidence in (
        (_RELATIVE_TERM_PATTERN, "RELATIVE_TERM", 0.88),
        (_DURATION_TERM_PATTERN, "DURATION_TERM", 0.68),
        (_CHINESE_DURATION_TERM_PATTERN, "DURATION_TERM", 0.68),
    ):
        for match in pattern.finditer(content):
            condition = match.group(0).replace("\n", " ").strip()
            snippet = _snippet_around(content, match.start(), match.end())
            if len(condition) < 2 or _is_date_fragment(condition) or not _looks_like_timeline_term(snippet):
                continue
            # Try to resolve relative date using contract effective_date
            resolved_date = _resolve_relative_date(condition, effective_date)
            if resolved_date:
                _add_timeline_node(nodes, seen, clause, snippet, resolved_date, condition,
                                   f"{mode}_RESOLVED", max(confidence, 0.75))
            else:
                _add_timeline_node(nodes, seen, clause, snippet, None, condition, mode, confidence)
    return nodes


def _add_timeline_node(
    nodes: list[dict],
    seen: set[str],
    clause: dict,
    quote: str,
    date: str | None,
    condition: str | None,
    source_mode: str,
    confidence: float,
) -> None:
    if not _quote_in_content(quote, str(clause.get("content") or "")):
        return
    if date is None and not condition:
        return
    node_type = _timeline_type(clause.get("clauseType"), quote)
    label = _timeline_label(node_type, quote)
    key = f"{clause.get('id')}|{date}|{condition}|{label}|{quote[:80]}"
    if key in seen:
        return
    seen.add(key)
    status = "EXTRACTED" if confidence >= 0.8 else "NEEDS_REVIEW"
    nodes.append({
        "clauseId": clause["id"],
        "nodeType": node_type,
        "label": label,
        "date": date,
        "condition": condition,
        "responsibleParty": _responsible_party(quote),
        "businessMeaning": _business_meaning(node_type, quote, source_mode),
        "confidence": confidence,
        "status": status,
        "source": "RULE_CANDIDATE",
        "citation": {
            "clauseId": clause["id"],
            "clauseNumber": clause.get("clauseNumber"),
            "title": clause.get("title"),
            "quote": quote,
            "page": 1,
            "extractionMode": source_mode,
        },
    })


_CN_DURATION_FOCUS_PATTERN = re.compile(
    r"(?:不可抗力[^。；;\n]{0,24}\d{1,3}\s*(?:个)?(?:工作日|自然日|日|天|个月|月|年)(?:以上|以内|内|前|后|届满)?)"
    r"|(?:(?:本合同|合同)?期满[^。；;\n]{0,12}(?:前|后|内)\s*\d{1,3}\s*(?:个)?(?:工作日|自然日|日|天|个月|月|年))"
    r"|(?:收到(?:发票|通知)[^。；;\n]{0,16}\d{1,3}\s*(?:个)?(?:工作日|自然日|日|天|个月|月|年)(?:内|前|后)?)"
    r"|(?:(?:验收|交付|付款|开具发票|书面通知)[^。；;\n]{0,20}\d{1,3}\s*(?:个)?(?:工作日|自然日|日|天|个月|月|年)(?:内|前|后)?)"
)


def _extract_clause_timeline_nodes_v2(
    clause: dict, inferred_year: int, effective_date, seen: set[str]
) -> list[dict]:
    content = str(clause.get("content") or "")
    nodes: list[dict] = []
    range_spans: list[tuple[int, int]] = []
    focus_spans: list[tuple[int, int]] = []

    for match in _CN_DATE_RANGE_PATTERN.finditer(content):
        context = f"{match.group('prefix')} {match.group('suffix')}"
        if _is_template_boilerplate(context) or _is_metadata_date_context(context):
            continue
        range_spans.append((match.start(), match.end()))
        kind = "SERVICE" if any(word in context for word in ("服务", "履行", "交付")) else "CONTRACT"
        quote = _snippet_around(content, match.start(), match.end())
        start_date = _normalize_cn_date(match.group("start"))
        end_date = _normalize_cn_date(match.group("end"))
        if start_date:
            _add_timeline_candidate(
                nodes, seen, clause, quote, start_date, None,
                "TEXT_DATE_RANGE", 0.95, f"{kind}_START",
                "技术服务开始" if kind == "SERVICE" else "合同开始",
            )
        if end_date:
            _add_timeline_candidate(
                nodes, seen, clause, quote, end_date, None,
                "TEXT_DATE_RANGE", 0.95, f"{kind}_END",
                "技术服务结束" if kind == "SERVICE" else "合同到期",
            )

    for match in _CN_DURATION_FOCUS_PATTERN.finditer(content):
        condition = re.sub(r"\s+", " ", match.group(0)).strip()
        quote = _snippet_around(content, match.start(), match.end())
        if len(condition) < 2 or _is_template_boilerplate(quote):
            continue
        focus_spans.append((match.start(), match.end()))
        resolved_date = _resolve_relative_date(condition, effective_date)
        _add_timeline_candidate(
            nodes, seen, clause, quote, resolved_date, condition,
            "DURATION_TERM_RESOLVED" if resolved_date else "DURATION_TERM",
            0.9 if resolved_date else 0.84,
        )

    for pattern, mode, confidence in (
        (_CN_DATE_PATTERN, "TEXT_DATE", 0.94),
        (_ISO_DATE_PATTERN, "TEXT_DATE", 0.92),
    ):
        for match in pattern.finditer(content):
            if any(start <= match.start() and match.end() <= end for start, end in range_spans):
                continue
            date = _safe_date(match.group(1), match.group(2), match.group(3))
            quote = _snippet_around(content, match.start(), match.end())
            if not date or _is_template_boilerplate(quote) or _is_metadata_date_context(quote) or not _looks_like_timeline_term_v2(quote):
                continue
            _add_timeline_candidate(nodes, seen, clause, quote, date, None, mode, confidence)

    for match in _MONTH_DAY_PATTERN.finditer(content):
        prefix = content[max(0, match.start() - 6):match.start()]
        if re.search(r"20\d{2}\s*[-年./]\s*$", prefix):
            continue
        date = _safe_date(str(inferred_year), match.group(1), match.group(2))
        quote = _snippet_around(content, match.start(), match.end())
        if not date or _is_template_boilerplate(quote) or _is_metadata_date_context(quote) or not _looks_like_timeline_term_v2(quote):
            continue
        _add_timeline_candidate(nodes, seen, clause, quote, date, None, "TEXT_DATE_INFERRED_YEAR", 0.72)

    for match in _CN_RELATIVE_TERM_PATTERN.finditer(content):
        if any(not (match.end() <= start or match.start() >= end) for start, end in focus_spans):
            continue
        condition = re.sub(r"\s+", " ", match.group(0)).strip()
        quote = _snippet_around(content, match.start(), match.end())
        if len(condition) < 2 or _is_template_boilerplate(quote):
            continue
        resolved_date = _resolve_relative_date(condition, effective_date)
        _add_timeline_candidate(
            nodes, seen, clause, quote, resolved_date, condition,
            "DURATION_TERM_RESOLVED" if resolved_date else "DURATION_TERM",
            0.86 if resolved_date else 0.78,
        )

    for pattern, mode, confidence in (
        (_RELATIVE_TERM_PATTERN, "RELATIVE_TERM", 0.88),
        (_DURATION_TERM_PATTERN, "DURATION_TERM", 0.68),
        (_CHINESE_DURATION_TERM_PATTERN, "DURATION_TERM", 0.68),
    ):
        for match in pattern.finditer(content):
            if any(not (match.end() <= start or match.start() >= end) for start, end in focus_spans):
                continue
            condition = match.group(0).replace("\n", " ").strip()
            quote = _snippet_around(content, match.start(), match.end())
            if len(condition) < 2 or _is_date_fragment(condition) or not _looks_like_timeline_term_v2(quote):
                continue
            resolved_date = _resolve_relative_date(condition, effective_date)
            if resolved_date:
                _add_timeline_candidate(
                    nodes, seen, clause, quote, resolved_date, condition,
                    f"{mode}_RESOLVED", max(confidence, 0.75),
                )
            else:
                _add_timeline_candidate(nodes, seen, clause, quote, None, condition, mode, confidence)

    return _limit_clause_timeline_nodes(nodes)


def _add_timeline_candidate(
    nodes: list[dict],
    seen: set[str],
    clause: dict,
    quote: str,
    date: str | None,
    condition: str | None,
    source_mode: str,
    confidence: float,
    node_type: str | None = None,
    label: str | None = None,
) -> None:
    before = len(nodes)
    _add_timeline_node(nodes, seen, clause, quote, date, condition, source_mode, confidence)
    if len(nodes) == before:
        return
    node = nodes[-1]
    if node_type:
        node["nodeType"] = node_type
    node["label"] = label or _rule_timeline_label(node["nodeType"], quote, condition)
    node["businessMeaning"] = _rule_business_meaning(node, quote)


def _limit_clause_timeline_nodes(nodes: list[dict], limit: int = 8) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for node in nodes:
        key = f"{node.get('date')}|{node.get('condition')}|{node.get('nodeType')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(node)
    return deduped[:limit]


def _is_template_boilerplate(text: str) -> bool:
    return any(term in text for term in ("填写说明", "示范文本", "中华人民共和国科学技术部印制", "技术合同登记机构"))


def _is_metadata_date_context(text: str) -> bool:
    if any(term in text for term in (
        "\u7b7e\u8ba2\u65f6\u95f4", "\u7b7e\u8ba2\u65e5\u671f", "\u7b7e\u7f72\u65e5\u671f",
        "\u7b7e\u8ba2\u5730\u70b9", "\u5408\u540c\u7f16\u53f7", "\u5408\u540c\u53f7", "\u7248\u672c\u53f7",
        "\u5370\u5236", "\u8bf4\u660e",
    )):
        return True
    return "\u6709\u6548\u671f\u9650" in text and any(term in text for term in (
        "\u7b7e\u8ba2", "\u7b7e\u7f72", "\u5730\u70b9", "\u5370\u5236", "\u586b\u5199\u8bf4\u660e",
    ))


def _looks_like_timeline_term_v2(snippet: str) -> bool:
    return any(term in snippet for term in (
        "生效", "有效期", "到期", "期满", "服务", "交付", "履约", "履行", "结算",
        "付款", "支付", "发票", "验收", "通知", "书面通知", "续签", "续约",
        "终止", "解除", "不可抗力", "完成",
    ))


def _normalize_cn_date(value: str) -> str | None:
    value = str(value or "").strip().replace(" ", "")
    match = _CN_DATE_PATTERN.search(value)
    if not match:
        return None
    return _safe_date(match.group(1), match.group(2), match.group(3))


def _rule_timeline_label(node_type: str, quote: str, condition: str | None) -> str:
    if node_type == "TERMINATION" and "不可抗力" in quote:
        return "不可抗力终止条件"
    if condition:
        compact = re.sub(r"\s+", " ", condition).strip()
        return compact[:36]
    compact = re.sub(r"\s+", " ", quote).strip()
    if node_type == "PAYMENT" and "发票" in compact:
        return "开票期限"
    if node_type == "PAYMENT":
        return "付款期限"
    if node_type == "ACCEPTANCE":
        return "验收期限"
    if node_type == "DELIVERY":
        return "服务/交付期限"
    if node_type == "NOTICE":
        return "书面通知期限"
    if node_type == "RENEWAL":
        return "续签协商期限"
    if node_type == "TERMINATION":
        return "解除/终止条件"
    return compact[:32] or "合同时间节点"


def _rule_business_meaning(node: dict, quote: str) -> str:
    label = node.get("label") or "合同时间节点"
    date_or_condition = node.get("condition") or node.get("date") or "约定期限"
    if node.get("date"):
        return f"需要关注“{label}”对应的时间点：{date_or_condition}。"
    return f"需要关注“{label}”对应的约束条件：{date_or_condition}。"


def _enrich_timeline_nodes(nodes: list[dict], clauses: list[dict]) -> tuple[list[dict], dict]:
    if not nodes:
        return [], {"status": "SKIPPED", "reason": "NO_CANDIDATES"}
    clause_text_by_id = {
        str(clause.get("id")): str(clause.get("content") or "")
        for clause in clauses
    }
    candidates = []
    for index, node in enumerate(nodes[:60]):
        candidate_id = f"timeline-{index + 1}"
        node["candidateId"] = candidate_id
        quote = str(node.get("citation", {}).get("quote") or "")
        clause_text = clause_text_by_id.get(str(node.get("clauseId"))) or ""
        candidates.append({
            "candidateId": candidate_id,
            "nodeType": node.get("nodeType"),
            "date": node.get("date"),
            "condition": node.get("condition"),
            "label": node.get("label"),
            "clauseNumber": node.get("citation", {}).get("clauseNumber"),
            "clauseTitle": node.get("citation", {}).get("title"),
            "quote": quote,
            "context": _timeline_clause_excerpt(clause_text, quote),
        })
    try:
        response = LLMService().enrich_contract_timeline(candidates)
    except Exception as exc:
        logger.warning("Contract timeline LLM enrichment failed: %s", exc)
        return nodes, {"status": "FALLBACK_RULE", "error": str(exc)[:300]}
    result_by_id = {
        str(item.get("candidateId")): item
        for item in (response.get("nodes") or [])
        if isinstance(item, dict) and item.get("candidateId")
    }
    enriched: list[dict] = []
    dropped = 0
    for node in nodes:
        result = result_by_id.get(node.get("candidateId"))
        if result and result.get("keep") is False:
            dropped += 1
            continue
        if result:
            label = str(result.get("label") or "").strip()[:128]
            meaning = str(result.get("businessMeaning") or "").strip()[:500]
            actor = str(result.get("responsibleParty") or "").strip().upper()
            event_type = str(result.get("eventType") or "").strip().upper()
            if label:
                node["label"] = label
            if meaning:
                node["businessMeaning"] = meaning
            if actor in {"OUR_ENTITY", "COUNTERPARTY", "BOTH", "UNKNOWN"}:
                node["responsibleParty"] = actor
            if event_type in {"CONTRACT_START", "CONTRACT_END", "SERVICE_START", "SERVICE_END", "PAYMENT", "ACCEPTANCE", "NOTICE", "RENEWAL", "TERMINATION", "PENALTY", "OTHER"}:
                node["nodeType"] = event_type
            try:
                node["confidence"] = min(0.99, max(float(node.get("confidence") or 0), float(result.get("confidence") or 0)))
            except (TypeError, ValueError):
                pass
            node["source"] = "LLM_ENRICHED"
            node["citation"]["timelineEnrichment"] = {
                "keep": result.get("keep", True),
                "reason": str(result.get("reason") or "")[:300],
            }
            if node["confidence"] < 0.8:
                node["status"] = "NEEDS_REVIEW"
        enriched.append(node)
    enriched.extend(nodes[60:])
    return enriched, {
        "status": "LLM_ENRICHED",
        "requested": len(candidates),
        "returned": len(result_by_id),
        "dropped": dropped,
    }


def _timeline_clause_excerpt(content: str, quote: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if not text:
        return ""
    needle = re.sub(r"\s+", " ", str(quote or "")).strip()
    if needle:
        idx = text.find(needle)
        if idx >= 0:
            start = max(0, idx - 80)
            end = min(len(text), idx + len(needle) + 120)
            return text[start:end][:limit]
        compact_text = text.replace(" ", "")
        compact_needle = needle.replace(" ", "")
        idx = compact_text.find(compact_needle)
        if idx >= 0:
            start = max(0, idx - 80)
            end = min(len(text), idx + len(needle) + 120)
            return text[start:end][:limit]
    return text[:limit]


def _index_contract_chunks(cur, job_id: int | None, document_id: int) -> dict:
    cur.execute(
        """SELECT ck.id, ck.case_id, ck.document_id, ck.clause_id, ck.clause_number,
                  ck.chunk_text, ck.source_page, c.title, c.clause_type
           FROM contract_clause_chunk ck
           LEFT JOIN contract_clause c ON c.id=ck.clause_id
           WHERE ck.document_id=%s
           ORDER BY ck.chunk_index ASC""",
        (document_id,),
    )
    rows = list(cur.fetchall())
    if not rows:
        return {"embedded": 0, "indexed": 0, "total": 0}

    _update_job(cur, job_id, "PROCESSING", "EMBEDDING", 92)
    embedding = EmbeddingService()
    vectors: list[list[float]] = [[] for _ in rows]
    embedding_error = ""
    embedded = 0
    if embedding.configured:
        try:
            vectors = embedding.embed_batch([row["chunk_text"] for row in rows])
            embedded = len([vector for vector in vectors if vector])
        except Exception as exc:
            embedding_error = str(exc)
            vectors = [[] for _ in rows]
    for row, vector in zip(rows, vectors):
        cur.execute(
            "UPDATE contract_clause_chunk SET embedding_status=%s WHERE id=%s",
            ("DONE" if vector else "FAILED" if embedding.configured else "SKIPPED", row["id"]),
        )
    _append_job_trace(
        cur,
        job_id,
        "EMBEDDING",
        f"合同切片向量化完成：{embedded}/{len(rows)}",
        {"documentId": document_id, "model": settings.embedding_model if embedding.configured else ""},
        {"total": len(rows), "embedded": embedded, "configured": embedding.configured},
        embedding_error or None,
    )

    _update_job(cur, job_id, "PROCESSING", "INDEXING", 96)
    es = ESService()
    indexed = 0
    index_ready = es.ensure_contract_index()
    if index_ready:
        es.delete_contract_document(document_id)
        for row, vector in zip(rows, vectors):
            ok = es.index_contract_chunk(row, embedding=vector or None)
            if ok:
                indexed += 1
            cur.execute(
                "UPDATE contract_clause_chunk SET index_status=%s WHERE id=%s",
                ("DONE" if ok else "FAILED", row["id"]),
            )
    else:
        cur.execute(
            "UPDATE contract_clause_chunk SET index_status='FAILED' WHERE document_id=%s",
            (document_id,),
        )
    _append_job_trace(
        cur,
        job_id,
        "INDEXING",
        f"合同私有 ES 索引完成：{indexed}/{len(rows)}",
        {"documentId": document_id, "index": settings.contract_index},
        {"total": len(rows), "indexed": indexed, "indexReady": index_ready},
        None if index_ready else "Elasticsearch 不可用或合同索引未就绪，已保留 MySQL 证据并可后续重建索引",
    )
    return {"embedded": embedded, "indexed": indexed, "total": len(rows)}


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _quote_in_content(quote: str, content: str) -> bool:
    normalized_quote = re.sub(r"\s+", "", quote or "")
    normalized_content = re.sub(r"\s+", "", content or "")
    return bool(normalized_quote) and normalized_quote in normalized_content


def _resolve_relative_date(condition: str, effective_date) -> str | None:
    """Resolve a Chinese relative date expression against the contract effective date.

    Examples: "签订合同后30日内" -> effective + 30d, "合同生效后180日" -> effective + 180d.
    Returns YYYY-MM-DD or None if unresolvable.
    """
    if not effective_date:
        return None
    from datetime import timedelta
    try:
        base = effective_date
        if hasattr(base, "strftime"):
            base_str = base.strftime("%Y-%m-%d")
            base = __import__("datetime").datetime.strptime(base_str, "%Y-%m-%d")
        elif isinstance(base, str):
            base = __import__("datetime").datetime.strptime(str(base)[:10], "%Y-%m-%d")
        else:
            return None
    except Exception:
        return None

    # "签订/生效后N日/天/个工作日内"
    m = re.search(r"(?:签订|生效|签署).*?[后之后]\s*(\d+)\s*(?:日|天|个工作日)", condition)
    if m:
        days = int(m.group(1))
        return (base + timedelta(days=days)).strftime("%Y-%m-%d")
    # "签订/生效后N个月"
    m = re.search(r"(?:签订|生效|签署).*?[后之后]\s*(\d+)\s*(?:个?月)", condition)
    if m:
        months = int(m.group(1))
        new_month = base.month + months
        new_year = base.year + (new_month - 1) // 12
        new_month = ((new_month - 1) % 12) + 1
        day = min(base.day, 28)
        return f"{new_year:04d}-{new_month:02d}-{day:02d}"
    # "合同到期前N日/个月"
    m = re.search(r"(?:到期|届满|终止).*?[前之前]\s*(\d+)\s*(?:日|天|个工作日|个?月)", condition)
    if m:
        # We don't have expiry_date here, skip
        return None
    return None


def _year_from_date(value) -> int:
    if value:
        try:
            return int(str(value)[:4])
        except Exception:
            pass
    from datetime import date
    return date.today().year


def _safe_date(year: str, month: str, day: str) -> str | None:
    from datetime import date
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except Exception:
        return None


def _snippet_around(content: str, start: int, end: int) -> str:
    left = max(0, start - 48)
    right = min(len(content), end + 72)
    return re.sub(r"\s+", " ", content[left:right]).strip()


def _is_date_fragment(condition: str) -> bool:
    value = re.sub(r"\s+", "", condition)
    if re.match(r".*20\d{2}年?$", value):
        return True
    if re.match(r"^(0?[1-9]|1[0-2])月$", value):
        return True
    if re.match(r"^(0?[1-9]|[12]\d|3[01])日(起|内|前|后)?$", value):
        return True
    return bool(re.match(r"^(至|自)?(0?[1-9]|1[0-2])月(0?[1-9]|[12]\d|3[01])日(起|内|前|后)?$", value))


def _looks_like_timeline_term(snippet: str) -> bool:
    keywords = (
        "生效", "到期", "期满", "续签", "终止", "解除", "提前", "逾期", "超过",
        "付款", "支付", "发票", "交付", "验收", "通知", "服务", "完成", "每月",
        "每季度", "每年",
    )
    return any(keyword in snippet for keyword in keywords)


def _timeline_type(clause_type: str | None, quote: str) -> str:
    text = f"{clause_type or ''} {quote}".upper()
    if "ACCEPTANCE" in text or "验收" in quote:
        return "ACCEPTANCE"
    if "TERMINATION" in text or any(k in quote for k in ("终止", "解除", "到期", "期满")) or (
        "不可抗力" in quote and any(k in quote for k in ("解除", "终止", "无法继续履行", "协商解除"))
    ):
        return "TERMINATION"
    if "PAYMENT" in text or any(k in quote for k in ("付款", "支付", "发票", "费用", "价款", "结算")):
        return "PAYMENT"
    if "DELIVERY" in text or any(k in quote for k in ("交付", "服务", "完成", "履行")):
        return "DELIVERY"
    if "NOTICE" in text or "通知" in quote:
        return "NOTICE"
    if any(k in quote for k in ("续签", "续约")):
        return "RENEWAL"
    if any(k in quote for k in ("逾期", "违约金", "赔偿")):
        return "PENALTY"
    return "OTHER"


def _timeline_label(node_type: str, quote: str) -> str:
    return {
        "PAYMENT": "付款/开票节点",
        "DELIVERY": "交付/服务节点",
        "ACCEPTANCE": "验收节点",
        "NOTICE": "通知节点",
        "RENEWAL": "续签节点",
        "TERMINATION": "终止/到期节点",
        "PENALTY": "逾期/违约节点",
    }.get(node_type, "合同时间节点")


def _responsible_party(quote: str) -> str:
    if "甲方" in quote and "乙方" in quote:
        return "BOTH"
    if "甲方" in quote:
        return "OUR_ENTITY"
    if "乙方" in quote:
        return "COUNTERPARTY"
    return "UNKNOWN"


def _business_meaning(node_type: str, quote: str, source_mode: str) -> str:
    type_text = {
        "PAYMENT": "需要跟踪付款、开票或费用结算时限",
        "DELIVERY": "需要跟踪服务或交付物完成时限",
        "ACCEPTANCE": "需要跟踪验收窗口和验收意见",
        "NOTICE": "需要跟踪书面通知或提醒期限",
        "RENEWAL": "需要在到期前评估续签或终止",
        "TERMINATION": "需要跟踪合同到期、解除或终止条件",
        "PENALTY": "需要关注逾期责任或违约风险",
    }.get(node_type, "需要人工判断该时间表达的履约意义")
    return f"{type_text}；来源={source_mode}；原文片段：{quote[:120]}"


def _parse_document_content(cur, job_id: int | None, document_id: int, document: dict) -> dict:
    inline_text = str(document.get("content_text") or "")
    if inline_text.strip():
        _update_job(cur, job_id, "PROCESSING", "TEXT_PARSING", 20)
        _append_job_trace(
            cur,
            job_id,
            "TEXT_PARSING",
            "读取内联合同正文，准备进行确定性条款切分",
            {"documentId": document_id, "contentLength": len(inline_text)},
            {"caseId": document["case_id"]},
        )
        return {
            "content": inline_text,
            "parser": "inline-text",
            "blockCount": len([p for p in re.split(r"\n\s*\n", inline_text) if p.strip()]),
            "pageCount": 1,
        }

    file_path = str(document.get("file_path") or "").strip()
    if not file_path or file_path == "inline:text":
        raise ValueError("Contract document has no inline text or file path")

    local_path = _resolve_local_file(file_path)
    file_type = _file_type(document.get("file_name"), local_path)
    if file_type not in _SUPPORTED_FILE_TYPES:
        raise ValueError(f"Unsupported contract file type: {file_type}")

    if file_type in {"DOC", "DOCX"}:
        stage = "DOC_CONVERSION" if file_type == "DOC" else "DOCX_PARSING"
        _update_job(cur, job_id, "PROCESSING", stage, 20)
        if file_type == "DOC":
            docx_path = _convert_doc_to_docx(local_path)
            blocks = parse_docx_blocks(str(docx_path))
            parser = "libreoffice->python-docx"
        else:
            blocks = parse_docx_blocks(str(local_path))
            parser = "python-docx"
    else:
        stage = "PDF_PARSING" if file_type == "PDF" else "TEXT_PARSING"
        _update_job(cur, job_id, "PROCESSING", stage, 20)
        blocks = DocumentParser().parse(str(local_path), file_type)
        parser = f"document-parser:{file_type.lower()}"

    content = "\n\n".join(block.text for block in blocks if block.text.strip())
    pages = [block.source_page for block in blocks if block.source_page]
    stage = "DOC_CONVERSION" if file_type == "DOC" else "DOCX_PARSING" if file_type == "DOCX" else "PDF_PARSING" if file_type == "PDF" else "TEXT_PARSING"
    _append_job_trace(
        cur,
        job_id,
        stage,
        f"{file_type} 文件解析完成，提取 {len(blocks)} 个文本块",
        {"documentId": document_id, "filePath": file_path, "localPath": str(local_path)},
        {
            "parser": parser,
            "fileType": file_type,
            "blockCount": len(blocks),
            "contentLength": len(content),
            "pageCount": max(pages) if pages else 1,
            "sampleBlocks": [block.text[:120] for block in blocks[:3]],
        },
    )
    return {
        "content": content,
        "parser": parser,
        "blockCount": len(blocks),
        "pageCount": max(pages) if pages else 1,
    }


def _file_type(file_name: object, path: Path) -> str:
    name = str(file_name or path.name)
    suffix = Path(name).suffix.lower() or path.suffix.lower()
    return {
        ".docx": "DOCX",
        ".doc": "DOC",
        ".pdf": "PDF",
        ".txt": "TXT",
        ".md": "MD",
        ".markdown": "MD",
    }.get(suffix, suffix.lstrip(".").upper())


def _convert_doc_to_docx(path: Path) -> Path:
    output_dir = Path(tempfile.mkdtemp(prefix="atlasmind-doc-"))
    converted = output_dir / f"{path.stem}.docx"

    converter = _find_office_converter()
    if converter:
        _convert_doc_with_libreoffice(path, converted, output_dir, converter)
        return converted

    if os.name == "nt" and _has_microsoft_word():
        _convert_doc_with_word_com(path, converted)
        return converted

    raise RuntimeError(
        "DOC 解析需要先转换为 DOCX。生产环境请在文档解析 Worker 中安装 LibreOffice；"
        "本机开发请安装 LibreOffice，或安装 Microsoft Word 作为本地转换 fallback。"
    )


def _convert_doc_with_libreoffice(path: Path, converted: Path, output_dir: Path, converter: str) -> None:
    command = [
        str(converter),
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(output_dir),
        str(path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if completed.returncode != 0 or not converted.exists():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"DOC 转 DOCX 失败: {detail[:500]}")


def _convert_doc_with_word_com(path: Path, converted: Path) -> None:
    # Build a self-contained PowerShell command with embedded arguments —
    # powershell -Command does not pass trailing args to an inline script block.
    escaped_input = str(path).replace("'", "''")
    escaped_output = str(converted).replace("'", "''")
    ps_command = (
        "$ErrorActionPreference='Stop';"
        f"$in='{escaped_input}';"
        f"$out='{escaped_output}';"
        "$w=$null;$d=$null;"
        "try{"
        "$w=New-Object -ComObject Word.Application;"
        "$w.Visible=$false;$w.DisplayAlerts=0;"
        "$d=$w.Documents.Open($in,$false,$true);"
        "$d.SaveAs2($out,16)"
        "}finally{"
        "if($d){$d.Close($false)|Out-Null};"
        "if($w){$w.Quit()|Out-Null;"
        "[Runtime.InteropServices.Marshal]::ReleaseComObject($w)|Out-Null}"
        "}"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 or not converted.exists():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"DOC 使用 Microsoft Word 转 DOCX 失败: {detail[:500]}")


def _has_microsoft_word() -> bool:
    candidates = [
        shutil.which("winword"),
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
    ]
    return any(candidate and Path(candidate).exists() for candidate in candidates)


def _find_office_converter() -> str | None:
    configured = os.getenv("LIBREOFFICE_PATH") or os.getenv("SOFFICE_PATH")
    candidates = [
        configured,
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def _resolve_local_file(file_path: str) -> Path:
    normalized = file_path.strip().replace("\\", "/")
    if normalized.startswith("http://") or normalized.startswith("https://"):
        raise ValueError("当前合同文档 Worker 仅支持本地上传文件，暂不直接拉取远程 URL")

    path = Path(normalized)
    if path.is_absolute() and path.exists():
        return path

    candidates = []
    upload_roots = [
        os.getenv("CONTRACT_UPLOAD_ROOT"),
        os.getenv("UPLOAD_PATH"),
        os.getenv("ATLASMIND_UPLOAD_PATH"),
        "/app/upload",
    ]
    for root in upload_roots:
        if not root:
            continue
        upload_root = Path(root)
        if normalized.startswith("/upload/"):
            candidates.append(upload_root / normalized.removeprefix("/upload/"))
        candidates.append(upload_root / normalized.lstrip("/"))

    resolved_file = Path(__file__).resolve()
    repo_root = None
    for parent in resolved_file.parents:
        if (parent / "agent-server").exists() or (parent / "docker-compose.yml").exists():
            repo_root = parent
            break
    if normalized.startswith("/upload/"):
        if repo_root:
            candidates.append(repo_root / "agent-server" / normalized.lstrip("/"))
    if repo_root:
        candidates.extend([
            repo_root / "agent-server" / normalized.lstrip("/"),
            repo_root / normalized.lstrip("/"),
        ])
    candidates.append(Path.cwd() / normalized.lstrip("/"))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"合同文件不存在: {file_path}")
