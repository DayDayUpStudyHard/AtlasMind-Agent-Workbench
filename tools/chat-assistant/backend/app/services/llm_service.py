"""LLM 服务 — prompt 构建 + 流式调用 DeepSeek API。"""
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


class LLMService:
    def __init__(self):
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY 未设置，请在 .env 中配置")
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
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
