"""Read-only, allowlisted MCP integration for external regulation research."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import logging
import time
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class RegulationMcpError(RuntimeError):
    """A configured external regulation MCP could not provide a usable response."""


@dataclass(frozen=True)
class RegulationQuery:
    query: str
    jurisdiction: str = "CN"
    effective_date: str = ""
    limit: int = 5

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any], max_results: int) -> "RegulationQuery":
        query = str(arguments.get("query") or "").strip()
        if len(query) < 2 or len(query) > 500:
            raise ValueError("Regulation query must contain 2 to 500 characters")
        jurisdiction = str(arguments.get("jurisdiction") or "CN").strip().upper()
        if jurisdiction != "CN":
            raise ValueError("Only CN jurisdiction is enabled")
        requested_limit = int(arguments.get("limit") or max_results)
        return cls(
            query=query,
            jurisdiction=jurisdiction,
            effective_date=str(arguments.get("effectiveDate") or "").strip()[:32],
            limit=max(1, min(requested_limit, max(1, max_results))),
        )


@dataclass(frozen=True)
class RegulationSource:
    source_id: str
    title: str
    url: str
    snippet: str
    issuer: str = ""
    effective_date: str = ""

    def citation(self) -> dict[str, Any]:
        return {
            "id": self.source_id,
            "sourceId": self.source_id,
            "sourceType": "EXTERNAL_REGULATION",
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "issuer": self.issuer,
            "effectiveDate": self.effective_date,
            "retrievalType": "EXTERNAL_MCP",
            "untrustedExternalContent": True,
            "contentTrust": "UNTRUSTED_REFERENCE_ONLY",
        }


@dataclass(frozen=True)
class RegulationSearchResult:
    status: str
    provider: str
    sources: tuple[RegulationSource, ...] = ()
    reason: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "reason": self.reason,
            "sources": [source.citation() for source in self.sources],
        }


class RegulationResearchGateway(Protocol):
    @property
    def available(self) -> bool: ...

    async def search(self, query: RegulationQuery, run_id: int) -> RegulationSearchResult: ...


class DisabledRegulationGateway:
    @property
    def available(self) -> bool:
        return False

    async def search(self, query: RegulationQuery, run_id: int) -> RegulationSearchResult:
        return RegulationSearchResult(
            status="DISABLED",
            provider="external-mcp",
            reason="External regulation MCP is not configured",
        )


class McpRegulationGateway:
    """A narrow interface over MCP transport, result parsing, policy, and cache."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        tool_name: str,
        timeout_seconds: float,
        max_calls_per_run: int,
        max_results: int,
        cache_seconds: int,
        allowed_domains: tuple[str, ...],
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.tool_name = tool_name
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.max_calls_per_run = max(1, max_calls_per_run)
        self.max_results = max(1, max_results)
        self.cache_seconds = max(0, cache_seconds)
        self.allowed_domains = tuple(domain.lower() for domain in allowed_domains)
        self._calls_by_run: dict[int, int] = {}
        self._cache: dict[tuple[str, str, str, int], tuple[float, RegulationSearchResult]] = {}
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return bool(self.url and self.api_key and self.tool_name and self.allowed_domains)

    async def search(self, query: RegulationQuery, run_id: int) -> RegulationSearchResult:
        if not self.available:
            return RegulationSearchResult("DISABLED", "external-mcp", reason="External regulation MCP is incomplete")
        cache_key = (query.query, query.jurisdiction, query.effective_date, query.limit)
        now = time.monotonic()
        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]
            used = self._calls_by_run.get(run_id, 0)
            if used >= self.max_calls_per_run:
                raise RegulationMcpError("External regulation MCP call budget exhausted for this run")
            self._calls_by_run[run_id] = used + 1

        try:
            raw = await self._call_mcp(query)
            sources = tuple(self._normalize_sources(raw, min(query.limit, self.max_results)))
            result = RegulationSearchResult("DONE", "external-mcp", sources=sources)
            if self.cache_seconds > 0:
                async with self._lock:
                    self._cache[cache_key] = (time.monotonic() + self.cache_seconds, result)
            return result
        except RegulationMcpError:
            raise
        except Exception as exc:
            logger.warning("External regulation MCP request failed: %s", exc)
            raise RegulationMcpError("External regulation MCP is unavailable") from exc

    async def _call_mcp(self, query: RegulationQuery) -> Any:
        # Import lazily so disabled local deployments do not initialise the MCP SDK.
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        headers = {"Authorization": f"Bearer {self.api_key}"}
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
            async with streamable_http_client(
                self.url, http_client=client, terminate_on_close=True
            ) as (read_stream, write_stream, _):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                ) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    if self.tool_name not in {tool.name for tool in tools.tools}:
                        raise RegulationMcpError("Configured MCP tool is not offered by the server")
                    response = await session.call_tool(
                        self.tool_name,
                        {
                            "query": query.query,
                            "jurisdiction": query.jurisdiction,
                            "effectiveDate": query.effective_date,
                            "limit": query.limit,
                        },
                        read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                    )
                    if response.isError:
                        raise RegulationMcpError("External regulation MCP returned an error")
                    return response

    def _normalize_sources(self, response: Any, limit: int) -> list[RegulationSource]:
        raw_items = self._extract_items(response)
        result: list[RegulationSource] = []
        seen_urls: set[str] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or item.get("sourceUrl") or "").strip()
            if not self._allowed_url(url) or url in seen_urls:
                continue
            title = self._clean_text(item.get("title") or item.get("name") or "")
            snippet = self._clean_text(item.get("snippet") or item.get("summary") or item.get("content") or item.get("text") or "")
            if not title or not snippet:
                continue
            seen_urls.add(url)
            result.append(RegulationSource(
                source_id=hashlib.sha256(url.encode("utf-8")).hexdigest()[:24],
                title=title[:300],
                url=url,
                snippet=snippet[:2000],
                issuer=self._clean_text(item.get("issuer") or item.get("publisher") or "")[:200],
                effective_date=self._clean_text(item.get("effectiveDate") or item.get("effective_date") or "")[:32],
            ))
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _extract_items(response: Any) -> list[Any]:
        if isinstance(response, dict):
            for key in ("sources", "results", "items", "data"):
                value = response.get(key)
                if isinstance(value, list):
                    return value
        structured = getattr(response, "structuredContent", None)
        if isinstance(structured, dict):
            for key in ("sources", "results", "items", "data"):
                value = structured.get(key)
                if isinstance(value, list):
                    return value
        if isinstance(structured, list):
            return structured
        for content in getattr(response, "content", []) or []:
            text = getattr(content, "text", None)
            if not isinstance(text, str):
                continue
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, list):
                return decoded
            if isinstance(decoded, dict):
                for key in ("sources", "results", "items", "data"):
                    if isinstance(decoded.get(key), list):
                        return decoded[key]
        return []

    def _allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(host == domain or host.endswith("." + domain) for domain in self.allowed_domains)

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = " ".join(str(value or "").split())
        return text.replace("<", "&lt;").replace(">", "&gt;")


_gateway: RegulationResearchGateway | None = None


def get_regulation_gateway() -> RegulationResearchGateway:
    global _gateway
    if _gateway is None:
        if not settings.regulation_mcp_enabled:
            _gateway = DisabledRegulationGateway()
        else:
            _gateway = McpRegulationGateway(
                url=settings.regulation_mcp_url,
                api_key=settings.regulation_mcp_api_key,
                tool_name=settings.regulation_mcp_tool_name,
                timeout_seconds=settings.regulation_mcp_timeout_seconds,
                max_calls_per_run=settings.regulation_mcp_max_calls_per_run,
                max_results=settings.regulation_mcp_max_results,
                cache_seconds=settings.regulation_mcp_cache_seconds,
                allowed_domains=settings.regulation_mcp_allowed_domains,
            )
    return _gateway
