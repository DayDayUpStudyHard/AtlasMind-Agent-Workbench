"""LLM Reranker — semantic re-ranking for contract clauses and knowledge base chunks.

Replaces the keyword-bonus heuristic (contract_store._rerank_contract_hits) with
a lightweight LLM cross-encoder pass that understands whether a clause actually
answers the review question.

Design:
- Recall 30–50 candidates from vector + ES keyword + MySQL keyword (already fused via RRF).
- LLM reranker scores each candidate on: question relevance, clause completeness,
  subject/condition matching, same-chapter coherence.
- Contract clauses and KB/policy items are ranked **separately** — they never
  compete against each other for the same slots.
- When RERANKER_API_KEY is empty, falls back to the existing keyword-bonus
  heuristic so the system remains functional without the reranker.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI, APIError, APIConnectionError

from app.config import settings

logger = logging.getLogger(__name__)

# ── Prompt templates ───────────────────────────────────────────────────────

_CONTRACT_RERANK_SYSTEM = """You are a contract review assistant. Your task is to re-rank retrieved
contract clauses by their relevance to a review question.

Ranking criteria (in order of importance):
1. **Question relevance** — does the clause directly answer or inform the question?
2. **Clause completeness** — prefer full, self-contained clauses over partial snippets.
3. **Subject/condition matching** — does the clause mention the same parties, amounts,
   dates, or conditions referenced in the question?
4. **Same-chapter coherence** — clauses from the same section/chapter that form a
   complete picture should rank together.

Return ONLY a JSON object with this structure:
{"rankings": [3, 0, 7, ...], "reasoning": "one-line summary in Chinese"}

- "rankings" is an ordered list of candidate indices (0-based), best first.
- Include every candidate index exactly once.
- Never include indices that don't exist in the input."""

_POLICY_RERANK_SYSTEM = """You are a legal knowledge assistant. Your task is to re-rank retrieved
knowledge base articles and standard clauses by their relevance to a review question.

Ranking criteria (in order of importance):
1. **Question relevance** — does the article/clause directly address the question?
2. **Content completeness** — prefer articles with complete regulatory or contractual guidance.
3. **Applicability** — does the article apply to the contract type, industry, or scenario?
4. **Authority** — standard clauses with mandatory language rank above informational articles.

Return ONLY a JSON object with this structure:
{"rankings": [2, 0, 5, ...], "reasoning": "one-line summary in Chinese"}

- "rankings" is an ordered list of candidate indices (0-based), best first.
- Include every candidate index exactly once.
- Never include indices that don't exist in the input."""


def _truncate(text: str, max_chars: int = 400) -> str:
    """Truncate text for LLM context efficiency."""
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _build_contract_candidate_block(index: int, hit: dict) -> str:
    """Format one contract clause candidate for the reranker prompt."""
    title = str(hit.get("title") or "无标题")
    clause_num = str(hit.get("clauseNumber") or "")
    snippet = _truncate(str(hit.get("snippet") or hit.get("content") or ""), 500)
    clause_type = str(hit.get("clauseType") or "")
    sources = hit.get("retrievalSources") or hit.get("sources") or []
    cross = "✓多源验证" if hit.get("crossValidated") else "单源"

    parts = [f"[{index}] {clause_num} {title}"]
    if clause_type:
        parts.append(f"    类型: {clause_type}  |  检索: {cross} ({', '.join(sources) if isinstance(sources, list) else sources})")
    else:
        parts.append(f"    检索: {cross} ({', '.join(sources) if isinstance(sources, list) else sources})")
    parts.append(f"    内容: {snippet}")
    return "\n".join(parts)


def _build_policy_candidate_block(index: int, hit: dict) -> str:
    """Format one KB/standard-clause candidate for the reranker prompt."""
    title = str(hit.get("title") or "无标题")
    source_type = str(hit.get("sourceType") or "POLICY")
    snippet = _truncate(str(hit.get("snippet") or hit.get("content") or ""), 500)
    section = str(hit.get("sectionTitle") or "")
    sources = hit.get("retrievalSources") or hit.get("sources") or []
    is_mandatory = hit.get("isMandatory")

    type_label = {
        "CONTRACT_STANDARD_CLAUSE": "标准条款",
        "KB_CHUNK": "知识库",
        "KB_DOCUMENT": "知识库文档",
    }.get(source_type, source_type)

    parts = [f"[{index}] [{type_label}] {title}"]
    if section:
        parts.append(f"    章节: {section}")
    if is_mandatory is not None:
        parts.append(f"    强制性: {'是' if is_mandatory else '否'}")
    parts.append(f"    检索: {', '.join(sources) if isinstance(sources, list) else sources}")
    parts.append(f"    内容: {snippet}")
    return "\n".join(parts)


