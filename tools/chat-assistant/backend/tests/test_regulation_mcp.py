import unittest

from app.agent_runtime.contract_tools import ContractToolRegistry
from app.integrations.mcp.regulation import (
    McpRegulationGateway,
    RegulationQuery,
    RegulationSearchResult,
    RegulationSource,
)


class FakeGateway:
    available = True

    async def search(self, query, run_id):
        return RegulationSearchResult(
            status="DONE",
            provider="fake-mcp",
            sources=(RegulationSource(
                source_id="reg-1",
                title="最高人民法院相关规定",
                url="https://court.gov.cn/regulation/1",
                snippet="外部法规摘录",
                issuer="最高人民法院",
            ),),
        )


class Context:
    run_id = 5
    project_id = 9


class RegulationMcpTest(unittest.IsolatedAsyncioTestCase):
    def test_query_rejects_non_cn_jurisdiction_and_invalid_length(self):
        with self.assertRaises(ValueError):
            RegulationQuery.from_arguments({"query": "x"}, 5)
        with self.assertRaises(ValueError):
            RegulationQuery.from_arguments({"query": "违约金", "jurisdiction": "US"}, 5)

    def test_gateway_only_keeps_https_allowlisted_sources(self):
        gateway = McpRegulationGateway(
            url="https://mcp.example.com/mcp",
            api_key="token",
            tool_name="search_regulations",
            timeout_seconds=3,
            max_calls_per_run=2,
            max_results=5,
            cache_seconds=0,
            allowed_domains=("gov.cn", "court.gov.cn"),
        )
        raw = {
            "results": [
                {"title": "有效来源", "url": "https://www.court.gov.cn/a", "snippet": "内容"},
                {"title": "HTTP 来源", "url": "http://court.gov.cn/b", "snippet": "内容"},
                {"title": "非白名单", "url": "https://example.com/c", "snippet": "内容"},
            ]
        }

        sources = gateway._normalize_sources(raw, 5)

        self.assertEqual(1, len(sources))
        self.assertEqual("https://www.court.gov.cn/a", sources[0].url)

    async def test_gateway_enforces_per_run_budget_and_reuses_cached_response(self):
        gateway = McpRegulationGateway(
            url="https://mcp.example.com/mcp",
            api_key="token",
            tool_name="search_regulations",
            timeout_seconds=3,
            max_calls_per_run=1,
            max_results=5,
            cache_seconds=60,
            allowed_domains=("court.gov.cn",),
        )
        calls = []

        async def fake_call(query):
            calls.append(query.query)
            return {"results": [{
                "title": "有效来源",
                "url": "https://court.gov.cn/a",
                "snippet": "内容",
            }]}

        gateway._call_mcp = fake_call
        query = RegulationQuery(query="违约金调整")
        first = await gateway.search(query, run_id=1)
        second = await gateway.search(query, run_id=1)

        self.assertEqual("DONE", first.status)
        self.assertEqual(first, second)
        self.assertEqual(["违约金调整"], calls)

        with self.assertRaisesRegex(RuntimeError, "budget"):
            await gateway.search(RegulationQuery(query="合同解除"), run_id=1)

    async def test_registry_exposes_and_returns_normalized_external_citation(self):
        registry = ContractToolRegistry(object(), regulation_gateway=FakeGateway())

        self.assertTrue(registry.supports("searchExternalRegulation"))
        output = await registry.execute(Context(), "searchExternalRegulation", {"query": "违约金调整"})
        citations = registry.citations_from([{"output": output}])

        self.assertEqual("DONE", output["status"])
        self.assertEqual("EXTERNAL_REGULATION", citations[0]["sourceType"])
        self.assertTrue(citations[0]["untrustedExternalContent"])
