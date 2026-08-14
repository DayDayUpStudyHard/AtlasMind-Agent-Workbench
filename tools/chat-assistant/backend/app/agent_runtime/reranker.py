"""Provider-native semantic reranking for contract and policy retrieval."""

from __future__ import annotations

import contextvars
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# PRD Phase 8 / §10: frozen rerank stack version, stamped on artifacts and
# agent_run so evaluation results stay traceable to the reranker that ran.
RERANK_VERSION = "reranker-v1"

_rerank_disabled: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "rerank_disabled", default=False
)
_rerank_methods: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "rerank_methods", default=()
)


def reset_rerank_observation() -> None:
    """Clear actual reranking methods observed in the current task context."""
    _rerank_methods.set(())


def _record_rerank_method(method: str) -> None:
    methods = _rerank_methods.get()
    if method not in methods:
        _rerank_methods.set((*methods, method))


def get_rerank_observation() -> dict[str, Any]:
    """Describe what reranking actually happened, not what was requested."""
    methods = list(_rerank_methods.get())
    if not methods:
        actual = "NOT_USED"
    elif len(methods) == 1:
        actual = methods[0]
    else:
        actual = "MIXED"
    return {"actualMethod": actual, "methods": methods}


def _truncate(value: Any, max_chars: int = 700) -> str:
    text = str(value or "").strip()
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def _contract_document(hit: dict) -> str:
    return "\n".join(filter(None, (
        f"Clause: {hit.get('clauseNumber') or ''} {hit.get('title') or ''}".strip(),
        f"Type: {hit.get('clauseType') or ''}".strip(),
        _truncate(hit.get("snippet") or hit.get("content")),
    )))


def _policy_document(hit: dict) -> str:
    return "\n".join(filter(None, (
        f"Source: {hit.get('sourceType') or 'POLICY'}",
        f"Title: {hit.get('title') or ''}".strip(),
        f"Section: {hit.get('sectionTitle') or ''}".strip(),
        _truncate(hit.get("snippet") or hit.get("content")),
    )))


class LLMReranker:
    """Use a provider's native cross-encoder rerank endpoint with safe fallback."""

    def __init__(self) -> None:
        self._api_key = (settings.reranker_api_key or "").strip()
        self._base_url = (settings.reranker_base_url or "").strip().rstrip("/")
        self._model = (settings.reranker_model or "").strip()
        self._configured = bool(self._api_key and self._base_url and self._model)
        self._init_error = ""
        if not self._configured:
            self._init_error = (
                "RERANKER_API_KEY, RERANKER_BASE_URL and RERANKER_MODEL must all be set"
            )

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def status(self) -> str:
        return "configured" if self._configured else self._init_error

    def rerank_contract_clauses(
        self, query: str, hits: list[dict], top_k: int
    ) -> list[dict]:
        if len(hits) <= 1:
            return hits[:top_k]
        if _rerank_disabled.get():
            _record_rerank_method("DISABLED")
            return _rerank_contract_hits_keyword(query, hits)[:top_k]
        if not self._configured:
            _record_rerank_method("KEYWORD_FALLBACK")
            return _rerank_contract_hits_keyword(query, hits)[:top_k]

        rankings = self._model_rerank(query, [_contract_document(hit) for hit in hits])
        if rankings is None:
            _record_rerank_method("KEYWORD_FALLBACK")
            return _rerank_contract_hits_keyword(query, hits)[:top_k]
        result = [hits[index] for index in rankings]
        for position, hit in enumerate(result, 1):
            hit["rerankPosition"] = position
            hit["rerankerMethod"] = "MODEL_RERANK"
        _record_rerank_method("MODEL_RERANK")
        return result[:top_k]

    def rerank_policy_items(
        self, query: str, hits: list[dict], top_k: int
    ) -> list[dict]:
        if len(hits) <= 1:
            return hits[:top_k]
        if _rerank_disabled.get():
            _record_rerank_method("DISABLED")
            return hits[:top_k]
        if not self._configured:
            _record_rerank_method("KEYWORD_FALLBACK")
            return hits[:top_k]

        rankings = self._model_rerank(query, [_policy_document(hit) for hit in hits])
        if rankings is None:
            _record_rerank_method("KEYWORD_FALLBACK")
            return hits[:top_k]
        result = [hits[index] for index in rankings]
        for position, hit in enumerate(result, 1):
            hit["rerankPosition"] = position
            hit["rerankerMethod"] = "MODEL_RERANK"
        _record_rerank_method("MODEL_RERANK")
        return result[:top_k]

    def _model_rerank(self, query: str, documents: list[str]) -> list[int] | None:
        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }
        request = urllib.request.Request(
            f"{self._base_url}/rerank",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=settings.reranker_timeout_seconds
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            logger.warning("Reranker API returned HTTP %s: %s", exc.code, detail)
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning("Reranker API request failed: %s", exc)
            return None

        results = body.get("results") or []
        ranked: list[int] = []
        seen: set[int] = set()
        for item in sorted(
            results,
            key=lambda value: float(value.get("relevance_score") or 0),
            reverse=True,
        ):
            try:
                index = int(item.get("index", -1))
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(documents) and index not in seen:
                ranked.append(index)
                seen.add(index)
        ranked.extend(index for index in range(len(documents)) if index not in seen)
        return ranked if len(ranked) > 1 else None


_reranker: LLMReranker | None = None


def get_reranker() -> LLMReranker:
    global _reranker
    if _reranker is None:
        _reranker = LLMReranker()
    return _reranker


_CONTRACT_SEARCH_TERMS = (
    "付款", "支付", "发票", "工作日", "自然日", "验收", "交付", "续签", "终止",
    "到期", "通知", "逾期", "违约", "赔偿", "保密", "个人信息", "数据",
)


def _rerank_contract_hits_keyword(query: str, hits: list[dict]) -> list[dict]:
    terms = [term for term in _CONTRACT_SEARCH_TERMS if term in query]
    if not terms:
        for position, hit in enumerate(hits, 1):
            hit["rerankPosition"] = position
            hit["rerankerMethod"] = "KEYWORD_BONUS_NO_MATCH"
        return hits

    def score(hit: dict) -> float:
        text = " ".join(str(hit.get(key) or "") for key in (
            "title", "clauseNumber", "snippet", "content", "clauseType",
        ))
        return sum(1 for term in terms if term in text) * 1000 + float(hit.get("score") or 0)

    result = sorted(hits, key=score, reverse=True)
    for position, hit in enumerate(result, 1):
        hit["rerankPosition"] = position
        hit["rerankerMethod"] = "KEYWORD_BONUS"
    return result
