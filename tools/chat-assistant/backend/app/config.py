"""配置中心 — 从 .env 加载，支持 LLM / Embedding 分离配置。

DeepSeek 不提供 embedding API，embedding 需单独配置提供商（如 OpenAI）。
- 已配置 embedding → ES kNN 语义搜索
- 未配置 embedding → ES multi_match 文本搜索（自动降级）
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # ====== LLM 对话模型 ======
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")

    # ====== Embedding 模型（独立配置，不 fallback 到 LLM） ======
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "2560"))
    # PRD §7.2: 外部 Embedding/Rerank 有独立短超时（远低于 LLM 会话超时）
    embedding_timeout_seconds: float = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "10"))

    # ====== Elasticsearch ======
    es_host: str = os.getenv("ES_HOST", "http://localhost:9200")
    es_index: str = os.getenv("ES_INDEX", "agent_contents")
    kb_index: str = os.getenv("KB_INDEX", "kb_chunks")
    contract_index: str = os.getenv("CONTRACT_INDEX", "contract_chunks")

    # ====== MySQL（知识库事实源） ======
    mysql_host: str = os.getenv("MYSQL_HOST", "localhost")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "123456")
    mysql_db: str = os.getenv("MYSQL_DB", "atlasmind_agent")

    # ====== Redis ======
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # ====== GitHub (for Agent source-code tools) ======
    github_token: str = os.getenv("GITHUB_TOKEN", "")

    # ====== Chat ======
    chat_max_tokens: int = int(os.getenv("CHAT_MAX_TOKENS", "2048"))
    chat_temperature: float = float(os.getenv("CHAT_TEMPERATURE", "0.7"))
    project_analysis_timeout_seconds: float = float(os.getenv("PROJECT_ANALYSIS_TIMEOUT_SECONDS", "90"))
    contract_timeline_llm_timeout_seconds: float = float(os.getenv("CONTRACT_TIMELINE_LLM_TIMEOUT_SECONDS", "45"))
    contract_timeline_llm_max_candidates: int = int(os.getenv("CONTRACT_TIMELINE_LLM_MAX_CANDIDATES", "24"))
    contract_timeline_llm_batch_size: int = int(os.getenv("CONTRACT_TIMELINE_LLM_BATCH_SIZE", "3"))
    retrieval_top_k: int = int(os.getenv("RETRIEVAL_TOP_K", "5"))

    # ====== Reranker (LLM cross-encoder for retrieval re-ranking) ======
    reranker_api_key: str = os.getenv("RERANKER_API_KEY", "")
    reranker_base_url: str = os.getenv("RERANKER_BASE_URL", "")
    reranker_model: str = os.getenv("RERANKER_MODEL", "")
    reranker_timeout_seconds: float = float(os.getenv("RERANKER_TIMEOUT_SECONDS", "15"))
    reranker_recall_multiplier: int = int(os.getenv("RERANKER_RECALL_MULTIPLIER", "6"))
    reranker_min_recall: int = int(os.getenv("RERANKER_MIN_RECALL", "30"))
    reranker_max_recall: int = int(os.getenv("RERANKER_MAX_RECALL", "50"))

    internal_token: str = os.getenv("CHAT_ASSISTANT_TOKEN", "")
    java_backend_url: str = os.getenv("JAVA_BACKEND_URL", "http://localhost:18080")
    kb_chunk_insert_batch_size: int = int(os.getenv("KB_CHUNK_INSERT_BATCH_SIZE", "200"))
    kb_embedding_batch_size: int = int(os.getenv("KB_EMBEDDING_BATCH_SIZE", "16"))

    # ====== OCR（扫描版 PDF，可选） ======
    pdf_parse_provider: str = os.getenv("PDF_PARSE_PROVIDER", "auto").strip().lower()
    pdf_auto_reparse: bool = _bool_env("PDF_AUTO_REPARSE", "true")
    ocr_enabled: bool = _bool_env("OCR_ENABLED", "false")
    ocr_provider: str = os.getenv("OCR_PROVIDER", "paddle").strip().lower()
    ocr_lang: str = os.getenv("OCR_LANG", "ch")
    ocr_render_dpi: int = int(os.getenv("OCR_RENDER_DPI", "180"))
    ocr_min_text_chars: int = int(os.getenv("OCR_MIN_TEXT_CHARS", "30"))
    ocr_max_pages: int = int(os.getenv("OCR_MAX_PAGES", "0"))
    cloud_ocr_base_url: str = os.getenv("CLOUD_OCR_BASE_URL", "")
    cloud_ocr_api_key: str = os.getenv("CLOUD_OCR_API_KEY", "")
    mineru_enabled: bool = _bool_env("MINERU_ENABLED", "false")
    mineru_command: str = os.getenv("MINERU_COMMAND", "magic-pdf -p {input} -o {output}")
    mineru_output_dir: str = os.getenv("MINERU_OUTPUT_DIR", ".mineru-output")

    def validate(self) -> list[str]:
        """启动时校验必要配置，返回错误列表（空列表 = 全部 OK）。"""
        errors = []
        if not self.llm_api_key:
            errors.append("LLM_API_KEY 未设置")
        if not self.llm_base_url:
            errors.append("LLM_BASE_URL 未设置")
        if not self.llm_model:
            errors.append("LLM_MODEL 未设置")
        # embedding 是可选的，不完整配置不阻止启动（EmbeddingService 自动降级）
        if bool(self.embedding_api_key) != bool(self.embedding_base_url):
            pass  # 静默降级，由 /health 端点告知状态
        return errors


settings = Settings()
