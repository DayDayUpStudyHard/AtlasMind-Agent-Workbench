"""LLM 服务 — prompt 构建 + 流式调用 DeepSeek API。"""
import json
import re
from typing import Generator
from openai import OpenAI, APIError, APIConnectionError, AuthenticationError
from app.config import settings

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
        messages = [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
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

    def analyze_project(self, project: dict, citations: list[dict], deterministic_scoring: dict | None = None) -> dict:
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
        response = self.analysis_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": PROJECT_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=max(4096, settings.chat_max_tokens),
            response_format={"type": "json_object"},
            stream=False,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def run_project_task(self, task_type: str, project: dict, task_input: dict, citations: list[dict]) -> dict:
        """Generate one supported project task artifact from bounded evidence."""
        system_prompt = PROJECT_TASK_SYSTEM_PROMPTS.get(task_type)
        if not system_prompt:
            raise ValueError(f"unsupported project task type: {task_type}")

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
        response = self.analysis_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.15,
            max_tokens=max(4096, settings.chat_max_tokens),
            response_format={"type": "json_object"},
            stream=False,
        )
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def plan_agent(self, payload: dict) -> dict:
        """Create a bounded plan. This stage cannot call tools or produce artifacts."""
        return self._structured_completion(AGENT_PLANNER_SYSTEM_PROMPT, payload, temperature=0.1)

    def next_agent_turn(self, payload: dict) -> dict:
        """Let the model select Java-owned tools through native function calling."""
        tools = payload.get("availableTools") or []
        if not tools:
            raise ValueError("availableTools is required for an Agent turn")
        response = self.analysis_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": AGENT_TOOL_TURN_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.05,
            max_tokens=1600,
            stream=False,
        )
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
        return self._structured_completion(AGENT_REFLECTION_SYSTEM_PROMPT, payload, temperature=0.0)

    def _structured_completion(self, system_prompt: str, payload: dict,
                               temperature: float = 0.1) -> dict:
        response = self.analysis_client.chat.completions.create(
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
        content = response.choices[0].message.content if response.choices else ""
        return self._parse_json_object(content or "")

    def _parse_json_object(self, content: str) -> dict:
        """Accept plain JSON and the fenced JSON some compatible models return."""
        candidate = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
        if fenced:
            candidate = fenced.group(1)
        else:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start:end + 1]
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("project analysis response must be a JSON object")
        return parsed
