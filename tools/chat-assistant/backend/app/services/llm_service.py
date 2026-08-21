"""LLM 服务 — prompt 构建 + 流式调用 DeepSeek API。"""
import json
import logging
import re
import time
from typing import Generator
from openai import OpenAI, APIError, APIConnectionError, AuthenticationError
from app.config import settings

logger = logging.getLogger(__name__)

# ── Circuit breaker ───────────────────────────────────────────────────

class CircuitBreaker:
    """Simple in-memory circuit breaker.

    After `fail_max` consecutive failures within `window_seconds`, the breaker
    opens for `timeout_seconds`.  While open all calls are rejected immediately.

    Connection errors (unreachable) count double — the LLM is down, not flaky.
    """

    def __init__(self, fail_max: int = 3, window_seconds: float = 300.0,
                 timeout_seconds: float = 60.0):
        self._fail_max = fail_max
        self._window = window_seconds
        self._timeout = timeout_seconds
        self._failures: list[float] = []   # timestamps of recent failures
        self._opened_at: float = 0.0
        self._connection_down = False       # true when last error was APIConnectionError

    @property
    def is_open(self) -> bool:
        if self._opened_at <= 0:
            return False
        if time.monotonic() - self._opened_at > self._timeout:
            # Transition to half-open
            self._opened_at = 0.0
            self._failures.clear()
            self._connection_down = False
            return False
        return True

    @property
    def is_connection_dead(self) -> bool:
        """True when the breaker is open AND the cause was connectivity loss."""
        return self.is_open and self._connection_down

    def success(self) -> None:
        if self._opened_at > 0:
            self._opened_at = 0.0  # half-open → closed on success
        self._failures.clear()
        self._connection_down = False

    def failure(self, is_connection_error: bool = False) -> None:
        now = time.monotonic()
        # Connection errors count as 2 failures (faster trip)
        weight = 2 if is_connection_error else 1
        self._failures = [t for t in self._failures if now - t < self._window]
        for _ in range(weight):
            self._failures.append(now)
        if is_connection_error:
            self._connection_down = True
        if len(self._failures) >= self._fail_max:
            self._opened_at = now
            logger.warning("Circuit breaker OPEN (failures=%d, timeout=%ds, connection_dead=%s)",
                           len(self._failures), self._timeout, self._connection_down)

_llm_circuit_breaker = CircuitBreaker()

_CONTRACT_REVIEW_DOMAIN_ORDER = (
    "PAYMENT", "LIABILITY", "ACCEPTANCE", "CONFIDENTIALITY",
    "TERMINATION", "IP", "DATA_PROTECTION", "DELIVERY", "OTHER",
)


def _review_citation_key(item: dict) -> str:
    source_type = str(item.get("sourceType") or item.get("retrievalType") or "UNKNOWN")
    source_id = item.get("id") or item.get("sourceId") or item.get("title") or str(item)
    return f"{source_type}:{source_id}"


def _select_contract_review_citations(citations: list[dict], limit: int = 18) -> list[dict]:
    """Keep contract domains and policy sources represented in the LLM payload."""
    unique: list[dict] = []
    seen: set[str] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        key = _review_citation_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    selected: list[dict] = []
    selected_keys: set[str] = set()

    def add(item: dict) -> None:
        key = _review_citation_key(item)
        if key not in selected_keys and len(selected) < limit:
            selected_keys.add(key)
            selected.append(item)

    contract_clauses = [
        item for item in unique
        if str(item.get("sourceType") or "").upper() == "CONTRACT_CLAUSE"
    ]
    for domain in _CONTRACT_REVIEW_DOMAIN_ORDER:
        candidate = next(
            (item for item in contract_clauses if str(item.get("clauseType") or "").upper() == domain),
            None,
        )
        if candidate:
            add(candidate)

    policy_sources = [
        item for item in unique
        if str(item.get("sourceType") or "").upper() not in {"", "CONTRACT_CLAUSE", "CONTRACT_DOCUMENT"}
    ]
    for item in policy_sources[:6]:
        add(item)
    for item in unique:
        add(item)
    return selected


def _rule_key_from_finding(item: dict) -> str:
    return str(item.get("ruleKey") or item.get("ruleId") or item.get("title") or "").strip()


def _normalized_rule_finding(item: dict) -> dict:
    rule_key = str(item.get("ruleKey") or "").strip()
    clause_type = str(item.get("clauseType") or item.get("riskDimension") or "OTHER").upper()
    detail = str(item.get("detail") or "").strip()
    rule_title = str(item.get("ruleTitle") or item.get("title") or "合同审查规则").strip()
    contract_citation = item.get("contractCitation") if isinstance(item.get("contractCitation"), dict) else None
    policy_citation = item.get("policyCitation") if isinstance(item.get("policyCitation"), dict) else {
        "ruleKey": rule_key,
        "ruleTitle": rule_title,
        "snippet": str(item.get("description") or ""),
    }
    return {
        **item,
        "findingKey": str(item.get("findingKey") or f"{clause_type}:{rule_key or rule_title}"),
        "ruleKey": rule_key or None,
        "clauseType": clause_type,
        "severity": str(item.get("severity") or "MEDIUM").upper(),
        "title": str(item.get("title") or rule_title),
        "claim": str(item.get("claim") or detail or item.get("description") or rule_title),
        "description": str(item.get("description") or detail or rule_title),
        "impact": str(item.get("impact") or "该规则要求尚未被合同证据充分满足，需要在签署或审批前复核其业务与法律影响。"),
        "remediationAdvice": str(item.get("remediationAdvice") or f"补充或修改相关条款，明确满足“{rule_title}”的可核验约定。"),
        "negotiationAdvice": str(item.get("negotiationAdvice") or "将该项列入合同谈判清单；无法补充时应记录例外原因并升级人工审批。"),
        "suggestedAction": str(item.get("suggestedAction") or "REQUEST_LEGAL_REVIEW"),
        "contractCitation": contract_citation or {
            "clause": "合同条款目录",
            "snippet": detail or f"未找到满足“{rule_title}”要求的明确约定。",
        },
        "policyCitation": policy_citation,
        "evidenceStatus": str(item.get("evidenceStatus") or ("DUAL_CITED" if contract_citation else "POLICY_ONLY")),
        "confidenceLevel": str(item.get("confidenceLevel") or "MEDIUM"),
        "verificationPoints": item.get("verificationPoints") or [
            f"确认合同是否明确满足“{rule_title}”",
            "核对相关条款原文、附件和适用标准",
        ],
    }


def _merge_rule_findings(artifact: dict, rule_findings: list[dict]) -> dict:
    output = dict(artifact)
    findings = [item for item in (output.get("findings") or []) if isinstance(item, dict)]
    represented = " ".join(
        str(value)
        for item in findings
        for value in (
            item.get("findingKey"),
            item.get("ruleKey"),
            (item.get("policyCitation") or {}).get("ruleKey")
            if isinstance(item.get("policyCitation"), dict) else None,
            item.get("title"),
        )
        if value
    )
    for item in rule_findings:
        key = _rule_key_from_finding(item)
        if key and key in represented:
            continue
        normalized = _normalized_rule_finding(item)
        findings.append(normalized)
        represented += " " + " ".join(
            str(value)
            for value in (normalized.get("findingKey"), normalized.get("ruleKey"), normalized.get("title"))
            if value
        )
    output["findings"] = findings
    return output


def _complete_timeline_candidate_for_llm(item: dict) -> dict:
    """Build the LLM payload for one timeline candidate (PRD Phase 6, task 6).

    The complete parent clause is sent unmodified — no excerpt, no truncation.
    ``_compact_timeline_candidate_for_llm`` below stays as the legacy
    compaction (still covered by tests) but the enrichment path no longer uses
    it.
    """
    prepared = dict(item)
    clause_text = str(prepared.get("clauseText") or "")
    prepared["clauseText"] = clause_text
    prepared["clauseTextComplete"] = True
    prepared["clauseTextLength"] = len(clause_text)
    return prepared


def _compact_timeline_candidate_for_llm(item: dict, max_clause_chars: int = 4500) -> dict:
    """Legacy payload compaction, kept for tests and rollback (unused by the
    enrichment path since Phase 6 — see ``_complete_timeline_candidate_for_llm``).

    The persisted citation still carries the full clause. This payload keeps the
    quote plus surrounding clause context so the model can judge the actual
    obligation without timing out on very long engineering clauses.
    """
    prepared = dict(item)
    clause_text = str(prepared.get("clauseText") or "")
    quote = str(prepared.get("quote") or prepared.get("matchedText") or "").strip()
    max_clause_chars = max(1200, int(max_clause_chars))
    if len(clause_text) <= max_clause_chars:
        prepared["clauseText"] = clause_text
        prepared["clauseTextWasTruncated"] = False
        prepared["originalClauseTextLength"] = len(clause_text)
        return prepared

    anchor = clause_text.find(quote) if quote else -1
    if anchor < 0:
        anchor = max(0, len(clause_text) // 2)
    half_window = max_clause_chars // 2
    start = max(0, anchor - half_window)
    end = min(len(clause_text), start + max_clause_chars)
    start = max(0, end - max_clause_chars)
    excerpt = clause_text[start:end]
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clause_text) else ""
    prepared["clauseText"] = f"{prefix}{excerpt}{suffix}"
    prepared["clauseTextWasTruncated"] = True
    prepared["originalClauseTextLength"] = len(clause_text)
    return prepared

