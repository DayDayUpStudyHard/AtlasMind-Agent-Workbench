"""知识库 MySQL 写入/更新。"""
from __future__ import annotations

import hmac
import pymysql
from pymysql.cursors import DictCursor

from app.config import settings
from app.services.document_parser import Chunk


class KbStore:
    _observability_ready = False

    def _conn(self):
        return pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    def ensure_observability_tables(self) -> None:
        if self.__class__._observability_ready:
            return
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kb_retrieval_trace (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        message_id BIGINT NOT NULL,
                        query TEXT NOT NULL,
                        retrieval_type VARCHAR(50),
                        top_k INT DEFAULT 5,
                        latency_ms BIGINT,
                        fallback_reason VARCHAR(500),
                        hit_count INT DEFAULT 0,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_message (message_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kb_retrieval_hit (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        trace_id BIGINT NOT NULL,
                        source_type VARCHAR(30) NOT NULL,
                        source_id BIGINT NOT NULL,
                        chunk_id BIGINT NULL,
                        title VARCHAR(255),
                        score DOUBLE DEFAULT 0,
                        snippet TEXT,
                        rank_no INT DEFAULT 0,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_trace (trace_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kb_tool_call (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        trace_id BIGINT NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        status VARCHAR(30) NOT NULL,
                        latency_ms BIGINT DEFAULT 0,
                        input_summary VARCHAR(1000),
                        output_summary VARCHAR(1000),
                        error_message TEXT,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_trace (trace_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            conn.commit()
        self.__class__._observability_ready = True

    def get_session(self, session_id: int | None, owner_token: str | None) -> dict | None:
        if not session_id or not owner_token:
            return None
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM kb_qa_session WHERE id=%s LIMIT 1",
                    (session_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        stored = str(row.get("owner_token") or "")
        if not hmac.compare_digest(stored, str(owner_token)):
            return None
        return row

    def get_project_context(self, project_id: int | None) -> dict | None:
        if not project_id:
            return None
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, name, description,
                               business_scope AS businessScope,
                               release_target AS releaseTarget,
                               current_milestone AS currentMilestone,
                               tech_stack AS techStack,
                               health_status AS healthStatus,
                               health_score AS healthScore
                        FROM agent_project
                        WHERE id=%s AND deleted=0
                        LIMIT 1
                        """,
                        (project_id,),
                    )
                    project = cur.fetchone()
                    if not project:
                        return None
                    cur.execute(
                        """
                        SELECT title, summary, health_status AS healthStatus,
                               health_score AS healthScore,
                               risks_json AS risksJson, plan_json AS planJson
                        FROM agent_report
                        WHERE project_id=%s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (project_id,),
                    )
                    project["latestReport"] = cur.fetchone()
                    return project
        except Exception:
            # Project context is an enhancement; global knowledge chat remains available.
            return None

    def list_session_messages(self, session_id: int, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content
                    FROM kb_qa_message
                    WHERE session_id=%s AND role IN ('user','assistant','system')
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (session_id, limit),
                )
                rows = list(cur.fetchall())
        rows.reverse()
        return rows

    def append_qa_message(
        self,
        session_id: int,
        role: str,
        content: str,
        model: str | None = None,
        latency_ms: int | None = None,
    ) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_qa_message (session_id, role, content, model, latency_ms)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (session_id, role, content, model, latency_ms),
                )
                message_id = int(cur.lastrowid)
            conn.commit()
        return message_id

    def create_retrieval_trace(
        self,
        message_id: int,
        query: str,
        retrieval_type: str,
        top_k: int,
        latency_ms: int,
        fallback_reason: str,
        hit_count: int,
    ) -> int:
        self.ensure_observability_tables()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_retrieval_trace
                    (message_id, query, retrieval_type, top_k, latency_ms, fallback_reason, hit_count)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (message_id, query, retrieval_type, top_k, latency_ms, fallback_reason, hit_count),
                )
                trace_id = int(cur.lastrowid)
            conn.commit()
        return trace_id

    def create_retrieval_hits(self, trace_id: int, hits: list[dict]) -> None:
        self.ensure_observability_tables()
        if not hits:
            return
        with self._conn() as conn:
            with conn.cursor() as cur:
                for rank, hit in enumerate(hits, 1):
                    cur.execute(
                        """
                        INSERT INTO kb_retrieval_hit
                        (trace_id, source_type, source_id, chunk_id, title, score, snippet, rank_no)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            trace_id,
                            hit.get("sourceType", "ARTICLE"),
                            hit.get("sourceId") or hit.get("id") or 0,
                            hit.get("chunkId"),
                            hit.get("title", ""),
                            float(hit.get("score") or 0),
                            hit.get("snippet", ""),
                            rank,
                        ),
                    )
            conn.commit()

    def create_tool_call(
        self,
        trace_id: int,
        name: str,
        status: str,
        latency_ms: int,
        input_summary: str = "",
        output_summary: str = "",
        error_message: str = "",
    ) -> None:
        self.ensure_observability_tables()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_tool_call
                    (trace_id, name, status, latency_ms, input_summary, output_summary, error_message)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (trace_id, name, status, latency_ms, input_summary, output_summary, error_message),
                )
            conn.commit()

    def update_job(self, job_id: int, status: str, progress: int, message: str = "", error: str = "") -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE kb_ingest_job
                    SET status=%s, progress=%s, message=%s, error_message=%s,
                        started_at=IF(started_at IS NULL, NOW(), started_at),
                        finished_at=IF(%s IN ('DONE','FAILED'), NOW(), finished_at)
                    WHERE id=%s
                    """,
                    (status, progress, message, error, status, job_id),
                )
            conn.commit()

    def update_document(self, document_id: int, status: str, chunk_count: int | None = None,
                        error: str = "", indexed: bool = False) -> None:
        fields = ["status=%s", "error_message=%s"]
        params: list = [status, error]
        if chunk_count is not None:
            fields.append("chunk_count=%s")
            params.append(chunk_count)
        if indexed:
            fields.append("last_index_time=NOW()")
        params.append(document_id)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE kb_document SET {', '.join(fields)} WHERE id=%s", params)
            conn.commit()

    def reset_chunks(self, document_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE kb_document_chunk SET deleted=1 WHERE document_id=%s", (document_id,))
            conn.commit()

    def replace_chunks(self, document_id: int, space_id: int, chunks: list[Chunk]) -> list[int]:
        self.reset_chunks(document_id)
        return self.insert_chunks_batch(document_id, space_id, chunks, 0)

    def insert_chunks_batch(self, document_id: int, space_id: int, chunks: list[Chunk], start_index: int) -> list[int]:
        if not chunks:
            return []
        with self._conn() as conn:
            with conn.cursor() as cur:
                ids: list[int] = []
                for offset, chunk in enumerate(chunks):
                    cur.execute(
                        """
                        INSERT INTO kb_document_chunk
                        (document_id, space_id, chunk_index, section_title, source_page, chunk_text,
                         char_count, token_count, embedding_status, index_status, deleted)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING','PENDING',0)
                        """,
                        (
                            document_id,
                            space_id,
                            start_index + offset,
                            chunk.section_title,
                            chunk.source_page,
                            chunk.text,
                            len(chunk.text),
                            max(1, len(chunk.text) // 2),
                        ),
                    )
                    ids.append(cur.lastrowid)
            conn.commit()
            return ids

    def count_chunks(self, document_id: int) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS count FROM kb_document_chunk WHERE document_id=%s AND deleted=0",
                    (document_id,),
                )
                row = cur.fetchone() or {}
                return int(row.get("count") or 0)

    def get_chunks(self, document_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.*, d.title
                    FROM kb_document_chunk c
                    JOIN kb_document d ON d.id = c.document_id
                    WHERE c.document_id=%s AND c.deleted=0
                    ORDER BY c.chunk_index ASC
                    """,
                    (document_id,),
                )
                return list(cur.fetchall())

    def iter_chunks(self, document_id: int, batch_size: int):
        last_id = 0
        while True:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT c.*, d.title
                        FROM kb_document_chunk c
                        JOIN kb_document d ON d.id = c.document_id
                        WHERE c.document_id=%s AND c.deleted=0 AND c.id>%s
                        ORDER BY c.id ASC
                        LIMIT %s
                        """,
                        (document_id, last_id, batch_size),
                    )
                    rows = list(cur.fetchall())
            if not rows:
                break
            last_id = rows[-1]["id"]
            yield rows

    def mark_chunk(self, chunk_id: int, embedding_status: str, index_status: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE kb_document_chunk SET embedding_status=%s, index_status=%s WHERE id=%s",
                    (embedding_status, index_status, chunk_id),
                )
            conn.commit()

    def create_notification(self, type_: str, title: str, content: str, related_type: str, related_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_notification
                    (type, title, content, related_type, related_id, read_status)
                    VALUES (%s,%s,%s,%s,%s,0)
                    """,
                    (type_, title, content, related_type, related_id),
                )
            conn.commit()
