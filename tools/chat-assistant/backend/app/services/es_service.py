"""ES 检索服务 — 语义搜索 (kNN dense_vector) + 文本搜索 (multi_match) 双模式。

语义搜索优先：有 embedding 配置时用 kNN；未配置时降级为 multi_match。
"""
import socket
import logging

from elasticsearch import BadRequestError, Elasticsearch
from app.config import settings

logger = logging.getLogger(__name__)

# ES 连接/请求超时（秒）
ES_TIMEOUT = 2

# dense_vector 索引 mapping 模板
INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "refresh_interval": "5s",
    },
    "mappings": {
        "properties": {
            "id": {"type": "long"},
            "title": {
                "type": "text",
                "analyzer": "standard",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "content": {
                "type": "text",
                "analyzer": "standard",
            },
            "summary": {
                "type": "text",
                "analyzer": "standard",
            },
            "categoryId": {"type": "long"},
            "status": {"type": "integer"},
            "visibility": {"type": "keyword"},
            "createTime": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time||epoch_millis"},
            # ====== dense_vector 语义搜索字段 ======
            "embedding": {
                "type": "dense_vector",
                "dims": settings.embedding_dim,
                "similarity": "cosine",
                "index": True,
            },
        }
    },
}

KB_INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "refresh_interval": "5s",
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "long"},
            "document_id": {"type": "long"},
            "space_id": {"type": "long"},
            "title": {"type": "text", "analyzer": "standard", "fields": {"keyword": {"type": "keyword"}}},
            "content": {"type": "text", "analyzer": "standard"},
            "section_title": {"type": "text", "analyzer": "standard"},
            "source_page": {"type": "integer"},
            "status": {"type": "keyword"},
            "embedding_model": {"type": "keyword"},
            "embedding": {
                "type": "dense_vector",
                "dims": settings.embedding_dim,
                "similarity": "cosine",
                "index": True,
            },
        }
    },
}


def _tcp_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """快速检测 TCP 端口是否可达。"""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