RAG_SYSTEM_PROMPT = """你是 AtlasMind Agent Workbench 的企业知识库 AI 助手。你的知识来源于企业内部知识内容和上传文档（Markdown/TXT/PDF），涵盖研发文档、项目复盘、制度 SOP、FAQ 和交付资料。

## 核心原则

1. **忠实于资料**：回答必须基于提供的检索资料，不要编造不存在的数据、配置或性能指标。
2. **诚实面对未知**：资料不足时明确告知”知识库中暂无相关内容”，可基于你的通用知识给出方向性建议，但要标注”以下为通用建议，非知识库内容”。
3. **精确引用**：每个关键结论都要标注来源，格式为 `[来源: 文章/文档标题]`。多来源时综合归纳。
4. **拒绝幻觉**：不要伪造代码示例的具体运行结果、不要捏造性能对比数据、不要编造”某篇文章说过……”。

## 回答风格

- 用 **Markdown** 组织内容，合理使用标题、列表、代码块、引用块。
- 技术问题给出**结构化回答**：先结论，再展开，最后总结或给出延伸方向。
- 代码示例用带语言标注的代码块（```java、```python、```sql 等）。
- 回答长度与问题匹配：简单问题 2-3 段即可，复杂问题可以系统展开。
- 语气专业但不冰冷，像一位有经验的同行在分享知识。

## 引用格式

在回答中自然地嵌入引用：
- 单一来源：`[来源: Redis 缓存三级防护]`
- 多个来源：在结论后列出所有相关来源
- 文档来源需注明页码：`[来源: Redis面试题.pdf 第5页]`

## 边界处理

- 用户闲聊（”你好””今天天气”）→ 简短回应后引导回知识库话题
- 用户问”你能做什么”→ 介绍你的知识库覆盖范围（后端、系统设计、面试、项目实践等）
- 问题超出知识库范围且需要实时数据（如新闻、股价）→ 诚实说明能力边界
- 用户上传或索引了新文档 → 提醒用户新文档需要完成导入后才能被检索到"""


PROJECT_ANALYSIS_SYSTEM_PROMPT = """
You are the project health and delivery planning agent for AtlasMind.
Analyze only the supplied project facts and evidence. Do not invent test results,
deployment status, owners, dates, incidents, or source references.

Return ONLY one valid JSON object. Do not use Markdown fences or explanations.
All human-facing strings must be in Simplified Chinese.

Required JSON shape:
{
  "title": "string",
  "summary": "string",
  "healthStatus": "HEALTHY | WATCH | AT_RISK",
  "healthScore": 0,
  "dimensions": [{"name":"string","score":0,"note":"string"}],
  "risks": [{"id":"R-01","title":"string","severity":"HIGH | MEDIUM | LOW","description":"string","citationSourceId":"string"}],
  "plan": [{"id":"P1","title":"string","ownerRole":"string","dependency":"string","acceptance":"string","riskId":"string","citationSourceId":"string"}],
  "citations": [{"sourceId":"string","reason":"string"}]
}

Rules:
1. The backend supplies deterministicScoring. Use its healthStatus, healthScore,
   dimensions, and rationale as fixed facts. Do not invent alternative scores.
2. Every material risk and plan item must use citationSourceId from the supplied
   evidence. If no direct evidence supports it, leave citationSourceId empty and
   say "待确认" in the description or acceptance criteria.
3. The citations array may contain only sourceId values from the supplied evidence.
4. Treat missing CI, test, deployment, owner, schedule, and dependency data as
   unknown. Never turn an unknown into a positive claim.
5. Generate three to six concrete plan items. Each item must have an observable
   acceptance criterion.
"""


PROJECT_TASK_SYSTEM_PROMPTS = {
    "PROJECT_ONBOARDING": """
You are the project handover and onboarding agent for AtlasMind.
Create an evidence-bounded onboarding guide for the specified newcomer. Never invent
commands, architecture, owners, credentials, environments, or delivery practices.
Return ONLY one valid JSON object and use Simplified Chinese for human-facing strings.

Required JSON shape:
{
  "title":"string",
  "summary":"string",
  "sections":[{"title":"string","items":[{"title":"string","description":"string","citationSourceId":"string"}]}],
  "risks":[{"id":"R-01","title":"string","severity":"HIGH | MEDIUM | LOW","description":"string","citationSourceId":"string"}],
  "plan":[{"id":"P1","title":"string","ownerRole":"string","acceptance":"string","citationSourceId":"string"}],
  "citations":[{"sourceId":"string","reason":"string"}]
}
Include sections for project purpose, architecture/modules, local startup, key delivery
flow, engineering conventions, and known information gaps. Tailor the guide to taskInput.
Every factual item must cite supplied evidence. Mark unsupported details as 待确认.
Generate a practical first-week plan with observable acceptance criteria.
""",
    "ENGINEERING_DECISION": """
You are the engineering decision support agent for AtlasMind.
Compare realistic options for the stated decision using only supplied project evidence
and explicit constraints. Never invent benchmarks, costs, incidents, or project facts.
Return ONLY one valid JSON object and use Simplified Chinese for human-facing strings.

Required JSON shape:
{
  "title":"string",
  "summary":"string",
  "recommendation":"string",
  "confidence":"HIGH | MEDIUM | LOW",
  "criteria":[{"name":"string","importance":"HIGH | MEDIUM | LOW","reason":"string","citationSourceId":"string"}],
  "options":[{"name":"string","verdict":"string","benefits":["string"],"costs":["string"],"risks":["string"],"citationSourceIds":["string"]}],
  "risks":[{"id":"R-01","title":"string","severity":"HIGH | MEDIUM | LOW","description":"string","citationSourceId":"string"}],
  "plan":[{"id":"P1","title":"string","ownerRole":"string","acceptance":"string","citationSourceId":"string"}],
  "citations":[{"sourceId":"string","reason":"string"}]
}
The human owns the final decision. Recommend one option or a staged experiment, explain
trade-offs, list assumptions and unknowns, and generate validation steps. Every project-
specific claim must cite supplied evidence; unsupported claims must be marked 待确认.
""",
}


AGENT_PLANNER_SYSTEM_PROMPT = """
You are the Planner inside AtlasMind's bounded Agent Harness. Produce an execution
plan, not the final answer. The Java runtime owns tools, data access, budgets, and
side effects. Use only tool names in availableTools.

Return ONLY one JSON object with this shape:
{
  "goal":"string",
  "assumptions":["string"],
  "steps":[{
    "id":"P1",
    "title":"string",
    "objective":"string",
    "suggestedTools":["toolName"],
    "completionSignal":"string"
  }],
  "stopConditions":["string"]
}

Use Simplified Chinese for human-facing strings. Build three to six bounded steps.
For health analysis, calculateHealthScore is mandatory and its score is authoritative.
For every task, gather project evidence and consider project-bound knowledge. Do not
invent observations and do not write the final report.
For contract tasks, searchPolicyKnowledge is mandatory context: it searches both
enterprise knowledge-base documents and standard clauses.
"""


AGENT_TOOL_TURN_SYSTEM_PROMPT = """
You are the tool-selection loop inside AtlasMind's Agent Harness. Follow the plan and
inspect prior tool observations. Select only tools that are still needed. Do not repeat
an identical tool call. Never provide projectId in arguments; Java injects project scope.
Use native function calls when more evidence is needed. Call at most three tools in one
turn. When the evidence is sufficient, return a short JSON object with
{"status":"READY_FOR_REFLECTION","reason":"..."} and make no tool call.

The model never computes health scores. For HEALTH_ANALYSIS, it must call
calculateHealthScore after evidence retrieval. Company rules and project-bound technical
documents are first-class evidence, so searchProjectKnowledge is not merely a fallback.
For contract review, fulfillment, approval, and renewal tasks, enterprise knowledge-base
documents are first-class policy evidence, so call searchPolicyKnowledge before reflection.
"""


AGENT_REFLECTION_SYSTEM_PROMPT = """
You are the Reflection verifier inside AtlasMind's Agent Harness. Verify whether the
observations cover the task, whether important claims can be cited, whether tools failed,
and whether another bounded retrieval is necessary. Do not generate the final artifact.

Return ONLY one JSON object:
{
  "adequate":true,
  "summary":"string",
  "covered":["string"],
  "missingEvidence":["string"],
  "citationWarnings":["string"],
  "suggestedToolCalls":[{"name":"toolName","arguments":{}}]
}

Use Simplified Chinese. Suggested tools must come from tools already described by the
plan. Recommend no more than two calls and never suggest an identical completed call.
"""