def _parse_rerank_response(raw: str, candidate_count: int) -> list[int] | None:
    """Parse LLM reranker JSON response to a validated ranking list."""
    if not raw:
        return None
    # Extract JSON block if wrapped in markdown fences
    text = raw.strip()
    if text.startswith("```"):
        # Remove opening fence
        text = text[text.find("\n") + 1:] if "\n" in text else text[3:]
        # Remove closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        import re
        m = re.search(r'\{[^{}]*"rankings"\s*:\s*\[[^\]]*\][^{}]*\}', raw, re.DOTALL)
        if not m:
            logger.warning("Reranker response could not be parsed as JSON: %.200s", raw)
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            logger.warning("Reranker JSON extraction failed: %.200s", raw)
            return None

    rankings = data.get("rankings", [])
    if not isinstance(rankings, list):
        return None

    # Validate: must contain all indices exactly once
    valid = []
    seen: set[int] = set()
    for idx in rankings:
        try:
            i = int(idx)
        except (ValueError, TypeError):
            continue
        if 0 <= i < candidate_count and i not in seen:
            valid.append(i)
            seen.add(i)

    # Append any missing indices at the end (LLM might have missed some)
    for i in range(candidate_count):
        if i not in seen:
            valid.append(i)

    if len(valid) != candidate_count:
        logger.warning("Reranker returned %d rankings for %d candidates, padded", len(valid), candidate_count)
        return None

    return valid if len(valid) > 1 else None  # no point reordering 0-1 items


