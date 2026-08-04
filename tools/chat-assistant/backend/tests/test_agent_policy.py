import unittest

from app.agent_runtime.policy import AgentExecutionPolicy, BudgetExceeded, RepeatedToolCall


class AgentExecutionPolicyTest(unittest.TestCase):
    def test_blocks_an_identical_tool_call(self):
        policy = AgentExecutionPolicy(max_tool_calls=4, max_turns=2, timeout_seconds=5)

        policy.reserve_tool_call("searchProjectEvidence", {"query": "CI", "limit": 5})

        with self.assertRaises(RepeatedToolCall):
            policy.reserve_tool_call("searchProjectEvidence", {"limit": 5, "query": "CI"})
        self.assertEqual(3, policy.remaining_tool_calls())

    def test_stops_at_the_tool_call_budget(self):
        policy = AgentExecutionPolicy(max_tool_calls=2, max_turns=2, timeout_seconds=5)

        policy.reserve_tool_call("getProjectProfile", {})
        policy.reserve_tool_call("getProjectMemory", {"limit": 5})

        with self.assertRaises(BudgetExceeded):
            policy.reserve_tool_call("getRecentRuns", {"limit": 5})
        self.assertEqual(0, policy.remaining_tool_calls())

    def test_stops_at_the_turn_budget(self):
        policy = AgentExecutionPolicy(max_tool_calls=2, max_turns=1, timeout_seconds=5)

        policy.begin_turn()

        with self.assertRaises(BudgetExceeded):
            policy.begin_turn()


if __name__ == "__main__":
    unittest.main()
