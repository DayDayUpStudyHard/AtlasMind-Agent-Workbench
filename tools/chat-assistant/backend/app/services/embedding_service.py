"""Embedding 服务 — 文本转向量，用于 ES kNN 语义搜索。

DeepSeek 不提供 embedding API，因此语义搜索需要单独配置 Embedding 提供商
（如 OpenAI text-embedding-ada-002 或任何 OpenAI 兼容接口）。

未配置时自动降级为 ES multi_match 文本搜索。
"""
import logging
from openai import OpenAI, APIError
from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingDimensionError(ValueError):
    """Raised when the provider returns vectors with a dimension that does not match config."""


class EmbeddingService:
    """OpenAI 兼容的 Embedding API 客户端。"""

    def __init__(self):
        self._configured = bool(
            settings.embedding_api_key and settings.embedding_base_url
        )
        if self._configured:
            self.client = OpenAI(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
            )
            self.model = settings.embedding_model
            self.dim = settings.embedding_dim
        else:
            self.client = None
            self.model = ""
            self.dim = 0

    @property
    def configured(self) -> bool:
        """是否已配置 embedding 服务。"""
        return self._configured

    def _validate_dimension(self, vector: list[float]) -> None:
        actual_dim = len(vector)
        if self.dim and actual_dim != self.dim:
            raise EmbeddingDimensionError(
                f"Embedding 维度不匹配：模型 {self.model} 返回 {actual_dim} 维，"
                f"但 EMBEDDING_DIM={self.dim}。请修正 .env 并重建 ES 索引。"
            )

    def embed(self, text: str) -> list[float] | None:
        """生成单条文本的 embedding 向量。

        Returns:
            配置维度的 float 列表；未配置或请求失败时返回 None。
        """
        if not self._configured:
            return None
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text[:8192],  # ada-002 max token limit ~8191 tokens ≈ 32K chars
            )
            vector = response.data[0].embedding
            self._validate_dimension(vector)
            return vector
        except EmbeddingDimensionError:
            raise
        except APIError as e:
            logger.warning("Embedding API error: %s", e)
            return None
        except Exception as e:
            logger.warning("Embedding request failed: %s", e)
            return None

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量生成 embedding 向量。

        Args:
            texts: 文本列表，每条自动截断到 8192 字符。

        Returns:
            向量列表，成功条目返回向量，失败条目返回空列表。
        """
        if not self._configured:
            return [[] for _ in texts]
        truncated = [t[:8192] for t in texts]
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=truncated,
            )
            vectors = [item.embedding for item in response.data]
            for vector in vectors:
                self._validate_dimension(vector)
            return vectors
        except EmbeddingDimensionError:
            raise
        except APIError as e:
            logger.warning("Batch embedding API error: %s", e)
            return [[] for _ in texts]
        except Exception as e:
            logger.warning("Batch embedding request failed: %s", e)
            return [[] for _ in texts]
