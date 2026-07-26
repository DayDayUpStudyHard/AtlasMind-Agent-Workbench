"""知识库 MySQL 写入/更新。"""
from __future__ import annotations

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings
from app.services.document_parser import Chunk


class KbStore:
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
