import unittest
from unittest.mock import patch

from app.agent_runtime.api_models import AgentTaskContext, StartRunRequest
from app.agent_runtime.contract_tools import ContractToolRegistry
from app.agent_runtime.policy import AgentExecutionPolicy
from app.agent_runtime.runner import AgentRunner, RunDispatcher


def contract_context() -> AgentTaskContext:
    return AgentTaskContext(
        run_id=42,
        project_id=7,
        task_type="CONTRACT_REVIEW",
        question="审查付款和违约条款",
        subject_type="CONTRACT_CASE",
        subject_id=7,
        project={"id": 7, "title": "采购合同"},
    )


class ContractRunnerRoutingTest(unittest.IsolatedAsyncioTestCase):
    def test_request_subject_is_preserved_in_context(self):
        request = StartRunRequest({
            "runId": 42,
            "subjectType": "CONTRACT_CASE",
            "subjectId": 7,
            "taskType": "CONTRACT_REVIEW",
        })

        context = AgentTaskContext.from_request(42, request)

        self.assertEqual("CONTRACT_CASE", context.subject_type)
        self.assertEqual(7, context.subject_id)
        self.assertEqual(7, context.project_id)

    def test_contract_fallback_uses_only_contract_tools(self):
        plan = AgentRunner._fallback_plan("CONTRACT_REVIEW", "LLM unavailable")
        plan_tools = {
            name
            for step in plan["steps"]
            for name in step["suggestedTools"]
        }
        turn = AgentRunner._fallback_turn(
            "CONTRACT_REVIEW",
            [{"toolName": "getContractCase", "status": "DONE"}],
            "LLM unavailable",
        )

        self.assertNotIn("getProjectMemory", plan_tools)
        self.assertNotIn("searchProjectEvidence", plan_tools)
        self.assertTrue(all(
            ContractToolRegistry.supports(object(), call["name"])
            for call in turn["toolCalls"]
        ))

    def test_contract_reflection_requests_contract_evidence(self):
        reflection = AgentRunner._local_reflection(
            contract_context(), [], [], "no citations"
        )

        names = [call["name"] for call in reflection["suggestedToolCalls"]]
        self.assertEqual(["readContractClause", "searchPolicyKnowledge"], names)

    async def test_quota_callback_uses_java_internal_token(self):
        captured = {}

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def post(self, url, headers):
                captured["url"] = url
                captured["headers"] = headers
                return FakeResponse()

        dispatcher = RunDispatcher(
            runner=object(), run_store=object(), report_store=object()
        )
        with (
            patch("app.agent_runtime.runner.aiohttp.ClientSession", return_value=FakeSession()),
            patch("app.agent_runtime.runner.settings.java_backend_url", "http://agent-server:18080"),
            patch("app.agent_runtime.runner.settings.java_internal_token", "java-callback-token"),
        ):
            await dispatcher._settle_quota(42, "COMPLETED")

        self.assertEqual(
            "http://agent-server:18080/api/internal/quota/confirm/42",
            captured["url"],
        )
        self.assertEqual(
            "java-callback-token",
            captured["headers"]["X-Internal-Token"],
        )

    async def test_contract_evidence_guarantee_requires_policy_knowledge(self):
        class TraceSpy:
            async def save_tool_call_start(self, *args):
                pass

            async def save_tool_call_done(self, *args):
                pass

            async def save_tool_call_failed(self, *args):
                pass

            async def append_trace(self, *args):
                pass

        class ToolSpy:
            def supports(self, name):
                return name in {"searchPolicyKnowledge", "calculateContractRisk"}

            def citations_from(self, observations):
                citations = []
                for observation in observations:
                    output = observation.get("output") or {}
                    citations.extend(output.get("clauses") or [])
                    citations.extend(output.get("items") or [])
                return citations

            def scoring_from(self, observations):
                for observation in observations:
                    output = observation.get("output") or {}
                    if "scoring" in output:
                        return output["scoring"]
                return {}

            async def execute(self, ctx, name, arguments):
                if name == "searchPolicyKnowledge":
                    return {"items": [{"sourceType": "KB_DOCUMENT", "sourceId": 9}]}
                if name == "calculateContractRisk":
                    return {"scoring": {"riskScore": 50}}
                return {}

        observations = [
            {
                "toolName": "readContractClause",
                "output": {"clauses": [{"id": 1, "content": "付款条款"}]},
            }
        ]
        runner = AgentRunner(
            llm=object(), tools=ToolSpy(), scoring=None,
            run_store=object(), trace_store=TraceSpy(), evidence_store=None,
            report_store=object(), memory_store=object(),
        )

        await runner._ensure_evidence_and_scoring(
            contract_context(), AgentExecutionPolicy(8, 2, 300), observations
        )

        self.assertIn(
            "searchPolicyKnowledge",
            [observation.get("toolName") for observation in observations],
        )

    async def test_fulfillment_check_requires_timeline_verification(self):
        class TraceSpy:
            async def save_tool_call_start(self, *args):
                pass

            async def save_tool_call_done(self, *args):
                pass

            async def save_tool_call_failed(self, *args):
                pass

            async def append_trace(self, *args):
                pass

        class ToolSpy:
            def __init__(self):
                self.calls = []

            def supports(self, name):
                return name in {"verifyFulfillmentEvidence", "readContractClause", "searchPolicyKnowledge"}

            def citations_from(self, observations):
                citations = []
                for observation in observations:
                    output = observation.get("output") or {}
                    citations.extend(output.get("clauses") or [])
                    citations.extend(output.get("items") or [])
                return citations

            def scoring_from(self, observations):
                return {}

            async def execute(self, ctx, name, arguments):
                self.calls.append((name, arguments))
                if name == "verifyFulfillmentEvidence":
                    return {"verification": {"timelineNodeId": arguments["timelineNodeId"]}}
                if name == "readContractClause":
                    return {"clauses": [{"id": 1, "content": "交付条款"}]}
                if name == "searchPolicyKnowledge":
                    return {"items": [{"sourceType": "KB_DOCUMENT", "sourceId": 9}]}
                return {}

        ctx = AgentTaskContext(
            run_id=43,
            project_id=7,
            task_type="FULFILLMENT_CHECK",
            question="核验时间节点",
            subject_type="CONTRACT_CASE",
            subject_id=7,
            project={"id": 7, "title": "采购合同"},
            task_input={"timelineNodeId": 88},
        )
        tools = ToolSpy()
        runner = AgentRunner(
            llm=object(), tools=tools, scoring=None,
            run_store=object(), trace_store=TraceSpy(), evidence_store=None,
            report_store=object(), memory_store=object(),
        )

        observations = []
        await runner._ensure_evidence_and_scoring(
            ctx, AgentExecutionPolicy(8, 2, 300), observations
        )

        self.assertIn(
            ("verifyFulfillmentEvidence", {"timelineNodeId": 88}),
            tools.calls,
        )
        self.assertIn(
            "verifyFulfillmentEvidence",
            [observation.get("toolName") for observation in observations],
        )

    async def test_contract_findings_reach_artifact_generator(self):
        class LlmSpy:
            def contract_review(self, case, findings, citations, scoring, run_id=0):
                return {
                    "case": case,
                    "findings": findings,
                    "citations": citations,
                    "scoring": scoring,
                    "runId": run_id,
                }

        runner = AgentRunner(
            llm=LlmSpy(), tools=object(), scoring=None,
            run_store=object(), trace_store=object(), evidence_store=None,
            report_store=object(), memory_store=object(),
        )
        artifact = await runner._generate_artifact(
            contract_context(),
            [
                {"output": {"case": {"counterparty": "乙方公司"}}},
                {"output": {"findings": [{"ruleKey": "PAYMENT_01"}]}},
            ],
            [{"id": 9, "content": "付款条款"}],
            {"riskScore": 72},
        )

        self.assertEqual("乙方公司", artifact["case"]["counterparty"])
        self.assertEqual("PAYMENT_01", artifact["findings"][0]["ruleKey"])
        self.assertEqual(42, artifact["runId"])


if __name__ == "__main__":
    unittest.main()
