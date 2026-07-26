"""知识库导入、索引和检索服务。"""
from __future__ import annotations

import logging

from app.config import settings
from app.services.document_parser import DocumentParser, HybridChunker
from app.services.embedding_service import EmbeddingService
from app.services.es_service import ESService
from app.services.kb_store import KbStore

logger = logging.getLogger(__name__)


class KbService:
    def __init__(self):
        self.store = KbStore()
        self.parser = DocumentParser()
        self.chunker = HybridChunker()
        self.embedding = EmbeddingService()
        self.es = ESService()

    def _index_chunks(
        self,
        document_id: int,
        job_id: int,
        progress_start: int,
        progress_span: int,
    ) -> int:
        total = self.store.count_chunks(document_id)
        if total == 0:
            raise RuntimeError("未解析出可索引内容，请检查文档内容是否为空或格式是否受支持")
        if not self.es.ensure_kb_index():
            raise RuntimeError(
                f"ES 知识库索引不可用或向量维度不匹配，请检查 {settings.kb_index} mapping 和 EMBEDDING_DIM"
            )

        indexed_count = 0
        processed = 0
        batch_size = max(1, settings.kb_embedding_batch_size)
        for rows in self.store.iter_chunks(document_id, batch_size):
            vectors = [None] * len(rows)
            if self.embedding.configured:
                texts = [row["chunk_text"] for row in rows]
                batch_vectors = self.embedding.embed_batch(texts)
                vectors = (batch_vectors + [[] for _ in rows])[:len(rows)]

            for row, vector in zip(rows, vectors):
                processed += 1
                if self.embedding.configured and not vector:
                    self.store.mark_chunk(row["id"], "FAILED", "PENDING")
                    continue

                ok = self.es.index_kb_chunk(row, embedding=vector)
                if ok:
                    indexed_count += 1
                self.store.mark_chunk(row["id"], "DONE" if vector else "SKIPPED", "DONE" if ok else "FAILED")

            progress = progress_start + int(processed / total * progress_span)
            self.store.update_job(job_id, "INDEXING", min(progress, 95), f"已索引 {processed}/{total} 个切片")

        if indexed_count == 0:
            raise RuntimeError(f"ES 索引失败：0/{total} 个切片写入成功，请检查 Elasticsearch 日志和 embedding 配置")
        return indexed_count

    def _parse_and_store_chunks(self, payload, job_id: int) -> int:
        chunk_count = 0
        batch: list = []
        insert_batch_size = max(1, settings.kb_chunk_insert_batch_size)

        def update_parse_progress(page: int, total: int, used_ocr: bool) -> None:
            if total <= 0:
                return
            progress = 10 + int(page / total * 20)
            if used_ocr:
                self.store.update_job(job_id, "OCR", min(progress, 30), f"OCR 识别 {page}/{total} 页")
            elif page == 1 or page == total or page % 20 == 0:
                self.store.update_job(job_id, "PARSING", min(progress, 30), f"解析 PDF {page}/{total} 页")

        self.store.reset_chunks(payload.documentId)
        if getattr(payload, "parseMode", "") == "MINERU":
            self.store.update_job(job_id, "MINERU", 20, "正在进行 MinerU 高质量解析")
        blocks = self.parser.iter_parse(
            payload.filePath,
            payload.fileType,
            update_parse_progress,
            getattr(payload, "parseMode", None),
        )
        for chunk in self.chunker.iter_chunks(blocks):
            batch.append(chunk)
            if len(batch) < insert_batch_size:
                continue
            self.store.insert_chunks_batch(payload.documentId, payload.spaceId, batch, chunk_count)
            chunk_count += len(batch)
            batch = []
            self.store.update_job(job_id, "CHUNKING", 30, f"已写入 {chunk_count} 个切片")

        if batch:
            self.store.insert_chunks_batch(payload.documentId, payload.spaceId, batch, chunk_count)
            chunk_count += len(batch)
            self.store.update_job(job_id, "CHUNKING", 30, f"已写入 {chunk_count} 个切片")

        if chunk_count == 0:
            raise RuntimeError("未解析出可索引内容，请检查文档内容是否为空或格式是否受支持")
        return chunk_count

    def ingest_document(self, payload) -> None:
        doc_id = payload.documentId
        job_id = payload.jobId
        try:
            self.store.update_job(job_id, "PARSING", 10, "正在解析文档")
            self.store.update_document(doc_id, "PARSING")

            self.store.update_job(job_id, "CHUNKING", 30, "正在切片")
            chunk_count = self._parse_and_store_chunks(payload, job_id)
            self.store.update_document(doc_id, "INDEXING", chunk_count=chunk_count)

            self.store.update_job(job_id, "EMBEDDING", 55, "正在生成向量")
            indexed_count = self._index_chunks(doc_id, job_id, 55, 40)

            self.store.update_document(doc_id, "READY", chunk_count=chunk_count, indexed=True)
            self.store.update_job(job_id, "DONE", 100, "导入完成")
            self.store.create_notification(
                "INGEST_SUCCESS",
                "知识库文档导入成功",
                f"{payload.title} 已生成 {chunk_count} 个切片，成功索引 {indexed_count} 个",
                "DOCUMENT",
                doc_id,
            )
        except Exception as exc:
            logger.exception("knowledge ingest failed")
            message = str(exc)
            self.store.update_document(doc_id, "FAILED", error=message)
            self.store.update_job(job_id, "FAILED", 100, "导入失败", message)
            self.store.create_notification(
                "INGEST_FAILED",
                "知识库文档导入失败",
                f"{payload.title}: {message}",
                "DOCUMENT",
                doc_id,
            )

    def reindex_document(self, document_id: int, job_id: int) -> None:
        try:
            chunk_count = self.store.count_chunks(document_id)
            self.store.update_job(job_id, "INDEXING", 20, "正在重建索引")
            self.es.delete_kb_document(document_id)
            indexed_count = self._index_chunks(document_id, job_id, 20, 75)
            self.store.update_document(document_id, "READY", chunk_count=chunk_count, indexed=True)
            self.store.update_job(job_id, "DONE", 100, "索引完成")
            self.store.create_notification(
                "REINDEX_SUCCESS",
                "知识库文档索引完成",
                f"文档已重新进入 RAG 检索，成功索引 {indexed_count} 个切片",
                "DOCUMENT",
                document_id,
            )
        except Exception as exc:
            message = str(exc)
            self.store.update_document(document_id, "FAILED", error=message)
            self.store.update_job(job_id, "FAILED", 100, "索引失败", message)
            self.store.create_notification("REINDEX_FAILED", "知识库文档索引失败", message, "DOCUMENT", document_id)

    def qa_test(self, query: str, space_id: int | None = None, document_id: int | None = None, top_k: int = 5) -> dict:
        vector = self.embedding.embed(query) if self.embedding.configured else None
        retrieval_type = "VECTOR"
        hits = self.es.search_kb_by_embedding(vector, top_k, space_id, document_id) if vector else []
        if not hits:
            retrieval_type = "KEYWORD_FALLBACK"
            hits = self.es.search_kb_by_keyword(query, top_k, space_id, document_id)
        return {
            "retrievalType": retrieval_type,
            "hits": hits,
            "embeddingModel": settings.embedding_model if self.embedding.configured else "",
        }
