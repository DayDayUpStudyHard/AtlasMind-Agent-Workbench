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
        return template, temperature

    # ── retry helper ─────────────────────────────────────────────────

    def _call_llm_with_retry(self, fn, max_retries: int = 3, backoff_base: float = 2.0):
        """Call *fn()* with exponential backoff retry + circuit breaker.

        *fn* is a zero-argument callable that performs a single LLM API call.
        Returns the result on success.  Raises the last exception after all
        retries are exhausted or the circuit breaker is open.

        Connection errors (APIConnectionError) are retried at most once — if the
        LLM is unreachable, waiting 2+4+8s is worse than failing fast so the
        harness can report the error immediately.
        """
        if _llm_circuit_breaker.is_open:
            raise RuntimeError("LLM circuit breaker is open - skipping call")

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
            label = "文档" if source_type == "DOCUMENT" else "文章"
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
        return self._structured_completion(template, payload, temperature=temperature)

    # ── Contract task methods (Phase 5) ────────────────────────────

    def contract_review(self, case: dict, findings: list[dict],
                        citations: list[dict], scoring: dict,
                        run_id: int = 0) -> dict:
        """Generate structured contract review report with findings and action proposals."""
        template, temperature = self._prompt("contract_review", run_id)
        payload = {
            "case": {
                "caseKey": case.get("caseKey", ""),
                "title": case.get("title", ""),
                "counterparty": case.get("counterparty", ""),
                "amount": case.get("amount"),
                "contractType": case.get("contractType", ""),
            },
            "findings": findings[:15],
            "citations": citations[:8],
            "deterministicScoring": scoring,
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
                stream=False,
            ),
            max_retries=3, backoff_base=2.0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

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
                                     run_id: int = 0) -> dict:
        """Generate detailed, auditable findings for one bounded risk domain."""
        template, temperature = self._prompt("contract_risk_domain_analysis", run_id)
        payload = {
            "case": case,
            "domain": domain,
            "availableEvidence": evidence[:18],
            "deterministicRuleFindings": rule_findings[:10],
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
                stream=False,
            ),
            max_retries=2,
            backoff_base=1.5,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

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
                stream=False,
            ),
            max_retries=2, backoff_base=1.0,
        )
        content = response.choices[0].message.content if response.choices else ""
        artifact = self._parse_json_object(content or "")
        artifact.setdefault("reportType", "FULFILLMENT_REPORT")
        artifact.setdefault("timelineNodeId", int((task_input or {}).get("timelineNodeId") or 0))
        artifact.setdefault("content", {})
        if isinstance(artifact["content"], dict):
            artifact["content"]["manualConfirmationRequired"] = True
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
""".strip()
        system_prompt += "\n如果原文明确写出所属部门、业务部门、需求部门、采购部门或经办部门，请在 fields.department 中返回；没有明确原文时返回 null。"
        payload = {
            "fileName": file_name,
            "deterministicHints": deterministic_hints,
            "contractExcerpt": text_excerpt,
        }
        errors: list[str] = []
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
                response = self._call_llm_with_retry(
                    lambda kwargs=kwargs: self.analysis_client.chat.completions.create(**kwargs),
                    max_retries=1,
                    backoff_base=1.0,
                )
                return self._parse_structured_response(response, required_key="fields")
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
      "eventType": "CONTRACT_START | CONTRACT_END | SERVICE_START | SERVICE_END | PAYMENT | ACCEPTANCE | NOTICE | RENEWAL | TERMINATION | PENALTY | OTHER",
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
""".strip()
        all_nodes: list[dict] = []
        errors: list[str] = []
        max_candidates = max(0, int(settings.contract_timeline_llm_max_candidates or 0))
        batch_size = max(1, int(settings.contract_timeline_llm_batch_size or 8))
        selected_candidates = candidates[:max_candidates]
        if not selected_candidates:
            return {"nodes": [], "errors": ["timeline enrichment disabled or no candidates"]}
        timeline_client = self.analysis_client.with_options(
            timeout=max(1.0, float(settings.contract_timeline_llm_timeout_seconds or 20))
        )
        for start in range(0, len(selected_candidates), batch_size):
            payload = {
                "candidates": [
                    {**item, "clauseText": str(item.get("clauseText") or "")[:12000]}
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
                    response = self._call_llm_with_retry(
                        lambda kwargs=kwargs: timeline_client.chat.completions.create(**kwargs),
                        max_retries=0,
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
                stream=False,
            ),
            max_retries=2, backoff_base=2.0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def _structured_completion(self, system_prompt: str, payload: dict,
                               temperature: float = 0.1,
                               timeout_seconds: float | None = None) -> dict:
        client = self.analysis_client
        if timeout_seconds is not None:
            client = client.with_options(timeout=max(1.0, float(timeout_seconds)))

        def _call():
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                temperature=temperature,
                max_tokens=2400,
                response_format={"type": "json_object"},
                stream=False,
            )
            return response
        response = self._call_llm_with_retry(_call, max_retries=3, backoff_base=2.0)
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

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
            return self._parse_json_object(content)

        reasoning = self._message_text(getattr(message, "reasoning_content", None))
        recovered = self._recover_json_from_reasoning(reasoning, required_key)
        if recovered is not None:
            logger.warning(
                "LLM returned empty visible content; recovered structured JSON from reasoning output"
            )
            return recovered
        raise ValueError("LLM returned empty structured content")
