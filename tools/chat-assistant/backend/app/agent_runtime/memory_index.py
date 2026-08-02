"""Vector memory index — semantic search over agent_project_memory entries.

Lazy-loads sentence-transformers (all-MiniLM-L6-v2, ~80 MB) on first use.
Builds a per-project in-memory vector index (< 1000 entries expected) and
supports cosine-similarity retrieval augmented with keyword pre-filtering.

Usage::

    index = MemoryVectorIndex()
    results = await index.search(project_id=2, query="CI failure pattern",
                                 top_k=5, keyword_filter="CI")
    # → list of agent_project_memory rows with 'similarity' field added
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Module-level model singleton (lazy-loaded, thread-safe)
_model = None
_model_lock = threading.Lock()


def _get_model():
    """Return the sentence-transformers model, loading it on first call."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("MemoryVectorIndex: loaded all-MiniLM-L6-v2 (%s dims)",
                         _model.get_sentence_embedding_dimension())
        except Exception:
            logger.warning(
                "sentence-transformers not available — "
                "semantic memory search disabled. "
                "Install with: pip install sentence-transformers"
            )
            _model = False  # sentinel: disabled
    return _model


class MemoryVectorIndex:
    """Per-project in-memory vector index for agent_project_memory semantic search.

    The index is rebuilt from the DB on first access per project (lazy) and
    cached until :meth:`invalidate` is called.  Embedding generation runs in
    a thread-pool executor so it never blocks the asyncio event loop.
    """

    def __init__(self):
        # project_id → {"entries": list[dict], "vectors": np.ndarray, "built_at": float}
        self._indexes: dict[int, dict] = {}
        self._lock = threading.Lock()

    # ── public API ──────────────────────────────────────────────────

    async def search(
        self,
        project_id: int,
        query: str,
        *,
        top_k: int = 5,
        keyword_filter: str = "",
    ) -> list[dict]:
        """Return memory entries ranked by cosine similarity to *query*.

        When *keyword_filter* is non-empty, entries whose title+content do not
        contain the filter string are excluded before ranking.
        """
        idx = await self._ensure_index(project_id)
        entries = idx["entries"]
        vectors = idx["vectors"]

        if not entries:
            return []

        # Keyword pre-filter
        if keyword_filter:
            kf_lower = keyword_filter.lower()
            mask = [
                (kf_lower in str(e.get("title", "")).lower()
                 or kf_lower in str(e.get("content", "")).lower())
                for e in entries
            ]
            if not any(mask):
                return []
            entries = [e for e, m in zip(entries, mask) if m]
            vectors = np.array([v for v, m in zip(vectors, mask) if m])

        if len(entries) == 0:
            return []

        # Encode query
        model = _get_model()
        if model is False:
            # Sentence-transformers not installed — return keyword-only results
            return entries[:top_k]

        query_vec = await self._encode(model, [query])
        query_vec = np.array(query_vec[0], dtype=np.float32)

        # Cosine similarity
        norms = np.linalg.norm(vectors, axis=1)
        norms[norms == 0] = 1e-10
        query_norm = np.linalg.norm(query_vec)
        if query_norm < 1e-10:
            query_norm = 1e-10

        similarities = np.dot(vectors, query_vec) / (norms * query_norm)

        # Rank and return top_k
        top_indices = np.argsort(similarities)[::-1][:top_k]
        result = []
        for i in top_indices:
            entry = dict(entries[i])
            entry["similarity"] = float(similarities[i])
            result.append(entry)

        return result

    def invalidate(self, project_id: int | None = None) -> None:
        """Drop cached index for *project_id* (or all if None)."""
        with self._lock:
            if project_id is None:
                self._indexes.clear()
            else:
                self._indexes.pop(project_id, None)

    # ── internals ───────────────────────────────────────────────────

    async def _ensure_index(self, project_id: int) -> dict:
        """Return cached index, building from DB if necessary."""
        with self._lock:
            cached = self._indexes.get(project_id)
            if cached is not None:
                return cached

        entries = await self._load_entries(project_id)
        vectors = await self._build_vectors(entries)

        idx = {"entries": entries, "vectors": vectors}
        with self._lock:
            self._indexes[project_id] = idx
        return idx

    @staticmethod
    async def _load_entries(project_id: int) -> list[dict]:
        """Load all memory entries for *project_id* from MySQL."""
        from .persistence import _conn

        def _load():
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, memory_type AS memoryType, title, content,
                                  source_type AS sourceType, source_id AS sourceId,
                                  confirmed, create_time AS createTime
                           FROM agent_project_memory
                           WHERE project_id = %s
                           ORDER BY update_time DESC
                           LIMIT 500""",
                        (project_id,),
                    )
                    return list(cur.fetchall())

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _load)

    @staticmethod
    async def _build_vectors(entries: list[dict]) -> np.ndarray:
        """Encode all entry texts into a [N, dim] float32 matrix."""
        if not entries:
            return np.empty((0, 384), dtype=np.float32)

        model = _get_model()
        if model is False:
            return np.empty((0, 384), dtype=np.float32)

        # Build texts: title + first 1000 chars of content
        texts = [
            f"{e.get('title', '')} {str(e.get('content', ''))[:1000]}"
            for e in entries
        ]

        vectors = await MemoryVectorIndex._encode(model, texts)
        return np.array(vectors, dtype=np.float32)

    @staticmethod
    async def _encode(model, texts: list[str]) -> list[list[float]]:
        """Run model.encode in a thread-pool executor (CPU-bound)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, model.encode, texts, None)


# Module-level singleton
_index: MemoryVectorIndex | None = None


def get_memory_index() -> MemoryVectorIndex:
    """Return the module-level MemoryVectorIndex singleton."""
    global _index
    if _index is None:
        _index = MemoryVectorIndex()
    return _index