class LLMReranker:
    """LLM-based semantic reranker for contract clause and KB retrieval.

    Uses a separate API key (RERANKER_API_KEY) so the reranker can use a
    different provider or cheaper model than the main LLM.  Falls back to
    the keyword-bonus heuristic when the key is not configured.
    """

    def __init__(self) -> None:
        self._client: OpenAI | None = None
        self._model: str = ""
        self._configured: bool = False
        self._init_error: str = ""

        rerank_key = (settings.reranker_api_key or "").strip()
        if not rerank_key:
            self._init_error = "RERANKER_API_KEY not set — using keyword-bonus fallback"
            return

        try:
            self._client = OpenAI(
                api_key=rerank_key,
                base_url=settings.reranker_base_url or settings.llm_base_url,
                timeout=settings.reranker_timeout_seconds,
                max_retries=0,
            )
            self._model = settings.reranker_model or settings.llm_model
            self._configured = True
        except Exception as exc:
            self._init_error = f"Reranker client init failed: {exc}"
            logger.warning(self._init_error)

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def status(self) -> str:
        return "configured" if self._configured else self._init_error

    # ── Public API ──────────────────────────────────────────────────────

    def rerank_contract_clauses(
        self, query: str, hits: list[dict], top_k: int
    ) -> list[dict]:
        """Re-rank contract clause candidates. Falls back to keyword-bonus heuristics.

        Args:
            query: The review question or search query.
            hits: Candidate clause dicts (already fused via RRF).
            top_k: Maximum number of results to return after reranking.

        Returns:
            Re-ranked hits, truncated to top_k.
        """
        if len(hits) <= 1:
            return hits[:top_k]

        if not self._configured:
            return _rerank_contract_hits_keyword(query, hits)[:top_k]

        try:
            rankings = self._llm_rerank(query, hits, "contract")
            if rankings is None:
                logger.info("LLM reranker returned invalid rankings, falling back to keyword")
                return _rerank_contract_hits_keyword(query, hits)[:top_k]
            result = [hits[i] for i in rankings]
            # Tag each result with reranker metadata
            for idx, hit in enumerate(result):
                hit["rerankPosition"] = idx + 1
                hit["rerankerMethod"] = "LLM_CROSS_ENCODER"
            return result[:top_k]
        except Exception as exc:
            logger.warning("LLM reranker failed for contract clauses: %s — falling back to keyword", exc)
            return _rerank_contract_hits_keyword(query, hits)[:top_k]

    def rerank_policy_items(
        self, query: str, hits: list[dict], top_k: int
    ) -> list[dict]:
        """Re-rank knowledge base / standard clause candidates.

        Args:
            query: The review question or search query.
            hits: Candidate policy item dicts.
            top_k: Maximum number of results to return after reranking.

        Returns:
            Re-ranked hits, truncated to top_k.
        """
        if len(hits) <= 1:
            return hits[:top_k]

        if not self._configured:
            # No keyword fallback for policy items — just keep original order + diversify
            return hits[:top_k]

        try:
            rankings = self._llm_rerank(query, hits, "policy")
            if rankings is None:
                return hits[:top_k]
            result = [hits[i] for i in rankings]
            for idx, hit in enumerate(result):
                hit["rerankPosition"] = idx + 1
                hit["rerankerMethod"] = "LLM_CROSS_ENCODER"
            return result[:top_k]
        except Exception as exc:
            logger.warning("LLM reranker failed for policy items: %s", exc)
            return hits[:top_k]

    # ── Internal ───────────────────────────────────────────────────────

    def _llm_rerank(
        self, query: str, hits: list[dict], source_type: str
    ) -> list[int] | None:
        """Call the LLM to re-rank candidates. Returns ordered indices or None."""
        if not self._client or not self._model:
            return None

        # Build candidate blocks
        if source_type == "contract":
            system_prompt = _CONTRACT_RERANK_SYSTEM
            candidate_blocks = [
                _build_contract_candidate_block(i, hit) for i, hit in enumerate(hits)
            ]
        else:
            system_prompt = _POLICY_RERANK_SYSTEM
            candidate_blocks = [
                _build_policy_candidate_block(i, hit) for i, hit in enumerate(hits)
            ]

        candidates_text = "\n\n".join(candidate_blocks)
        user_prompt = (
            f"问题：{query}\n\n"
            f"候选列表（共 {len(hits)} 条，请全部排序）：\n\n"
            f"{candidates_text}\n\n"
            f"请按与问题的相关性从高到低排序所有 {len(hits)} 个候选项，返回 JSON。"
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            raw = response.choices[0].message.content or ""
            logger.debug("Reranker LLM response: %.300s", raw)
            return _parse_rerank_response(raw, len(hits))
        except (APIError, APIConnectionError) as exc:
            logger.warning("Reranker LLM API error: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Reranker unexpected error: %s", exc)
            return None


# ── Singleton ─────────────────────────────────────────────────────────────

_reranker: LLMReranker | None = None


def get_reranker() -> LLMReranker:
    """Return the singleton LLMReranker instance."""
    global _reranker
    if _reranker is None:
        _reranker = LLMReranker()
    return _reranker


# ── Keyword-bonus fallback (preserved from original contract_store) ────────

_CONTRACT_SEARCH_TERMS = (
    "付款", "支付", "发票", "工作日", "自然日", "验收", "交付", "续签", "终止",
    "到期", "通知", "逾期", "违约", "赔偿", "保密", "个人信息", "数据",
)


def _rerank_contract_hits_keyword(query: str, hits: list[dict]) -> list[dict]:
    """Original keyword-bonus heuristic — used as fallback when no reranker API key."""
    terms = [term for term in _CONTRACT_SEARCH_TERMS if term in query]
    if not terms:
        for idx, hit in enumerate(hits):
            hit["rerankPosition"] = idx + 1
            hit["rerankerMethod"] = "KEYWORD_BONUS_NO_MATCH"
        return hits

    def score(hit: dict) -> float:
        text = " ".join([
            str(hit.get("title") or ""),
            str(hit.get("clauseNumber") or ""),
            str(hit.get("snippet") or ""),
            str(hit.get("content") or ""),
            str(hit.get("clauseType") or ""),
        ])
        bonus = sum(1 for term in terms if term in text)
        return bonus * 1000 + float(hit.get("score") or 0)

    result = sorted(hits, key=score, reverse=True)
    for idx, hit in enumerate(result):
        hit["rerankPosition"] = idx + 1
        hit["rerankerMethod"] = "KEYWORD_BONUS"
    return result