class ESService:
    def __init__(self):
        host_str = settings.es_host.replace("http://", "").replace("https://", "")
        if ":" in host_str:
            self._host, self._port = host_str.rsplit(":", 1)
            self._port = int(self._port)
        else:
            self._host, self._port = host_str, 9200

        self.client = Elasticsearch(
            settings.es_host,
            request_timeout=ES_TIMEOUT,
            max_retries=0,
            retry_on_timeout=False,
        )
        self.index = settings.es_index
        self.kb_index = settings.kb_index

    # ==================== 基础健康检查 ====================

    def health(self) -> bool:
        """快速健康检查（仅 TCP 端口检测，不发起 HTTP 请求）。"""
        return _tcp_port_open(self._host, self._port)

    def ping(self) -> bool:
        """ES HTTP ping 检查。"""
        if not _tcp_port_open(self._host, self._port):
            return False
        try:
            return self.client.ping()
        except Exception:
            return False

    # ==================== 索引管理 ====================

    def _embedding_dims(self, index: str) -> int | None:
        mapping = self.client.indices.get_mapping(index=index)
        props = mapping[index]["mappings"].get("properties", {})
        embedding = props.get("embedding")
        if not embedding:
            return None
        return embedding.get("dims")

    def ensure_index(self) -> bool:
        """确保索引存在且 mapping 包含 dense_vector 字段。

        新索引直接按完整 mapping 创建；已存在的老索引（无 embedding 字段）
        会被删除重建。生产环境请通过 Java 侧管理索引。

        Returns:
            True 表示索引就绪。
        """
        if not _tcp_port_open(self._host, self._port):
            return False
        try:
            exists = self.client.indices.exists(index=self.index)
            if exists:
                # 检查 mapping 是否包含 embedding 字段
                mapping = self.client.indices.get_mapping(index=self.index)
                props = mapping[self.index]["mappings"]["properties"]
                if "embedding" in props:
                    return True  # 已是最新 mapping
                # 老索引 → 删除重建
                logger.info("Deleting old index '%s' (missing embedding field)...", self.index)
                self.client.indices.delete(index=self.index)

            # 创建新索引
            self.client.indices.create(index=self.index, body=INDEX_MAPPING)
            logger.info("Index '%s' created with dense_vector mapping.", self.index)
            return True
        except Exception as e:
            logger.warning("ensure_index failed: %s", e)
            return False

    # ==================== 语义搜索（kNN + Embedding）====================

    def search_by_embedding(
        self, query_vector: list[float], top_k: int = None
    ) -> list[dict]:
        """kNN 语义搜索 — 用 cosine 相似度找最相关的文章。

        Args:
            query_vector: 查询文本的 embedding 向量（由 EmbeddingService 生成）。
            top_k: 返回结果数，默认取配置值。

        Returns:
            文章列表 [{id, title, content, summary, snippet, score}, ...]。
            ES 不可用或索引缺失时返回空列表。
        """
        if top_k is None:
            top_k = settings.retrieval_top_k

        if not _tcp_port_open(self._host, self._port):
            return []

        body = {
            "knn": {
                "field": "embedding",
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": max(top_k * 4, 20),
                "filter": {
                    "terms": {"visibility": ["PUBLIC", "RAG_ONLY"]}
                },
            },
            "_source": ["id", "title", "content", "summary"],
            "size": top_k,
        }

        try:
            response = self.client.search(index=self.index, body=body)
        except Exception as e:
            logger.warning("kNN search failed: %s", e)
            return []

        return self._parse_hits(response)

    # ==================== 文本搜索（multi_match 降级）====================

    def search_articles(self, query: str, top_k: int = None) -> list[dict]:
        """多字段匹配文本搜索（ES 不可用时降级为空列表）。

        当 embedding 未配置时用作降级方案。
        """
        if top_k is None:
            top_k = settings.retrieval_top_k

        if not _tcp_port_open(self._host, self._port):
            return []

        body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "summary^2", "content"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "filter": [
                        {"terms": {"visibility": ["PUBLIC", "RAG_ONLY"]}}
                    ],
                }
            },
            "highlight": {
                "fields": {
                    "content": {"fragment_size": 150, "number_of_fragments": 2}
                }
            },
            "_source": ["id", "title", "content", "summary"],
            "size": top_k,
        }

        try:
            response = self.client.search(index=self.index, body=body)
        except Exception:
            return []

        return self._parse_hits(response)

    # ==================== 文档索引（含 embedding）====================

    def index_article(
        self,
        article_id: int,
        title: str,
        content: str,
        summary: str,
        category_id: int = 0,
        status: int = 1,
        visibility: str = "PUBLIC",
        create_time: str = None,
        embedding: list[float] | None = None,
    ) -> bool:
        """索引单篇文章到 ES。

        Args:
            embedding: 预计算的 embedding 向量（含 embedding 时启用语义搜索）。

        Returns:
            True 表示索引成功。
        """
        if not _tcp_port_open(self._host, self._port):
            return False

        doc = {
            "id": article_id,
            "title": title,
            "content": content,
            "summary": summary or "",
            "categoryId": category_id,
            "status": status,
            "visibility": visibility,
            "createTime": create_time,
        }
        if embedding:
            doc["embedding"] = embedding

        try:
            self.client.index(index=self.index, id=article_id, body=doc)
            return True
        except Exception as e:
            logger.warning("Index article %d failed: %s", article_id, e)
            return False

    def delete_article(self, article_id: int) -> bool:
        """从 ES 删除文章。"""
        if not _tcp_port_open(self._host, self._port):
            return False
        try:
            self.client.delete(index=self.index, id=article_id, ignore=[404])
            return True
        except Exception as e:
            logger.warning("delete article %s failed: %s", article_id, e)
            return False

    # ==================== 知识库 chunk 索引 ====================

    def ensure_kb_index(self) -> bool:
        """确保知识库 chunk 索引存在且 dense_vector 维度匹配当前配置。"""
        if not _tcp_port_open(self._host, self._port):
            return False
        try:
            exists = self.client.indices.exists(index=self.kb_index)
            if exists:
                actual_dim = self._embedding_dims(self.kb_index)
                expected_dim = settings.embedding_dim
                if actual_dim == expected_dim:
                    return True

                count = self.client.count(index=self.kb_index).get("count", 0)
                message = (
                    "Knowledge index '%s' embedding dims mismatch: mapping=%s, config=%s, docs=%s"
                    % (self.kb_index, actual_dim, expected_dim, count)
                )
                if count == 0:
                    logger.warning("%s. Recreating empty index.", message)
                    self.client.indices.delete(index=self.kb_index)
                else:
                    logger.warning("%s. Please rebuild the index before ingesting.", message)
                    return False

            self.client.indices.create(index=self.kb_index, body=KB_INDEX_MAPPING)
            logger.info(
                "Knowledge index '%s' created with %sd dense_vector mapping.",
                self.kb_index,
                settings.embedding_dim,
            )
            return True
        except BadRequestError as e:
            if "resource_already_exists_exception" in str(e):
                try:
                    actual_dim = self._embedding_dims(self.kb_index)
                    if actual_dim == settings.embedding_dim:
                        return True
                    logger.warning(
                        "Knowledge index '%s' already exists but dims mismatch: mapping=%s, config=%s",
                        self.kb_index,
                        actual_dim,
                        settings.embedding_dim,
                    )
                except Exception as check_error:
                    logger.warning("ensure_kb_index post-conflict check failed: %s", check_error)
            else:
                logger.warning("ensure_kb_index failed: %s", e)
            return False
        except Exception as e:
            logger.warning("ensure_kb_index failed: %s", e)
            return False

    def index_kb_chunk(self, row: dict, embedding: list[float] | None = None) -> bool:
        """写入知识库 chunk 到 ES。"""
        if not _tcp_port_open(self._host, self._port):
            return False

        doc = {
            "chunk_id": row["id"],
            "document_id": row["document_id"],
            "space_id": row["space_id"],
            "title": row.get("title") or "",
            "content": row.get("chunk_text") or "",
            "section_title": row.get("section_title") or "",
            "source_page": row.get("source_page"),
            "status": "READY",
            "embedding_model": settings.embedding_model,
        }
        if embedding:
            doc["embedding"] = embedding

        try:
            self.client.index(index=self.kb_index, id=row["id"], body=doc)
            return True
        except Exception as e:
            logger.warning("index kb chunk %s failed: %s", row.get("id"), e)
            return False

    def delete_kb_document(self, document_id: int) -> bool:
        """删除某个文档在 ES 中的全部 chunk。"""
        if not _tcp_port_open(self._host, self._port):
            return False
        try:
            self.client.delete_by_query(
                index=self.kb_index,
                body={"query": {"term": {"document_id": document_id}}},
                conflicts="proceed",
                ignore=[404],
            )
            return True
        except Exception as e:
            logger.warning("delete kb document %s index failed: %s", document_id, e)
            return False

    def search_kb_by_embedding(
        self,
        query_vector: list[float],
        top_k: int = None,
        space_id: int | None = None,
        document_id: int | None = None,
    ) -> list[dict]:
        """知识库向量检索。"""
        if top_k is None:
            top_k = settings.retrieval_top_k
        if not query_vector or not _tcp_port_open(self._host, self._port):
            return []

        filters = [{"term": {"status": "READY"}}]
        if space_id:
            filters.append({"term": {"space_id": space_id}})
        if document_id:
            filters.append({"term": {"document_id": document_id}})

        body = {
            "knn": {
                "field": "embedding",
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": max(top_k * 4, 20),
                "filter": {"bool": {"filter": filters}},
            },
            "_source": ["chunk_id", "document_id", "space_id", "title", "content", "section_title", "source_page"],
            "size": top_k,
        }
        try:
            response = self.client.search(index=self.kb_index, body=body)
            return self._parse_kb_hits(response)
        except Exception as e:
            logger.warning("kb vector search failed: %s", e)
            return []

    def search_kb_by_keyword(
        self,
        query: str,
        top_k: int = None,
        space_id: int | None = None,
        document_id: int | None = None,
    ) -> list[dict]:
        """知识库关键词 fallback 检索。"""
        if top_k is None:
            top_k = settings.retrieval_top_k
        if not _tcp_port_open(self._host, self._port):
            return []

        filters = [{"term": {"status": "READY"}}]
        if space_id:
            filters.append({"term": {"space_id": space_id}})
        if document_id:
            filters.append({"term": {"document_id": document_id}})

        body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "section_title^2", "content"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "highlight": {"fields": {"content": {"fragment_size": 180, "number_of_fragments": 2}}},
            "_source": ["chunk_id", "document_id", "space_id", "title", "content", "section_title", "source_page"],
            "size": top_k,
        }
        try:
            response = self.client.search(index=self.kb_index, body=body)
            return self._parse_kb_hits(response)
        except Exception as e:
            logger.warning("kb keyword search failed: %s", e)
            return []

    # ==================== 内部工具 ====================

    def _parse_hits(self, response: dict) -> list[dict]:
        """解析 ES search response 为统一文章列表。"""
        hits = response.get("hits", {}).get("hits", [])
        results = []
        for hit in hits:
            source = hit.get("_source", {})
            highlights = hit.get("highlight", {}).get("content", [])
            snippet = (
                " ... ".join(highlights)
                if highlights
                else (source.get("summary", "") or "")[:200]
            )
            results.append(
                {
                    "id": source.get("id"),
                    "title": source.get("title", ""),
                    "content": source.get("content", ""),
                    "summary": source.get("summary", ""),
                    "snippet": snippet,
                    "score": hit.get("_score", 0),
                }
            )
        return results

    def _parse_kb_hits(self, response: dict) -> list[dict]:
        """解析知识库 chunk 检索结果。"""
        hits = response.get("hits", {}).get("hits", [])
        results = []
        for hit in hits:
            source = hit.get("_source", {})
            highlights = hit.get("highlight", {}).get("content", [])
            content = source.get("content", "") or ""
            snippet = " ... ".join(highlights) if highlights else content[:220]
            results.append(
                {
                    "sourceType": "DOCUMENT",
                    "sourceId": source.get("document_id"),
                    "chunkId": source.get("chunk_id"),
                    "spaceId": source.get("space_id"),
                    "title": source.get("title", ""),
                    "content": content,
                    "snippet": snippet,
                    "sectionTitle": source.get("section_title", ""),
                    "page": source.get("source_page"),
                    "score": hit.get("_score", 0),
                }
            )
        return results