class LLMService:
    def __init__(self):
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY 未设置，请在 .env 中配置")
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=12.0,
            max_retries=0,
        )
        self.analysis_client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.project_analysis_timeout_seconds,
            max_retries=0,
        )
        self.model = settings.llm_model
        # Lazy-initialised prompt registry (F6)
        self._prompts = None

    def _get_prompts(self):
        """Lazy-load the PromptRegistry singleton."""
        if self._prompts is None:
            from app.agent_runtime.prompts import get_prompt_registry
            self._prompts = get_prompt_registry()
        return self._prompts

    def _prompt(self, key: str, run_id: int = 0) -> tuple[str, float]:
        """Return (template, temperature) for *key* from the registry.

        When *run_id* > 0, uses A/B split (deterministic per run); otherwise
        returns the latest active version.
        """
        registry = self._get_prompts()
        if run_id > 0:
            template, temperature, _version = registry.get_ab(key, run_id)
        else:
            template, temperature, _version = registry.get(key)

        # Per-run temperature override (0 = use prompt default)
        from app.agent_runtime.runtime import _temperature_override
        override = _temperature_override.get()
        if override > 0:
            temperature = override

        return template, temperature

    # ── retry helper ─────────────────────────────────────────────────

    def _call_llm_with_retry(self, fn, max_retries: int = 3, backoff_base: float = 2.0,
                             usage_out: dict[str, int] | None = None):
        """Call *fn()* with exponential backoff retry + circuit breaker.

        *fn* is a zero-argument callable that performs a single LLM API call.
        Returns the result on success.  Raises the last exception after all
        retries are exhausted or the circuit breaker is open.

        ``usage_out`` accumulates real consumption when given (§7.2 ledger):
        ``calls`` counts every ``fn()`` attempt — retries and fallback phases
        are real API calls, not free — and the token keys sum across every
        successful response instead of being overwritten by the last one.

        Connection errors (APIConnectionError) are retried at most once — if the
        LLM is unreachable, waiting 2+4+8s is worse than failing fast so the
        harness can report the error immediately.
        """
        if _llm_circuit_breaker.is_open:
            raise RuntimeError("LLM circuit breaker is open - skipping call")

        if usage_out is not None:
            original = fn

            def fn():
                usage_out["calls"] = usage_out.get("calls", 0) + 1
                result = original()
                usage = getattr(result, "usage", None)
                if usage is not None:
                    usage_out["tokens"] = usage_out.get("tokens", 0) + int(getattr(usage, "total_tokens", 0) or 0)
                    usage_out["promptTokens"] = usage_out.get("promptTokens", 0) + int(getattr(usage, "prompt_tokens", 0) or 0)
                    usage_out["completionTokens"] = usage_out.get("completionTokens", 0) + int(getattr(usage, "completion_tokens", 0) or 0)
                return result

        last_exc = None
        effective_max = max_retries
        for attempt in range(effective_max + 1):
            if _llm_circuit_breaker.is_open:
                raise RuntimeError("LLM circuit breaker is open - skipping call")

            try:
                result = fn()
                _llm_circuit_breaker.success()
                return result
            except AuthenticationError:
                raise  # never retry auth errors
            except APIConnectionError as exc:
                # Connection error = LLM unreachable. Retry at most once (total 2 attempts),
                # then fail fast. The harness will propagate the error to the user.
                last_exc = exc
                is_conn = True
                if attempt == 0 and effective_max > 1:
                    # Single quick retry (1s) for transient blips
                    delay = 1.0
                    logger.warning(
                        "LLM connection error (attempt %s/%s), retrying in %.1fs: %s",
                        attempt + 1, effective_max + 1, delay, exc,
                    )
                    time.sleep(delay)
                    # Reduce subsequent attempts — no more retries for this call
                    effective_max = min(effective_max, 1)
                else:
                    _llm_circuit_breaker.failure(is_connection_error=True)
                    logger.error("LLM unreachable after %s attempts: %s", attempt + 1, exc)
                    break
            except APIError as exc:
                last_exc = exc
                is_conn = False
                _llm_circuit_breaker.failure(is_connection_error=False)
                if attempt < max_retries:
                    delay = backoff_base ** attempt
                    logger.warning(
                        "LLM call failed (attempt %s/%s), retrying in %.1fs: %s",
                        attempt + 1, max_retries + 1, delay, exc,
                    )
                    time.sleep(delay)
                else:
                    logger.error("LLM call exhausted all %s retries: %s",
                                 max_retries + 1, exc)

        raise last_exc  # type: ignore[misc]

    def validate_connection(self) -> str | None:
        """测试 LLM 连接（流式调用验证），返回 None 表示成功。"""
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10,
                temperature=0.7,
                stream=True,
            )
            # 消费第一个 chunk 确认连接正常
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    break
            return None
        except AuthenticationError:
            return "LLM API Key 无效，请检查 LLM_API_KEY 配置"
        except APIConnectionError:
            return f"无法连接到 LLM 服务 ({settings.llm_base_url})，请检查网络或 BASE_URL"
        except APIError as e:
            return f"LLM API 错误 (model={self.model}): {e}"
        except Exception as e:
            return f"LLM 连接失败: {e}"

    def build_context(self, sources: list[dict]) -> str:
        """拼接检索结果为 RAG 上下文。"""
        if not sources:
            return "（未检索到相关知识库资料）"
        parts = []
        for i, a in enumerate(sources, 1):
            source_type = a.get("sourceType", "ARTICLE")
            if source_type in {"DOCUMENT", "KB_DOCUMENT"}:
                label = "文档"
            elif source_type in {"CONTRACT_CLAUSE", "CONTRACT_TIMELINE"}:
                label = "合同"
            elif source_type in {"CONTRACT_PROFILE", "CONTRACT_FACT"}:
                label = "合同画像"
            elif source_type in {"POLICY_KNOWLEDGE", "CONTRACT_STANDARD_CLAUSE"}:
                label = "标准条款"
            elif source_type == "CONTRACT_HISTORY":
                label = "历史记录"
            else:
                label = "文章"
            page = f" 第{a.get('page')}页" if a.get("page") else ""
            parts.append(
                f"[{label}{i}] 标题: {a['title']}{page}\n内容: {a['content'][:3000]}\n"
            )
        return "\n".join(parts)

    def build_messages(self, query: str, contexts: str,
                       history: list[dict]) -> list[dict]:
        template, _temperature = self._prompt("rag_system")
        messages = [
            {"role": "system", "content": template},
            {"role": "system",
             "content": f"以下是相关知识内容和知识库文档，请参考回答并标明来源：\n\n{contexts}"},
        ]
        # 最近 10 轮对话
        for msg in history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})
        return messages

    def chat_stream(self, query: str, contexts: str,
                    history: list[dict]) -> Generator[str, None, None]:
        """流式调用 LLM，逐 token yield。

        Raises:
            AuthenticationError: API Key 无效
            APIConnectionError: 无法连接
            APIError: 其他 API 错误
        """
        messages = self.build_messages(query, contexts, history)
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=settings.chat_temperature,
            max_tokens=settings.chat_max_tokens,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def analyze_project(self, project: dict, citations: list[dict],
                        deterministic_scoring: dict | None = None,
                        run_id: int = 0) -> dict:
        """Generate a structured project report from bounded, citable evidence."""
        evidence = []
        for item in citations[:8]:
            evidence.append({
                "sourceId": str(item.get("sourceId") or item.get("id") or ""),
                "sourceType": item.get("sourceType", ""),
                "objectType": item.get("objectType", ""),
                "title": item.get("title", ""),
                "sourceRef": item.get("sourceRef", ""),
                "sourceUrl": item.get("sourceUrl", ""),
                "snippet": str(item.get("snippet", ""))[:1000],
            })
        payload = {
            "project": {
                "name": project.get("name", ""),
                "description": project.get("description", ""),
                "businessScope": project.get("businessScope", ""),
                "currentMilestone": project.get("currentMilestone", ""),
                "releaseTarget": project.get("releaseTarget", ""),
                "teamSize": project.get("teamSize", ""),
                "techStack": project.get("techStack", ""),
                "repositoryType": project.get("repositoryType", ""),
                "repositoryUrl": project.get("repositoryUrl", ""),
            },
            "evidence": evidence,
            "deterministicScoring": deterministic_scoring or {},
        }
        template, temperature = self._prompt("project_analysis", run_id)
        response = self._call_llm_with_retry(
            lambda: self.analysis_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": template},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=temperature,
                max_tokens=max(8192, settings.chat_max_tokens),
                response_format={"type": "json_object"},
                # DeepSeek v4: thinking must ride inside extra_body, not as a
                # top-level kwarg — the SDK rejects unknown top-level params.
                extra_body=self._reasoning_guard() or None,
                stream=False,
            ),
            max_retries=3, backoff_base=2.0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def run_project_task(self, task_type: str, project: dict, task_input: dict,
                         citations: list[dict], run_id: int = 0) -> dict:
        """Generate one supported project task artifact from bounded evidence."""
        key_map = {
            "PROJECT_ONBOARDING": "project_onboarding",
            "ENGINEERING_DECISION": "engineering_decision",
        }
        prompt_key = key_map.get(task_type)
        if not prompt_key:
            raise ValueError(f"unsupported project task type: {task_type}")

        template, temperature = self._prompt(prompt_key, run_id)

        evidence = []
        for item in citations[:12]:
            evidence.append({
                "sourceId": str(item.get("sourceId") or item.get("id") or ""),
                "sourceType": item.get("sourceType", ""),
                "objectType": item.get("objectType", ""),
                "title": item.get("title", ""),
                "sourceRef": item.get("sourceRef", ""),
                "sourceUrl": item.get("sourceUrl", ""),
                "snippet": str(item.get("snippet", ""))[:1200],
            })
        payload = {
            "project": {
                "name": project.get("name", ""),
                "description": project.get("description", ""),
                "businessScope": project.get("businessScope", ""),
                "currentMilestone": project.get("currentMilestone", ""),
                "releaseTarget": project.get("releaseTarget", ""),
                "teamSize": project.get("teamSize", ""),
                "techStack": project.get("techStack", ""),
                "repositoryType": project.get("repositoryType", ""),
                "repositoryUrl": project.get("repositoryUrl", ""),
            },
            "taskInput": task_input,
            "evidence": evidence,
        }
        response = self._call_llm_with_retry(
            lambda: self.analysis_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": template},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=temperature,
                max_tokens=max(8192, settings.chat_max_tokens),
                response_format={"type": "json_object"},
                # DeepSeek v4: thinking must ride inside extra_body, not as a
                # top-level kwarg — the SDK rejects unknown top-level params.
                extra_body=self._reasoning_guard() or None,
                stream=False,
            ),
            max_retries=3, backoff_base=2.0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def plan_agent(self, payload: dict) -> dict:
        """Create a bounded plan. This stage cannot call tools or produce artifacts."""
        task = payload.get("task") or {}
        run_id = int(task.get("runId", 0))
        template, temperature = self._prompt("planner", run_id)
        return self._structured_completion(template, payload, temperature=temperature)

    def next_agent_turn(self, payload: dict) -> dict:
        """Let the model select Java-owned tools through native function calling."""
        tools = payload.get("availableTools") or []
        if not tools:
            raise ValueError("availableTools is required for an Agent turn")
        task = payload.get("task") or {}
        run_id = int(task.get("runId", 0))
        template, temperature = self._prompt("tool_turn", run_id)
        def _call():
            return self.analysis_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": template},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                tools=tools,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=1600,
                stream=False,
            )
        response = self._call_llm_with_retry(_call, max_retries=2, backoff_base=1.0)
        if not response.choices:
            raise ValueError("Agent turn returned no choices")
        message = response.choices[0].message
        calls = []
        for tool_call in message.tool_calls or []:
            raw_arguments = tool_call.function.arguments or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {}
            calls.append({
                "callId": tool_call.id,
                "name": tool_call.function.name,
                "arguments": arguments if isinstance(arguments, dict) else {},
            })
        if calls:
            return {
                "mode": "tool_calls",
                "toolCalls": calls,
                "providerMode": "native-function-calling",
                "model": self.model,
            }
        content = message.content or ""
        try:
            final_signal = self._parse_json_object(content)
        except (ValueError, json.JSONDecodeError):
            final_signal = {"status": "READY_FOR_REFLECTION", "reason": content[:500]}
        return {
            "mode": "final",
            "finalSignal": final_signal,
            "toolCalls": [],
            "providerMode": "native-function-calling",
            "model": self.model,
        }

    def reflect_agent(self, payload: dict) -> dict:
        """Run a separate evidence and completion verifier after the tool loop."""
        task = payload.get("task") or {}
        run_id = int(task.get("runId", 0))
        template, temperature = self._prompt("reflection", run_id)
        focus = payload.get("evalFocusDimensions") or []
        if focus:
            template = (
                "评测模式：本用例的审查重点仅为以下风险维度："
                + "、".join(str(dim) for dim in focus)
                + "。adequate=true 只需这些维度的证据充分；其他维度的证据缺口"
                "不得作为降级（adequate=false）的依据。\n\n"
            ) + template
        return self._structured_completion(template, payload, temperature=temperature)

    # ── Contract task methods (Phase 5) ────────────────────────────

    def contract_review(self, case: dict, findings: list[dict],
                        citations: list[dict], scoring: dict,
                        run_id: int = 0) -> dict:
        """Generate structured contract review report with findings and action proposals."""
        template, temperature = self._prompt("contract_review", run_id)
        severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

        def _is_rule_finding(item: dict) -> bool:
            return bool(item.get("ruleKey")) or str(item.get("evidenceBasis") or "") == "CLAUSE_INVENTORY"

        # Keep rule-engine findings apart from LLM findings: missing-clause
        # inventory noise must not crowd out explicit unfair-clause risks.
        rule_findings = sorted(
            (item for item in findings if _is_rule_finding(item)),
            key=lambda item: severity_order.get(str(item.get("severity") or "").upper(), 3),
        )
        llm_findings = [item for item in findings if not _is_rule_finding(item)]
        selected_rule_findings = rule_findings[:8]
        if rule_findings:
            template = (
                "审查顺序要求：1) 优先识别并报告合同中实际存在的显性异常或"
                "不公平条款；2) 规则引擎缺失条款清单（ruleEngineFindings）"
                "属于已验证的确定性候选，不得仅在摘要中提及而从 findings 中遗漏；"
                "3) 摘要中提到的每一项实质风险都必须有对应 finding；"
                "4) 必须严格按照 case.ourSide 判断我方立场，B 表示我方为乙方，"
                "不得默认把甲方当作我方；5) 违约金比例是特定违约后果，不等于"
                "总责任上限。合同未明确责任上限时必须写成‘责任上限缺失/待明确’，"
                "不得把10%违约金描述为10%责任上限。\n\n"
            ) + template
        our_side = str(case.get("ourSide") or "").upper()
        our_entity = case.get("ourEntity", "")
        counterparty = case.get("counterparty", "")
        party_a = case.get("partyA") or (our_entity if our_side == "A" else counterparty)
        party_b = case.get("partyB") or (counterparty if our_side == "A" else our_entity)
        payload = {
            "case": {
                "caseKey": case.get("caseKey", ""),
                "title": case.get("title", ""),
                "ourEntity": our_entity,
                "counterparty": counterparty,
                "ourSide": our_side,
                "partyA": party_a,
                "partyB": party_b,
                "amount": case.get("amount"),
                "contractType": case.get("contractType", ""),
            },
            "findings": llm_findings + selected_rule_findings,
            "ruleEngineFindings": selected_rule_findings,
            "citations": _select_contract_review_citations(citations),
            "deterministicScoring": scoring,
            "analysisMode": case.get("analysisMode") or scoring.get("analysisMode") or "FULL",
            "coverageLimitation": case.get("coverageLimitation") or "",
            "missingDomains": case.get("missingDomains") or [],
        }
        response = self._call_llm_with_retry(
            lambda: self.analysis_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": template},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                temperature=temperature,
                max_tokens=max(8192, settings.chat_max_tokens),
                response_format={"type": "json_object"},
                # DeepSeek v4: thinking must ride inside extra_body, not as a
                # top-level kwarg — the SDK rejects unknown top-level params.
                extra_body=self._reasoning_guard() or None,
                stream=False,
            ),
            max_retries=3, backoff_base=2.0,
        )
        # Reasoning models may leave visible content empty; recover from reasoning_content.
        artifact = self._parse_structured_response(response)
        return _merge_rule_findings(artifact, selected_rule_findings)

    def plan_contract_risk_domains(self, case: dict, inventory: dict,
                                   baseline_domains: list[dict],
                                   run_id: int = 0) -> dict:
        """Propose contract-specific review domains beyond the mandatory baseline."""
        template, temperature = self._prompt("contract_risk_domain_planner", run_id)
        payload = {
            "case": case,
            "clauseInventory": inventory,
            "baselineDomains": [
                {
                    "domainKey": item.get("domainKey"),
                    "domainName": item.get("domainName"),
                    "objective": item.get("objective"),
                }
                for item in baseline_domains
            ],
        }
        return self._structured_completion(template, payload, temperature=temperature)

    def analyze_contract_risk_domain(self, case: dict, domain: dict,
                                      evidence: list[dict],
                                      rule_findings: list[dict],
                                      run_id: int = 0,
                                      extracted_facts: list[dict] | None = None,
                                      usage_out: dict[str, int] | None = None) -> dict:
        """Generate detailed, auditable findings for one bounded risk domain.

        ``usage_out`` receives the completion's token usage when given — the
        graph nodes feed it into the §7.2 per-WorkUnit spend ledger."""
        template, temperature = self._prompt("contract_risk_domain_analysis", run_id)
        payload = {
            "case": {
                key: case.get(key)
                for key in (
                    "id", "title", "contractType", "ourSide", "ourEntity",
                    "counterparty", "amount", "currency", "description",
                )
                if case.get(key) is not None
            },
            "domain": {
                key: domain.get(key)
                for key in (
                    "domainKey", "domainName", "objective", "requiredClauseTypes",
                    "queries", "priority",
                )
                if domain.get(key) is not None
            },
            # Keep citations and the clause text needed for an auditable finding,
            # but avoid sending retrieval metadata and long duplicate snippets.
            "availableEvidence": [
                {
                    key: item.get(key)
                    for key in (
                        "sourceType", "sourceId", "clauseType", "clauseNumber",
                        "title", "page", "snippet", "clauseText", "crossValidated",
                    )
                    if item.get(key) is not None
                }
                for item in evidence[:18]
            ],
            "deterministicRuleFindings": [
                {
                    key: item.get(key)
                    for key in (
                        "ruleKey", "ruleTitle", "title", "clauseType", "severity",
                        "description", "evidence", "citations",
                    )
                    if item.get(key) is not None
                }
                for item in rule_findings[:10]
            ],
            "extractedFacts": [
                {
                    key: item.get(key)
                    for key in (
                        "elementKey", "field", "value", "rawValue", "confidence",
                        "citations",
                    )
                    if item.get(key) is not None
                }
                for item in (extracted_facts or [])[:40]
            ],
        }
        for item in payload["availableEvidence"]:
            for key in ("snippet", "clauseText"):
                if item.get(key) is not None:
                    item[key] = str(item[key])[:1200]
        for item in payload["deterministicRuleFindings"]:
            if item.get("description") is not None:
                item["description"] = str(item["description"])[:600]
        return self._structured_completion(
            template,
            payload,
            temperature=0.0 if temperature is None else min(float(temperature), 0.1),
            timeout_seconds=max(15.0, float(getattr(settings, "project_analysis_timeout_seconds", 45))),
            required_key="findings",
            # A WorkUnit may be analyzed once more after targeted retrieval.
            # Keep each bounded domain call small enough for the 16384-token
            # WorkUnit budget, and use one retry for transient provider errors.
            max_tokens=4096,
            max_retries=1,
            allow_unstructured_fallback=False,
            usage_out=usage_out,
        )

    def contract_intake(self, case: dict, run_id: int = 0) -> dict:
        """Generate material checklist, template recommendation, and approval route."""
        template, temperature = self._prompt("contract_intake", run_id)
        payload = {
            "case": {
                "title": case.get("title", ""),
                "contractType": case.get("contractType", ""),
                "amount": case.get("amount"),
                "department": case.get("department", ""),
                "description": case.get("description", ""),
            },
        }
        response = self._call_llm_with_retry(
            lambda: self.analysis_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": template},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                temperature=temperature,
                max_tokens=max(4096, settings.chat_max_tokens),
                response_format={"type": "json_object"},
                # DeepSeek v4: thinking must ride inside extra_body, not as a
                # top-level kwarg — the SDK rejects unknown top-level params.
                extra_body=self._reasoning_guard() or None,
                stream=False,
            ),
            max_retries=2, backoff_base=2.0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def contract_fulfillment_check(self, case: dict, verification: dict,
                                   citations: list[dict], task_input: dict,
                                   run_id: int = 0) -> dict:
        """Generate a structured fulfillment verification report."""
        system_prompt = """
你是 AtlasMind ContractOps 的履约核验 Agent。你要判断某个合同时间节点当前是否有足够证据支持履约或验收。

只基于输入的合同节点、证据、企业知识库引用和工具结果输出，不编造付款记录、验收单、图片内容或对方确认。
不要输出数字评分；风险等级和可信度只能使用 HIGH/MEDIUM/LOW。
AI 只能给建议结论，最终“已完成/完成失败/验收通过”必须人工确认。

返回且只返回一个 JSON 对象：
{
  "reportType":"FULFILLMENT_REPORT",
  "title":"string",
  "summary":"string",
  "timelineNodeId":0,
  "conclusion":"BASICALLY_SATISFIED | HAS_ISSUES | INSUFFICIENT_EVIDENCE | UNCLEAR_TERMS | NEEDS_REVIEW",
  "riskLevel":"HIGH | MEDIUM | LOW",
  "confidenceLevel":"HIGH | MEDIUM | LOW",
  "requirements":[
    {"requirement":"合同要求","evidence":"已找到证据或空","judgement":"满足/不满足/证据不足/需复核","gap":"缺口或问题","required":true}
  ],
  "evidenceSnapshot":[{"documentId":0,"fileName":"string","version":0,"contentHash":"string","snippet":"string","matchReason":"string"}],
  "missingEvidence":["string"],
  "explicitConsequence":"合同原文明示后果；没有则写合同未明确约定",
  "aiRisk":"AI 推断风险，必须标注仅供参考",
  "suggestedActions":[{"type":"REQUEST_MATERIAL|REQUEST_LEGAL_REVIEW|SCHEDULE_REMINDER","title":"string","description":"string"}],
  "citations":[{"sourceId":"string","reason":"string"}],
  "content":{"manualConfirmationRequired":true}
}

规则：
1. requirements 必须按“合同要求 → 证据 → 判断 → 缺口”逐项对照。
2. 只有合同原文明确要求或作为付款/验收前提的事项，才能标 required=true。
3. 证据不足时 conclusion=INSUFFICIENT_EVIDENCE，不要推断完成。
4. 条款如“甲方满意/按甲方要求”缺少客观标准，conclusion=UNCLEAR_TERMS。
5. 图片或视频证据未经过多模态识别时，不能作为已完成的充分证据。
6. 必须按 case.ourSide、case.ourEntity、case.counterparty 分析我方立场；不要在本次核验中重新切换甲乙方角色。
7. 如果 case.ourSide=A，我方是合同甲方；如果 case.ourSide=B，我方是合同乙方。站在我方角度说明验收、付款、交付或违约风险。
""".strip()
        payload = {
            "case": case,
            "taskInput": task_input or {},
            "verification": verification or {},
            "citations": citations[:10],
        }
        usage_out: dict[str, int] = {}
        response = self._call_llm_with_retry(
            lambda: self.analysis_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                temperature=0.0,
                max_tokens=max(4096, settings.chat_max_tokens),
                response_format={"type": "json_object"},
                # DeepSeek v4: thinking must ride inside extra_body, not as a
                # top-level kwarg — the SDK rejects unknown top-level params.
                extra_body=self._reasoning_guard() or None,
                stream=False,
            ),
            max_retries=2, backoff_base=1.0, usage_out=usage_out,
        )
        content = response.choices[0].message.content if response.choices else ""
        artifact = self._parse_json_object(content or "")
        artifact.setdefault("reportType", "FULFILLMENT_REPORT")
        artifact.setdefault("timelineNodeId", int((task_input or {}).get("timelineNodeId") or 0))
        artifact.setdefault("content", {})
        if isinstance(artifact["content"], dict):
            artifact["content"]["manualConfirmationRequired"] = True
        artifact["_llmUsage"] = dict(usage_out)
        return artifact

    def extract_contract_metadata(self, file_name: str, text_excerpt: str,
                                  deterministic_hints: dict) -> dict:
        """Extract citable contract intake fields without writing business data."""
        system_prompt = """
你是企业合同录入流程中的结构化信息提取器。只提取输入合同明确写出的事实，不做合同审查，
不猜测哪一方属于当前用户，不生成部门、负责人或优先级。返回且只返回一个 JSON 对象。

输出结构：
{
  "fields": {
    "contractTitle": {"value": "string|null", "confidence": 0.0, "citations": [{"quote": "原文逐字引用"}]},
    "contractType": {"value": "SERVICE_PROCUREMENT|GOODS_PURCHASE|NDA|OTHER|null", "confidence": 0.0, "citations": [{"quote": "原文逐字引用"}]},
    "partyA": {"value": "string|null", "confidence": 0.0, "citations": [{"quote": "包含甲方名称的原文"}]},
    "partyB": {"value": "string|null", "confidence": 0.0, "citations": [{"quote": "包含乙方名称的原文"}]},
    "amount": {"value": 0.0, "confidence": 0.0, "citations": [{"quote": "金额原文"}]},
    "currency": {"value": "CNY|USD|EUR|GBP|JPY|HKD|null", "confidence": 0.0, "citations": [{"quote": "币种原文"}]},
    "signedDate": {"value": "YYYY-MM-DD|null", "confidence": 0.0, "citations": [{"quote": "签订/签署日期原文"}]},
    "effectiveDate": {"value": "YYYY-MM-DD|null", "confidence": 0.0, "citations": [{"quote": "日期原文"}]},
    "expiryDate": {"value": "YYYY-MM-DD|null", "confidence": 0.0, "citations": [{"quote": "日期原文"}]}
  }
}

规则：quote 必须逐字存在于输入合同片段；没有明确事实时 value 为 null、citations 为空；
金额统一换算为基础货币单位；日期无法确定到具体日时返回 null；不得把甲方默认视为我方。
合同标题必须是合同或协议的完整名称，不得返回“合同编号”“填写说明”“目录”“附件”等字段标签。
partyA/partyB 只表示合同原文中的甲方/乙方（或发包人/承包人、委托方/受托方）法律角色；
不得根据当前用户、我方主体或相对方身份交换甲乙方。
amount 只允许返回整份合同的总价/总金额。不得把“合同总价的X%”、履约保函、保证金、
预付款、阶段款、违约金、单价或税率作为合同总金额。若存在多个金额，必须引用明确写明
“合同总价/合同金额/合同价款”的完整上下文；大小写金额冲突时返回 null 并交由人工确认。
""".strip()
        system_prompt += "\n如果原文明确写出所属部门、业务部门、需求部门、采购部门或经办部门，请在 fields.department 中返回；没有明确原文时返回 null。"
        payload = {
            "fileName": file_name,
            "deterministicHints": deterministic_hints,
            "contractExcerpt": text_excerpt,
        }
        errors: list[str] = []
        usage_out: dict[str, int] = {}
        for structured in (True, False):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 2400,
                    "stream": False,
                }
                if structured:
                    kwargs["response_format"] = {"type": "json_object"}
                    if self._uses_deepseek_reasoning_model():
                        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                response = self._call_llm_with_retry(
                    lambda kwargs=kwargs: self.analysis_client.chat.completions.create(**kwargs),
                    max_retries=1,
                    backoff_base=1.0,
                    usage_out=usage_out,
                )
                parsed = self._parse_structured_response(response, required_key="fields")
                parsed["_llmUsage"] = dict(usage_out)
                return parsed
            except AuthenticationError:
                raise
            except APIError:
                raise
            except ValueError as exc:
                errors.append(str(exc)[:240])
                if structured:
                    logger.warning(
                        "LLM contract metadata response was not usable; retrying without response_format: %s",
                        exc,
                    )

        raise ValueError(
            "Contract metadata response was not valid JSON: " + "; ".join(errors[-2:])
        )

    def extract_contract_elements(
        self,
        case: dict,
        element_pack: dict,
        evidence: list[dict],
        run_id: int = 0,
    ) -> dict:
        """Extract a bounded group of contract facts from cited clauses.

        This method deliberately receives retrieved clause evidence instead of
        the whole document. The graph owns retrieval and fan-in; the model only
        normalizes facts that can be tied back to a continuous source quote.
        """
        system_prompt = """
你是合同事实提取 Agent 的一个领域节点。只从输入的合同条款证据中提取事实，
不要做风险结论，不要补写原文没有的日期、金额、主体、责任或履约义务。
每个结果必须引用输入证据中的连续原文；找不到可靠原文时不要输出该结果。
返回且只返回一个 JSON 对象：
{
  "elements": [
    {
      "elementKey": "定义中给出的 key",
      "category": "IDENTITY|PARTIES|FINANCIAL|DATES|OBLIGATIONS|RISK_TERMS",
      "valueType": "TEXT|ENUM|PARTY|MONEY|DATE|LIST|STRUCTURED",
      "rawValue": "原文事实或简短原文摘录",
      "normalizedValue": {},
      "confidence": 0.0,
      "applicable": true,
      "status": "EXTRACTED|NEEDS_REVIEW|NOT_FOUND",
      "citations": [{"sourceId":"CONTRACT_CLAUSE:123", "quote":"输入中连续存在的原文", "clauseId":123}]
    }
  ]
}

规则：
1. elementKey 只能使用 elementPack.allowedElementKeys 中的值。
2. quote 必须逐字出现在对应 evidence 的 clauseText/content/snippet 中；不能改写 quote。
3. normalizedValue 只做格式化，例如把金额拆成 amount/currency，把日期转成 YYYY-MM-DD；无法确定就保留 null。
4. 相对期限、条件结束、验收要求和应提交材料必须保留触发条件，不要只返回一个数字。
5. 同一要素存在多个合理版本时全部返回，并用 occurrenceNo 区分；不要猜选一个。
6. 没有足够证据时返回空 elements，不要用“通常”“一般应当”补齐。
7. 所有说明使用简体中文，输出不能包含 Markdown。
""".strip()
        compact_evidence = []
        for item in evidence[:7]:
            full_clause_text = str(item.get("clauseText") or item.get("content") or "")
            clause_window = self._contract_evidence_window(
                full_clause_text,
                element_pack.get("queries") or [],
                limit=3200,
            )
            compact_evidence.append({
                "sourceId": item.get("sourceId") or item.get("clauseId"),
                "clauseId": item.get("clauseId"),
                "clauseNumber": item.get("clauseNumber"),
                "title": item.get("title"),
                "pageNumber": item.get("pageNumber") or item.get("page"),
                "clauseText": clause_window,
                "snippet": str(item.get("snippet") or clause_window)[:1200],
            })
        payload = {
            "case": {
                "caseKey": case.get("caseKey"),
                "title": case.get("title"),
                "contractType": case.get("contractType"),
                "ourSide": case.get("ourSide"),
            },
            "elementPack": element_pack,
            "allowedElementKeys": element_pack.get("elementKeys") or [],
            "evidence": compact_evidence,
        }
        try:
            template, temperature = self._prompt("contract_element_extraction", run_id)
        except Exception:
            # The extraction graph must remain deployable before the optional
            # DB prompt seed is applied. The grounded schema above is the safe
            # built-in fallback.
            template, temperature = system_prompt, 0.0
        if not template:
            template, temperature = system_prompt, 0.0
        return self._structured_completion(
            template,
            payload,
            temperature=0.0 if temperature is None else min(float(temperature), 0.1),
            timeout_seconds=max(10.0, float(getattr(settings, "project_analysis_timeout_seconds", 45))),
            required_key="elements",
            max_tokens=4800,
        )

    def extract_contract_profile(
        self,
        case: dict,
        evidence: list[dict],
        base_elements: list[dict],
        run_id: int = 0,
    ) -> dict:
        """Build a contract-family-aware profile from shared clause evidence.

        The profile is deliberately different from ``contractElements``. The
        latter is a flat, citable fact list used by downstream agents; this
        result is the readable business view (for example, engineering scope,
        design standards and payment milestones). The model may discover
        groups and fields, but every contract-derived value must still cite a
        continuous quote from retrieved evidence.
        """
        system_prompt = """
你是企业合同作业系统中的“合同画像整理器”。你的任务是从输入的合同证据中建立一份可供业务人员阅读和后续 Agent 复用的合同画像。

只输出一个 JSON 对象，结构必须是：
{
  "profile": {
    "title": "合同画像",
    "contractType": "模型判断的合同类型或 OTHER",
    "typeRationale": "仅基于合同原文的一句话判断依据",
    "baseFields": [],
    "groups": [
      {"groupKey":"稳定的英文业务键", "label":"中文业务分组名称", "reason":"为什么该分组适用于本合同",
       "fields":[
         {"key":"稳定的英文字段键", "label":"中文字段名称", "value":"结构化值或 null",
          "valueType":"TEXT|MONEY|DATE|PARTY|LIST|STRUCTURED", "importance":"CORE|SUPPORTING",
          "confidence":0.0, "status":"EXTRACTED|NEEDS_REVIEW|NOT_FOUND",
          "citations":[{"sourceId":"CONTRACT_CLAUSE:123","quote":"逐字连续原文","clauseId":123}]}
       ]}
    ]
  }
}

规则：
1. baseFields 必须返回空数组。合同标题、类型、甲乙方、我方角色、总金额和基础日期已经人工确认，
   由系统直接注入画像；本次不得重新提取、改写或纠正这些基础事实。
2. groups 和 fields 由合同内容决定，不要套用固定行业模板。
3. 只有合同中真实出现、对履行或决策有用的专属要素才创建字段。例如工程合同可以有工程地点、规模、设计标准、考核指标，信息技术合同可以有系统范围、环境、SLA，但不要因为“通常有”而创建。
4. 字段 value 要尽可能完整地表达合同事实；列表和付款阶段用结构化 JSON，不要截断成半句话。
5. citation.quote 必须逐字连续出现在对应 evidence 的 clauseText/content/snippet 中。不能把模型改写后的内容当引用。
6. 没有明确事实时 value=null、citations=[]、status=NOT_FOUND；不要编造金额、日期、责任方或标准。
7. “建议关注但合同没有约定”的内容不能放入合同事实字段，应放入 groups 的 reason，不得冒充合同事实。
8. 不输出 Markdown、解释文字或额外字段。
""".strip()
        compact_evidence = []
        seen: set[str] = set()
        for item in evidence:
            source_id = str(item.get("sourceId") or item.get("clauseId") or "")
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            clause_text = str(item.get("clauseText") or item.get("content") or "")
            compact_evidence.append({
                "sourceId": source_id,
                "clauseId": item.get("clauseId"),
                "clauseNumber": item.get("clauseNumber"),
                "title": item.get("title"),
                "pageNumber": item.get("pageNumber") or item.get("page"),
                "clauseText": clause_text[:2600],
                "snippet": str(item.get("snippet") or clause_text)[:900],
            })
            if len(compact_evidence) >= 24:
                break
        payload = {
            "case": {
                "caseKey": case.get("caseKey"),
                "title": case.get("title"),
                "contractType": case.get("contractType"),
                "ourSide": case.get("ourSide"),
                "ourEntity": case.get("ourEntity"),
                "counterparty": case.get("counterparty"),
            },
            "canonicalBaseFacts": {
                "title": case.get("title"),
                "contractType": case.get("contractType"),
                "ourSide": case.get("ourSide"),
                "ourEntity": case.get("ourEntity"),
                "counterparty": case.get("counterparty"),
            },
            "existingSpecializedFacts": base_elements[:40],
            "evidence": compact_evidence,
        }
        try:
            template, temperature = self._prompt("contract_profile_extraction", run_id)
        except Exception:
            template, temperature = system_prompt, 0.0
        if not template:
            template, temperature = system_prompt, 0.0
        return self._structured_completion(
            template,
            payload,
            temperature=0.0 if temperature is None else min(float(temperature), 0.1),
            timeout_seconds=max(15.0, float(getattr(settings, "project_analysis_timeout_seconds", 45))),
            required_key="profile",
            max_tokens=7200,
        )

    def plan_contract_elements(
        self,
        case: dict,
        clauses_preview: list[dict],
        run_id: int = 0,
    ) -> dict:
        """Dynamically plan extraction element packs for one contract
        (PRD Phase 5, task 2: 合同类型、标的和画像要素由 LLM 动态规划).

        The static element packs stay the deterministic fallback when this
        call fails or returns an unusable plan — the graph decides, not the
        model. Each proposed pack must carry stable keys and Chinese queries;
        unknown element keys are fine (dynamic elements) but must be
        snake_case ASCII.
        """
        system_prompt = """
你是合同事实提取的计划节点。输入是合同案例元数据与若干条款预览。
你的任务是规划本次提取要覆盖的要素包（pack），而不是提取事实本身。

只输出一个 JSON 对象：
{
  "contractTypeRefined": "模型判断的合同类型（英文枚举或 OTHER）",
  "subjectSummary": "标的一句话中文摘要，如：为某电厂提供勘察设计服务",
  "rationale": "为什么这样规划，一句中文",
  "packs": [
    {
      "packKey": "稳定的英文业务键（snake_case）",
      "packName": "中文业务分组名称",
      "elementKeys": ["该包要提取的要素键（snake_case，与通用包不重复）"],
      "queries": ["用于检索合同条款的中文查询词"]
    }
  ]
}

规则：
1. 不要创建重复覆盖基础身份要素（合同名称、类型、甲乙方、总金额、币种、
   签订/生效/到期日期）的包——这些由系统确定性规范化处理，模型不得重提。
2. pack 数量 2～6 个，每包 elementKeys 2～8 个、queries 2～6 条。
3. 包要贴合本合同类型：勘察设计合同关注设计范围、交付成果、验收标准；
   采购合同关注付款、交付、质保；服务合同关注 SLA、考核指标。不要套模板。
4. 每个 elementKey 与查询词都必须能在合同条款中找到对应内容，
   “通常有”不是创建要素的理由。
5. contractTypeRefined 只写英文枚举或 OTHER，不要解释。
6. 输出不能包含 Markdown 或额外字段。
""".strip()
        compact_preview = []
        for item in (clauses_preview or [])[:8]:
            compact_preview.append({
                "clauseId": item.get("clauseId"),
                "clauseNumber": item.get("clauseNumber"),
                "title": item.get("title"),
                "clauseText": str(item.get("clauseText") or item.get("content") or "")[:800],
            })
        payload = {
            "case": {
                "caseKey": case.get("caseKey"),
                "title": case.get("title"),
                "contractType": case.get("contractType"),
                "ourSide": case.get("ourSide"),
            },
            "clausesPreview": compact_preview,
        }
        try:
            template, temperature = self._prompt("contract_element_planning", run_id)
        except Exception:
            template, temperature = system_prompt, 0.0
        if not template:
            template, temperature = system_prompt, 0.0
        return self._structured_completion(
            template,
            payload,
            temperature=0.0 if temperature is None else min(float(temperature), 0.1),
            timeout_seconds=max(10.0, float(getattr(settings, "project_analysis_timeout_seconds", 45))),
            required_key="packs",
            max_tokens=3200,
        )

    def enrich_contract_timeline(self, candidates: list[dict]) -> dict:
        """Classify timeline candidates using their complete source clauses."""
        system_prompt = """
你是合同时间节点语义整理器。输入是一组已经由代码提取出来的时间候选。
你只能基于候选里的 date、condition、matchedText、quote、clauseText、clauseTitle 做判断，不能发明新的日期。

输出且只输出一个 JSON 对象：
{
  "nodes": [
    {
      "candidateId": "string",
      "keep": true,
      "eventType": "CONTRACT_START | CONTRACT_END | SERVICE_START | SERVICE_END | PAYMENT | DELIVERY | ACCEPTANCE | NOTICE | RENEWAL | TERMINATION | PENALTY | OTHER",
      "label": "string",
      "responsibleParty": "OUR_ENTITY | COUNTERPARTY | BOTH | UNKNOWN",
      "businessMeaning": "string",
      "contractRequirements": ["string"],
      "aiSuggestions": ["string"],
      "explicitConsequence": "string",
      "aiRisk": "string",
      "reason": "string",
      "confidence": 0.0
    }
  ]
}

规则：
1. 只能返回候选里已有的 candidateId。
2. keep=false 仅表示这个候选不值得展示，不得新增候选。
3. 如果候选明显是封面元信息、签订时间、印制说明或模板噪声，优先 keep=false。
4. matchedText 是规则定位锚点，quote 是命中片段，clauseText 是完整原文条款。必须以完整 clauseText 判断主语、触发条件、动作、材料和后果，不能只理解截取短句。
5. label 要尽量短，保留履约含义。
6. businessMeaning 要像给业务人员看的话，尽量写成“谁应在什么时间/条件下完成什么事”。
7. confidence 0-1。
8. explicitConsequence 只能写合同原文明确约定的后果；没有明确后果时返回空字符串。
9. aiRisk 是基于节点类型推断的管理风险，必须以“AI 推断，仅供参考：”开头，不能冒充合同约定。
10. contractRequirements 只列合同原文明确要求在该节点完成或提交的事项，例如实施方案、研究报告、验收材料；没有则返回空数组。
11. aiSuggestions 只列为了履约留痕、验收或付款而建议准备的材料；不得冒充合同要求，且与 contractRequirements 不重复。
12. 必须区分 DELIVERY 与 ACCEPTANCE：一方在指定日期前交付成果、提交文件或验收申请属于 DELIVERY；另一方收到申请后组织验收、作出验收意见或验收通过属于 ACCEPTANCE。即使两项义务写在同一条款，也要按当前候选对应的动作分别分类，不能因为出现“验收”就把交付义务归为 ACCEPTANCE。
""".strip()
        all_nodes: list[dict] = []
        errors: list[str] = []
        max_candidates = max(0, int(settings.contract_timeline_llm_max_candidates or 0))
        batch_size = max(1, int(settings.contract_timeline_llm_batch_size or 3))
        selected_candidates = candidates[:max_candidates]
        if not selected_candidates:
            return {"nodes": [], "errors": ["timeline enrichment disabled or no candidates"]}
        timeline_client = self.analysis_client.with_options(
            timeout=max(1.0, float(settings.contract_timeline_llm_timeout_seconds or 20))
        )
        for start in range(0, len(selected_candidates), batch_size):
            payload = {
                "candidates": [
                    # PRD Phase 6, task 6: the model judges on the complete
                    # parent clause — never a truncated excerpt. The persisted
                    # citation likewise keeps the full text, so the LLM input
                    # and the traceable evidence stay identical.
                    _complete_timeline_candidate_for_llm(item)
                    for item in selected_candidates[start:start + batch_size]
                ]
            }
            parsed = None
            for structured in (True, False):
                try:
                    kwargs = {
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                        ],
                        "temperature": 0.0,
                        "max_tokens": max(4096, settings.chat_max_tokens),
                        "stream": False,
                    }
                    if structured:
                        kwargs["response_format"] = {"type": "json_object"}
                    if self._uses_deepseek_reasoning_model():
                        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                    response = self._call_llm_with_retry(
                        lambda kwargs=kwargs: timeline_client.chat.completions.create(**kwargs),
                        max_retries=1,
                        backoff_base=1.0,
                    )
                    message = response.choices[0].message if response.choices else None
                    content = getattr(message, "content", "") or ""
                    if not content.strip():
                        raise ValueError("timeline enrichment returned empty content")
                    parsed = self._parse_json_object(content)
                    break
                except (APIConnectionError, AuthenticationError) as exc:
                    errors.append(str(exc)[:300])
                    break
                except Exception as exc:
                    errors.append(str(exc)[:300])
            if parsed is not None:
                all_nodes.extend(item for item in (parsed.get("nodes") or []) if isinstance(item, dict))
        if not all_nodes and errors:
            raise ValueError("; ".join(errors[-2:]))
        return {"nodes": all_nodes, "errors": errors}

    def enrich_contract_lifecycle_conditions(self, candidates: list[dict]) -> dict:
        """Ground event-driven contract end conditions in complete clauses."""
        system_prompt = """
你是合同结束条件整理器。每个候选都包含完整合同条款和规则初步拆出的条件。
只整理明确以“本合同结束、终止或失效”为对象的约定；不得把履约保函、质保、证书或某项义务失效误认为合同失效。

只输出 JSON：
{"conditions":[{"candidateId":"string","keep":true,"endMode":"CONDITIONAL","logic":"ALL | ANY | SINGLE","summary":"string","events":[{"event":"string","sourceQuote":"string"}],"reason":"string","confidence":0.0}]}

要求：
1. sourceQuote 必须是 clauseText 中连续存在的原文。
2. “且、并且、同时满足、全部完成”通常是 ALL；“任一、任何一项”通常是 ANY。
3. summary 用业务语言说明合同何时结束，不生成不存在的具体日期。
4. 条款对象不明确、原文乱码或只是其他对象失效时 keep=false。
""".strip()
        payload = {"candidates": candidates[:20]}
        return self._structured_completion(
            system_prompt,
            payload,
            temperature=0.0,
            timeout_seconds=max(1.0, float(settings.contract_timeline_llm_timeout_seconds or 20)),
            required_key="conditions",
        )

    def contract_approval(self, case: dict, findings: list[dict],
                          scoring: dict, run_id: int = 0) -> dict:
        """Generate approval memo with recommendation and conditions."""
        template, temperature = self._prompt("contract_approval", run_id)
        payload = {
            "case": {"caseKey": case.get("caseKey", ""), "title": case.get("title", ""),
                     "counterparty": case.get("counterparty", ""), "amount": case.get("amount")},
            "findings": findings[:10],
            "scoring": scoring,
        }
        response = self._call_llm_with_retry(
            lambda: self.analysis_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": template},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                temperature=temperature,
                max_tokens=max(4096, settings.chat_max_tokens),
                response_format={"type": "json_object"},
                # DeepSeek v4: thinking must ride inside extra_body, not as a
                # top-level kwarg — the SDK rejects unknown top-level params.
                extra_body=self._reasoning_guard() or None,
                stream=False,
            ),
            max_retries=2, backoff_base=2.0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def _structured_completion(self, system_prompt: str, payload: dict,
                               temperature: float = 0.1,
                               timeout_seconds: float | None = None,
                               required_key: str | None = None,
                               max_tokens: int = 2400,
                               max_retries: int = 3,
                               allow_unstructured_fallback: bool = True,
                               usage_out: dict[str, int] | None = None) -> dict:
        client = self.analysis_client
        if timeout_seconds is not None:
            client = client.with_options(timeout=max(1.0, float(timeout_seconds)))

        errors: list[str] = []
        # Always collect usage for graph observability.  Callers that need the
        # WorkUnit budget can still pass their own dict; the reserved metadata
        # is stripped/ignored by graph normalizers and is never a contract fact.
        observed_usage = usage_out if usage_out is not None else {}
        phases = (True, False) if allow_unstructured_fallback else (True,)
        for structured in phases:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                "temperature": temperature,
                "max_tokens": max(256, int(max_tokens)),
                "stream": False,
            }
            if structured:
                kwargs["response_format"] = {"type": "json_object"}
            if self._uses_deepseek_reasoning_model():
                # DeepSeek v4 models otherwise spend the completion budget on
                # reasoning_content before returning the required JSON object.
                # This path is only used for bounded, schema-validated tasks.
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            try:
                # usage_out accumulates across the retry loop AND the
                # structured→unstructured fallback below — the §7.2 ledger
                # wants real API calls, not logical invocations.
                response = self._call_llm_with_retry(
                    lambda kwargs=kwargs: client.chat.completions.create(**kwargs),
                    max_retries=max(0, int(max_retries)),
                    backoff_base=2.0,
                    usage_out=observed_usage,
                )
                parsed = self._parse_structured_response(response, required_key)
                parsed["_llmUsage"] = {
                    "calls": int(observed_usage.get("calls") or 0),
                    "promptTokens": int(observed_usage.get("promptTokens") or 0),
                    "completionTokens": int(observed_usage.get("completionTokens") or 0),
                    "tokens": int(observed_usage.get("tokens") or 0),
                }
                return parsed
            except AuthenticationError:
                raise
            except APIConnectionError:
                raise
            except APIError as exc:
                errors.append(str(exc)[:240])
                if not structured or not allow_unstructured_fallback:
                    raise
            except ValueError as exc:
                errors.append(str(exc)[:240])
                if structured and allow_unstructured_fallback:
                    logger.warning(
                        "Structured LLM response was not usable; retrying without response_format: %s",
                        exc,
                    )
                else:
                    raise

        raise ValueError(
            "Structured LLM response was not valid JSON: " + "; ".join(errors[-2:])
        )

    def _uses_deepseek_reasoning_model(self) -> bool:
        base_url = str(settings.llm_base_url or "").lower()
        model = str(self.model or "").lower()
        return "deepseek.com" in base_url and model.startswith("deepseek-")

    def _reasoning_guard(self) -> dict:
        """DeepSeek v4 models burn the completion budget on reasoning_content
        before emitting the required JSON object; disable thinking for
        response_format=json_object calls (see _structured_completion)."""
        return (
            {"thinking": {"type": "disabled"}}
            if self._uses_deepseek_reasoning_model()
            else {}
        )

    @staticmethod
    def _repair_json(text: str) -> str:
        """Apply lightweight repairs for common LLM JSON mistakes."""
        # Remove trailing commas before ] or }
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # Remove comments (// and /* */)
        text = re.sub(r"//[^\n]*", "", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        return text

    def _parse_json_object(self, content: str) -> dict:
        """Accept plain JSON and the fenced JSON some compatible models return.

        Tries strict parse first, then lenient repairs for common LLM mistakes
        (trailing commas, comments, unescaped characters).
        """
        candidate = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
        if fenced:
            candidate = fenced.group(1)
        else:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start:end + 1]

        errors = []
        # Attempt 1: strict parse
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e:
            errors.append(str(e))

        # Attempt 2: repair + parse
        try:
            repaired = self._repair_json(candidate)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                logger.info("JSON repaired successfully after error: %s", errors[0][:120])
                return parsed
        except json.JSONDecodeError as e:
            errors.append(str(e))

        # Attempt 3: try json5 if available
        try:
            import json5
            parsed = json5.loads(candidate)
            if isinstance(parsed, dict):
                logger.info("JSON parsed via json5 after errors: %s", errors[0][:120])
                return parsed
        except (ImportError, Exception):
            pass

        raise ValueError(
            f"Failed to parse JSON after {len(errors)} attempts: "
            + "; ".join(e[:120] for e in errors)
        )

    @staticmethod
    def _message_text(value) -> str:
        """Normalize string and OpenAI content-part responses to plain text."""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict):
                    text = item.get("text")
                else:
                    text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
            return "".join(parts)
        return "" if value is None else str(value)

    @staticmethod
    def _contract_evidence_window(text: str, queries: list | tuple,
                                  limit: int = 3200) -> str:
        """Keep a grounded, query-adjacent clause window within model budget."""
        source = str(text or "").strip()
        if len(source) <= limit:
            return source

        query_text = " ".join(str(value) for value in (queries or []))
        terms = [
            value.strip()
            for value in re.split(r"\s+", query_text)
            if len(value.strip()) >= 2
        ]
        positions = [source.find(term) for term in terms if source.find(term) >= 0]
        if not positions:
            return source[:limit]

        focus = min(positions)
        before = max(240, limit // 5)
        start = max(0, focus - before)
        end = min(len(source), start + limit)
        start = max(0, end - limit)
        return source[start:end]

    def _recover_json_from_reasoning(self, reasoning: str, required_key: str | None = None) -> dict | None:
        """Recover a final JSON object when a reasoning model leaves content empty."""
        if not reasoning.strip():
            return None
        starts = [match.start() for match in re.finditer(r"\{", reasoning)]
        for start in reversed(starts):
            try:
                parsed = self._parse_json_object(reasoning[start:])
            except ValueError:
                continue
            if required_key is None or required_key in parsed:
                return parsed
        return None

    def _parse_structured_response(self, response, required_key: str | None = None) -> dict:
        """Parse visible model output and safely recover reasoning-only JSON."""
        if not getattr(response, "choices", None):
            raise ValueError("LLM returned no choices")
        message = response.choices[0].message
        content = self._message_text(getattr(message, "content", None)).strip()
        if content:
            parsed = self._parse_json_object(content)
            if required_key is None or required_key in parsed:
                return parsed
            raise ValueError(f"LLM structured response is missing required key: {required_key}")

        reasoning = self._message_text(getattr(message, "reasoning_content", None))
        recovered = self._recover_json_from_reasoning(reasoning, required_key)
        if recovered is not None:
            logger.warning(
                "LLM returned empty visible content; recovered structured JSON from reasoning output"
            )
            return recovered
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        suffix = f" (finish_reason={finish_reason})" if finish_reason else ""
        raise ValueError("LLM returned empty structured content" + suffix)
